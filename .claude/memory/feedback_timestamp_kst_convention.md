---
name: All operator-facing timestamps are KST, not UTC
description: Project-wide convention locked twenty-third-session opening (2026-05-04 KST). All human-readable timestamps emitted by godo-webctl + godo-tracker — derived map filenames, backup directory names, sidecar JSON `created` fields, mapping-completion records, restart-pending flag bodies, godo_smoke session-log headers — use KST via explicit `ZoneInfo("Asia/Seoul")` (or `localtime_r` on the C++ side, host-tz fixed to KST). UTC is forbidden for these surfaces.
type: feedback
---

All operator-facing timestamps in godo-webctl and the godo-tracker
production binary are KST (Korea Standard Time, GMT+9). UTC is forbidden
for any surface the operator reads as a human (filenames, log lines,
sidecar metadata, `cat`-able pending-flag bodies, session-log headers).

**Why:** the production host (`news-pi01`) is fixed to KST, every
operator who consumes these artefacts works in KST, and CLAUDE.md §6
already prescribes KST for date-bearing SSOT entries. PR #81 / B-MAPEDIT-3
cascade analysis surfaced derived-map filenames in UTC (`...20260504-041104-test01.pgm`
emitted at KST 13:11:04) — operator could not match filename clock to
wallclock without mental conversion. Lock corrected at twenty-third-session
opening, 2026-05-04 KST.

**How to apply:**

1. **Filename forms** — `YYYYMMDD-HHMMSS` (derived maps) /
   `YYYYMMDDTHHMMSS` (backup directories). Drop the trailing `Z`
   (which used to mark UTC). No offset suffix — host-KST is the
   convention; tests inject explicit datetimes.
2. **JSON metadata + log line forms** — ISO 8601 with explicit `+09:00`
   offset (`2026-05-04T17:15:30+09:00`). Never bare `Z` (UTC marker).
3. **Python implementation** — use the canonical helper in
   `godo-webctl/src/godo_webctl/timestamps.py`:
   - `now_kst()` for tz-aware `datetime` in KST.
   - `kst_iso_seconds()` for ISO 8601 strings with `+09:00`.
   - Both bind explicit `ZoneInfo("Asia/Seoul")` so unit tests on
     macOS / CI hosts produce the right value regardless of host TZ.
4. **C++ implementation** — `production/RPi5/src/godo_smoke/timestamp.cpp`
   uses `localtime_r` (relies on host TZ being KST, which is fixed).
   Format strings drop the `Z` suffix and use `+09:00` for ISO.
   Function names (`utc_timestamp_compact`, `utc_timestamp_iso`) are
   retained for ABI stability — bodies emit KST.
5. **Backward-compat regex** — `map_backup.py::_TS_REGEX` accepts both
   `[0-9]{8}T[0-9]{6}Z?$` so pre-convention UTC-suffixed backup
   directories on disk remain readable. New writes never emit `Z`.
6. **systemd journal + Python `logging` `%(asctime)s`** — already KST
   on the production host (host TZ default). No code change needed
   there.

**Out of scope:**

- Internal monotonic / steady_clock instants (e.g. `time.monotonic_ns()`,
  `std::chrono::steady_clock`) — these are duration sources, not
  wallclock. Leave alone.
- Byte-stream protocol fields where the consumer expects UTC by spec
  (FreeD over UDP — none currently). If any new protocol consumer
  arrives demanding UTC, document the exception explicitly here.

**Cross-references:**

- `CLAUDE.md` §6 — date+time stamp rules in date-bearing SSOT entries.
- `godo-webctl/src/godo_webctl/timestamps.py` — canonical helper.
- `production/RPi5/src/godo_smoke/timestamp.cpp` — tracker counterpart.
- `/doc/issue30_yaml_normalization_design_analysis.md` §7 row 10 —
  initial lock decision context.
