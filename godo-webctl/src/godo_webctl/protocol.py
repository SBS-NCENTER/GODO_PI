"""
UDS wire-protocol constants. Mirrors a subset of the C++ Tier-1 invariants
in production/RPi5/src/core/{constants.hpp, rt_flags.hpp} that appear ON
THE WIRE (request max bytes, command names, mode names, error codes).

This module deliberately does NOT mirror tracker-internal Tier-1: FreeD
packet layout (FREED_*), RT cadence (FRAME_PERIOD_NS), AMCL kernel sizes
(PARTICLE_BUFFER_MAX, EDT_MAX_CELLS), GPIO debounce window
(GPIO_DEBOUNCE_NS), shutdown timeout (SHUTDOWN_POLL_TIMEOUT_MS). Those
are C++-only and webctl never sees them.

Cross-language drift policy: see godo-webctl/CODEBASE.md invariant (b).
SSOT for the wire format is production/RPi5/doc/uds_protocol.md.
"""

from __future__ import annotations

from typing import Final

from .constants import MAPS_NAME_REGEX

# --- Bytes on the wire (mirrors constants.hpp) ----------------------------
# UDS_REQUEST_MAX_BYTES: production/RPi5/src/core/constants.hpp:54
UDS_REQUEST_MAX_BYTES: Final[int] = 4096

# Client-side response read cap. Matches the server's request cap; responses
# are far smaller in practice (~30 bytes), but we share the bound so the
# read loop has a single ceiling.
UDS_RESPONSE_READ_BUFSIZE: Final[int] = 4096

# Track D — wider read cap for `get_last_scan` whose JSON reply spans
# up to ~14 KiB (720 rays × 2 doubles × ~10 chars + scalar header).
# 32 KiB scratch leaves >2× headroom while staying well under the C++
# formatter's 24 KiB scratch (production/RPi5/src/core/constants.hpp::
# JSON_SCRATCH_BYTES). Only get_last_scan reads with this wider cap;
# all other commands keep UDS_RESPONSE_READ_BUFSIZE.
LAST_SCAN_RESPONSE_CAP: Final[int] = 32768

# --- Command names (mirrors uds_server.cpp:201,206,212 — req.cmd compares) -
CMD_PING: Final[str] = "ping"  # uds_server.cpp:201
CMD_GET_MODE: Final[str] = "get_mode"  # uds_server.cpp:206
CMD_SET_MODE: Final[str] = "set_mode"  # uds_server.cpp:212
# Track B (Phase 4-2 D Track B) — uds_server.cpp `get_last_pose` branch
# below the `set_mode` branch. Field-name SSOT is the format string in
# production/RPi5/src/uds/json_mini.cpp::format_ok_pose; LAST_POSE_FIELDS
# below is regex-pinned against that source by tests/test_protocol.py.
CMD_GET_LAST_POSE: Final[str] = "get_last_pose"
# Track D (Phase 4.5+ Track D) — uds_server.cpp `get_last_scan` branch.
# Field-name SSOT is the LastScan struct in production/RPi5/src/core/
# rt_types.hpp; LAST_SCAN_HEADER_FIELDS below is regex-pinned against
# that source by tests/test_protocol.py.
CMD_GET_LAST_SCAN: Final[str] = "get_last_scan"
# PR-DIAG (Track B-DIAG) — uds_server.cpp `get_jitter` / `get_amcl_rate`
# branches. Field-name SSOT is the format strings in
# production/RPi5/src/uds/json_mini.cpp::format_ok_jitter +
# format_ok_amcl_rate. JITTER_FIELDS / AMCL_RATE_FIELDS below are
# regex-pinned against those sources by tests/test_protocol.py.
# Mode-A M2 fold: command name uses `amcl_rate` (renamed from
# `scan_rate` per the reviewer — the metric measures AMCL iteration
# cadence, not raw LiDAR scan rate; in Idle the LiDAR is parked and
# the rate is 0 Hz by design).
CMD_GET_JITTER: Final[str] = "get_jitter"
CMD_GET_AMCL_RATE: Final[str] = "get_amcl_rate"
# Track B-CONFIG (PR-CONFIG-β) — config edit pipeline. Wire shape lives
# in production/RPi5/doc/uds_protocol.md §C.8 / §C.9 / §C.10. The C++
# tracker's `apply_set` returns `{"ok":true,"reload_class":"hot|restart|recalibrate"}`
# on success or `{"ok":false,"err":"<code>","detail":"<text>"}` on failure.
CMD_GET_CONFIG: Final[str] = "get_config"
CMD_GET_CONFIG_SCHEMA: Final[str] = "get_config_schema"
CMD_SET_CONFIG: Final[str] = "set_config"

