/**
 * Wire-protocol mirror.
 *
 * Hand-mirrored from `godo-webctl/src/godo_webctl/protocol.py`. The backend
 * file is in turn mirrored from the C++ tracker's `constants.hpp` /
 * `json_mini.cpp`. This file is the SPA-side endpoint of that chain.
 *
 * Drift policy: changing any value here without changing the corresponding
 * `protocol.py` line (and re-running the backend `tests/test_protocol.py`)
 * is a code-review block.
 *
 * `LAST_POSE_FIELDS` order MUST match `protocol.py::LAST_POSE_FIELDS`
 * exactly — backend tests assert byte-equality against the C++ source.
 */

// --- Mode names (mirrors backend MODE_*) --------------------------------
export const MODE_IDLE = 'Idle';
export const MODE_ONESHOT = 'OneShot';
export const MODE_LIVE = 'Live';

export type Mode = typeof MODE_IDLE | typeof MODE_ONESHOT | typeof MODE_LIVE;

export const VALID_MODES: ReadonlySet<string> = new Set([MODE_IDLE, MODE_ONESHOT, MODE_LIVE]);

// --- LastPose (Track B schema, mirrors backend LAST_POSE_FIELDS) --------
// Tuple order is ABI-visible.
export const LAST_POSE_FIELDS = [
  'valid',
  'x_m',
  'y_m',
  'yaw_deg',
  'xy_std_m',
  'yaw_std_deg',
  'iterations',
  'converged',
  'forced',
  'published_mono_ns',
] as const;

export interface LastPose {
  valid: boolean;
  x_m: number;
  y_m: number;
  yaw_deg: number;
  xy_std_m: number;
  yaw_std_deg: number;
  iterations: number;
  converged: boolean;
  forced: boolean;
  published_mono_ns: number;
}

// --- LastScan (Track D schema, mirrors backend LAST_SCAN_HEADER_FIELDS) --
// Tuple order matches the wire body emitted by
// godo_webctl.app::_last_scan_view, which iterates LAST_SCAN_HEADER_FIELDS.
// MUST equal protocol.py::LAST_SCAN_HEADER_FIELDS exactly. Drift detected
// by inspection per godo-frontend/CODEBASE.md invariant (l).
export const LAST_SCAN_HEADER_FIELDS = [
  'valid',
  'forced',
  'pose_valid',
  'iterations',
  'published_mono_ns',
  'pose_x_m',
  'pose_y_m',
  'pose_yaw_deg',
  'n',
  'angles_deg',
  'ranges_m',
] as const;

// Mirror of production/RPi5/src/core/constants.hpp::LAST_SCAN_RANGES_MAX
// AND godo_webctl.protocol::LAST_SCAN_RANGES_MAX_PYTHON_MIRROR. All three
// must agree (see CODEBASE.md invariant (l)).
export const LAST_SCAN_RANGES_MAX = 720;

// Track D — `get_last_scan` UDS command name. Anchor for the SPA's
// awareness of the wire surface; the SPA never builds UDS bytes (the
// backend does), but having the literal here keeps the cross-language
// drift triple consistent.
export const CMD_GET_LAST_SCAN = 'get_last_scan';

// LastScan wire shape. The two arrays (`angles_deg`, `ranges_m`) carry
// the LiDAR's polar samples in the LiDAR frame; the SPA does the
// polar→Cartesian world-frame transform using the same-frame anchor
// pose (`pose_x_m`, `pose_y_m`, `pose_yaw_deg`) baked into THIS frame —
// NOT from a parallel `lastPose` SSE (Mode-A TM5).
//
// `_arrival_ms` is a CLIENT-SIDE NON-WIRE field set in the SSE adapter
// at `Date.now()`-time of frame arrival, used by the freshness gate
// per Mode-A M2 (do not subtract `published_mono_ns` from `Date.now()`
// — the clock domains differ). The wire never carries this field.
export interface LastScan {
  valid: number; // 0 | 1 (uint8 on wire, kept as number to match JSON)
  forced: number; // 0 | 1
  pose_valid: number; // 0 | 1
  iterations: number;
  published_mono_ns: number;
  pose_x_m: number;
  pose_y_m: number;
  pose_yaw_deg: number;
  n: number;
  angles_deg: number[];
  ranges_m: number[];
  _arrival_ms?: number; // client-side; set by sse adapter
}

// --- Error codes (mirrors backend ERR_* + handler error strings) -------
export const ERR_PARSE_ERROR = 'parse_error';
export const ERR_UNKNOWN_CMD = 'unknown_cmd';
export const ERR_BAD_MODE = 'bad_mode';

