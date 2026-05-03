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
// /api/system/restart_pending polling backstop. Action-driven refreshes
// (post service-restart, post cfg-PATCH) fire too early to see the
// tracker's own clear_pending_flag(); without polling the banner sticks
// at pending=true until a hard reload. 1 Hz matches HEALTH_POLL_MS so
// banner clearance feels paired with the tracker-status chip.
export const RESTART_PENDING_POLL_MS = 1000;

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

// issue#14 follow-up (operator HIL 2026-05-02 KST): /api/mapping/start
// blocks for up to MAPPING_TRACKER_STOP_TIMEOUT_S (5) + tracker-down
// settle (~10) + container-start polling (8) = ~25 s before responding.
// /api/mapping/stop blocks for up to MAPPING_CONTAINER_STOP_TIMEOUT_S
// (35 s — Maj-1 ladder). With API_FETCH_TIMEOUT_MS = 3 s the SPA aborts
// the fetch long before the backend completes — operator sees
// `request_aborted` while the backend successfully writes the PGM /
// transitions state.json. Use this longer timeout for the two
// mapping endpoints that drive multi-step subprocess work.
//
// 60 s margins both: start (~25 s real) + safety; stop (~35 s real)
// + safety. If operator-tunable timing is bumped via Config tab beyond
// 60 s combined, this constant must be re-tuned (or recomputed from
// status snapshot).
export const MAPPING_OPERATION_TIMEOUT_MS = 60000;

// --- Storage keys -------------------------------------------------------
export const STORAGE_KEY_TOKEN = 'godo:auth';
export const STORAGE_KEY_THEME = 'godo:theme';

// --- Map render --------------------------------------------------------
// Pixel-space radius of the pose dot.
export const MAP_POSE_DOT_RADIUS_PX = 6;
// Length of the heading arrow in pixels.
export const MAP_POSE_HEADING_LEN_PX = 22;
// Default world-to-pixel zoom (1 px = N meters).
// Internally consumed by mapViewport.svelte.ts only; no external readers
// after PR β (Mode-A S4 — kept-not-renamed to avoid drive-by churn).
export const MAP_DEFAULT_ZOOM = 1;
// (`MAP_WHEEL_ZOOM_FACTOR` was deleted in PR β commit 3 — Rule 1 of
// `.claude/memory/project_map_viewport_zoom_rules.md` forbids
// mouse-wheel zoom. The (+/−) buttons + numeric input are the
// operator-locked replacement. A writer reintroducing the constant
// without first amending Rule 1 fails Mode-A Critical (CODEBASE.md
// invariant `(ab)`); pinned by `tests/unit/mapViewportNoWheelImports.test.ts`.)
// Min/max zoom clamps.
// Internally consumed by mapViewport.svelte.ts only.
export const MAP_MIN_ZOOM = 0.1;
export const MAP_MAX_ZOOM = 20;

/**
 * Discrete (+/−) zoom step factor for the shared map viewport (PR β).
 *
 * **Chosen value: 1.25.** Operator-friendly trade-off:
 *   - 100 % → 200 % takes 4 clicks (`100 → 125 → 156 → 195 → 244`).
 *   - 10 % → 1000 % takes ~10 clicks; the operator reaches any target
 *     in roughly 3-4 clicks plus a quick numeric-field correction.
 *
 * **Alternatives evaluated**:
 *   - **1.5**: 100 → 150 → 225 — too coarse; missing intermediate steps.
 *   - **√2 ≈ 1.414**: 100 → 141 → 200 — irrational, awkward percentages.
 *   - **2.0**: 100 → 200 — too aggressive; operators can't preview.
 *   - **1.1** (the old wheel factor): too fine for a discrete button.
 *
 * Precision is supplied by the numeric input (operators can type the
 * exact percent); (+/−) buttons optimize for rough exploration.
 *
 * Pinned by `tests/unit/mapViewport.test.ts::applyZoomStep` (Mode-A S3 —
 * tests assert EXACT value, so a future change here surfaces in CI).
 */
