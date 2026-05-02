"""
issue#16 — CP2102N USB unbind/rebind recovery unit tests.

Coverage:
  - `_resolve_usb_sysfs_path` happy path: mocked readlink result resolves
    to the bus-port string the cp210x driver accepts.
  - Resolver rejects malformed sysfs targets (no `:` interface suffix).
  - USB-path regex rejects shell-injection style payloads.
  - `_write_cp210x_envfile` writes `USB_PATH=<x>\\n` atomically.
  - `recover_cp210x` argv pin against systemctl exact form.
  - Subprocess returncode != 0 raises CP210xRecoveryFailed.

Spec memory: `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from godo_webctl import mapping as M
from godo_webctl.config import Settings
from godo_webctl.constants import MAPPING_CP210X_RECOVER_ENV_FILENAME


def _settings(tmp_path: Path) -> Settings:
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir(mode=0o750, exist_ok=True)
    (maps_dir / ".preview").mkdir(mode=0o750, exist_ok=True)
    return Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=tmp_path / "ctl.sock",
        backup_dir=tmp_path / "bk",
        map_path=tmp_path / "fake.pgm",
        maps_dir=maps_dir,
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
        jwt_secret_path=tmp_path / "jwt",
        users_file=tmp_path / "users.json",
        spa_dist=None,
        chromium_loopback_only=True,
        disk_check_path=tmp_path,
        restart_pending_path=tmp_path / "restart_pending",
        pidfile_path=tmp_path / "godo-webctl.pid",
        tracker_toml_path=tmp_path / "tracker.toml",
        # mapping_runtime_dir is /run/godo/mapping in production; the
        # cp210x envfile lives in its parent (/run/godo). Using a tmp
        # subdir mirrors that layout.
        mapping_runtime_dir=tmp_path / "godo" / "mapping",
        mapping_image_tag="godo-mapping:dev",
        docker_bin=Path("/usr/bin/docker"),
        mapping_webctl_stop_timeout_s=35.0,
        mapping_auto_recover_lidar=True,
    )


# --- _resolve_usb_sysfs_path --------------------------------------------


def test_resolve_usb_sysfs_path_layout_a_interface_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Layout (a) — tail segment is the USB interface (`:1.0` suffix).
    Resolver strips `:1.0` and returns `1-1.4`."""
    monkeypatch.setattr(
        M.os.path,
        "realpath",
        lambda p: "/sys/devices/platform/scb/fd500000.pcie/pci0000:00/0000:01:00.0/usb1/1-1/1-1.4/1-1.4:1.0/ttyUSB1/tty/ttyUSB1",
    )
    assert M._resolve_usb_sysfs_path("/dev/ttyUSB1") == "1-1.4"


def test_resolve_usb_sysfs_path_layout_b_no_interface_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Layout (b) — tail segment is the tty device, USB port is one
    level UP. issue#16 HIL hot-fix v3: walk-up resolver returns
    `1-1.4` (parent) instead of raising on absence of `:` suffix.
    Operator's news-pi01 RPi 5 hardware exhibits this layout."""
    monkeypatch.setattr(
        M.os.path,
        "realpath",
        lambda p: "/sys/devices/platform/scb/fd500000.pcie/pci0000:00/0000:01:00.0/usb1/1-1/1-1.4/ttyUSB0",
    )
    assert M._resolve_usb_sysfs_path("/dev/ttyUSB0") == "1-1.4"


def test_resolve_usb_sysfs_path_handles_complex_port_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-hop port chains (e.g. through a hub) — first non-prefix
    match wins. `3-2.1.4` is the leaf, not `3-2.1` or `3-2`."""
    monkeypatch.setattr(
        M.os.path,
        "realpath",
        lambda p: "/sys/devices/.../usb3/3-2/3-2.1/3-2.1.4/3-2.1.4:1.0/ttyUSB0",
    )
    assert M._resolve_usb_sysfs_path("/dev/ttyUSB0") == "3-2.1.4"


def test_resolve_usb_sysfs_path_no_usb_segment_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A realpath with no USB-port-shaped segment anywhere → raise.
    Reaches the helper would mean a malformed unbind/bind write; the
    regex gate is defence-in-depth (helper script also validates)."""
    monkeypatch.setattr(M.os.path, "realpath", lambda p: "/sys/class/tty/ttyUSB1")
    with pytest.raises(M.LidarPortNotResolvable):
        M._resolve_usb_sysfs_path("/dev/ttyUSB1")


def test_resolve_usb_sysfs_path_realpath_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(_p: str) -> str:
        raise OSError("ENOENT")

    monkeypatch.setattr(M.os.path, "realpath", _raise)
    with pytest.raises(M.LidarPortNotResolvable):
        M._resolve_usb_sysfs_path("/dev/ttyUSB99")


def test_resolve_usb_sysfs_path_unexpected_root_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """realpath returning something outside /sys → reject. Defence-in-
    depth — should never happen but the helper script's sysfs writes
    must not be driven by an off-tree path."""
    monkeypatch.setattr(M.os.path, "realpath", lambda p: "/etc/passwd")
    with pytest.raises(M.LidarPortNotResolvable):
        M._resolve_usb_sysfs_path("/dev/ttyUSB1")


