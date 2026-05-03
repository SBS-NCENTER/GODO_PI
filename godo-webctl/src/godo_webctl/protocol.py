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
# issue#27 — `get_last_output` UDS command. Field-name SSOT is the format
# string in production/RPi5/src/uds/json_mini.cpp::format_ok_output;
# LAST_OUTPUT_FIELDS below is regex-pinned against that source by
# tests/test_protocol.py.
CMD_GET_LAST_OUTPUT: Final[str] = "get_last_output"
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

# --- issue#27: get_last_output response field order ---------------------
# SOLE Python mirror of the field names embedded in the C++ wire format
# string `format_ok_output`. Order MUST match production/RPi5/src/uds/
# json_mini.cpp::format_ok_output verbatim. tests/test_protocol.py
# regex-extracts the JSON keys from the format string and asserts
# byte-equal — drift fails the pin.
#
# The 6 transformed channels (x_m, y_m, z_m, pan_deg, tilt_deg, roll_deg)
# carry the post-AMCL-merge + post-output-transform values being sent to
# UE; zoom + focus are pass-through raw u24 cast to double. `valid` and
# `published_mono_ns` mirror the LastPose envelope semantics.
#
# `ok` is intentionally NOT in this tuple (JSON-level success flag).
LAST_OUTPUT_FIELDS: Final[tuple[str, ...]] = (
    "valid",
    "x_m",
    "y_m",
    "z_m",
    "pan_deg",
    "tilt_deg",
    "roll_deg",
    "zoom",
    "focus",
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

# issue#14 Mode-B N1 fix (2026-05-02 KST) — docker-family processes are
# god-family in this project. Operator confirmed docker is only used for
# the mapping container (`godo-mapping@active.service` → `docker run
# --name godo-mapping ...`).
#
# issue#16 (2026-05-02 KST, spec §"ProcessTable classification
# refinement"). The first revision split docker-family into two
# categories (daemons → general; containers → godo); operator HIL
# response: "기존에는 dockerd, containerd등 docker 관련 프로세스는
# 파랑색이었어. 앞으로도 평상시에는 녹색에 볼드체, mapping이 running인
# 경우 파랑에 볼드체로 부탁해" — they want ALL docker-family to stay
# bold-stylised, with a state-aware colour swap on the SPA side
# (mapping idle → green, mapping running → blue). Encode this on the
# wire as a fourth `docker` category and let the SPA pick the colour
# based on the mappingStatus store.
#
# Spec memory: `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.
# Pinned by `tests/test_processes.py::test_classify_pid_docker_family`.
DOCKER_FAMILY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "docker",       # `docker run --name godo-mapping ...` run-parent
        "dockerd",      # docker daemon — always running once Docker is installed
        "containerd",   # containerd daemon — same lifecycle as dockerd
    },
)
# `containerd-shim*` is matched by argv-prefix at classify time (the
# kernel-truncated comm sometimes shows the bare `containerd-shim` and
# sometimes the longer `containerd-shim-runc-v2`); kept out of the set
# above so the prefix discipline lives next to the consumer.

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

# --- issue#14 — mapping pipeline state-machine + wire shapes -------------
# The 5 states `mapping.MappingState` can carry. Mirrored on the SPA via
# `godo-frontend/src/lib/protocol.ts::MAPPING_STATE_*`. Drift detected by
# inspection per godo-frontend/CODEBASE.md invariant (the new mapping
# block).
MAPPING_STATE_IDLE: Final[str] = "idle"
MAPPING_STATE_STARTING: Final[str] = "starting"
MAPPING_STATE_RUNNING: Final[str] = "running"
MAPPING_STATE_STOPPING: Final[str] = "stopping"
MAPPING_STATE_FAILED: Final[str] = "failed"

VALID_MAPPING_STATES: Final[frozenset[str]] = frozenset(
    {
        MAPPING_STATE_IDLE,
        MAPPING_STATE_STARTING,
        MAPPING_STATE_RUNNING,
        MAPPING_STATE_STOPPING,
        MAPPING_STATE_FAILED,
    },
)