export const MAP_ZOOM_STEP = 1.25;

// Fallback minimum zoom percentage before first map-metadata-arrival
// freezes the actual minimum. 10 % is visibly tiny but allows
// exploration before the first PGM lands.
export const MAP_ZOOM_PERCENT_MIN_DEFAULT = 10;
// Hard ceiling on the numeric input. 1000 % is "every PGM cell ~10 CSS
// px" at our typical 0.05 m/cell resolution — already far past useful.
export const MAP_ZOOM_PERCENT_MAX = 1000;
// Default initial zoom percentage on first paint.
export const MAP_ZOOM_PERCENT_DEFAULT = 100;
// Display rounding for the percentage input. 0 = integer percentages.
export const MAP_ZOOM_PERCENT_DECIMAL_DISPLAY = 0;
// Minimum overlap (px) the map's projected bounding box must keep with
// the viewport on every side once it is larger than the viewport on
// that axis. 100 px is large enough that operators never lose track of
// the map yet small enough that they can still pan to the edges.
export const MAP_PAN_OVERSCAN_PX = 100;

// issue#2.2 follow-up — trackpad-pinch sensitivity. Each wheel event
// from a pinch gesture applies a fractional zoom step, where
// `stepFraction = -e.deltaY / MAP_PINCH_DELTA_PX_PER_STEP`. With
// `MAP_PINCH_DELTA_PX_PER_STEP = 100`, ten 10-px ticks (a typical
// pinch gesture on a Mac trackpad fires ~20 wheel events with
// |deltaY| in the 1–20 range) accumulate to ~1× MAP_ZOOM_STEP, giving
// a controllable feel comparable to a couple of (+/−) button clicks
// per gesture rather than the ~9× explosive zoom of one-step-per-event.
// Operator-locked 2026-04-30 KST: HIL on news-pi01 trackpad found that
// one-step-per-event was too aggressive ("원하는 확대 비율에 정착하기
// 어려워"). 100 was tuned by treating 10 px ≈ one button click.
export const MAP_PINCH_DELTA_PX_PER_STEP = 100;

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

// --- Track B-SYSTEM PR-2 — service observability ----------------------
// 1 Hz polling cadence for `/api/system/services`. Matches the backend
// cache TTL (`SYSTEM_SERVICES_CACHE_TTL_S = 1.0 s`) so the page sees a
// fresh snapshot on every tick without piling DOS pressure on systemctl.
export const SYSTEM_SERVICES_POLL_MS = 1000;

// Stale-banner threshold. 3 × the poll cadence — a missed fetch round
// (poll, retry, retry) before the operator sees the warning. Mirrors
// `Diagnostics.svelte`'s freshness pattern.
export const SYSTEM_SERVICES_STALE_MS = 3000;

// Auto-dismiss interval for the 409 transition-in-progress toast on
// ServiceCard / ServiceStatusCard. 4 s is long enough to read a Korean
// sentence aloud, short enough not to linger past a successful retry.
export const SERVICE_TRANSITION_TOAST_TTL_MS = 4000;

// --- Track B-SYSTEM PR-B — process monitor + extended resources -------
// SSE polling-fallback cadence (when the SSE stream errors). Matches
// the backend SSE_PROCESSES_TICK_S / SSE_RESOURCES_EXTENDED_TICK_S
// (1.0 s).
export const PROCESSES_POLL_FALLBACK_MS = 1000;
export const EXTENDED_RESOURCES_POLL_FALLBACK_MS = 1000;

// Sub-tab keys for `routes/System.svelte`. Component-local `$state`
// holds the current key; the URL doesn't reflect it (in-page state
// like Map.svelte's pan/zoom — Mode-A R10 deferred per Final fold S3).
export const SYSTEM_SUBTAB_OVERVIEW = 'overview';
export const SYSTEM_SUBTAB_PROCESSES = 'processes';
export const SYSTEM_SUBTAB_EXTENDED = 'extended';
// issue#16.1 — manual restore hint for tracker.toml.bak.<unixts>; future
// operator-side help notes can stack inside this subtab.
export const SYSTEM_SUBTAB_HELP = 'help';