# Reload-class enum strings — mirror json_mini.cpp's `format_ok_config_set`
# output and config_schema.hpp's `reload_class_to_string`.
RELOAD_CLASS_HOT: Final[str] = "hot"
RELOAD_CLASS_RESTART: Final[str] = "restart"
RELOAD_CLASS_RECALIBRATE: Final[str] = "recalibrate"

VALID_RELOAD_CLASSES: Final[frozenset[str]] = frozenset(
    {RELOAD_CLASS_HOT, RELOAD_CLASS_RESTART, RELOAD_CLASS_RECALIBRATE},
)

# Set-config response field order. SOLE Python mirror of the JSON keys
# emitted by `format_ok_config_set` in json_mini.cpp. `ok` is the JSON-
# level success flag (UdsServerRejected is raised on `ok: false`); not
# in this tuple per the same convention as LAST_POSE_FIELDS.
SET_CONFIG_RESPONSE_FIELDS: Final[tuple[str, ...]] = ("reload_class",)

# Schema row keys (mirrors `format_ok_config_get_schema` per row + the
# `ConfigSchemaRow` Python NamedTuple in `config_schema.py`). Pinned
# against the parser by `tests/test_config_schema.py`.
CONFIG_SCHEMA_ROW_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "type",
    "min",
    "max",
    "default",
    "reload_class",
    "description",
)

# Wider read cap for `get_config_schema` whose JSON reply spans ~7 KiB
# (37 rows × ~200 B). 16 KiB leaves >2× headroom while staying under
# the C++ scratch ceiling (24 KiB). Other config commands keep the
# default 4 KiB.
CONFIG_SCHEMA_RESPONSE_CAP: Final[int] = 16384

# --- Mode names (mirrors json_mini.cpp:119-121 mode_to_string + :127-129) -
MODE_IDLE: Final[str] = "Idle"  # json_mini.cpp:119, :127
MODE_ONESHOT: Final[str] = "OneShot"  # json_mini.cpp:120, :128
MODE_LIVE: Final[str] = "Live"  # json_mini.cpp:121, :129

VALID_MODES: Final[frozenset[str]] = frozenset({MODE_IDLE, MODE_ONESHOT, MODE_LIVE})

# --- Track B: get_last_pose response field order --------------------------
# SOLE Python mirror of the field names embedded in the C++ wire format
# string. Order MUST match production/RPi5/src/uds/json_mini.cpp::
# format_ok_pose verbatim. tests/test_protocol.py reads the C++ source as
# text, regex-extracts field names from the format-string literal, and
# asserts byte-equal against this tuple — so editing one side without the
# other fails the drift pin.
#
# `ok` is intentionally NOT in this tuple: it is the JSON-level success
# flag (always true for get_last_pose; error responses use the standard
# {"ok":false,"err":...} shape and are surfaced via UdsError).
LAST_POSE_FIELDS: Final[tuple[str, ...]] = (
    "valid",
    "x_m",
    "y_m",
    "yaw_deg",
    "xy_std_m",
    "yaw_std_deg",
    "iterations",
    "converged",
    "forced",
    "published_mono_ns",
)

# --- Track D: get_last_scan response field order --------------------------
# Mirror of the JSON wire payload emitted by format_ok_scan in
# production/RPi5/src/uds/json_mini.cpp. Pinned in two complementary
# places: (1) test_last_scan_header_fields_match_cpp_source extracts
# field NAMES from the LastScan struct in rt_types.hpp and asserts
# set-equality (catches name drift / additions / removals), (2)
# test_last_scan_wire_order_matches_format_ok_scan regex-extracts the
# JSON keys from format_ok_scan's snprintf format string and asserts
# tuple-equality with this Python tuple (catches wire-order drift).
# The two arrays (angles_deg, ranges_m) appear at the tail; the SPA
# filters individual ray invalid-sentinels (0.0) during render.
#
# `ok` is intentionally NOT in this tuple — same reason as LAST_POSE_FIELDS.
LAST_SCAN_HEADER_FIELDS: Final[tuple[str, ...]] = (
    "valid",
    "forced",
    "pose_valid",
    "iterations",
    "published_mono_ns",
    "pose_x_m",
    "pose_y_m",
    "pose_yaw_deg",
    "n",
    "angles_deg",
    "ranges_m",
)