# `GET /api/mapping/status` response field order. SOLE Python mirror of
# the JSON keys emitted by `app.py::map_status_endpoint` (which iterates
# this tuple). Frontend mirror at `lib/protocol.ts::MAPPING_STATUS_FIELDS`.
MAPPING_STATUS_FIELDS: Final[tuple[str, ...]] = (
    "state",
    "map_name",
    "container_id_short",
    "started_at",
    "error_detail",
    "journal_tail_available",
)

# `GET /api/mapping/monitor/stream` per-frame field order. Docker-only
# (S1 amendment); RPi5 host stats live in the existing
# `/api/system/resources/extended/stream`. SPA's two-region monitor strip
# subscribes to BOTH streams in parallel.
MAPPING_MONITOR_FIELDS: Final[tuple[str, ...]] = (
    "valid",
    "container_id_short",
    "container_state",
    "container_cpu_pct",
    "container_mem_bytes",
    "container_net_rx_bytes",
    "container_net_tx_bytes",
    "var_lib_godo_disk_avail_bytes",
    "var_lib_godo_disk_total_bytes",
    "in_progress_map_size_bytes",
    "published_mono_ns",
)

# Mapping-pipeline error codes (webctl-internal; no C++ wire counterpart).
# Mirror in `lib/protocol.ts`.
ERR_INVALID_MAPPING_NAME: Final[str] = "invalid_mapping_name"
ERR_NAME_EXISTS: Final[str] = "name_exists"
ERR_MAPPING_ALREADY_ACTIVE: Final[str] = "mapping_already_active"
ERR_MAPPING_ACTIVE: Final[str] = "mapping_active"
ERR_IMAGE_MISSING: Final[str] = "image_missing"
ERR_DOCKER_UNAVAILABLE: Final[str] = "docker_unavailable"
ERR_TRACKER_STOP_FAILED: Final[str] = "tracker_stop_failed"
ERR_CONTAINER_START_TIMEOUT: Final[str] = "container_start_timeout"
ERR_CONTAINER_STOP_TIMEOUT: Final[str] = "container_stop_timeout"
ERR_NO_ACTIVE_MAPPING: Final[str] = "no_active_mapping"
ERR_PREVIEW_NOT_YET_PUBLISHED: Final[str] = "preview_not_yet_published"
ERR_STATE_FILE_CORRUPT: Final[str] = "state_file_corrupt"
ERR_BAD_N: Final[str] = "bad_n"

# --- issue#16 — mapping pre-check + cp210x recovery wire shapes ---------
# Spec memory: `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.
# The precheck endpoint (`GET /api/mapping/precheck`) is anonymous-readable
# (mirrors `/api/mapping/status`) so the SPA's 1 Hz banner state stays
# consistent. The recover-lidar endpoint (`POST /api/mapping/recover-lidar`)
# is admin-only.
PRECHECK_FIELDS: Final[tuple[str, ...]] = ("ready", "checks")

# One row of the `checks` array. `value` carries auxiliary information
# (e.g. disk-free MiB, image tag); `detail` carries a human-readable
# failure reason. Both are emitted as JSON `null` on the wire when the
# check has no extra info — fixed key set keeps the SPA's row renderer
# trivial.
PRECHECK_CHECK_FIELDS: Final[tuple[str, ...]] = ("name", "ok", "value", "detail")

# Canonical names (and emit order) of the 7 checks. Drift here breaks
# the SPA's labelled rows. Pinned by `tests/test_protocol.py`.
#
# v7 (2026-05-02 KST) added `mapping_unit_clean` after operator HIL
# surfaced precheck-passes-but-Start-fails cases caused by a
# `failed`-state systemd unit OR a lingering `godo-mapping` container
# that the other 6 rows didn't catch.
PRECHECK_CHECK_NAMES: Final[tuple[str, ...]] = (
    "lidar_readable",
    "tracker_stopped",
    "image_present",
    "disk_space_mb",
    "name_available",
    "state_clean",
    "mapping_unit_clean",
)

