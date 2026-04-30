"""
Track B-CONFIG (PR-CONFIG-β) — Python mirror of the C++ tracker's
``core/restart_pending`` flag manager.

The flag is a sentinel file at ``cfg.restart_pending_path`` (default
``/var/lib/godo/restart_pending``). Existence semantics:

  - Tracker touches the file on every successful ``set_config`` whose
    ``reload_class != "hot"`` (atomic write through C++
    ``touch_pending_flag``).
  - Webctl ALSO touches the file on a successful ``POST /api/map/edit``
    (Track B-MAPEDIT, Phase 4.5 P2). The map editor does NOT route
    through the tracker UDS — it rewrites the active PGM file directly
    — so webctl must drive the sentinel itself for the SPA's
    `RestartPendingBanner` to flip.
  - Tracker clears the file at boot, AFTER ``Config::load()`` succeeds
    and BEFORE thread spawn (TM10 / TM11 ordering pin in main.cpp).

Webctl reads via ``is_pending(flag_path)`` for the
``GET /api/system/restart_pending`` endpoint and the SPA banner.
The asymmetry is contractual: webctl never clears, tracker never reads
the touch path. Both processes run as user `ncenter` (StateDirectory=
godo) so the sentinel file's writers and the clearer share a uid — no
cross-uid permission concern.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

# Sentinel file mode. World-readable so a future read-only diagnostic
# helper running as another uid can inspect it. Mirror of the C++
# tracker's `touch_pending_flag` (which writes 0644).
_FLAG_FILE_MODE = 0o644
_TMP_SUFFIX = ".tmp"


def is_pending(flag_path: Path) -> bool:
    """Return True iff the flag file exists.

    No content inspection — the file is a presence sentinel. ENOENT and
    permission errors during stat fail closed (return False); the flag
    cannot be observed without read access, and the SPA simply does not
    show the banner. Operator failure modes (no /var/lib/godo) get
    caught by the systemd service file's ReadWritePaths.
    """
    try:
        return flag_path.exists()
    except OSError:
        return False


def touch(flag_path: Path) -> None:
    """Atomically create-or-update the sentinel file at ``flag_path``.

    Implementation: open a tmp file in the SAME directory at mode
    `_FLAG_FILE_MODE = 0o644`, write a ``YYYY-MM-DDTHH:MM:SSZ\\n``-style
    UTC stamp body (informational; readers must not inspect the body
    per `is_pending` semantics), then `os.replace` onto the target.
    Same-FS guarantee: the tmp lives in the same directory, so rename
    is atomic.

    Idempotent: a second call simply replaces the existing file. The
    parent directory is `mkdir(parents=True, exist_ok=True)` at mode
    0750 so the systemd `StateDirectory=godo` default works on a fresh
    deployment without pre-creating intermediate dirs.

    Raises ``OSError`` from the underlying syscalls (ENOSPC, EROFS,
    EACCES, ...) — caller maps to HTTP 500. The tmp is cleaned up on
    failure paths.
    """
    flag_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    tmp = flag_path.with_suffix(flag_path.suffix + _TMP_SUFFIX)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FLAG_FILE_MODE)
    try:
        try:
            # Body is informational. Mirror of the tracker's payload
            # shape ("ISO-8601 UTC + LF") so an operator who `cat`s the
            # file sees a meaningful stamp regardless of which writer
            # touched it last.
            from datetime import UTC, datetime

            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ\n")
            with os.fdopen(fd, "wb", closefd=True) as f:
                f.write(stamp.encode("ascii"))
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        try:
            os.replace(tmp, flag_path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
