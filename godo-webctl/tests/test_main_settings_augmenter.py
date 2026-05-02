"""issue#14 Mode-B C1 fix (2026-05-02 KST) — unit-level coverage of
``godo_webctl.__main__._augment_with_webctl_section``.

Pre-fix, ``Settings.mapping_*_s`` was loaded ONLY from env / module
defaults. Operator edits to ``[webctl]`` keys in tracker.toml never
reached ``cfg.mapping_webctl_stop_timeout_s`` at runtime, so the Maj-1
"torn lifetime asset" deadline reverted to 35 s regardless of intent.

Tests in this file pin the augmenter contract:
1. TOML overrides default when env did not fire.
2. Env override is preserved when present (precedence).
3. Missing/malformed TOML → defaults retained (no crash).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from godo_webctl import webctl_toml
from godo_webctl.__main__ import _augment_with_webctl_section
from godo_webctl.config import Settings


def _make_settings(
    *,
    tmp_path: Path,
    webctl: float = float(webctl_toml.WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S_DEFAULT),
    tracker_toml_path: Path | None = None,
) -> Settings:
    """Construct a minimal Settings instance — every required Path field
    points into ``tmp_path`` so the constructor accepts it."""
    return Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=tmp_path / "uds.sock",
        backup_dir=tmp_path / "bk",
        map_path=tmp_path / "studio.pgm",
        maps_dir=tmp_path / "maps",
        health_uds_timeout_s=2.0,
        calibrate_uds_timeout_s=2.0,
        jwt_secret_path=tmp_path / "jwt.bin",
        users_file=tmp_path / "users.json",
        spa_dist=None,
        chromium_loopback_only=False,
        disk_check_path=tmp_path,
        restart_pending_path=tmp_path / "restart.lock",
        pidfile_path=tmp_path / "webctl.pid",
        tracker_toml_path=tracker_toml_path or (tmp_path / "tracker.toml"),
        mapping_runtime_dir=tmp_path / "mapping",
        mapping_image_tag="godo-mapping:dev",
        docker_bin=Path("/usr/bin/docker"),
        mapping_webctl_stop_timeout_s=webctl,
        mapping_auto_recover_lidar=True,
    )


def test_augment_pulls_mapping_timing_from_toml_when_settings_at_default(
    tmp_path: Path,
) -> None:
    """C1 happy path: tracker.toml has the trio under [webctl]; Settings
    field carries its bare module default (= env did not fire). The
    runtime field ``mapping_webctl_stop_timeout_s`` picks up the TOML
    value."""
    toml = tmp_path / "tracker.toml"
    toml.write_text(
        "[webctl]\n"
        "pose_stream_hz = 30\n"
        "scan_stream_hz = 30\n"
        "mapping_docker_stop_grace_s = 25\n"
        "mapping_systemd_stop_timeout_s = 40\n"
        "mapping_webctl_stop_timeout_s = 50\n"
    )
    s = _make_settings(tmp_path=tmp_path, tracker_toml_path=toml)
    augmented = _augment_with_webctl_section(s)
    assert augmented.mapping_webctl_stop_timeout_s == 50.0


def test_augment_preserves_env_override(tmp_path: Path) -> None:
    """Env precedence: a Settings field that does NOT match the bare
    module default is treated as env-overridden and left untouched."""
    toml = tmp_path / "tracker.toml"
    toml.write_text(
        "[webctl]\n"
        "pose_stream_hz = 30\n"
        "scan_stream_hz = 30\n"
        "mapping_docker_stop_grace_s = 25\n"
        "mapping_systemd_stop_timeout_s = 40\n"
        "mapping_webctl_stop_timeout_s = 50\n"
    )
    # Env-overridden field carries a non-default value (45.0 ≠ default 35).
    s = _make_settings(tmp_path=tmp_path, tracker_toml_path=toml, webctl=45.0)
    augmented = _augment_with_webctl_section(s)
    # webctl was env-overridden → TOML must NOT clobber.
    assert augmented.mapping_webctl_stop_timeout_s == 45.0


def test_augment_keeps_default_when_toml_missing(tmp_path: Path) -> None:
    """No tracker.toml file at all → fall back gracefully, no crash."""
    s = _make_settings(tmp_path=tmp_path)
    augmented = _augment_with_webctl_section(s)
    assert augmented.mapping_webctl_stop_timeout_s == float(
        webctl_toml.WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S_DEFAULT,
    )


def test_augment_keeps_default_when_toml_malformed(tmp_path: Path) -> None:
    """Malformed TOML → graceful fallback (default retained)."""
    toml = tmp_path / "tracker.toml"
    toml.write_text("this is not valid TOML\n[unclosed\n")
    s = _make_settings(tmp_path=tmp_path, tracker_toml_path=toml)
    augmented = _augment_with_webctl_section(s)
    assert augmented.mapping_webctl_stop_timeout_s == float(
        webctl_toml.WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S_DEFAULT,
    )


def test_augment_keeps_default_when_toml_lacks_webctl_section(tmp_path: Path) -> None:
    """tracker.toml exists but has no [webctl] table → defaults retained
    (read_webctl_section returns the WebctlSection of defaults)."""
    toml = tmp_path / "tracker.toml"
    toml.write_text("[main]\nsomething_else = 42\n")
    s = _make_settings(tmp_path=tmp_path, tracker_toml_path=toml)
    augmented = _augment_with_webctl_section(s)
    assert augmented.mapping_webctl_stop_timeout_s == float(
        webctl_toml.WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S_DEFAULT,
    )


def test_augment_keeps_default_on_torn_ladder_via_section_validation(
    tmp_path: Path,
) -> None:
    """A torn ordering (docker ≥ systemd) raises WebctlTomlError inside
    read_webctl_section. The augmenter logs WARNING and keeps defaults
    — webctl boot continues."""
    toml = tmp_path / "tracker.toml"
    toml.write_text(
        "[webctl]\n"
        "mapping_docker_stop_grace_s = 50\n"
        "mapping_systemd_stop_timeout_s = 30\n"  # torn: docker > systemd
        "mapping_webctl_stop_timeout_s = 60\n"
    )
    # Direct-call sanity: the parser raises so the augmenter sees the
    # error.
    with pytest.raises(webctl_toml.WebctlTomlError):
        webctl_toml.read_webctl_section(toml)
    s = _make_settings(tmp_path=tmp_path, tracker_toml_path=toml)
    augmented = _augment_with_webctl_section(s)
    # Default retained, no crash.
    assert augmented.mapping_webctl_stop_timeout_s == float(
        webctl_toml.WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S_DEFAULT,
    )
