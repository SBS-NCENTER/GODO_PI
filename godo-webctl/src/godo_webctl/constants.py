"""
Webctl-internal Tier-1 constants.

Scope: values that are NOT on the wire to the C++ tracker. The wire SSOT
lives in ``protocol.py``; that file is a deliberate one-to-one mirror of
production/RPi5/src/core/constants.hpp + uds_server.cpp + json_mini.cpp
and must stay free of webctl-only knobs.

Anything pinned here is a **deliberate** choice; tests in
``tests/test_constants.py`` pin every value so changes require a visible
diff. CLAUDE.md §6 forbids magic numbers in ``src/`` — every literal in
``src/godo_webctl/`` that is not a local iteration bound or a wire-side
mirror MUST resolve to a constant declared here or a Settings field in
``config.py``.

Leaf module: imports nothing from the package.
"""

from __future__ import annotations

import re
from typing import Final

# --- JWT / auth -----------------------------------------------------------
# HS256 keeps the secret + verify operations inside the FastAPI process —
# no public-key infrastructure needed for a 1-2 user studio host.
JWT_ALGORITHM: Final[str] = "HS256"

# 6 h session window. Long enough that an operator who logs in at the
# start of a recording day does not get bounced; short enough that a
# stolen token has a bounded blast radius.
JWT_TTL_SECONDS: Final[int] = 21600  # 6 h

# bcrypt cost factor. ~300 ms per login on RPi 5 Cortex-A76 — deliberate
# friction against credential-stuffing on a LAN-exposed host. Do NOT
# lower without revisiting the threat model; at 1-2 users / ~1 login per
# day cadence the latency is invisible.
BCRYPT_COST_FACTOR: Final[int] = 12

# --- SSE cadence ----------------------------------------------------------
# Last-pose stream tick: 5 Hz matches the cold-writer publish cadence
# (no benefit polling faster than the tracker updates the seqlock).
SSE_TICK_S: Final[float] = 0.2  # 5 Hz

# Services stream tick: 1 Hz is plenty for systemctl status — service
# state transitions are operator-driven, not high-frequency events.
SSE_SERVICES_TICK_S: Final[float] = 1.0

# Keepalive comment line interval. 15 s is well under typical 60 s
# proxy/browser idle timeouts and short enough that a cold reverse-proxy
# does not buffer past the first frame.
SSE_HEARTBEAT_S: Final[float] = 15.0

# --- Map image cache ------------------------------------------------------
# PGM → PNG conversion takes ~200 ms for a 1024×1024 map. Cache for 5 min
# so back-to-back B-MAP page loads are O(1). Invalidation is mtime-keyed
# (see map_image.render_pgm_to_png).
MAP_IMAGE_CACHE_TTL_S: Final[float] = 300.0

# --- Activity log ---------------------------------------------------------
# In-process ring buffer size. Last 50 actions covers a typical recording
# session; older entries fall off silently. Process restart wipes the
# buffer (documented in CODEBASE.md invariant — in-memory only for P0).
ACTIVITY_BUFFER_SIZE: Final[int] = 50

# Default `n` for /api/activity?n=… when the operator does not specify.
# 5 matches the DASH "last 5 activities" line (FRONT_DESIGN §7.1).
ACTIVITY_TAIL_DEFAULT_N: Final[int] = 5

# --- Journalctl tail ------------------------------------------------------
# Default `n` for /api/local/journal/<svc>?n=… when the operator does not
# specify. 30 lines covers most "what just went wrong" debugging without
# blowing up the response size.
JOURNAL_TAIL_DEFAULT_N: Final[int] = 30

# --- LoginBody field bounds ----------------------------------------------
# Wire-side bounds on /api/auth/login payload. 64 covers the existing
# `ncenter` seed plus any reasonable LDAP migration; 256 leaves headroom
# above bcrypt's 72-byte input limit (longer passwords are silently
# truncated by bcrypt, but we accept them client-side).
LOGIN_USERNAME_MAX_LEN: Final[int] = 64
LOGIN_PASSWORD_MAX_LEN: Final[int] = 256

