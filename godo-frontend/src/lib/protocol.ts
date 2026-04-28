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
