"""
Map backup history primitives (Track B-BACKUP).

Read-only enumeration of saved map backups under `cfg.backup_dir`
(`/var/lib/godo/map-backups/`) plus an admin-triggered restore that
copies a snapshot back into `cfg.maps_dir`. Mirror of `maps.py`'s
sole-owner discipline (Track E invariant (o)): every read or write
inside `cfg.backup_dir` goes through this module's public API; the
restore writer additionally writes the named pair into
`cfg.maps_dir` but does NOT import `maps.py` — restore deliberately
does not touch the `active.pgm` / `active.yaml` symlinks (Option A
semantics; operator activates separately via `POST /api/maps/<name>/activate`
+ `godo-tracker` restart).

Backup directory layout (created by `backup.backup_map`):

    /var/lib/godo/map-backups/
    ├─ 20260429T143022Z/         (canonical UTC stamp, lexicographic == chronological)
    │   ├─ studio_v1.pgm
    │   └─ studio_v1.yaml
    ├─ 20260429T154100Z/
    │   ├─ studio_v2.pgm
    │   └─ studio_v2.yaml
    └─ 20260429T160500Z.tmp/      (orphan from a crashed backup; filtered out)

Path-traversal defence: every public function validates the `<ts>`
argument against `_TS_REGEX` before any FS touch. Malformed and
unknown-ts arguments BOTH raise `BackupNotFound` (deliberate folding
for log-uniformity; the handler returns 404 for both).

Concurrency: `backup_map` is single-writer per webctl invariant (e)
(single uvicorn worker = serial handler execution); `restore_backup`
inherits the same single-writer property. No dedicated concurrent
test; pinned by inspection + invariant cross-reference.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger("godo_webctl.map_backup")


# --- Constants ---------------------------------------------------------

# Canonical backup-directory name format: `YYYYMMDDTHHMMSSZ` (UTC). The
# producer is `backup.backup_map`; the regex is the second defence layer
# inside `restore_backup` against path-traversal.
_TS_REGEX: Final[re.Pattern[str]] = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")

# Suffix used by `backup.backup_map` for the in-flight tmp directory.
_TMP_SUFFIX: Final[str] = ".tmp"

# Per-restored-file in-flight tmp prefix inside `cfg.maps_dir`. The
# leading dot keeps it out of `maps.list_pairs` enumeration; the random
# token (mirror of `secrets.token_hex` discipline used by `maps.py`)
# avoids collisions with a concurrent restore in the same UTC second.
_RESTORE_TMP_PREFIX: Final[str] = ".restore."

# 64-bit collision space — same discipline as `maps.py::_new_tmp_name`.
_RESTORE_TMP_TOKEN_HEX_BYTES: Final[int] = 8


# --- Exceptions --------------------------------------------------------


class BackupNotFound(LookupError):
    """`<ts>` does not exist under `backup_dir`, OR `<ts>` is malformed
    (deliberate folding — log-uniformity, see module docstring)."""


class RestoreNameConflict(RuntimeError):
    """Reserved for future use — the current contract overwrites by
    design (the backup is the authoritative snapshot). Kept in the
    public surface so a future stricter-mode flag can raise this without
    a wire-shape change."""


# --- Data class --------------------------------------------------------


@dataclass(frozen=True)
class BackupEntry:
    """One backup-directory row.

    `size_bytes` is the sum of `stat.st_size` across all files in the
    backup directory; will include yaml + any future map artefacts
    (Mode-A N5 fold — SSOT-friendly against B-MAPEDIT adding files).
    """

    ts: str
    files: list[str]
    size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "files": list(self.files),
            "size_bytes": self.size_bytes,
        }


# --- Public API --------------------------------------------------------


def list_backups(backup_dir: Path) -> list[BackupEntry]:
    """Enumerate backups under `backup_dir`, newest first.

    Newest-first by ts string-compare (UTC stamp lexicographic ==
    chronological). Returns `[]` if `backup_dir` does not exist or
    contains no canonical-ts subdirectories. Skips `<ts>.tmp/` orphans
    and any non-conformant directory name.
    """
    if not backup_dir.exists() or not backup_dir.is_dir():
        return []

    entries: list[BackupEntry] = []
    for child in backup_dir.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not _TS_REGEX.match(name):
            # `<ts>.tmp/` orphans + any other non-canonical subdir
            # (random `foo/`, leftover stale crash dirs).
            continue
        files: list[str] = []
        size_total = 0
        try:
            for file_entry in child.iterdir():
                if not file_entry.is_file():
                    continue
                files.append(file_entry.name)
                # Best-effort: a file vanishing mid-iteration is the
                # same as it never having been there for sizing.
                with contextlib.suppress(OSError):
                    size_total += file_entry.stat().st_size
        except OSError:
            continue
        files.sort()
        entries.append(BackupEntry(ts=name, files=files, size_bytes=size_total))

    entries.sort(key=lambda e: e.ts, reverse=True)
    return entries


def restore_backup(backup_dir: Path, ts: str, maps_dir: Path) -> list[str]:
    """Atomically copy every file in `<backup_dir>/<ts>/` into `maps_dir/`.

    Two-phase per file: copy to `<maps_dir>/.restore.<rand>.<basename>.tmp`
    then `os.replace` over the destination.

    Returns the list of restored basenames (sorted). Raises:

    - `BackupNotFound` if `<ts>` is malformed or the directory does
      not exist (deliberate folding for log-uniformity; the handler
      returns 404 for both).
    - `OSError` if a copy or replace syscall fails. Per-file `.tmp`
      files in `maps_dir` are best-effort cleaned up on failure.

    Partial restore semantics: files copied before the failure remain
    replaced (irreversible). Files at-or-after the failure point retain
    their pre-restore state. Caller should treat OSError as 'restore
    incomplete; manual recovery required'; the activity log records the
    attempt regardless.

    Restore re-creates the named pair (e.g. `studio_v1.pgm` +
    `studio_v1.yaml`) inside `maps_dir`. It does NOT touch `active.pgm`
    / `active.yaml` symlinks — operator activates separately via the
    existing `POST /api/maps/<name>/activate` flow (Option A semantics).
    """
    if not _TS_REGEX.match(ts):
        raise BackupNotFound(ts)

    src_dir = backup_dir / ts
    if not src_dir.exists() or not src_dir.is_dir():
        raise BackupNotFound(ts)

    # Capture every basename in the source verbatim — we do NOT derive
    # `.yaml` from `.pgm` (Mode-A M4 fold; Track E `_yaml_path_for`
    # stays private to `backup.py`). Future map artefacts (B-MAPEDIT)
    # land in the backup unchanged.
    sources: list[Path] = []
    for entry in src_dir.iterdir():
        if not entry.is_file():
            continue
        sources.append(entry)
    sources.sort(key=lambda p: p.name)

    # Defence-in-depth: ensure `maps_dir` exists before we start writing.
    # `maps.set_active` and friends would do this; here we own the
    # write-side (Track E uncoupled-leaves discipline).
    maps_dir.mkdir(parents=True, exist_ok=True, mode=0o750)

    restored: list[str] = []
    for src in sources:
        dest = maps_dir / src.name
        # Two-phase per-file: copy to a randomly-suffixed `.restore.*.tmp`
        # then `os.replace` into place. The random token (64-bit collision
        # space) makes EEXIST impossible, so no retry loop is needed; any
        # OSError is genuine (ENOSPC, EROFS, EACCES) and propagates.
        tmp_path = _new_restore_tmp(maps_dir, src.name)
        try:
            shutil.copy2(src, tmp_path)
        except OSError:
            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()
            raise
        try:
            os.replace(tmp_path, dest)
        except OSError as e:
            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()
            logger.error(
                "map_backup.restore_replace_failed: ts=%s file=%s err=%s",
                ts,
                src.name,
                e,
            )
            raise
        restored.append(src.name)

    return restored


# --- Internal helpers --------------------------------------------------


def _new_restore_tmp(maps_dir: Path, basename: str) -> Path:
    """Random in-flight tmp name inside `maps_dir`. The leading dot keeps
    it out of `maps.list_pairs`; the random token (64-bit collision
    space) defends against a concurrent restore in the same UTC second."""
    import secrets

    token = secrets.token_hex(_RESTORE_TMP_TOKEN_HEX_BYTES)
    return maps_dir / f"{_RESTORE_TMP_PREFIX}{token}.{basename}{_TMP_SUFFIX}"
