"""
Track B-CONFIG (PR-CONFIG-β) — Python mirror of the C++ tracker's
``core/restart_pending`` flag manager.

The flag is a sentinel file at ``cfg.restart_pending_path`` (default
``/var/lib/godo/restart_pending``). Existence semantics:

  - Tracker touches the file on every successful ``set_config`` whose
    ``reload_class != "hot"`` (atomic write through C++
    ``touch_pending_flag``).
  - Tracker clears the file at boot, AFTER ``Config::load()`` succeeds
    and BEFORE thread spawn (TM10 / TM11 ordering pin in main.cpp).

Webctl reads via ``is_pending(flag_path)`` for the
``GET /api/system/restart_pending`` endpoint and the SPA banner.
The C++ tracker is authoritative — this module does NOT mirror the
write path; the tracker owns the file. (The earlier α plan considered
defence-in-depth touch from webctl on PATCH success; PR-CONFIG-β scope
fold dropped that — the tracker's UDS handler completes the touch on
the response path before returning, no defence-in-depth needed.)
"""

from __future__ import annotations

from pathlib import Path


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