# Mirror of production/RPi5/src/core/constants.hpp::LAST_SCAN_RANGES_MAX.
# Defines both the C++ array bound and the JSON formatter's per-array
# cap. SPA's lib/protocol.ts has a parallel constant; all three must
# agree (drift detection: by inspection during code review + the
# regex pin below).
LAST_SCAN_RANGES_MAX_PYTHON_MIRROR: Final[int] = 720

# --- PR-DIAG: get_jitter / get_amcl_rate response field orders -----------
# Sole Python mirror of the field names embedded in the C++ wire format
# strings. Order MUST match production/RPi5/src/uds/json_mini.cpp::
# format_ok_jitter + format_ok_amcl_rate verbatim. tests/test_protocol.py
# regex-extracts the JSON keys from those format strings and asserts
# tuple-equal — drift fails the pin.
#
# `ok` is intentionally NOT in either tuple (JSON-level success flag).
JITTER_FIELDS: Final[tuple[str, ...]] = (
    "valid",
    "p50_ns",
    "p95_ns",
    "p99_ns",
    "max_ns",
    "mean_ns",
    "sample_count",
    "published_mono_ns",
)

AMCL_RATE_FIELDS: Final[tuple[str, ...]] = (
    "valid",
    "hz",
    "last_iteration_mono_ns",
    "total_iteration_count",
    "published_mono_ns",
)

# --- PR-DIAG: webctl-only Resources schema (no C++ counterpart) ----------
# Pinned by tests/test_resources.py + tests/test_protocol.py
# self-consistency. The SPA's lib/protocol.ts mirror is by inspection.
RESOURCES_FIELDS: Final[tuple[str, ...]] = (
    "cpu_temp_c",
    "mem_used_pct",
    "mem_total_bytes",
    "mem_avail_bytes",
    "disk_used_pct",
    "disk_total_bytes",
    "disk_avail_bytes",
    "published_mono_ns",
)

# --- PR-DIAG: multiplexed DiagFrame top-level keys -----------------------
# `Resources.published_mono_ns` is the WEBCTL `time.monotonic_ns()`
# (Python clock domain), NOT the C++ tracker's CLOCK_MONOTONIC. They
# happen to share the same kernel + the same domain on RPi 5, but the
# project discipline (Track D Mode-A M2) is that the SPA never crosses
# the boundary — freshness uses arrival-wall-clock (`Date.now()` stamped
# in `lib/sse.ts`).
DIAG_FRAME_FIELDS: Final[tuple[str, ...]] = (
    "pose",
    "jitter",
    "amcl_rate",
    "resources",
)

# --- Error codes (mirrors json_mini.cpp::format_err callers) --------------
ERR_PARSE_ERROR: Final[str] = "parse_error"  # json_mini.cpp callers
ERR_UNKNOWN_CMD: Final[str] = "unknown_cmd"  # uds_server.cpp:225
ERR_BAD_MODE: Final[str] = "bad_mode"  # json_mini.cpp:215 caller

# --- Track E (PR-C) — multi-map error codes ------------------------------
# These are webctl-internal (no C++ wire counterpart) but live here so
# the frontend mirror can be derived from a single source.
ERR_INVALID_MAP_NAME: Final[str] = "invalid_map_name"
ERR_MAP_NOT_FOUND: Final[str] = "map_not_found"
ERR_MAP_IS_ACTIVE: Final[str] = "map_is_active"
ERR_MAPS_DIR_MISSING: Final[str] = "maps_dir_missing"

# --- Track B-MAPEDIT — POST /api/map/edit error codes -------------------
# Webctl-internal (no C++ wire counterpart). Mirror in the SPA's
# `lib/protocol.ts`. Pinned by `tests/test_protocol.py::
# test_map_edit_error_codes_pinned`.
ERR_MASK_SHAPE_MISMATCH: Final[str] = "mask_shape_mismatch"
ERR_MASK_TOO_LARGE: Final[str] = "mask_too_large"
ERR_MASK_DECODE_FAILED: Final[str] = "mask_decode_failed"
ERR_EDIT_FAILED: Final[str] = "edit_failed"
ERR_ACTIVE_MAP_MISSING: Final[str] = "active_map_missing"

