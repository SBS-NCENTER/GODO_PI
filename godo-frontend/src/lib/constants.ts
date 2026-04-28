/**
 * SPA-internal Tier-1 constants.
 *
 * Every numeric literal in `src/` MUST trace to either:
 *   (a) this file (named, documented),
 *   (b) the wire-side mirror in `protocol.ts` (when the value is on the wire
 *       to the backend), or
 *   (c) a local iteration bound (e.g. a `for` loop counter).
 *
 * Mirroring rules:
 *   - `SSE_TICK_MS`, `JWT_TTL_S`, `ACTIVITY_TAIL_DEFAULT_N` mirror values in
 *     `godo-webctl/src/godo_webctl/constants.py`. Drift is a CODEBASE
 *     invariant violation.
 *   - `LOCAL_HOSTNAMES` mirrors the loopback gate in
 *     `godo-webctl/src/godo_webctl/local_only.py`. Both gates must agree.
 */

// --- SSE cadence (mirrors backend SSE_TICK_S * 1000) --------------------
export const SSE_TICK_MS = 200;

// --- JWT (mirrors backend JWT_TTL_SECONDS) ------------------------------
export const JWT_TTL_S = 21600; // 6 h
// Refresh threshold: when the token is within this many seconds of expiry,
// we silently call /api/auth/refresh. 10 min gives ample margin for the
// 6 h TTL while staying short enough that the server-side restart-rotation
// of the JWT secret takes effect within one operator interaction.
export const JWT_REFRESH_THRESHOLD_S = 600;

// --- Map view ----------------------------------------------------------
// 5 trail points × 200 ms tick = 1 s of pose history. Beyond ~1 s the trail
// degenerates to a straight line at typical crane speeds.
export const MAP_TRAIL_LENGTH = 5;
export const MAP_TRAIL_TTL_MS = 1000;

// --- Polling fallbacks --------------------------------------------------
// LastPose poll fallback when SSE drops or is unavailable.
export const LAST_POSE_POLL_FALLBACK_MS = 1000;
// /api/health polling cadence on DASH (1 Hz is plenty for a status chip).
export const HEALTH_POLL_MS = 1000;

// --- Activity log -------------------------------------------------------
// Mirrors backend ACTIVITY_TAIL_DEFAULT_N.
export const ACTIVITY_TAIL_DEFAULT_N = 5;

// --- Loopback gate (mirrors backend local_only.py) ----------------------
// SPA gates B-LOCAL render via window.location.hostname BEFORE making any
// /api/local/* calls; backend separately enforces 403 via Depends(loopback_only).
export const LOCAL_HOSTNAMES: readonly string[] = ['127.0.0.1', 'localhost', '::1'];

// --- UI breakpoint -----------------------------------------------------
// At >= this width, the sidebar is open by default; below, hamburger.
export const MOBILE_BREAKPOINT_PX = 1024;

// --- Topbar countdown ---------------------------------------------------
// Tick interval for "X후 만료" countdown. 1 s feels alive without burning
// frames.
export const COUNTDOWN_TICK_MS = 1000;

// --- HTTP timing --------------------------------------------------------
// Default HTTP fetch timeout (ms) for non-streaming /api calls. The
// backend's UDS round-trip cap is ~1 s; we give 3 s headroom for slow LAN.
export const API_FETCH_TIMEOUT_MS = 3000;

// --- Storage keys -------------------------------------------------------
export const STORAGE_KEY_TOKEN = 'godo:auth';
export const STORAGE_KEY_THEME = 'godo:theme';
export const STORAGE_KEY_SIDEBAR = 'godo:sidebar';

// --- Map render --------------------------------------------------------
// Pixel-space radius of the pose dot.
export const MAP_POSE_DOT_RADIUS_PX = 6;
// Length of the heading arrow in pixels.
export const MAP_POSE_HEADING_LEN_PX = 22;
// Default world-to-pixel zoom (1 px = N meters). Overridden by user wheel.
export const MAP_DEFAULT_ZOOM = 1;
// Wheel sensitivity (multiplier per wheel notch).
export const MAP_WHEEL_ZOOM_FACTOR = 1.1;
// Min/max zoom clamps.
export const MAP_MIN_ZOOM = 0.1;
export const MAP_MAX_ZOOM = 20;

// --- Service status colours (3 systemd services on B-LOCAL) ------------
export const SVC_NAMES = ['godo-tracker', 'godo-webctl', 'godo-irq-pin'] as const;

// --- Journal tail default n ---------------------------------------------
export const JOURNAL_TAIL_DEFAULT_N = 30;

// --- Dashboard refresh cadence -----------------------------------------
// /api/activity + /api/health re-fetch interval on the dashboard. 5 s is
// fast enough that activity entries from a click feel "live"-ish without
// piling load on a backend that's already polling at 1 Hz.
export const DASHBOARD_REFRESH_MS = 5000;

// --- Local services polling fallback -----------------------------------
// When SSE for /api/local/services/stream is unavailable, fall back to
// polling at this cadence (matches the SSE tick).
export const LOCAL_SERVICES_POLL_MS = 1000;

// --- Map render scale factor -------------------------------------------
// World meters → screen pixels at zoom=1. Empirical: 100 px/m matches a
// typical studio scale where the operator can see the whole crane footprint
// in a 600 px-tall canvas.
export const MAP_PIXELS_PER_METER = 100;

// Minimum on-screen canvas dimensions (used when getBoundingClientRect
// reports 0 because the layout hasn't settled before mount).
export const MAP_CANVAS_MIN_WIDTH_PX = 600;
export const MAP_CANVAS_MIN_HEIGHT_PX = 400;

// Trail dot radius is 0.6× the current-pose dot radius — visibly different
// without overlapping the heading arrow when motion is small.
export const MAP_TRAIL_DOT_RADIUS_RATIO = 0.6;
// Maximum opacity for the most-recent trail point (older fade to 0).
export const MAP_TRAIL_MAX_OPACITY = 0.6;

// Hex colours for canvas drawing. These are NOT keyed off the theme tokens
// because the canvas image is rasterised regardless of CSS variables.
export const MAP_TRAIL_COLOR = '#1565c0';
export const MAP_POSE_COLOR = '#c62828';
export const MAP_HEADING_LINE_WIDTH_PX = 2;

// Conversion factor for degrees → radians.
export const DEG_TO_RAD = Math.PI / 180;