// HTTP-level error codes used by handlers (FRONT_DESIGN §7).
export const ERR_AUTH_REQUIRED = 'auth_required';
export const ERR_AUTH_UNAVAILABLE = 'auth_unavailable';
export const ERR_BAD_CREDENTIALS = 'bad_credentials';
export const ERR_TOKEN_INVALID = 'token_invalid';
export const ERR_ADMIN_REQUIRED = 'admin_required';
export const ERR_TRACKER_TIMEOUT = 'tracker_timeout';
export const ERR_TRACKER_UNREACHABLE = 'tracker_unreachable';
export const ERR_PROTOCOL_ERROR = 'protocol_error';
export const ERR_MAP_PATH_NOT_FOUND = 'map_path_not_found';
export const ERR_MAP_INVALID = 'map_invalid';
export const ERR_UNKNOWN_SERVICE = 'unknown_service';
export const ERR_UNKNOWN_ACTION = 'unknown_action';
export const ERR_SUBPROCESS_TIMEOUT = 'subprocess_timeout';
export const ERR_SUBPROCESS_FAILED = 'subprocess_failed';

// Track E (PR-C) — multi-map error codes (mirror godo_webctl/protocol.py).
export const ERR_INVALID_MAP_NAME = 'invalid_map_name';
export const ERR_MAP_NOT_FOUND = 'map_not_found';
export const ERR_MAP_IS_ACTIVE = 'map_is_active';
export const ERR_MAPS_DIR_MISSING = 'maps_dir_missing';

// Track E — map-name regex pattern. SPA-side validation (e.g. disable
// the activate button on a name the backend will reject anyway).
// MUST equal `godo_webctl.constants.MAPS_NAME_REGEX.pattern` —
// drift detected by inspection per godo-frontend/CODEBASE.md
// invariant (k).
export const MAPS_NAME_REGEX_PATTERN_STR = '^[a-zA-Z0-9_-]{1,64}$';

// --- PR-DIAG (Track B-DIAG) — diagnostics page wire shapes ---------------
// `JitterSnapshot` / `AmclIterationRate` / `Resources` / `DiagFrame` mirror
// the webctl-side projections (godo_webctl.protocol::JITTER_FIELDS /
// AMCL_RATE_FIELDS / RESOURCES_FIELDS / DIAG_FRAME_FIELDS). Upstream C++
// origin: production/RPi5/src/core/rt_types.hpp::JitterSnapshot +
// AmclIterationRate. Mode-A M2 fold renamed scan_rate → amcl_rate.
//
// Drift policy: changing this shape without changing protocol.py +
// rt_types.hpp is a code-review block.

export const CMD_GET_JITTER = 'get_jitter';
export const CMD_GET_AMCL_RATE = 'get_amcl_rate';

export const JITTER_FIELDS = [
  'valid',
  'p50_ns',
  'p95_ns',
  'p99_ns',
  'max_ns',
  'mean_ns',
  'sample_count',
  'published_mono_ns',
] as const;

export interface JitterSnapshot {
  valid: number; // 0 | 1
  p50_ns: number;
  p95_ns: number;
  p99_ns: number;
  max_ns: number;
  mean_ns: number;
  sample_count: number;
  published_mono_ns: number;
  err?: string; // present when the sub-fetch failed; valid=0
}

export const AMCL_RATE_FIELDS = [
  'valid',
  'hz',
  'last_iteration_mono_ns',
  'total_iteration_count',
  'published_mono_ns',
] as const;

export interface AmclIterationRate {
  valid: number;
  hz: number;
  last_iteration_mono_ns: number;
  total_iteration_count: number;
  published_mono_ns: number;
  err?: string;
}

export const RESOURCES_FIELDS = [
  'cpu_temp_c',
  'mem_used_pct',
  'mem_total_bytes',
  'mem_avail_bytes',
  'disk_used_pct',
  'disk_total_bytes',
  'disk_avail_bytes',
  'published_mono_ns',
] as const;

export interface Resources {
  cpu_temp_c: number | null;
  mem_used_pct: number | null;
  mem_total_bytes: number | null;
  mem_avail_bytes: number | null;
  disk_used_pct: number | null;
  disk_total_bytes: number | null;
  disk_avail_bytes: number | null;
  published_mono_ns: number;
  // Sentinel field set by sse.py when resources.snapshot() raises;
  // the SPA renders the panel as "unavailable".
  valid?: number;
  err?: string;
}

// Multiplexed SSE frame from /api/diag/stream. Mode-A M2 fold: keys are
// `pose / jitter / amcl_rate / resources` (NOT scan_rate).
//
// `_arrival_ms` is a CLIENT-SIDE NON-WIRE field set by the diag store on
// receipt; the SPA freshness gate uses `Date.now() - _arrival_ms` (per
// Track D Mode-A M2 + PR-DIAG N4 fold) and never compares
// published_mono_ns across the C++ / webctl boundary.
export const DIAG_FRAME_FIELDS = ['pose', 'jitter', 'amcl_rate', 'resources'] as const;

export interface DiagFrame {
  pose: LastPose;
  jitter: JitterSnapshot;
  amcl_rate: AmclIterationRate;
  resources: Resources;
  _arrival_ms?: number;
}