# `POST /api/map/edit` success response field order. SOLE Python mirror
# of the JSON keys emitted by `app.py::map_edit_endpoint` on the 200 path.
# `restart_required` is forward-compat — v1 always emits `True`, but the
# field stays in the wire schema so a future writer that introduces a
# hot-reload edit class can flip per-call without a wire shape change.
EDIT_RESPONSE_FIELDS: Final[tuple[str, ...]] = (
    "ok",
    "backup_ts",
    "pixels_changed",
    "restart_required",
)

# --- Track B-MAPEDIT-2 — POST /api/map/origin error codes ---------------
# Webctl-internal (no C++ wire counterpart). Mirror in the SPA's
# `lib/protocol.ts`. Pinned by `tests/test_protocol.py::
# test_origin_error_codes_pinned`.
ERR_ORIGIN_BAD_VALUE: Final[str] = "bad_origin_value"
ERR_ORIGIN_YAML_PARSE_FAILED: Final[str] = "origin_yaml_parse_failed"
ERR_ORIGIN_EDIT_FAILED: Final[str] = "origin_edit_failed"
ERR_ACTIVE_YAML_MISSING: Final[str] = "active_yaml_missing"

# `POST /api/map/origin` success response field order. SOLE Python mirror
# of the JSON keys emitted by `app.py::map_origin_endpoint` on the 200
# path. `prev_origin` and `new_origin` are 3-element JSON arrays
# `[x, y, theta]`; `restart_required` is always `True` for B-MAPEDIT-2
# (origin lives in the YAML, tracker reads YAML at boot only — same
# shape as B-MAPEDIT's `restart_required`).
ORIGIN_EDIT_RESPONSE_FIELDS: Final[tuple[str, ...]] = (
    "ok",
    "backup_ts",
    "prev_origin",
    "new_origin",
    "restart_required",
)

# Mode literals for the `mode` field of `OriginPatchBody`. Pydantic's
# `Literal` enforces the value at parse time; this Python tuple mirrors
# the SPA-side `OriginMode` literal type.
ORIGIN_MODE_ABSOLUTE: Final[str] = "absolute"
ORIGIN_MODE_DELTA: Final[str] = "delta"

VALID_ORIGIN_MODES: Final[frozenset[str]] = frozenset(
    {ORIGIN_MODE_ABSOLUTE, ORIGIN_MODE_DELTA},
)

# --- Track B-BACKUP — map-backup history error codes ---------------------
# Webctl-internal (no C++ wire counterpart). Mirror in the SPA's
# `lib/protocol.ts`. Per Mode-A M5 fold there is no `backup_dir_missing`
# error: `list_backups` returns `[]` for both "dir missing" and "dir
# exists but empty" so the wire shape is uniformly 200.
ERR_BACKUP_NOT_FOUND: Final[str] = "backup_not_found"
ERR_RESTORE_NAME_CONFLICT: Final[str] = "restore_name_conflict"

# --- Track B-SYSTEM PR-2 — service observability -------------------------
# `/api/system/services` payload field order (one entry per allowed
# service). Webctl-only (no C++ counterpart). Pinned by
# `tests/test_protocol.py::test_system_services_fields_pinned`.
SYSTEM_SERVICES_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "active_state",
    "sub_state",
    "main_pid",
    "active_since_unix",
    "memory_bytes",
    "env_redacted",
    "env_stale",
)

# Substring patterns matched (case-insensitive) against env-var KEY names.
# Any KEY whose upper-case form contains any of these substrings has its
# VALUE replaced with `REDACTED_PLACEHOLDER`. Defence-in-depth — the SSOT
# is the systemd unit-file authoring discipline that keeps secrets out
# of plain env vars. False-positives (`MOST_KEY_BUNDLES`) are accepted.
ENV_REDACTION_PATTERNS: Final[tuple[str, ...]] = (
    "SECRET",
    "KEY",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
)

# Replacement text for redacted env-var values.
REDACTED_PLACEHOLDER: Final[str] = "<redacted>"

