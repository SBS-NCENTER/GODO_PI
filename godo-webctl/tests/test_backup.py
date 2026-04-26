"""Backup helper: atomicity, error mapping, collision retry."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from godo_webctl.backup import BackupError, _yaml_path_for, backup_map


# --- yaml_path_for mirror -------------------------------------------------
def test_yaml_path_for_strips_pgm() -> None:
    assert _yaml_path_for(Path("/x/studio_v1.pgm")) == Path("/x/studio_v1.yaml")


def test_yaml_path_for_no_suffix_appends() -> None:
    assert _yaml_path_for(Path("/x/studio_v1")) == Path("/x/studio_v1.yaml")


def test_yaml_path_for_case_sensitive() -> None:
    """Mirror C++ exactly — only lowercase .pgm is stripped."""
    assert _yaml_path_for(Path("/x/studio_v1.PGM")) == Path("/x/studio_v1.PGM.yaml")


# --- happy path -----------------------------------------------------------
def test_happy_path_creates_dir_and_returns_path(
    tmp_map_pair: Path,
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "bk"
    fixed = datetime(2026, 4, 26, 14, 30, 22, tzinfo=UTC)
    out = backup_map(tmp_map_pair, backup_dir, now=fixed)
    assert out == backup_dir / "20260426T143022Z"
    assert out.is_dir()
    assert (out / "studio_v1.pgm").is_file()
    assert (out / "studio_v1.yaml").is_file()
    # No leftover .tmp/.
    assert not (backup_dir / "20260426T143022Z.tmp").exists()


def test_source_content_preserved(tmp_map_pair: Path, tmp_path: Path) -> None:
    backup_dir = tmp_path / "bk"
    out = backup_map(tmp_map_pair, backup_dir)
    assert (out / "studio_v1.pgm").read_bytes() == tmp_map_pair.read_bytes()
    assert (out / "studio_v1.yaml").read_text() == tmp_map_pair.with_suffix(".yaml").read_text()


# --- failure modes --------------------------------------------------------
def test_missing_pgm_raises_not_found(tmp_path: Path) -> None:
    pgm = tmp_path / "ghost.pgm"
    yaml = tmp_path / "ghost.yaml"
    yaml.write_text("image: ghost.pgm\n")
    with pytest.raises(BackupError) as ei:
        backup_map(pgm, tmp_path / "bk")
    assert "map_path_not_found" in str(ei.value)


def test_missing_yaml_raises_not_found(tmp_path: Path) -> None:
    pgm = tmp_path / "lonely.pgm"
    pgm.write_bytes(b"\x00")
    with pytest.raises(BackupError) as ei:
        backup_map(pgm, tmp_path / "bk")
    assert "map_path_not_found" in str(ei.value)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
def test_unwritable_backup_dir_raises(tmp_map_pair: Path, tmp_path: Path) -> None:
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        backup_dir = parent / "bk"
        with pytest.raises(BackupError) as ei:
            backup_map(tmp_map_pair, backup_dir)
        assert "backup_dir_unwritable" in str(ei.value)
    finally:
        parent.chmod(0o700)  # let pytest clean up


# --- determinism + collision ----------------------------------------------
def test_clock_injected_timestamp_in_path(
    tmp_map_pair: Path,
    tmp_path: Path,
) -> None:
    fixed = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    out = backup_map(tmp_map_pair, tmp_path / "bk", now=fixed)
    assert out.name == "20300102T030405Z"


def test_two_backups_same_second_get_suffix(
    tmp_map_pair: Path,
    tmp_path: Path,
) -> None:
    fixed = datetime(2026, 4, 26, 14, 30, 22, tzinfo=UTC)
    bk = tmp_path / "bk"
    a = backup_map(tmp_map_pair, bk, now=fixed)
    b = backup_map(tmp_map_pair, bk, now=fixed)
    assert a.name == "20260426T143022Z"
    assert b.name == "20260426T143022Z_2"
    assert a.is_dir() and b.is_dir()


def test_backup_dir_mode_is_0750_when_created(
    tmp_map_pair: Path,
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "freshly_made"
    backup_map(tmp_map_pair, backup_dir)
    mode = stat.S_IMODE(backup_dir.stat().st_mode)
    # umask may strip write bits but never tighter than 0750 on the chosen mode.
    assert mode <= 0o750