# --- SSE per-poll UDS timeout --------------------------------------------
# Short — if the tracker stalls, we want the loop to skip a frame, not
# stall the stream. 0.5 s is well under the 1 s services tick and the
# 0.2 s last_pose tick (the latter falls back to skip-on-timeout cleanly
# because the next tick re-queries).
SSE_UDS_TIMEOUT_S: Final[float] = 0.5

# --- Backup-side Tier-1 (relocated from protocol.py per planner M2) ------
# Bound on rename collision retries inside backup.backup_map. Above 9
# means more than 9 backups in the same UTC second, which never happens
# in practice. Lives here because it is webctl-internal — the tracker
# has no opinion on how webctl manages its backup directory.
MAX_RENAME_ATTEMPTS: Final[int] = 9

# --- Multi-map management (Track E, PR-C) --------------------------------
# Map name validator. ASCII only, case-sensitive. Allowed chars:
# letters, digits, underscore, hyphen, dot, parentheses. The FIRST char
# may NOT be a dot — this rejects `..`, `.hidden`, and similar forms that
# would otherwise traverse / shadow filtered hidden files. `/` and
# whitespace are forbidden anywhere.
#
# The reserved name `"active"` passes this regex (so a router-level
# mismatch cannot dodge it) and is rejected separately by the public
# maps.py functions to keep the active-symlink names from colliding with
# a regular map.
#
# `.pgm` / `.yaml` extensions are appended by the caller — names are
# stems. With dot now allowed inside the stem, `Path.stem` / `Path.suffix`
# split at the LAST dot (POSIX convention), so `foo.bar.pgm` → stem
# `foo.bar`, suffix `.pgm`. Operators who mistakenly submit `foo.pgm` as
# a stem will get a saved pair `foo.pgm.{pgm,yaml}` — semantic warning
# is the SPA's job, not the regex's.
MAPS_NAME_MAX_LEN: Final[int] = 64
MAPS_NAME_REGEX: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9_()-][a-zA-Z0-9._()-]{0,63}$",
)

# Reserved basename used for the active-pair symlink pair
# (`active.pgm` + `active.yaml`). Operators cannot upload a regular map
# with this name — `set_active`/`delete_pair` reject it before any FS op.
MAPS_ACTIVE_BASENAME: Final[str] = "active"

# Advisory `flock(LOCK_EX)` target inside `cfg.maps_dir`. The leading dot
# keeps it out of `list_pairs` (which only enumerates `<stem>.pgm` +
# `<stem>.yaml` pairs).
MAPS_ACTIVATE_LOCK_BASENAME: Final[str] = ".activate.lock"

# Maximum bytes to read from a netpbm `P5` PGM header. Any practical map
# header (P5\nW H\nMAXVAL\n) fits in well under 64 ASCII bytes; bounding
# the read makes `read_pgm_dimensions` safe against pathologically large
# PGM files (e.g. a 1 GB sparse file — we never stream pixel data).
PGM_HEADER_MAX_BYTES: Final[int] = 64

# --- PR-DIAG (Track B-DIAG) — diagnostics page constants -----------------
# Resources sub-payload cache TTL — `/sys/class/thermal/...` and
# `/proc/meminfo` reads cost ~10 µs each. With 5 Hz × 4 reads/tick =
# 20 reads/s, the cache reduces this to ~1/s without affecting freshness
# (operator-visible stat is "%-loaded" which doesn't move that fast).
RESOURCES_CACHE_TTL_S: Final[float] = 1.0

# journald tail server-side cap. 500 lines × ~2 KB worst-case = 1 MB
# response — well within FastAPI's default budget. SPA's <input> mirrors
# this max for defense in depth.
LOGS_TAIL_MAX_N: Final[int] = 500

# Default `n` for /api/logs/tail when the operator does not specify.
LOGS_TAIL_DEFAULT_N: Final[int] = 50

# Filesystem paths read by `resources.snapshot()`. Pinned here so the
# tests can monkeypatch them without touching real /sys or /proc.
THERMAL_ZONE_PATH: Final[str] = "/sys/class/thermal/thermal_zone0/temp"
MEMINFO_PATH: Final[str] = "/proc/meminfo"

# --- Track B-CONFIG (PR-CONFIG-β) — config-edit endpoints ----------------
# `/api/config` and `/api/config/schema` UDS round-trip timeout. Short
# read; tracker simply walks its constexpr array and emits ~2/7 KiB.
CONFIG_GET_UDS_TIMEOUT_S: Final[float] = 0.5