// --- Roles (mirrors backend ROLE_*) ------------------------------------
export const ROLE_ADMIN = 'admin';
export const ROLE_VIEWER = 'viewer';
export type Role = typeof ROLE_ADMIN | typeof ROLE_VIEWER;

// --- Health response shape ---------------------------------------------
export interface Health {
  webctl: 'ok';
  tracker: 'ok' | 'unreachable';
  mode: Mode | null;
}

// --- Auth response shapes ----------------------------------------------
export interface LoginResponse {
  ok: true;
  token: string;
  exp: number;
  role: Role;
  username: string;
}

export interface MeResponse {
  ok: true;
  username: string;
  role: Role;
  exp: number;
}

export interface RefreshResponse {
  ok: true;
  token: string;
  exp: number;
}

// --- Activity entry ----------------------------------------------------
// `ts` is unix-seconds (float, from Python `time.time()`).
export interface ActivityEntry {
  ts: number;
  type: string;
  detail: string;
}

// --- Service status ----------------------------------------------------
// Mirrors `services.list_active()` row shape. `active` is the raw status
// word from `systemctl is-active`: "active" | "inactive" | "failed" |
// "activating" | "timeout" | "unknown".
export interface ServiceStatus {
  name: string;
  active: string;
}

// SSE frame from /api/local/services/stream wraps the list under "services".
export interface ServicesStreamFrame {
  services: ServiceStatus[];
}

// --- Live mode response ------------------------------------------------
export interface LiveResponse {
  ok: true;
  mode: Mode;
}

// --- Generic OK / error ------------------------------------------------
export interface OkResponse {
  ok: true;
  [k: string]: unknown;
}

export interface ErrResponse {
  ok: false;
  err: string;
  detail?: string;
}

// --- Track B-CONFIG (PR-CONFIG-β) — config edit pipeline ---------------
// Hand-mirrored from `godo-webctl/src/godo_webctl/config_schema.py`'s
// `ConfigSchemaRow` NamedTuple + `protocol.py::CONFIG_SCHEMA_ROW_FIELDS`.
// Drift detected by inspection per godo-frontend/CODEBASE.md invariant.

export const RELOAD_CLASS_HOT = 'hot';
export const RELOAD_CLASS_RESTART = 'restart';
export const RELOAD_CLASS_RECALIBRATE = 'recalibrate';
export type ReloadClass =
  | typeof RELOAD_CLASS_HOT
  | typeof RELOAD_CLASS_RESTART
  | typeof RELOAD_CLASS_RECALIBRATE;

export const VALID_RELOAD_CLASSES: ReadonlySet<ReloadClass> = new Set<ReloadClass>([
  RELOAD_CLASS_HOT,
  RELOAD_CLASS_RESTART,
  RELOAD_CLASS_RECALIBRATE,
]);

export type ConfigValueType = 'int' | 'double' | 'string';

// One schema row from GET /api/config/schema. Mirror of the C++
// ConfigSchemaRow (production/RPi5/src/core/config_schema.hpp); drift
// detected via the regex parser in godo-webctl + manual review here.
export interface ConfigSchemaRow {
  name: string;
  type: ConfigValueType;
  min: number;
  max: number;
  default: string;
  reload_class: ReloadClass;
  description: string;
}

// One key/value entry. The wire JSON-types `value` per the schema's
// `type`; the SPA carries that distinction through to the editor input.
export type ConfigValue = number | string | boolean;
export interface ConfigKV {
  name: string;
  value: ConfigValue;
}

// GET /api/config response — projected dict of `name → value`.
export type ConfigGetResponse = Record<string, ConfigValue>;

// PATCH /api/config request body. Mode-A S4 fold: webctl pre-checks
// body size + single-key + JSON well-formedness only; tracker is the
// canonical validator.
export interface ConfigPatchBody {
  key: string;
  value: ConfigValue;
}

// PATCH /api/config success response.
export interface ConfigSetResult {
  ok: true;
  reload_class: ReloadClass;
}

// GET /api/system/restart_pending response.
export interface RestartPendingResponse {
  pending: boolean;
}

// --- Track E (PR-C) — multi-map management wire shapes ---------------
// JSON shape for one row of GET /api/maps. Mirrors backend
// `maps.MapEntry.to_dict()` (mtime is float epoch seconds, NOT raw
// nanoseconds — per Mode-A N3 wire format).
export interface MapEntry {
  name: string;
  size_bytes: number;
  mtime_unix: number;
  is_active: boolean;
}

// GET /api/maps response = array of MapEntry. The store keeps the array
// in `Writable<MapEntry[]>` directly; this type alias documents the
// wire shape without a wrapper object.
export type MapListResponse = MapEntry[];

// POST /api/maps/<name>/activate response shape.
export interface ActivateResponse {
  ok: true;
  restart_required: true;
}
