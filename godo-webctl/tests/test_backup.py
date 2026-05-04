"""Backup helper: atomicity, error mapping, collision retry."""

from __future__ import annotations

import fcntl
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from godo_webctl.backup import BackupError, _yaml_path_for, backup_map
from godo_webctl.constants import BACKUP_LOCK_FILENAME


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
    assert out == backup_dir / "20260426T143022"
    assert out.is_dir()
    assert (out / "studio_v1.pgm").is_file()
    assert (out / "studio_v1.yaml").is_file()
    # No leftover .tmp/.
    assert not (backup_dir / "20260426T143022.tmp").exists()


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
    assert out.name == "20300102T030405"


def test_two_backups_same_second_get_suffix(
    tmp_map_pair: Path,
    tmp_path: Path,
) -> None:
    fixed = datetime(2026, 4, 26, 14, 30, 22, tzinfo=UTC)
    bk = tmp_path / "bk"
    a = backup_map(tmp_map_pair, bk, now=fixed)
    b = backup_map(tmp_map_pair, bk, now=fixed)
    assert a.name == "20260426T143022"
    assert b.name == "20260426T143022_2"
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


# --- defence-in-depth flock (PR-1) ---------------------------------------
def test_backup_lock_acquired_and_released(
    tmp_map_pair: Path,
    tmp_path: Path,
) -> None:
    """After ``backup_map`` returns, the .lock file persists but the
    flock is released — a manual re-lock from this test process must
    succeed.
    """
    backup_dir = tmp_path / "bk"
    backup_map(tmp_map_pair, backup_dir)
    lock_path = backup_dir / BACKUP_LOCK_FILENAME
    assert lock_path.is_file(), (
        ".lock should persist between backup_map calls (kernel releases "
        "the lock state on FD close, file presence is not the signal)"
    )
    # If backup_map released cleanly, we can take the flock now.
    fd = os.open(str(lock_path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_concurrent_backup_raises_concurrent_in_progress(
    tmp_map_pair: Path,
    tmp_path: Path,
) -> None:
    """Hold the .lock from this test, then call backup_map → should
    raise ``BackupError("concurrent_backup_in_progress")``.
    """
    backup_dir = tmp_path / "bk"
    backup_dir.mkdir(mode=0o750)
    lock_path = backup_dir / BACKUP_LOCK_FILENAME
    holder_fd = os.open(
        str(lock_path),
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC,
        0o644,
    )
    try:
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BackupError) as ei:
            backup_map(tmp_map_pair, backup_dir)
        assert str(ei.value) == "concurrent_backup_in_progress"
    finally:
        try:
            fcntl.flock(holder_fd, fcntl.LOCK_UN)
        finally:
            os.close(holder_fd)


def test_backup_lock_file_persists_but_unlocked_after_call(
    tmp_map_pair: Path,
    tmp_path: Path,
) -> None:
    """After two back-to-back backups, the .lock file is still present
    AND a third concurrent flock attempt from outside succeeds.
    """
    backup_dir = tmp_path / "bk"
    fixed_a = datetime(2026, 4, 26, 14, 30, 22, tzinfo=UTC)
    fixed_b = datetime(2026, 4, 26, 14, 30, 23, tzinfo=UTC)
    backup_map(tmp_map_pair, backup_dir, now=fixed_a)
    backup_map(tmp_map_pair, backup_dir, now=fixed_b)
    lock_path = backup_dir / BACKUP_LOCK_FILENAME
    assert lock_path.is_file()
    fd = os.open(str(lock_path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