@pytest.mark.parametrize(
    "evil_realpath",
    [
        # Even with `/sys` prefix, malformed segments must be rejected.
        # The walk-up looks for a USB-port-shaped segment; injection
        # attempts produce no such segment.
        "/sys/devices/.../evil; rm -rf //ttyUSB0",
        "/sys/devices/.../$(curl evil)/ttyUSB0",
        "/sys/devices/.../abc/ttyUSB0",  # bare alphabet, no digits
        "/sys/devices/.../usb1/ttyUSB0",  # `usb1` is the controller, not a port
    ],
)
def test_resolve_usb_sysfs_path_rejects_malformed_payloads(
    monkeypatch: pytest.MonkeyPatch,
    evil_realpath: str,
) -> None:
    """Defence-in-depth: the regex anchor rejects any non-canonical USB
    bus-port form before the value reaches the bash helper. (The helper
    itself ALSO validates with the same regex — belt and suspenders.)"""
    monkeypatch.setattr(M.os.path, "realpath", lambda p: evil_realpath)
    with pytest.raises(M.LidarPortNotResolvable):
        M._resolve_usb_sysfs_path("/dev/ttyUSB1")


def test_resolve_usb_sysfs_path_empty_basename_raises() -> None:
    with pytest.raises(M.LidarPortNotResolvable):
        M._resolve_usb_sysfs_path("/dev/")


# --- _write_cp210x_envfile -----------------------------------------------


def test_write_cp210x_envfile_writes_atomically(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    target = M._write_cp210x_envfile(cfg, "1-1.4")
    expected = cfg.mapping_runtime_dir.parent / MAPPING_CP210X_RECOVER_ENV_FILENAME
    assert target == expected
    assert target.read_text("utf-8") == "USB_PATH=1-1.4\n"


def test_write_cp210x_envfile_overwrites_previous_atomic(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    M._write_cp210x_envfile(cfg, "1-1.4")
    target = M._write_cp210x_envfile(cfg, "2-3.5")
    assert target.read_text("utf-8") == "USB_PATH=2-3.5\n"


def test_write_cp210x_envfile_no_lingering_temp_files(tmp_path: Path) -> None:
    """Atomic-rename pattern: no `.cp210x.*.env.tmp` siblings after success."""
    cfg = _settings(tmp_path)
    M._write_cp210x_envfile(cfg, "1-1.4")
    parent = cfg.mapping_runtime_dir.parent
    leftover = list(parent.glob(".cp210x.*.env.tmp"))
    assert leftover == []


# --- recover_cp210x ------------------------------------------------------


@pytest.fixture
def fake_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[list[str]]]:
    """Capture every subprocess.run argv. By default returns rc=0."""
    captured: list[list[str]] = []

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    yield captured


def test_recover_cp210x_argv_pin(
    tmp_path: Path,
    fake_subprocess: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact subprocess argv. Drift here would break the polkit rule
    contract (the rule scopes to verb=start + the unit name)."""
    cfg = _settings(tmp_path)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: "/dev/ttyUSB1")
    monkeypatch.setattr(M.os.path, "realpath", lambda p: "/sys/devices/.../1-1.4:1.0/ttyUSB1")
    M.recover_cp210x(cfg)
    assert fake_subprocess == [
        ["systemctl", "start", "--no-pager", "godo-cp210x-recover.service"],
    ]


def test_recover_cp210x_writes_envfile_before_systemctl(
    tmp_path: Path,
    fake_subprocess: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: "/dev/ttyUSB1")
    monkeypatch.setattr(M.os.path, "realpath", lambda p: "/sys/devices/.../1-1.4:1.0/ttyUSB1")
    M.recover_cp210x(cfg)
    envfile = cfg.mapping_runtime_dir.parent / MAPPING_CP210X_RECOVER_ENV_FILENAME
    assert envfile.exists()
    assert envfile.read_text("utf-8") == "USB_PATH=1-1.4\n"


def test_recover_cp210x_systemctl_failure_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: "/dev/ttyUSB1")
    monkeypatch.setattr(M.os.path, "realpath", lambda p: "/sys/devices/.../1-1.4:1.0/ttyUSB1")

    def _failing_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="permission denied\n")

    monkeypatch.setattr(M.subprocess, "run", _failing_run)
    with pytest.raises(M.CP210xRecoveryFailed) as exc_info:
        M.recover_cp210x(cfg)
    assert "permission denied" in str(exc_info.value)


def test_recover_cp210x_systemctl_timeout_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: "/dev/ttyUSB1")
    monkeypatch.setattr(M.os.path, "realpath", lambda p: "/sys/devices/.../1-1.4:1.0/ttyUSB1")

    def _timeout_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, 15.0)

    monkeypatch.setattr(M.subprocess, "run", _timeout_run)
    with pytest.raises(M.CP210xRecoveryFailed):
        M.recover_cp210x(cfg)


def test_recover_cp210x_resolver_failure_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LidarPortNotResolvable bubbles up — the SPA shows 400, not 500."""
    cfg = _settings(tmp_path)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: "/dev/ttyUSB1")

    def _bad_readlink(_p: str) -> str:
        raise FileNotFoundError("missing")

    monkeypatch.setattr(M.os.path, "realpath", _bad_readlink)
    with pytest.raises(M.LidarPortNotResolvable):
        M.recover_cp210x(cfg)