# Track B-SYSTEM PR-2 — error codes for the transition-in-progress gate.
ERR_SERVICE_STARTING: Final[str] = "service_starting"
ERR_SERVICE_STOPPING: Final[str] = "service_stopping"

# --- Track B-SYSTEM PR-B — process monitor + extended resources ----------
# Process-name whitelist used for classification (NOT for filtering: PR-B
# enumerates EVERY live PID and classifies per-row). Each name matches an
# argv[0] basename from `/proc/<pid>/cmdline`, with one exception:
# `godo-webctl` is matched via argv[1..] containing `godo_webctl` because
# its argv[0] is `python` / `uvicorn`. See `processes.py::parse_pid_cmdline`
# docstring + `tests/test_processes.py::test_parse_pid_cmdline_godo_webctl_*`.
#
# Drift catch — `tests/test_protocol.py::test_godo_process_names_match_cmake_executables`
# regex-extracts `add_executable(<name>` from each
# `production/RPi5/src/*/CMakeLists.txt` and asserts the C++ subset of
# this set equals `{godo_tracker_rt, godo_freed_passthrough, godo_smoke,
# godo_jitter}`. The `godo-webctl` literal is webctl-internal and pinned
# separately.
GODO_PROCESS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "godo_tracker_rt",  # production/RPi5/src/godo_tracker_rt/CMakeLists.txt:1
        "godo_freed_passthrough",  # production/RPi5/src/godo_freed_passthrough/CMakeLists.txt:1
        "godo_smoke",  # production/RPi5/src/godo_smoke/CMakeLists.txt:8
        "godo_jitter",  # production/RPi5/src/godo_jitter/CMakeLists.txt:1
        "godo-webctl",  # python -m godo_webctl, matched via argv[1..]
    },
)

# Subset of GODO_PROCESS_NAMES that maps to `services.ALLOWED_SERVICES`
# units. Asymmetry vs. `services.ALLOWED_SERVICES`: this set is the
# PROCESS-LIST view (argv-derived basenames), not the SYSTEMD-UNIT view
# (`godo-tracker.service`, etc.):
#
# - `godo-tracker.service` runs the `godo_tracker_rt` binary
#   → `MANAGED_PROCESS_NAMES` carries `godo_tracker_rt` (binary).
#   → `ALLOWED_SERVICES` carries `godo-tracker` (unit).
# - `godo-webctl.service` runs `python -m godo_webctl`
#   → both sets carry `godo-webctl` (matched via argv[1..] in the
#     process list; identical token in the systemd unit).
# - `godo-irq-pin.service` is `Type=oneshot`
#   → never live in the process list; the literal is here so the
#     classifier still flags it `managed` if a future operator
#     enables `RemainAfterExit=yes` on that unit.
#
# Pinned by `tests/test_protocol.py::test_managed_process_names_cardinality`.
MANAGED_PROCESS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "godo_tracker_rt",
        "godo-webctl",
        "godo-irq-pin",
    },
)

# `/api/system/processes` per-row schema. Row category ∈ {"general",
# "godo", "managed"} per `processes.classify_pid`. `published_mono_ns` on
# the parent envelope is the WEBCTL `time.monotonic_ns()` (Python clock
# domain), NOT the C++ tracker's CLOCK_MONOTONIC; SPA freshness gates use
# arrival-wall-clock (`Date.now() - _arrival_ms`) per Track D Mode-A M2
# (mirrored above for `RESOURCES_FIELDS`).
#
# Pinned by `tests/test_protocol.py::test_process_fields_pinned`.
PROCESS_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "pid",
    "user",
    "state",
    "cmdline",
    "cpu_pct",
    "rss_mb",
    "etime_s",
    "category",
    "duplicate",
)

# Top-level envelope of `/api/system/processes`. `duplicate_alert` is the
# OR of the per-row `duplicate` flags — convenience for the SPA banner.
PROCESSES_RESPONSE_FIELDS: Final[tuple[str, ...]] = (
    "processes",
    "duplicate_alert",
    "published_mono_ns",
)

