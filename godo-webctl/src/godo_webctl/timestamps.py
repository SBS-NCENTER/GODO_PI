"""KST timestamp helpers — single source for all human-readable
timestamps emitted by godo-webctl.

Project convention (see `.claude/memory/feedback_timestamp_kst_convention.md`
+ CLAUDE.md §6 "Date + time stamps in date-bearing SSOT entries"):

- All operator-facing timestamps (filenames, sidecar JSON metadata,
  pending-flag bodies, mapping completion records) are written in KST
  via `ZoneInfo("Asia/Seoul")` — explicit, host-TZ-independent.
- Filename forms drop the offset suffix (host-KST convention) — see
  `DERIVED_TS_STRFTIME` and `BACKUP_DIR_STRFTIME`.
- ISO 8601 forms keep the offset (`+09:00`) so machine readers cannot
  misinterpret them as UTC.

Tracker-side (production/RPi5) has its own equivalent in
`production/RPi5/src/godo_smoke/timestamp.cpp` — keep both in sync."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

KST: Final[ZoneInfo] = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """Return current time as a tz-aware datetime in KST.

    Always KST regardless of host TZ; production host happens to be on
    KST already, but unit tests under macOS / CI may not be."""
    return datetime.now(KST)


def kst_iso_seconds() -> str:
    """ISO 8601 second-resolution timestamp with explicit KST offset
    (`2026-05-04T17:15:30+09:00`). Used by JSON metadata bodies (mapping
    completion, restart-pending flag, sidecar `created`)."""
    return now_kst().isoformat(timespec="seconds")
