"""
Pure-function tests for `map_backup` (Track B-BACKUP).

Mode-A folds applied:
  M4 — `restore_backup` does NOT import `_yaml_path_for`; copies every
       basename verbatim from `<backup_dir>/<ts>/`.
  M5 — `list_backups` returns `[]` for both "dir missing" and
       "dir exists empty" (no `BackupDirMissing` exception).
  M6 — `test_restore_never_leaves_partial_pgm` pins the visible
       contract (no half-written file ever visible) instead of the
       implementation (`os.replace`).
  M7 — partial-mid-copy semantics documented in `restore_backup`
       docstring.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from godo_webctl import map_backup as MB

# --- list_backups ------------------------------------------------------


def test_list_empty_returns_empty_list(tmp_path: Path) -> None:
    """Dir exists, no children — empty list, no exception."""
    empty = tmp_path / "bk"
    empty.mkdir()
    assert MB.list_backups(empty) == []


def test_list_dir_missing_returns_empty_list(tmp_path: Path) -> None:
    """Mode-A M5: missing dir is NOT an exception — uniform empty
    list shape on the wire (200 always)."""
    missing = tmp_path / "no-such-dir"
    assert MB.list_backups(missing) == []


def test_list_returns_newest_first_by_ts(tmp_backup_dir: Path) -> None:
    """Newer backup ts comes first in the list (lexicographic == chronological
    on canonical KST stamps; legacy UTC `Z`-suffixed dirs from before the
    KST convention are still readable via the relaxed `_TS_REGEX`)."""
    entries = MB.list_backups(tmp_backup_dir)
    assert len(entries) == 2
    assert entries[0].ts == "20260202T020202Z"
    assert entries[1].ts == "20260101T010101Z"


def test_list_skips_tmp_orphan(tmp_backup_dir: Path) -> None:
    """`<ts>.tmp/` from a crashed backup is filtered out."""
    entries = MB.list_backups(tmp_backup_dir)
    ts_set = {e.ts for e in entries}
    assert "20260303T030303Z.tmp" not in ts_set
    # The non-suffix part also must not appear (defence against a sloppy
    # regex that strips `.tmp`).
    assert "20260303T030303Z" not in ts_set


def test_list_skips_nonconformant_names(tmp_path: Path) -> None:
    """Random subdir like `foo/` is skipped silently."""
    bk = tmp_path / "bk"
    bk.mkdir()
    (bk / "foo").mkdir()
    (bk / "20260404T040404Z").mkdir()
    (bk / "20260404T040404Z" / "studio_v1.pgm").write_bytes(b"x")
    (bk / "not-a-ts").mkdir()
    entries = MB.list_backups(bk)
    assert [e.ts for e in entries] == ["20260404T040404Z"]


def test_list_size_sums_all_files(tmp_backup_dir: Path) -> None:
    """Mode-A N5 fold: `size_bytes` is the sum of stat.st_size across
    every file in the backup directory (will include yaml + future map
    artefacts)."""
    entries = MB.list_backups(tmp_backup_dir)
    older = next(e for e in entries if e.ts == "20260101T010101Z")
    expected = sum(
        (tmp_backup_dir / "20260101T010101Z" / name).stat().st_size for name in older.files
    )
    assert older.size_bytes == expected
    # Both pgm + yaml are visible; this is the SSOT-friendly behaviour.
    assert sorted(older.files) == ["studio_v1.pgm", "studio_v1.yaml"]


# --- restore_backup ----------------------------------------------------


def test_restore_copies_all_files_atomically(
    tmp_backup_dir: Path,
    tmp_path: Path,
) -> None:
    """Pgm + yaml present in `maps_dir` after a successful restore."""
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    restored = MB.restore_backup(tmp_backup_dir, "20260101T010101Z", maps_dir)
    assert sorted(restored) == ["studio_v1.pgm", "studio_v1.yaml"]
    assert (maps_dir / "studio_v1.pgm").is_file()
    assert (maps_dir / "studio_v1.yaml").is_file()
    # No `.restore.*` tmp leftovers in maps_dir.
    leftovers = list(maps_dir.glob(".restore.*"))
    assert leftovers == []


def test_restore_overwrites_existing_named_pair(
    tmp_backup_dir: Path,
    tmp_path: Path,
) -> None:
    """Pre-existing pair is replaced bytewise (the backup is the
    authoritative snapshot)."""
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    (maps_dir / "studio_v1.pgm").write_bytes(b"OLD-CONTENT")
    (maps_dir / "studio_v1.yaml").write_text("OLD-YAML\n")

    MB.restore_backup(tmp_backup_dir, "20260101T010101Z", maps_dir)

    expected_pgm = (tmp_backup_dir / "20260101T010101Z" / "studio_v1.pgm").read_bytes()
    expected_yaml = (tmp_backup_dir / "20260101T010101Z" / "studio_v1.yaml").read_text()
    assert (maps_dir / "studio_v1.pgm").read_bytes() == expected_pgm
    assert (maps_dir / "studio_v1.yaml").read_text() == expected_yaml


def test_restore_raises_on_unknown_ts(tmp_backup_dir: Path, tmp_path: Path) -> None:
    """Well-formed but non-existent ts → `BackupNotFound`."""
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    with pytest.raises(MB.BackupNotFound):
        MB.restore_backup(tmp_backup_dir, "29991231T235959Z", maps_dir)


def test_restore_raises_on_invalid_ts_regex(tmp_backup_dir: Path, tmp_path: Path) -> None:
    """Mode-A TB4 + module docstring: malformed ts collapses to
    `BackupNotFound` (deliberate folding for log-uniformity; the
    handler returns 404 for both). Sanitised before any FS touch —
    no `IOError` or path-traversal escape ever reaches disk."""
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    for bad in ("..", ".", "foo", "", "20260101", "20260101T010101"):
        with pytest.raises(MB.BackupNotFound):
            MB.restore_backup(tmp_backup_dir, bad, maps_dir)


def test_restore_cleans_tmp_on_copy_failure(
    tmp_backup_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monkeypatch `shutil.copy2` to raise mid-copy; assert no
    `.restore.*` leftovers remain in `maps_dir`."""
    import shutil as _shutil

    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()

    def _boom(*_a: object, **_kw: object) -> None:
        raise OSError(28, "ENOSPC")

    monkeypatch.setattr(_shutil, "copy2", _boom)
    with pytest.raises(OSError):
        MB.restore_backup(tmp_backup_dir, "20260101T010101Z", maps_dir)
    leftovers = list(maps_dir.glob(".restore.*"))
    assert leftovers == []