# `/api/config` PATCH UDS round-trip timeout. The tracker `set_config`
# handler does an `fsync` on /etc partition (~10 ms RPi5 SD), then a
# rename + a flag touch — generous 2 s ceiling against worst-case fs
# stall while keeping the SPA's "submitting…" spinner snappy.
CONFIG_SET_UDS_TIMEOUT_S: Final[float] = 2.0

# Schema cache TTL. The C++ schema is constexpr — never changes within
# a tracker boot — so any positive cache window means the SPA's repeat
# `/api/config/schema` calls become O(1). 60 s lets a fresh tracker
# boot propagate within one cache window.
CONFIG_SCHEMA_CACHE_TTL_S: Final[float] = 60.0

# Server-side ceiling on `PATCH /api/config` body size. Single-key
# payload is ~50 B in practice; 1 KiB stops a malicious operator from
# DoS-ing the parser with a multi-MB JSON. Mirror in Pydantic field
# bound below.
CONFIG_PATCH_BODY_MAX_BYTES: Final[int] = 1024

# Per-value text length cap. The C++ validator independently enforces
# 256 (validate.cpp::kStringValueMaxLen); this is the webctl-side
# defence-in-depth pre-check.
CONFIG_VALUE_TEXT_MAX_LEN: Final[int] = 256

# Default flag-file location. Override via
# GODO_WEBCTL_RESTART_PENDING_PATH.
RESTART_PENDING_FLAG_PATH: Final[str] = "/var/lib/godo/restart_pending"

# --- Single-instance lock (CLAUDE.md §6) ---------------------------------
# Sentinel filename for the defence-in-depth ``flock(LOCK_EX | LOCK_NB)``
# in backup.backup_map. Lives inside ``cfg.backup_dir``. Concurrent
# invocation is already prevented at runtime by the webctl pidfile lock
# (invariant (e)); this is a second line of defence so a future operator
# running ``backup_map`` directly from a script (bypassing webctl) cannot
# corrupt the directory.
BACKUP_LOCK_FILENAME: Final[str] = ".lock"

# --- Track B-SYSTEM PR-2 — service observability -------------------------
# `system_services.snapshot()` cache TTL. 1 s matches the SPA's polling
# cadence so a single 1 Hz poll skews at most by the inflight call's
# subprocess latency (~30-50 ms per `systemctl show` call on RPi 5;
# planner estimate, sanity-check on the Diagnostics jitter dashboard).
# Per-service degradation: a `systemctl show` failure for one unit
# yields `active_state="unknown"` for that entry; the aggregate
# endpoint always returns 200.
SYSTEM_SERVICES_CACHE_TTL_S: Final[float] = 1.0

# --- PR-B (Track B-SYSTEM PR-B) — process monitor + extended resources ---
# Filesystem root for `/proc` walks. Pinned here so tests can monkeypatch
# it onto a tmp_path-anchored fake `/proc` tree without touching real
# kernel state.
PROC_PATH: Final[str] = "/proc"

# `/proc/stat` aggregate-CPU + per-core jiffy counters. Read by both
# `processes.ProcessSampler` (aggregate "total CPU jiffies" denominator)
# and `resources_extended.ResourcesExtendedSampler` (per-core delta).
PROC_STAT_PATH: Final[str] = "/proc/stat"

# SSE tick for `/api/system/processes/stream` and
# `/api/system/resources/extended/stream`. 1 Hz matches the operator's
# debug-loop cadence (htop refreshes at ~1.5 s by default; we use 1 s
# to feel slightly more responsive while still being sub-htop on
# `/proc` syscalls — see processes.py "Expected cost").
SSE_PROCESSES_TICK_S: Final[float] = 1.0
SSE_RESOURCES_EXTENDED_TICK_S: Final[float] = 1.0

# --- Track B-MAPEDIT — POST /api/map/edit body + paint constants --------
# Server-side ceiling on the multipart `mask` part. 4 MiB is generous
# vs. a 1024×1024 single-channel PNG (≤ 1 MB after zlib) but stops a
# malicious operator from DoS-ing the mask decoder with a multi-MB
# payload. SPA's `MASK_PNG_MAX_BYTES` mirror enforces the same cap
# client-side so the upload never starts.
MAP_EDIT_MASK_PNG_MAX_BYTES: Final[int] = 4_194_304  # 4 MiB

