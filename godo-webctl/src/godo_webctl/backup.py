"""
Atomic ``.pgm + .yaml`` map backup.

Two-phase rename for crash-safety:
  1. ``shutil.copy2`` both files into ``<backup_dir>/<UTC ts>.tmp/``.
  2. ``os.rename`` to ``<backup_dir>/<UTC ts>/`` (atomic on the same FS).

Same-FS guarantee: ``<ts>.tmp/`` and ``<ts>/`` are both children of
``backup_dir``, so ``os.rename`` is always atomic by construction.

Concurrency invariant: ``backup_map`` is single-writer at runtime
(uvicorn ``workers=1`` + handler single-await). Concurrent invocation is
undefined; collision retry exists only for back-to-back calls in the
same UTC second by a SINGLE writer.

The ``.yaml`` path is derived from the ``.pgm`` path via the same rule the
tracker uses (``occupancy_grid.cpp::yaml_path_for`` at L253-258): strip
the trailing ``.pgm`` and append ``.yaml``. Mirrored here so a future
operator typo (``studio_v1`` vs. ``studio_v1.pgm``) fails fast on the
HTTP response, not silently in the tracker.
"""

from __future__ import annotations

import errno
import fcntl
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .constants import BACKUP_LOCK_FILENAME, MAX_RENAME_ATTEMPTS


class BackupError(Exception):
    """Raised by ``backup_map`` for any documented failure mode."""


def _yaml_path_for(pgm_path: Path) -> Path:
    """Mirror of production/RPi5/src/localization/occupancy_grid.cpp:253-258."""
    s = str(pgm_path)
    if len(s) >= 4 and s[-4:] == ".pgm":
        return Path(s[:-4] + ".yaml")
    return Path(s + ".yaml")


def backup_map(
    map_path: Path,
    backup_dir: Path,
    *,
    now: datetime | None = None,
) -> Path:
    """
    Copy ``map_path`` (the ``.pgm``) and its sibling ``.yaml`` into
    ``backup_dir/<UTC ts>/``. Returns the final directory path on success.

    Raises ``BackupError`` with one of:
      - ``map_path_not_found``       — either source file is missing
      - ``backup_dir_unwritable``    — cannot create / mkdir the parent
      - ``copy_failed: <errno-string>`` — a copy or rename syscall failed
      - ``collision_exhausted``      — ``MAX_RENAME_ATTEMPTS`` collisions
      - ``concurrent_backup_in_progress`` — another writer holds the
        defence-in-depth flock on ``backup_dir/.lock``. Mapped to
        HTTP 409 in app.py. Reachable only if the webctl pidfile lock
        invariant (e) is broken.
    """
    yaml_path = _yaml_path_for(map_path)
    if not map_path.is_file() or not yaml_path.is_file():
        raise BackupError("map_path_not_found")

    try:
        # Defence-in-depth (S6): systemd's StateDirectory normally creates
        # /var/lib/godo with mode 0750, but tests bypass systemd.
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    except OSError as e:
        raise BackupError("backup_dir_unwritable") from e

    # Acquire the defence-in-depth flock on ``backup_dir/.lock``. The
    # file is created on first use, persists between calls (the kernel
    # releases the lock state when the FD closes — file presence is
    # NOT the lock signal), and is intentionally NOT unlinked at the
    # end so back-to-back webctl restarts do not race the lock setup.
    lock_path = backup_dir / BACKUP_LOCK_FILENAME
    lock_fd = os.open(
        str(lock_path),
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC,
        0o644,
    )
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise BackupError("concurrent_backup_in_progress") from e

        if now is None:
            now = datetime.now(UTC)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        base = backup_dir / stamp
        tmp_dir = backup_dir / f"{stamp}.tmp"

        # If a prior crash left a .tmp/ at the same stamp, blow it away —
        # nothing inside is committed (rename has not happened yet by definition).
        shutil.rmtree(tmp_dir, ignore_errors=True)

        try:
            tmp_dir.mkdir(mode=0o750)
            shutil.copy2(map_path, tmp_dir / map_path.name)
            shutil.copy2(yaml_path, tmp_dir / yaml_path.name)
        except OSError as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise BackupError(f"copy_failed: {e}") from e

        # Retry-on-rename (M5): TOCTOU-safe, no pre-check.
        for attempt in range(MAX_RENAME_ATTEMPTS):
            target = base if attempt == 0 else Path(f"{base}_{attempt + 1}")
            try:
                os.rename(tmp_dir, target)
                return target
            except OSError as e:
                if e.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    raise BackupError(f"copy_failed: {e}") from e
                # Collision; try the next suffix.

        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise BackupError("collision_exhausted")
    finally:
        # ``flock`` is auto-released on close, but unlock + close
        # explicitly so the order is unambiguous and a stray reference
        # (none today) cannot extend the hold.
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