def test_restore_never_leaves_partial_pgm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mode-A M6 fold (replaces `test_restore_two_phase_uses_os_replace`).

    Setup: 3-file backup at `<backup_dir>/<ts>/` (file_a, file_b, file_c).
    Pre-existing `maps_dir` contents (OLD bytes for file_a, file_b —
    file_c is absent). Monkeypatch `os.replace` to raise
    `OSError(ENOSPC)` on its 2nd invocation (file_b).

    Assert:
      - file_a is NEW bytes (already replaced).
      - file_b is OLD bytes (its `.tmp` was orphaned and cleaned).
      - file_c is absent (never copied).

    Pins the visible contract (no half-written file ever visible)
    without pinning the implementation — could later use `shutil.move`
    or anything else with the same semantics.
    """
    import errno

    backup_dir = tmp_path / "bk"
    backup_dir.mkdir()
    src = backup_dir / "20260505T050505Z"
    src.mkdir()
    (src / "file_a").write_bytes(b"NEW-A")
    (src / "file_b").write_bytes(b"NEW-B")
    (src / "file_c").write_bytes(b"NEW-C")

    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    (maps_dir / "file_a").write_bytes(b"OLD-A")
    (maps_dir / "file_b").write_bytes(b"OLD-B")
    # file_c absent.

    real_replace = os.replace
    call_counter = {"n": 0}

    def _flaky_replace(src_path: object, dst_path: object) -> None:
        call_counter["n"] += 1
        # Sources are sorted by basename: file_a, file_b, file_c.
        # Fail on the 2nd replace call (file_b).
        if call_counter["n"] == 2:
            raise OSError(errno.ENOSPC, "disk full")
        real_replace(src_path, dst_path)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", _flaky_replace)
    with pytest.raises(OSError):
        MB.restore_backup(backup_dir, "20260505T050505Z", maps_dir)

    # File_a was replaced before the failure — irreversible per the
    # documented partial-restore semantics.
    assert (maps_dir / "file_a").read_bytes() == b"NEW-A"
    # File_b retains its OLD bytes — the tmp was orphaned and cleaned;
    # the destination was never replaced.
    assert (maps_dir / "file_b").read_bytes() == b"OLD-B"
    # File_c never got touched (loop aborted at file_b).
    assert not (maps_dir / "file_c").exists()
    # No .restore.*.tmp leftovers.
    assert list(maps_dir.glob(".restore.*")) == []
