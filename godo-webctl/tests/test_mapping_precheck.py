"""
issue#16 — Mapping pre-check unit tests.

Coverage:
  - Each helper's happy path (mocked subprocess / filesystem).
  - Each helper's failure mode produces ok=False with the right detail.
  - `_check_name_available` returns ok=None on empty/missing name (the
    SPA's "operator hasn't typed yet" pending state).
  - `precheck()` aggregates rows in PRECHECK_CHECK_NAMES order.
  - `to_dict()` emits keys in PRECHECK_FIELDS / PRECHECK_CHECK_FIELDS
    order (drift-pin against the wire).
  - `ready=True` only when every row is ok=True.

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
from godo_webctl.protocol import (
    PRECHECK_CHECK_FIELDS,
    PRECHECK_CHECK_NAMES,
    PRECHECK_FIELDS,
)


def _settings(tmp_path: Path) -> Settings:
    """Mirror of test_mapping.py::_settings — every path under tmp_path."""
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
        mapping_runtime_dir=tmp_path / "runtime",
        mapping_image_tag="godo-mapping:dev",
        docker_bin=Path("/usr/bin/docker"),
        mapping_webctl_stop_timeout_s=35.0,
    )


# --- helper: monkeypatch a working LiDAR + happy-path subprocess --------


@pytest.fixture
def fake_lidar(tmp_path: Path) -> Path:
    """Create a real-ish file under tmp_path that os.open() can hit
    without colliding with hardware. We use a regular file rather than
    a tty — the tests mock `_resolve_lidar_port` to return this path."""
    lidar = tmp_path / "ttyUSB_fake"
    lidar.write_bytes(b"")
    return lidar


@pytest.fixture
def all_pass_subprocess(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Mock subprocess.run to return systemctl=inactive + image present."""

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["systemctl", "is-active", "--no-pager"]:
            return subprocess.CompletedProcess(argv, 0, stdout="inactive\n", stderr="")
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, stdout="image-id\n", stderr="")
        # Default: success, empty stdout.
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    yield


# --- _check_lidar_readable ----------------------------------------------


def test_check_lidar_readable_happy_path(
    tmp_path: Path,
    fake_lidar: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: str(fake_lidar))
    row = M._check_lidar_readable(cfg)
    assert row.name == "lidar_readable"
    assert row.ok is True
    assert row.detail is None


def test_check_lidar_readable_missing_device_returns_ok_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    monkeypatch.setattr(
        M, "_resolve_lidar_port", lambda c: str(tmp_path / "does_not_exist"),
    )
    row = M._check_lidar_readable(cfg)
    assert row.name == "lidar_readable"
    assert row.ok is False
    # ENOENT for a missing file → "ENOENT" via errno.errorcode.
    assert "ENOENT" in (row.detail or "")


# --- _check_tracker_stopped ----------------------------------------------


def test_check_tracker_stopped_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="inactive\n", stderr="")

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    row = M._check_tracker_stopped(cfg)
    assert row.ok is True
    assert row.value == "inactive"


def test_check_tracker_stopped_active_returns_ok_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="active\n", stderr="")

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    row = M._check_tracker_stopped(cfg)
    assert row.ok is False
    assert row.detail == "active"


def test_check_tracker_stopped_failed_state_treated_as_ok(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`failed` is acceptable: the unit isn't holding the LiDAR."""
    cfg = _settings(tmp_path)

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 3, stdout="failed\n", stderr="")

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    row = M._check_tracker_stopped(cfg)
    assert row.ok is True


# --- _check_image_present ------------------------------------------------


def test_check_image_present_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="image-id\n", stderr="")

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    row = M._check_image_present(cfg)
    assert row.ok is True
    assert row.value == cfg.mapping_image_tag


def test_check_image_present_missing_image_returns_ok_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="Error: No such image: godo-mapping:dev\n",
        )

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    row = M._check_image_present(cfg)
    assert row.ok is False
    assert "docker build" in (row.detail or "")


# --- _check_disk_space_mb -----------------------------------------------


def test_check_disk_space_mb_above_threshold_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)

    class _Usage:
        free = 10 * 1024 * 1024 * 1024  # 10 GiB

    monkeypatch.setattr(M.shutil, "disk_usage", lambda p: _Usage())
    row = M._check_disk_space_mb(cfg)
    assert row.ok is True
    assert isinstance(row.value, int)
    assert row.value >= 500


def test_check_disk_space_mb_below_threshold_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)

    class _Usage:
        free = 100 * 1024 * 1024  # 100 MiB

    monkeypatch.setattr(M.shutil, "disk_usage", lambda p: _Usage())
    row = M._check_disk_space_mb(cfg)
    assert row.ok is False
    assert row.value == 100


# --- _check_name_available ----------------------------------------------