# Canonical "free" pixel value the brush writes into masked cells. 254
# matches the ROS map_server `free_thresh` default of 0.196 × 255 ≈ 50
# (so a value above 254 × (1 - 0.196) = 204 is "free"); 254 is the
# project-wide "fully free" sentinel. Choosing 255 would clash with
# uninitialised PGM cells; 254 is unambiguous.
MAP_EDIT_FREE_PIXEL_VALUE: Final[int] = 254

# Greyscale mask threshold: a mask pixel value `>= 128` means paint.
# 128 is the conventional midpoint of the 0..255 range; the bright/
# dark split is operator-intuitive ("white = erase, black = leave
# alone"). RGBA masks use alpha > 0 instead per `map_edit.py`.
MAP_EDIT_PAINT_THRESHOLD: Final[int] = 128

# --- Track B-MAPEDIT-2 — POST /api/map/origin body + bound constants ----
# Server-side ceiling on the JSON body. A canonical body is ~80 B
# (`{"x_m":-1.5,"y_m":-2.0,"mode":"absolute"}`). 256 covers
# floating-point representations with full repr precision plus modest
# whitespace; bigger than that is malformed or DoS. Mirrors the
# discipline of `CONFIG_PATCH_BODY_MAX_BYTES` (1 KiB) but tighter
# because the origin payload is even smaller.
ORIGIN_BODY_MAX_BYTES: Final[int] = 256

# Magnitude bound on `x_m` / `y_m` (after delta resolution). Studio is
# ~10 m square; 1 km bound covers the studio (~100×) plus headroom for
# shared-frame debug scenarios with multiple studios in the same world
# frame. Values >1 km are flagged as operator typos rather than valid
# geometry. Reviewer N2 nudge to 1 000.0 (vs. the planner's initial
# 10 000.0 default) accepted by Parent 2026-04-30 KST.
ORIGIN_X_Y_ABS_MAX_M: Final[float] = 1_000.0

# Korean transition-warning strings keyed by `(svc, transition)`. Used
# by the 409-translation arm of `local_service_action` and
# `system_service_action` (both share `services.control()` underneath).
# Particle convention (M3 fold): Korean reading convention — read each
# romanized name as a Korean speaker would pronounce it, then apply the
# 받침 rule to the Korean syllable.
#
# - godo-tracker      → 트래커  (last syllable: 커, no 받침) → 가
# - godo-webctl       → 웹씨티엘 (last syllable: 엘, ㄹ 받침) → 이
# - godo-irq-pin      → 아이알큐 핀 (last syllable: 핀, ㄴ 받침) → 이
SERVICE_TRANSITION_MESSAGES_KO: Final[dict[tuple[str, str], str]] = {
    ("godo-tracker", "starting"): "godo-tracker가 시동 중입니다. 잠시 후 다시 시도해주세요.",
    ("godo-tracker", "stopping"): "godo-tracker가 종료 중입니다. 잠시 후 다시 시도해주세요.",
    ("godo-webctl", "starting"): "godo-webctl이 시동 중입니다. 잠시 후 다시 시도해주세요.",
    ("godo-webctl", "stopping"): "godo-webctl이 종료 중입니다. 잠시 후 다시 시도해주세요.",
    ("godo-irq-pin", "starting"): "godo-irq-pin이 시동 중입니다. 잠시 후 다시 시도해주세요.",
    ("godo-irq-pin", "stopping"): "godo-irq-pin이 종료 중입니다. 잠시 후 다시 시도해주세요.",
}

# --- issue#14 — mapping pipeline ----------------------------------------
# Mapping mode coordinator's runtime directory (single-writer = webctl).
# /run is tmpfs; webctl creates the dir at runtime via
# mapping._write_run_envfile, NOT at install-time (M2 fix).
MAPPING_RUNTIME_DIR_DEFAULT: Final[str] = "/run/godo/mapping"