# `/api/system/resources/extended` schema. Six fields: per-core CPU list,
# aggregate CPU pct, mem total/used (MiB), disk pct, published_mono_ns.
# GPU fields are intentionally absent (per operator decision 2026-04-30
# 06:38 KST — V3D `gpu_busy_percent` is unreliable on Trixie firmware,
# CPU temp is already surfaced by the existing System tab CPU-temp
# sparkline panel via `RESOURCES_FIELDS.cpu_temp_c`).
#
# Same `published_mono_ns` clock-domain note as `RESOURCES_FIELDS` /
# `PROCESS_FIELDS` above: Python `time.monotonic_ns()`, SPA freshness
# uses arrival-wall-clock.
#
# Pinned by `tests/test_protocol.py::test_extended_resources_fields_pinned`.
EXTENDED_RESOURCES_FIELDS: Final[tuple[str, ...]] = (
    "cpu_per_core",
    "cpu_aggregate_pct",
    "mem_total_mb",
    "mem_used_mb",
    "disk_pct",
    "published_mono_ns",
)

# Mirror the regex pattern as a string so the SPA can do client-side
# validation without depending on a Python regex parse. Frontend file:
# `godo-frontend/src/lib/protocol.ts::MAPS_NAME_REGEX_PATTERN_STR`.
MAPS_NAME_REGEX_PATTERN_STR: Final[str] = MAPS_NAME_REGEX.pattern


# --- Canonical request encoders -------------------------------------------
# The server tolerates whitespace + arbitrary key order, but the client MUST
# emit canonical form (declaration order, no whitespace, ASCII, single
# trailing '\n') so the server's request log is grep-able and the wire test
# is byte-exact.
def encode_ping() -> bytes:
    """Canonical wire encoding of the ``ping`` request."""
    return b'{"cmd":"ping"}\n'


def encode_get_mode() -> bytes:
    """Canonical wire encoding of the ``get_mode`` request."""
    return b'{"cmd":"get_mode"}\n'


def encode_set_mode(mode: str) -> bytes:
    """Canonical wire encoding of ``set_mode`` for a validated mode name."""
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    return b'{"cmd":"set_mode","mode":"' + mode.encode("ascii") + b'"}\n'


def encode_get_last_pose() -> bytes:
    """Canonical wire encoding of the Track B ``get_last_pose`` request."""
    return b'{"cmd":"get_last_pose"}\n'


def encode_get_last_scan() -> bytes:
    """Canonical wire encoding of the Track D ``get_last_scan`` request."""
    return b'{"cmd":"get_last_scan"}\n'


def encode_get_jitter() -> bytes:
    """Canonical wire encoding of the PR-DIAG ``get_jitter`` request."""
    return b'{"cmd":"get_jitter"}\n'


def encode_get_amcl_rate() -> bytes:
    """Canonical wire encoding of the PR-DIAG ``get_amcl_rate`` request.

    Mode-A M2 fold: command name is ``get_amcl_rate`` (NOT
    ``get_scan_rate``) — the metric measures AMCL iteration cadence.
    """
    return b'{"cmd":"get_amcl_rate"}\n'


# --- Track B-CONFIG (PR-CONFIG-β) ----------------------------------------
def encode_get_config() -> bytes:
    """Canonical wire encoding of the ``get_config`` request."""
    return b'{"cmd":"get_config"}\n'


def encode_get_config_schema() -> bytes:
    """Canonical wire encoding of the ``get_config_schema`` request."""
    return b'{"cmd":"get_config_schema"}\n'


def encode_set_config(key: str, value: str) -> bytes:
    """Canonical wire encoding of ``set_config`` for a (key, value) pair.

    Both arguments are forwarded verbatim as JSON strings — the tracker
    parses them per the schema (Int/Double/String) at validate time.
    Webctl pre-validation (Mode-A S4 fold) guarantees ASCII shape +
    body size + single-key form upstream; this encoder trusts both
    arguments are already validated.

    The wire embeds raw bytes — backslash and double-quote MUST be
    rejected upstream by `parse_patch_payload` before reaching here.
    """
    # Defence-in-depth: reject the two byte values that would break the
    # tracker's hand-rolled JSON parser (json_mini.cpp tolerates ASCII
    # only and does not unescape).
    if any(c in key for c in ('"', "\\", "\n")):
        raise ValueError(f"invalid character in key: {key!r}")
    if any(c in value for c in ('"', "\\", "\n")):
        raise ValueError(f"invalid character in value: {value!r}")
    return (
        b'{"cmd":"set_config","key":"'
        + key.encode("ascii")
        + b'","value":"'
        + value.encode("ascii")
        + b'"}\n'
    )