def test_check_name_available_pending_when_name_none(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    row = M._check_name_available(cfg, None)
    assert row.name == "name_available"
    assert row.ok is None  # pending state
    assert row.detail is None


def test_check_name_available_pending_when_name_empty(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    row = M._check_name_available(cfg, "")
    assert row.ok is None


def test_check_name_available_invalid_name_fails(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    row = M._check_name_available(cfg, "../etc/passwd")
    assert row.ok is False


def test_check_name_available_existing_pgm_fails(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    (cfg.maps_dir / "studio_v1.pgm").write_bytes(b"P5\n1 1\n255\n\x00")
    row = M._check_name_available(cfg, "studio_v1")
    assert row.ok is False
    assert row.detail == "name_exists"


def test_check_name_available_happy_path(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    row = M._check_name_available(cfg, "studio_v1")
    assert row.ok is True


# --- _check_state_clean -------------------------------------------------


def test_check_state_clean_idle_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    # No state.json → Idle by default.
    row = M._check_state_clean(cfg)
    assert row.ok is True
    assert row.value == "idle"


def test_check_state_clean_running_state_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-02T10:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    # Mock docker inspect so the reconcile keeps state Running.
    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="running\n", stderr="")

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    row = M._check_state_clean(cfg)
    assert row.ok is False
    assert row.detail == "running"


# --- precheck() aggregator ----------------------------------------------


def test_precheck_emits_rows_in_canonical_order(
    tmp_path: Path,
    fake_lidar: Path,
    monkeypatch: pytest.MonkeyPatch,
    all_pass_subprocess: None,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: str(fake_lidar))
    result = M.precheck(cfg, "studio_v1")
    assert tuple(r.name for r in result.checks) == PRECHECK_CHECK_NAMES


def test_precheck_ready_true_when_all_rows_pass(
    tmp_path: Path,
    fake_lidar: Path,
    monkeypatch: pytest.MonkeyPatch,
    all_pass_subprocess: None,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: str(fake_lidar))
    result = M.precheck(cfg, "studio_v1")
    # Quietly verify the underlying disk has > 500 MiB; CI hosts always do.
    assert result.ready is True


def test_precheck_ready_false_when_name_pending(
    tmp_path: Path,
    fake_lidar: Path,
    monkeypatch: pytest.MonkeyPatch,
    all_pass_subprocess: None,
) -> None:
    """ok=None counts as not-ready (operator typing)."""
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: str(fake_lidar))
    result = M.precheck(cfg, None)
    assert result.ready is False
    name_row = next(r for r in result.checks if r.name == "name_available")
    assert name_row.ok is None


def test_precheck_ready_false_when_lidar_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    all_pass_subprocess: None,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    # Path that doesn't exist → ENOENT on os.open.
    monkeypatch.setattr(
        M, "_resolve_lidar_port", lambda c: str(tmp_path / "missing"),
    )
    result = M.precheck(cfg, "studio_v1")
    assert result.ready is False
    lidar_row = next(r for r in result.checks if r.name == "lidar_readable")
    assert lidar_row.ok is False


def test_precheck_ready_false_when_tracker_active(
    tmp_path: Path,
    fake_lidar: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: str(fake_lidar))

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["systemctl", "is-active", "--no-pager"]:
            return subprocess.CompletedProcess(argv, 0, stdout="active\n", stderr="")
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, stdout="image-id\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(M.subprocess, "run", _fake_run)
    result = M.precheck(cfg, "studio_v1")
    assert result.ready is False
    tracker_row = next(r for r in result.checks if r.name == "tracker_stopped")
    assert tracker_row.ok is False


# --- to_dict() field-order pin ------------------------------------------


def test_to_dict_top_level_keys_match_precheck_fields(
    tmp_path: Path,
    fake_lidar: Path,
    monkeypatch: pytest.MonkeyPatch,
    all_pass_subprocess: None,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: str(fake_lidar))
    result = M.precheck(cfg, "studio_v1")
    d = result.to_dict()
    assert tuple(d.keys()) == PRECHECK_FIELDS


def test_to_dict_check_row_keys_match_precheck_check_fields(
    tmp_path: Path,
    fake_lidar: Path,
    monkeypatch: pytest.MonkeyPatch,
    all_pass_subprocess: None,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: str(fake_lidar))
    result = M.precheck(cfg, "studio_v1")
    d = result.to_dict()
    for row_dict in d["checks"]:
        assert tuple(row_dict.keys()) == PRECHECK_CHECK_FIELDS


def test_to_dict_check_row_count_matches_canonical_names(
    tmp_path: Path,
    fake_lidar: Path,
    monkeypatch: pytest.MonkeyPatch,
    all_pass_subprocess: None,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(M, "_resolve_lidar_port", lambda c: str(fake_lidar))
    result = M.precheck(cfg, "studio_v1")
    d = result.to_dict()
    assert len(d["checks"]) == len(PRECHECK_CHECK_NAMES)
    assert tuple(row["name"] for row in d["checks"]) == PRECHECK_CHECK_NAMES