# Disk-free threshold for the `disk_space_mb` check. Tier-1 mirror of the
# spec value (500 MiB). Smaller than this and the operator should clean
# up before mapping — a single PGM is well under 100 MiB but the docker
# image, intermediate slam_toolbox state, and an existing maps tree all
# share the same volume.
PRECHECK_DISK_FREE_MIN_MB: Final[int] = 500

# issue#16 error codes (webctl-internal; no C++ wire counterpart). Mirror
# in `lib/protocol.ts`.
ERR_CP210X_RECOVERY_FAILED: Final[str] = "cp210x_recovery_failed"
ERR_LIDAR_PORT_NOT_RESOLVABLE: Final[str] = "lidar_port_not_resolvable"


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


def encode_set_mode(
    mode: str,
    *,
    seed: tuple[float, float, float] | None = None,
    sigma_xy_m: float | None = None,
    sigma_yaw_deg: float | None = None,
) -> bytes:
    """Canonical wire encoding of ``set_mode`` for a validated mode name.

    issue#3 (pose hint) — when ``seed`` is supplied as
    ``(x_m, y_m, yaw_deg)``, the encoder appends three JSON NUMBER keys
    ``seed_x_m``, ``seed_y_m``, ``seed_yaw_deg`` (in that order). When
    ``sigma_xy_m`` / ``sigma_yaw_deg`` are also supplied, they append
    after the seed triple. The C++ tracker parser
    (``json_mini.cpp::parse_request``) accepts these as JSON numbers
    only — strings would be rejected.

    Pre-issue#3 byte shape (no seed, no sigma) is preserved verbatim
    for back-compat — anti-regression pinned by
    ``test_protocol::encode_set_mode_no_hint_byte_identical``.

    All numeric values are formatted via ``repr(float)`` which gives a
    shortest round-trip representation acceptable to the tracker's
    parse_number subset (no leading +, no leading dot, no NaN/Infinity
    — webctl Pydantic validates finite + range BEFORE this encoder is
    reached).
    """
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    if seed is None and (sigma_xy_m is not None or sigma_yaw_deg is not None):
        # The tracker rejects σ-without-seed as bad_sigma_without_seed;
        # webctl Pydantic catches the same shape upstream as 422. This
        # raise is a defence-in-depth so a programming-error caller
        # cannot bypass both checks.
        raise ValueError("sigma overrides require seed to be present")
    base = b'{"cmd":"set_mode","mode":"' + mode.encode("ascii") + b'"'
    if seed is None:
        return base + b"}\n"
    sx, sy, syaw = seed
    parts = [
        base,
        b',"seed_x_m":',     _encode_json_number(sx),
        b',"seed_y_m":',     _encode_json_number(sy),
        b',"seed_yaw_deg":', _encode_json_number(syaw),
    ]
    if sigma_xy_m is not None:
        parts += [b',"sigma_xy_m":',    _encode_json_number(sigma_xy_m)]
    if sigma_yaw_deg is not None:
        parts += [b',"sigma_yaw_deg":', _encode_json_number(sigma_yaw_deg)]
    parts.append(b"}\n")
    return b"".join(parts)


def _encode_json_number(v: float) -> bytes:
    """Render a Python float into the C++ parse_number subset. Rejects
    NaN / Infinity (Pydantic + the C++ parser already reject these; we
    raise here as a defence-in-depth so a buggy upstream caller cannot
    emit a malformed wire payload).

    Python's `repr(float)` is the right choice over `str` (Python 3.x
    they are identical) — gives shortest round-trip representation
    that strtod restores byte-exactly.
    """
    import math as _math
    if not _math.isfinite(v):
        raise ValueError(f"non-finite float in set_mode hint: {v!r}")
    return repr(float(v)).encode("ascii")


def encode_get_last_pose() -> bytes:
    """Canonical wire encoding of the Track B ``get_last_pose`` request."""
    return b'{"cmd":"get_last_pose"}\n'


def encode_get_last_scan() -> bytes:
    """Canonical wire encoding of the Track D ``get_last_scan`` request."""
    return b'{"cmd":"get_last_scan"}\n'


def encode_get_last_output() -> bytes:
    """Canonical wire encoding of the issue#27 ``get_last_output`` request."""
    return b'{"cmd":"get_last_output"}\n'


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
