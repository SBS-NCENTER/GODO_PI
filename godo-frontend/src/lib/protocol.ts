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
  /** issue#27 SSE wrap — sentinel field set by sse.py when the
   * sub-fetch failed. */
  err?: string;
}

// --- issue#27 — LastOutputFrame mirror ----------------------------------
// Tuple order MUST match `godo-webctl/src/godo_webctl/protocol.py::
// LAST_OUTPUT_FIELDS` exactly (the backend regex-pins the Python tuple
// against the C++ format string at test time; this TS mirror is hand-
// pinned by inspection).
export const LAST_OUTPUT_FIELDS = [
  'valid',
  'x_m',
  'y_m',
  'z_m',
  'pan_deg',
  'tilt_deg',
  'roll_deg',
  'zoom',
  'focus',
  'published_mono_ns',
] as const;

export interface LastOutputFrame {
  valid: number; // 0 | 1
  x_m: number;
  y_m: number;
  z_m: number;
  pan_deg: number;
  tilt_deg: number;
  roll_deg: number;
  zoom: number;
  focus: number;
  published_mono_ns: number;
  err?: string;
}

// issue#27 — wrap-and-version SSE frame from /api/last_pose/stream.
// Either sub-payload may be a `{valid: 0, err: <ExceptionClass>}`
// sentinel if its UDS round-trip failed; the SPA renders that sub-card
// as "unavailable" while keeping the other live.
export interface LastPoseStreamFrame {
  pose: LastPose;
  output: LastOutputFrame;
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
export const MAPS_NAME_REGEX_PATTERN_STR = '^[a-zA-Z0-9_()-][a-zA-Z0-9._()-]{0,63}$';

// --- Track D scale fix — map metadata wire shapes ----------------------
// `MapYaml` is parsed CLIENT-SIDE from the body of GET /api/maps/<name>/yaml
// (plain ROS map_server YAML — `image`, `resolution`, `origin`, `negate`).
// `MapDimensions` is the JSON shape of GET /api/maps/<name>/dimensions
// (PGM header bytes, no Pillow on the backend).
//
// `MapMetadata` is the COMPOSED struct the SPA carries through the
// `mapMetadata` store; PoseCanvas consumes it directly.
export interface MapYaml {
  image: string;
  resolution: number; // meters per cell
  origin: [number, number, number]; // [x, y, theta] — theta in radians
  negate: number;
}

export interface MapDimensions {
  width: number; // PGM image width in pixels
  height: number; // PGM image height in pixels
}

export interface MapMetadata extends MapYaml, MapDimensions {
  // Source URL the metadata was loaded for; useful for the SPA to
  // detect "metadata snapshot is stale w.r.t. current mapImageUrl".
  source_url: string;
}

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
  // Rendered as a muted `(default: …)` hint under each row's Current
  // value per `godo-frontend/CODEBASE.md` invariant (z) (PR-C).
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
//
// Operator UX 2026-05-02 KST: width_px / height_px / resolution_m
// added so the SPA Map list can render `W×H px (X.X×Y.Y m)`. Any field
// may be null if the corresponding header is malformed (graceful
// degradation — the row still appears, the SPA shows '—' for unknown
// dimensions).
export interface MapEntry {
  name: string;
  size_bytes: number;
  mtime_unix: number;
  is_active: boolean;
  width_px: number | null;
  height_px: number | null;
  resolution_m: number | null;
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

// --- Track B-BACKUP — map-backup history wire shapes -----------------
// Mirror of `godo_webctl.map_backup.BackupEntry.to_dict()` and the
// HTTP shapes in `godo_webctl.app::map_backup_list` /
// `map_backup_restore`. Mode-A M5 fold: `list_backups` returns 200
// always (no `backup_dir_missing` error) — the wire shape is
// `{items: [...]}` even when the directory is missing.

export interface BackupEntry {
  ts: string; // canonical "YYYYMMDDTHHMMSSZ"
  files: string[]; // sorted basenames present in the dir
  size_bytes: number; // sum of stat.st_size across all files
}

export interface BackupListResponse {
  items: BackupEntry[];
}

export interface RestoreResponse {
  ok: true;
  ts: string;
  restored: string[];
}

// Track B-BACKUP error codes. Mode-A M5 fold: only 2 codes (no
// `backup_dir_missing` — list returns [] uniformly).
export const ERR_BACKUP_NOT_FOUND = 'backup_not_found';
export const ERR_RESTORE_NAME_CONFLICT = 'restore_name_conflict';

// --- Track B-MAPEDIT — POST /api/map/edit wire shapes -----------------
// Mirror of `godo_webctl.protocol::ERR_MASK_*` / `EDIT_RESPONSE_FIELDS`.
// Drift detected by inspection per godo-frontend/CODEBASE.md invariant
// (u). The `restart_required` field is forward-compat: v1 always
// emits `true`, but the field stays in the wire schema so a future
// hot-reload edit class can flip per-call without a wire shape change.
export const ERR_MASK_SHAPE_MISMATCH = 'mask_shape_mismatch';
export const ERR_MASK_TOO_LARGE = 'mask_too_large';
export const ERR_MASK_DECODE_FAILED = 'mask_decode_failed';
export const ERR_EDIT_FAILED = 'edit_failed';
export const ERR_ACTIVE_MAP_MISSING = 'active_map_missing';

export interface EditResponse {
  ok: true;
  backup_ts: string; // canonical "YYYYMMDDTHHMMSSZ"
  pixels_changed: number;
  restart_required: true;
}

// --- Track B-MAPEDIT-2 — POST /api/map/origin wire shapes -------------
// Mirror of `godo_webctl.protocol::ERR_ORIGIN_*` /
// `ORIGIN_EDIT_RESPONSE_FIELDS` / `ORIGIN_MODE_*`. Drift detected by
// inspection per godo-frontend/CODEBASE.md invariant (aa).
export const ERR_ORIGIN_BAD_VALUE = 'bad_origin_value';
export const ERR_ORIGIN_YAML_PARSE_FAILED = 'origin_yaml_parse_failed';
export const ERR_ORIGIN_EDIT_FAILED = 'origin_edit_failed';
export const ERR_ACTIVE_YAML_MISSING = 'active_yaml_missing';

// `mode` literal type — Pydantic Literal["absolute","delta"] mirror.
export type OriginMode = 'absolute' | 'delta';

// POST /api/map/origin request body.
//
// issue#27 — `theta_deg` is optional. When omitted (existing public
// API contract before the OriginPicker theta input lands), the YAML
// theta token is preserved byte-for-byte by the backend. When supplied
// the value is converted to radians and written via `repr(theta_rad)`.
export interface OriginPatchBody {
  x_m: number;
  y_m: number;
  mode: OriginMode;
  theta_deg?: number;
}

// POST /api/map/origin success response. `prev_origin` and `new_origin`
// are 3-element tuples `[x, y, theta]`. Theta is preserved
// byte-for-byte on disk (the YAML's theta token bytes are NOT
// reformatted); the wire value here is a Python-float parse for SPA
// display convenience only (see invariant (ab) on the webctl side).
export interface OriginEditResponse {
  ok: true;
  backup_ts: string; // canonical "YYYYMMDDTHHMMSSZ"
  prev_origin: [number, number, number];
  new_origin: [number, number, number];
  restart_required: true;
}

// --- Track B-SYSTEM PR-2 — service observability wire shapes ---------
// Mirror of `godo_webctl.protocol::SYSTEM_SERVICES_FIELDS` and the
// `services.ServiceShow` dataclass. Drift detected by inspection per
// godo-frontend/CODEBASE.md invariant (t).
export const SYSTEM_SERVICES_FIELDS = [
  'name',
  'active_state',
  'sub_state',
  'main_pid',
  'active_since_unix',
  'memory_bytes',
  'env_redacted',
  'env_stale',
] as const;

// One row of `/api/system/services`.
export interface SystemServiceEntry {
  name: string; // e.g. "godo-tracker"
  active_state: string; // "active" | "activating" | ... | "unknown" (degraded)
  sub_state: string; // systemd sub-state ("running", "dead", "auto-restart", ...)
  main_pid: number | null; // null when MainPID=0 or [not set]
  active_since_unix: number | null; // unix-seconds derived from ActiveEnterTimestampMonotonic; null when not active
  memory_bytes: number | null; // null when MemoryAccounting=no or [not set]
  env_redacted: Record<string, string>; // env-vars with secret-pattern KEYS replaced by `<redacted>`
  env_stale: boolean; // true when any EnvironmentFile=mtime > active_since_unix (operator edited envfile post-start; restart pending)
}

// GET /api/system/services response shape.
export interface SystemServicesResponse {
  services: SystemServiceEntry[];
}

// Track B-SYSTEM PR-2 — transition-in-progress error codes (HTTP 409).
export const ERR_SERVICE_STARTING = 'service_starting';
export const ERR_SERVICE_STOPPING = 'service_stopping';

// Track B-SYSTEM PR-2 — wire-side redaction placeholder (mirror of
// `godo_webctl.protocol.REDACTED_PLACEHOLDER`). The SPA renders this
// string verbatim and tags the row with `(secret)` for clarity.
export const REDACTED_PLACEHOLDER = '<redacted>';

// Track B-SYSTEM PR-2 — admin-non-loopback action endpoint path builder.
// Mirrors `/api/local/service/<name>/<action>` shape, but routed at
// `/api/system/service/<name>/<action>` (no loopback gate).
export const apiSystemServiceAction = (name: string, action: string): string =>
  `/api/system/service/${name}/${action}`;

// --- Track B-SYSTEM PR-B — process monitor + extended resources --------
// Mirror of `godo_webctl.protocol::PROCESS_FIELDS` /
// `PROCESSES_RESPONSE_FIELDS` / `EXTENDED_RESOURCES_FIELDS` /
// `GODO_PROCESS_NAMES` / `MANAGED_PROCESS_NAMES`. Drift detected by
// inspection per godo-frontend/CODEBASE.md invariant (y).
//
// Wire field name is `category` (NOT `class` — TS reserved word +
// Svelte template collision). Per Mode-A M3 fold.
//
// `published_mono_ns` clock domain: webctl `time.monotonic_ns()`
// (Python clock domain), NOT the C++ tracker's CLOCK_MONOTONIC.
// SPA freshness uses arrival-wall-clock (`Date.now() - _arrival_ms`)
// per invariant (m) — never compares published_mono_ns across the
// C++/webctl boundary.

// issue#16 HIL hot-fix (2026-05-02 KST) — added "docker" category for
// docker-family processes (dockerd / containerd / docker run-parent /
// containerd-shim*). The SPA picks the rendered colour based on the
// current mapping state (idle → green, running → blue) so the operator
// sees at a glance whether the docker daemons are sitting idle or are
// actively driving the mapping container.
export type ProcessCategory = 'general' | 'godo' | 'managed' | 'docker';

export const PROCESS_FIELDS = [
  'name',
  'pid',
  'user',
  'state',
  'cmdline',
  'cpu_pct',
  'rss_mb',
  'etime_s',
  'category',
  'duplicate',
] as const;

export interface ProcessEntry {
  name: string;
  pid: number;
  user: string;
  state: string; // R/S/D/Z/T/I/W/X
  cmdline: string[];
  cpu_pct: number;
  rss_mb: number | null;
  etime_s: number;
  category: ProcessCategory;
  duplicate: boolean;
}

export interface ProcessesSnapshot {
  processes: ProcessEntry[];
  duplicate_alert: boolean;
  published_mono_ns: number;
  _arrival_ms?: number; // client-side; set by store on receipt
}

export const EXTENDED_RESOURCES_FIELDS = [
  'cpu_per_core',
  'cpu_aggregate_pct',
  'mem_total_mb',
  'mem_used_mb',
  'disk_pct',
  'published_mono_ns',
] as const;

export interface ExtendedResources {
  cpu_per_core: number[];
  cpu_aggregate_pct: number;
  mem_total_mb: number | null;
  mem_used_mb: number | null;
  disk_pct: number | null;
  published_mono_ns: number;
  _arrival_ms?: number; // client-side; set by store on receipt
}

// Subset of `GODO_PROCESS_NAMES` whose category is `"managed"` —
// styled differently in the SPA than `general` / `godo`. Mirror of
// `godo_webctl.protocol::MANAGED_PROCESS_NAMES`.
export const MANAGED_PROCESS_NAMES: ReadonlySet<string> = new Set<string>([
  'godo_tracker_rt',
  'godo-webctl',
  'godo-irq-pin',
]);

// Full GODO process whitelist mirror.
export const GODO_PROCESS_NAMES: ReadonlySet<string> = new Set<string>([
  'godo_tracker_rt',
  'godo_freed_passthrough',
  'godo_smoke',
  'godo_jitter',
  'godo-webctl',
]);

// --- issue#3 — POST /api/calibrate body ----------------------------------
// Mirror of `godo-webctl/src/godo_webctl/app.py::CalibrateBody`. All
// fields optional; webctl Pydantic enforces all-or-none on the seed
// triple AND that σ overrides require seed_* to be present. Bounds
// match production/RPi5/src/uds/uds_server.cpp::hint_within_bounds:
//   - seed_x_m, seed_y_m ∈ [-100, 100]
//   - seed_yaw_deg ∈ [0, 360)
//   - sigma_xy_m ∈ [0.05, 5.0]
//   - sigma_yaw_deg ∈ [1.0, 90.0]
//
// Drift policy: changing any field name / bound here without changing
// the corresponding webctl Pydantic + C++ uds_server bounds is a
// code-review block.
export interface CalibrateBody {
  seed_x_m?: number;
  seed_y_m?: number;
  seed_yaw_deg?: number;
  sigma_xy_m?: number;
  sigma_yaw_deg?: number;
}

// --- issue#14 — mapping pipeline wire shapes -------------------------
// Mirror of `godo_webctl.protocol::MAPPING_STATE_*` /
// `MAPPING_STATUS_FIELDS` / `MAPPING_MONITOR_FIELDS` and the mapping-
// pipeline error codes. Drift detected by inspection per
// godo-frontend/CODEBASE.md invariant (the new mapping block).

export const MAPPING_STATE_IDLE = 'idle';
export const MAPPING_STATE_STARTING = 'starting';
export const MAPPING_STATE_RUNNING = 'running';
export const MAPPING_STATE_STOPPING = 'stopping';
export const MAPPING_STATE_FAILED = 'failed';

export type MappingState =
  | typeof MAPPING_STATE_IDLE
  | typeof MAPPING_STATE_STARTING
  | typeof MAPPING_STATE_RUNNING
  | typeof MAPPING_STATE_STOPPING
  | typeof MAPPING_STATE_FAILED;

export const VALID_MAPPING_STATES: ReadonlySet<MappingState> = new Set<MappingState>([
  MAPPING_STATE_IDLE,
  MAPPING_STATE_STARTING,
  MAPPING_STATE_RUNNING,
  MAPPING_STATE_STOPPING,
  MAPPING_STATE_FAILED,
]);

export const MAPPING_STATUS_FIELDS = [
  'state',
  'map_name',
  'container_id_short',
  'started_at',
  'error_detail',
  'journal_tail_available',
] as const;

export interface MappingStatus {
  state: MappingState;
  map_name: string | null;
  container_id_short: string | null;
  started_at: string | null; // ISO 8601 UTC
  error_detail: string | null;
  journal_tail_available: boolean;
}

// Mapping-pipeline error codes (mirror of `godo_webctl.protocol::ERR_*`).
export const ERR_INVALID_MAPPING_NAME = 'invalid_mapping_name';
export const ERR_NAME_EXISTS = 'name_exists';
export const ERR_MAPPING_ALREADY_ACTIVE = 'mapping_already_active';
export const ERR_MAPPING_ACTIVE = 'mapping_active';
export const ERR_IMAGE_MISSING = 'image_missing';
export const ERR_DOCKER_UNAVAILABLE = 'docker_unavailable';
export const ERR_TRACKER_STOP_FAILED = 'tracker_stop_failed';
export const ERR_CONTAINER_START_TIMEOUT = 'container_start_timeout';
export const ERR_CONTAINER_STOP_TIMEOUT = 'container_stop_timeout';
export const ERR_NO_ACTIVE_MAPPING = 'no_active_mapping';
export const ERR_PREVIEW_NOT_YET_PUBLISHED = 'preview_not_yet_published';
export const ERR_STATE_FILE_CORRUPT = 'state_file_corrupt';

// Docker-only monitor frame (S1 amendment). RPi5 host stats live in
// /api/system/resources/extended/stream.
export const MAPPING_MONITOR_FIELDS = [
  'valid',
  'container_id_short',
  'container_state',
  'container_cpu_pct',
  'container_mem_bytes',
  'container_net_rx_bytes',
  'container_net_tx_bytes',
  'var_lib_godo_disk_avail_bytes',
  'var_lib_godo_disk_total_bytes',
  'in_progress_map_size_bytes',
  'published_mono_ns',
] as const;

export type MappingContainerState = 'running' | 'exited' | 'no_active';

export interface MappingMonitorFrame {
  valid: boolean;
  container_id_short: string | null;
  container_state: MappingContainerState;
  container_cpu_pct: number | null;
  container_mem_bytes: number | null;
  container_net_rx_bytes: number | null;
  container_net_tx_bytes: number | null;
  var_lib_godo_disk_avail_bytes: number | null;
  var_lib_godo_disk_total_bytes: number | null;
  in_progress_map_size_bytes: number | null;
  published_mono_ns: number;
}

// MAPPING_NAME_REGEX_PATTERN_STR — mirror of webctl
// `MAPPING_NAME_REGEX.pattern`. C5 fix: leading dot REJECTED. Pinned
// by `tests/unit/mappingNameValidation.test.ts` for parity.
export const MAPPING_NAME_REGEX_PATTERN_STR =
  '^[A-Za-z0-9_()-][A-Za-z0-9._()\\-,]{0,63}$';

// --- issue#16 — mapping pre-check + cp210x recovery wire shapes -------
// Mirror of `godo_webctl.protocol::PRECHECK_FIELDS` /
// `PRECHECK_CHECK_FIELDS` / `PRECHECK_CHECK_NAMES` and the issue#16
// error codes. Spec memory:
// `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.
// Drift detected by inspection per godo-frontend/CODEBASE.md invariant.

export const PRECHECK_FIELDS = ['ready', 'checks'] as const;

export const PRECHECK_CHECK_FIELDS = ['name', 'ok', 'value', 'detail'] as const;

// Canonical names + emit order of the 6 checks. Order matches the
// backend's `precheck()` so the SPA can iterate the tuple to render
// rows in the operator-locked sequence.
export const PRECHECK_CHECK_NAMES = [
  'lidar_readable',
  'tracker_stopped',
  'image_present',
  'disk_space_mb',
  'name_available',
  'state_clean',
] as const;

export type PrecheckCheckName = (typeof PRECHECK_CHECK_NAMES)[number];

// One row of the `checks` array. `ok` is `null` for the pending state
// (operator hasn't typed a name yet); SPA renders ⋯. `value` and
// `detail` are always emitted (null when absent) so the renderer's
// shape is stable.
export interface PrecheckCheck {
  name: string;
  ok: boolean | null;
  value: number | string | null;
  detail: string | null;
}

export interface PrecheckResult {
  ready: boolean;
  checks: PrecheckCheck[];
}

// issue#16 error codes (mirror of webctl `protocol.py::ERR_*`).
export const ERR_CP210X_RECOVERY_FAILED = 'cp210x_recovery_failed';
export const ERR_LIDAR_PORT_NOT_RESOLVABLE = 'lidar_port_not_resolvable';