# Subdirectory inside cfg.maps_dir where the preview PGM lands. Hidden
# (dot-prefixed) so the multi-map enumerator (`maps.list_pairs`) skips it
# (already does — MAPS_NAME_REGEX requires non-dot first char).
MAPPING_PREVIEW_SUBDIR: Final[str] = ".preview"

# Container name (fixed; see decision D4 — single instance only).
MAPPING_CONTAINER_NAME: Final[str] = "godo-mapping"

# systemd template instance name (fixed; see decision D4).
MAPPING_UNIT_NAME: Final[str] = "godo-mapping@active.service"

# Default Docker image tag — overridable via env-var
# GODO_WEBCTL_MAPPING_IMAGE_TAG for dev hosts that build with a different
# tag.
MAPPING_IMAGE_TAG_DEFAULT: Final[str] = "godo-mapping:dev"

# Polling cadence for the Mapping monitor SSE producer. 1 Hz = 1.0 s; the
# parity comment with the frontend MAPPING_STATUS_POLL_MS = 1000 (ms) is
# load-bearing — both surfaces tick at the same rate.
MAPPING_MONITOR_TICK_S: Final[float] = 1.0

# Singleton-ticker idle-grace before stopping after the last subscriber
# drops (M4 broadcast pattern). Avoids thrashing the ticker on rapid
# reconnects (e.g. operator switching tabs).
MAPPING_MONITOR_IDLE_GRACE_S: Final[float] = 5.0

# Tracker-stop window before mapping-start gives up. systemctl stop +
# kernel close-on-last-fd of /dev/ttyUSBn typically completes < 500 ms;
# 5 s is generous.
MAPPING_TRACKER_STOP_TIMEOUT_S: Final[float] = 5.0

# Container-start polling window — `docker run` returns immediately but
# the entrypoint takes ~3-4 s to source ROS overlays + start nodes.
MAPPING_CONTAINER_START_TIMEOUT_S: Final[float] = 8.0

# Container-stop window. Ordering invariant (M5 fix):
#   docker stop --time grace (10s) < TimeoutStopSec (20s) < webctl_timeout (25s)
# so the trap's map_saver_cli save (~2-5 s) completes before any layer
# escalates to SIGKILL.
MAPPING_CONTAINER_STOP_TIMEOUT_S: Final[float] = 25.0

# `docker inspect` polling cadence inside the start/stop wait loops.
MAPPING_DOCKER_INSPECT_POLL_S: Final[float] = 0.25

# Default n for /api/mapping/journal?n=…
MAPPING_JOURNAL_TAIL_DEFAULT_N: Final[int] = 50
MAPPING_JOURNAL_TAIL_MAX_N: Final[int] = 500

# Map name regex (L5 inner-char set verbatim — `,` allowed; C5 tightening
# applied — leading-dot REJECTED). Operator-locked decision 2026-05-01:
# the L5 wording would accept `.foo` but a leading-dot map name produces
# `/var/lib/godo/maps/.foo.pgm`, which `MAPS_NAME_REGEX` (used by
# `maps.list_pairs`) silently filters out — the operator would never see
# the new map in Map > Overview to activate it. Operator confirmed
# "leading dot은 거부하자. 숨김 파일같은 경우가 있을 수 있으니". Pattern
# below: first char ∈ {A-Z, a-z, 0-9, _, (, ), -}; subsequent chars also
# allow `.` and `,`; total 1..64 chars. Path traversal still defended in
# depth via `MAPPING_RESERVED_NAMES` + realpath containment.
MAPPING_NAME_REGEX: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9_()-][A-Za-z0-9._()\-,]{0,63}$",
)
MAPPING_NAME_MAX_LEN: Final[int] = 64

# Reserved names rejected at public-API layer regardless of regex match.
MAPPING_RESERVED_NAMES: Final[frozenset[str]] = frozenset({".", "..", "active"})

# `docker stats --no-stream` subprocess timeout. Slow when first warming
# the cgroups; 3 s is enough.
MAPPING_DOCKER_STATS_TIMEOUT_S: Final[float] = 3.0

# `docker inspect` subprocess timeout. Always fast.
MAPPING_DOCKER_INSPECT_TIMEOUT_S: Final[float] = 2.0

# `du -sb` subprocess timeout for the in-progress preview PGM size.
MAPPING_DU_TIMEOUT_S: Final[float] = 2.0