// Sub-tab keys for `routes/Map.svelte`. URL-backed (unlike System): the
// Overview sub-tab lives at `/map`, the Edit sub-tab lives at
// `/map-edit`, and the Mapping sub-tab lives at `/map-mapping` (issue#14).
// Refresh + browser back-button preserve the active view; sidebar Map
// link + e2e direct-navigate to `/map-edit` and `/map-mapping` continue
// to work without the legacy top-level Map Edit menu entry.
export const MAP_SUBTAB_OVERVIEW = 'overview';
export const MAP_SUBTAB_EDIT = 'edit';
export const MAP_SUBTAB_MAPPING = 'mapping';

// Per-core CPU bar height. 12 px is dense enough to show 4–8 cores in
// the same panel without scrolling on a 720p preview.
export const CPU_BAR_HEIGHT_PX = 12;

// --- Track B-MAPEDIT — POST /api/map/edit constants ------------------
// Brush radius slider clamps in CSS pixels. The mask canvas is sized to
// PGM logical dimensions (R2 mitigation), so 5..100 CSS px translates
// 1:1 to logical mask cells regardless of `devicePixelRatio`.
export const BRUSH_RADIUS_PX_MIN = 5;
export const BRUSH_RADIUS_PX_MAX = 100;
export const BRUSH_RADIUS_PX_DEFAULT = 15;

// SPA-side mirror of webctl `MAP_EDIT_MASK_PNG_MAX_BYTES` (4 MiB). The
// SPA short-circuits the upload before it even starts (the backend's
// 413 path is defence-in-depth).
export const MASK_PNG_MAX_BYTES = 4_194_304;

// On a successful edit, redirect the operator back to /map after this
// delay so the success toast is visible. 3 s matches the typical
// "ack-and-move-on" cadence operators are used to from /backup.
export const MAP_EDIT_REDIRECT_DELAY_MS = 3000;

// --- Track B-MAPEDIT-2 — POST /api/map/origin SPA constants ----------
// Magnitude bound mirror of webctl `ORIGIN_X_Y_ABS_MAX_M`. Studio is
// ~10 m square; 1 km bound covers it plus 100x headroom for shared-
// frame debug. SPA-side validation rejects values beyond this so the
// upload never starts (the backend's 400 path is defence-in-depth).
export const ORIGIN_X_Y_ABS_MAX_M = 1_000.0;

// Decimal places shown in the operator-facing display (1 mm). The
// underlying state keeps full float precision; this only controls
// the `toFixed`-style render. 3 places is the sub-cm precision the
// operator-locked accuracy target asks for.
export const ORIGIN_DECIMAL_DISPLAY_MM = 3;

// Mirror of MAP_EDIT_REDIRECT_DELAY_MS — same 3 s "ack-and-move-on"
// pacing so the operator sees the success banner before /map opens.
export const ORIGIN_PICK_REDIRECT_DELAY_MS = 3000;

// issue#27 — OriginPicker +/- step defaults. Mirror of the C++ schema
// row defaults (`origin_step.x_m`, `.y_m`, `.yaw_deg`). The SPA reads
// the live values from /api/config when mounted; these constants are
// the fallback shown before the fetch resolves (or when /api/config
// fails). Kept in sync by inspection — drift would mean the operator
// sees a different step pre/post-fetch, harmless but inconsistent.
export const ORIGIN_STEP_X_M_DEFAULT = 0.01;
export const ORIGIN_STEP_Y_M_DEFAULT = 0.01;
export const ORIGIN_STEP_YAW_DEG_DEFAULT = 0.1;

// issue#27 — theta input bound mirror. The schema's
// `amcl.origin_yaw_deg` row bounds [-180, 180]; mirror in the SPA so
// the input rejects out-of-bound values before the backend's 400.
export const ORIGIN_THETA_DEG_ABS_MAX = 180.0;

