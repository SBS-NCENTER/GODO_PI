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

// --- Track D: live LIDAR overlay ---------------------------------------
// Pixel-space radius of each scan dot. 1.5 px keeps the overlay readable
// without obscuring the underlying map / pose layer.
export const MAP_SCAN_DOT_RADIUS_PX = 1.5;
// Teal (Q-OQ-D3) — visually distinct from pose red (#c62828) + trail
// blue (#1565c0); color-blind friendly trio per the user decision.
export const MAP_SCAN_DOT_COLOR = '#26a69a';
// Slight transparency so dots stacking on a wall still show wall edges.
export const MAP_SCAN_DOT_OPACITY = 0.7;
// Mode-A M2 fold: freshness window in MILLISECONDS, measured against
// `Date.now() - lastScan._arrival_ms` (NOT against published_mono_ns,
// which is in tracker CLOCK_MONOTONIC ns). 1000 ms = 5 ticks @ 5 Hz —
// generous against transient SSE delays.
export const MAP_SCAN_FRESHNESS_MS = 1000;
// Polling fallback when SSE drops. Slightly slower than LastPose's 1 s
// because the scan reply is wider (~14 KiB vs ~250 B for pose).
export const LAST_SCAN_POLL_FALLBACK_MS = 1000;

// --- PR-DIAG (Track B-DIAG) — diagnostics page constants ----------------
// Sparkline ring depth: 60 frames × 5 Hz = 12 s of recent history per
// metric. Bigger than the visible chart width (200 px / ~3 px per dot
// = ~66 dots) so the ring buffer is always wider than the render.
export const DIAG_SPARKLINE_DEPTH = 60;
export const DIAG_SPARKLINE_WIDTH_PX = 200;
export const DIAG_SPARKLINE_HEIGHT_PX = 32;

// Freshness budget for the multiplexed DiagFrame. 2 s = 10 ticks @ 5 Hz —
// generous against transient SSE delays. Mode-A M2 / N4 fold pin: this
// is measured against `Date.now() - frame._arrival_ms` (NOT against
// any published_mono_ns field — clock domain mismatch).
export const DIAG_FRESHNESS_MS = 2000;

// Diagnostics polling fallback when SSE drops. 1 Hz feels slightly
// choppy when SSE is broken — itself a useful operator signal that
// "something's off".
export const DIAG_POLL_FALLBACK_MS = 1000;

// Logs tail caps — MUST equal webctl `LOGS_TAIL_MAX_N` /
// `LOGS_TAIL_DEFAULT_N`. Mode-A invariant (m): drift detected by
// inspection during code review; the webctl-side cap is authoritative
// (Pydantic Field(le=...) rejects oversized values).
export const LOGS_TAIL_MAX_N_MIRROR = 500;
export const LOGS_TAIL_DEFAULT_N = 50;

// Diagnostics-panel canvas colours. Distinct from Track D's pose red /
// trail blue / scan teal trio for color-blind friendliness.
export const JITTER_PANEL_COLOR = '#7e57c2'; // purple
export const AMCL_RATE_PANEL_COLOR = '#26a69a'; // teal (matches scan dot)
export const RESOURCES_PANEL_COLOR = '#42a5f5'; // light blue

// --- Track B-BACKUP — map-backup history page strings ----------------
// Mode-A N1 fold: success toast wording mirrors Track E
// `MapListPanel.svelte:116` so operators see consistent restart-flow
// language across both flows. TB1 fold pins this as a constant so
// `Backup.svelte` AND `tests/unit/backup.test.ts` import the same
// symbol — no literal-string duplication.
export const BACKUP_RESTORE_SUCCESS_TOAST =
  '복원 완료. /map에서 활성화하면 godo-tracker 재시작 후 적용됩니다.';

// Mode-A N2 fold: confirm dialog two-line body. The first line
// interpolates `<ts>` at render time; the warning line is static.
// Mirror of `MapListPanel.svelte:262-264` delete-dialog shape.
export const BACKUP_RESTORE_OVERWRITE_WARNING = '⚠ 기존 동일 이름 맵 페어를 덮어씁니다.';