// --- Track B-CONFIG PR-C — per-row apply-result marker TTL ------------
// After Apply finishes, ✓ / ✗ glyphs render next to each row's input.
// The markers auto-clear after this delay; 2 s is half the System
// transition toast (above) because the operator is reading the row at
// arm's length, not glancing at a top-bar toast.
export const CONFIG_APPLY_RESULT_MARKER_TTL_MS = 5000;

// --- Backup flash banner (operator UX 2026-05-02 KST) -------------------
// /api/map/backup is a fire-and-result action — operators need a visible
// success/failure flash that auto-dismisses. 3 s gives enough time to
// read "백업 완료 (path)" without the banner persisting into unrelated
// navigation.
export const BACKUP_FLASH_DISMISS_MS = 3000;

// --- issue#3 — pose hint UI (Map Overview sub-tab) --------------------
// Pixel distance threshold separating gesture path A (single drag) from
// path B (click-then-click). pointerdown→pointerup with movement <
// MIN_PX is treated as a click, ≥ MIN_PX is treated as a drag. 8 px
// (Mode-A N4 fold) is empirically wide enough that operators don't
// trigger A by accident on the first click of B, and tight enough that
// a deliberate drag of even 1 cm on a typical display triggers A.
export const POSE_HINT_DRAG_MIN_PX = 8;
// Visual marker constants — chosen to be visually distinct from existing
// pose dot (red #c62828) and trail dot (blue #1565c0). The hint marker
// uses a brighter red with a cyan arrow so it's immediately
// distinguishable from the converged pose marker the operator is also
// looking at.
export const POSE_HINT_MARKER_COLOR = '#ff5252';        // bright red
export const POSE_HINT_ARROW_COLOR = '#00e5ff';         // cyan
export const POSE_HINT_MARKER_RADIUS_PX = 7;
export const POSE_HINT_ARROW_LENGTH_PX = 28;
export const POSE_HINT_ARROW_HEAD_PX = 6;
// Numeric panel display rounding (mirrors ORIGIN_DECIMAL_DISPLAY_MM idiom).
export const POSE_HINT_DECIMAL_DISPLAY_MM = 3;
// Numeric input bounds — mirrors webctl Pydantic CalibrateBody bounds:
//   seed_x_m, seed_y_m ∈ [-100, 100]
//   seed_yaw_deg ∈ [0, 360)
export const POSE_HINT_X_Y_ABS_MAX_M = 100.0;
export const POSE_HINT_YAW_DEG_LT = 360.0;

// --- issue#14 — mapping pipeline -------------------------------------
// 1 Hz polling of /api/mapping/status. Mirrors backend
// MAPPING_MONITOR_TICK_S * 1000 = 1000 ms. Same cadence as
// HEALTH_POLL_MS so the operator perceives banner + status flips at
// the same rate.
export const MAPPING_STATUS_POLL_MS = 1000;
// 1 Hz cache-bust refresh for the preview <img> blob URL.
export const MAPPING_PREVIEW_REFRESH_MS = 1000;
// Mirror of webctl `MAPPING_NAME_REGEX.pattern`. Pinned by parity test
// vs. `protocol.ts::MAPPING_NAME_REGEX_PATTERN_STR`. C5 fix: leading
// dot REJECTED — the SPA short-circuits before the upload starts.
// Operator-locked 2026-05-01.
export const MAPPING_NAME_REGEX_SOURCE = '^[A-Za-z0-9_()-][A-Za-z0-9._()\\-,]{0,63}$';
export const MAPPING_NAME_MAX_LEN = 64;
// Reserved names — rejected at validate-name layer regardless of regex.
export const MAPPING_RESERVED_NAMES: ReadonlySet<string> = new Set<string>([
  '.',
  '..',
  'active',
]);
// (S2 amendment — no SSE polling fallback. When the monitor stream
// closes, the SPA freezes the last Docker frame and shows a "중단됨"
// badge; never re-issues HTTP. The only way to refresh Docker stats
// post-close is to start a new mapping run.)
