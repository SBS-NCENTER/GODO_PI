/**
 * Track B-MAPEDIT-2 — pure helpers for pixel↔world math + origin
 * delta/absolute resolution.
 *
 * Sole owner of the SPA-side pixel→world conversion for the new
 * OriginPicker GUI-pick flow (per godo-frontend CODEBASE.md invariant
 * (aa)). The existing PoseCanvas world↔canvas math at
 * `components/PoseCanvas.svelte:148-149` uses the same convention but
 * is not extracted into this module in this PR (would be a refactor
 * outside the LOC budget). Documented rule: every NEW pixel↔world site
 * uses `originMath.ts`.
 *
 * ROS map_server convention reminder (per
 * `.claude/tmp/plan_track_d_scale_yflip.md` + PoseCanvas.svelte:126):
 *
 *   img_col = (wx - origin_x) / resolution
 *   img_row = (height - 1) - (wy - origin_y) / resolution     ← Y-flip
 *
 *   inverse:
 *     world_x = origin[0] + px * resolution
 *     world_y = origin[1] + (height - 1 - py) * resolution
 *
 * The `-1` in the Y-flip is load-bearing: PGM origin is the top-left
 * pixel, world origin is the bottom-left pixel. A writer who drops
 * the `-1` shifts the candidate marker by exactly one cell row
 * (silent ~5 cm error at 0.05 m/cell — caught by Mode-A reviewer M4).
 */

export interface PixelToWorldDims {
  width: number;
  height: number;
}

export type OriginXyTheta = readonly [number, number, number];

/**
 * Convert a logical PGM pixel (px, py) to world coordinates using
 * the active map's resolution + origin. Y-flips per the ROS
 * convention so a click on the map's bottom-left pixel returns
 * `(origin[0], origin[1])`.
 *
 * Caller is responsible for clamping (px, py) to [0, width-1] and
 * [0, height-1] respectively; passing out-of-range values returns
 * extrapolated world coords.
 */
export function pixelToWorld(
  px: number,
  py: number,
  dims: PixelToWorldDims,
  resolution: number,
  origin: OriginXyTheta,
): { world_x: number; world_y: number } {
  const world_x = origin[0] + px * resolution;
  const world_y = origin[1] + (dims.height - 1 - py) * resolution;
  return { world_x, world_y };
}

/**
 * @deprecated since issue#30; remove in issue#31+. Pre-issue#30 SUBTRACT
 *             semantic; new code should use `composeCumulative` +
 *             `pickAnchoredPreview` instead.
 *
 * Pinned by `tests/unit/originMath.test.ts::resolveDeltaFromPose subtracts`
 * (kept as a marker test so the symbol export stays.
 */
export function resolveDeltaFromPose(
  currentPose: { x_m: number; y_m: number },
  dx: number,
  dy: number,
): { x_m: number; y_m: number } {
  return {
    x_m: currentPose.x_m + dx,
    y_m: currentPose.y_m + dy,
  };
}

/**
 * issue#30 — yaw-aware pristine world↔pixel SSOT (mirror of
 * `godo_webctl.map_transform.pristine_world_to_pixel`).
 *
 * Convert pristine-frame cumulative-translate world coord
 * (`cumTx, cumTy`) — the pristine-frame world coord that lands at
 * derived world (0, 0) — to pristine bitmap pixel
 * `(i_p, j_p_top)` (column-from-left, row-from-top).
 *
 * The yaw-aware form: when `othetaP === 0` this collapses to
 *     `i_p = (cumTx - oxP) / res`
 *     `j_p_top = HP - 1 - (cumTy - oyP) / res`
 *
 * SSOT discipline: this function lives in `originMath.ts` (TS) AND
 * `map_transform.py` (Python). Mirror tests pin them to bit-identical
 * outputs across yaw ∈ {0, 0.5, 1.604, π/2, π, -π/3}.
 */
export function pristineWorldToPixel(
  cumTx: number,
  cumTy: number,
  oxP: number,
  oyP: number,
  othetaP: number,
  WP: number,
  HP: number,
  res: number,
): { i_p: number; j_p_top: number } {
  const dx = cumTx - oxP;
  const dy = cumTy - oyP;
  const c = Math.cos(-othetaP);
  const s = Math.sin(-othetaP);
  const localX = c * dx - s * dy;
  const localY = s * dx + c * dy;
  const i_p = localX / res;
  const j_p_top = HP - 1 - localY / res;
  return { i_p, j_p_top };
}

/**
 * issue#30 — sidecar `Cumulative` mirror (matches webctl
 * `godo.map.sidecar.v1` schema).
 */
export interface Cumulative {
  translate_x_m: number;
  translate_y_m: number;
  rotate_deg: number;
}

export interface ThisStepLocal {
  delta_translate_x_m: number;
  delta_translate_y_m: number;
  delta_rotate_deg: number;
  picked_world_x_m: number;
  picked_world_y_m: number;
}

/**
 * issue#30 — compose new cumulative from parent + this Apply's typed
 * delta (mirror of `godo_webctl.sidecar.compose_cumulative`).
 *
 * Per the C-2.1 round-3 lock: cumulative.translate is the pristine-
 * frame world coord that lands at derived world (0, 0) and is computed
 * as `picked_world − R(-θ_active)·typed_delta` where standard 2D CCW
 * rotation matrix `[c -s; s c]` applies.
 */
export function composeCumulative(parent: Cumulative, step: ThisStepLocal): Cumulative {
  const thetaActive = (parent.rotate_deg * Math.PI) / 180;
  const c = Math.cos(-thetaActive);
  const s = Math.sin(-thetaActive);
  const typedDx = step.delta_translate_x_m;
  const typedDy = step.delta_translate_y_m;
  const rotatedDx = c * typedDx - s * typedDy;
  const rotatedDy = s * typedDx + c * typedDy;
  return {
    translate_x_m: step.picked_world_x_m - rotatedDx,
    translate_y_m: step.picked_world_y_m - rotatedDy,
    rotate_deg: wrapYawDeg(parent.rotate_deg + step.delta_rotate_deg),
  };
}

/**
 * Identity wrapper for absolute-mode input. Exists for symmetry with
 * `resolveDeltaFromPose` so the call sites read uniformly regardless of
 * mode and tests can pin the shape contract. Under issue#27 SUBTRACT
 * semantic, the typed value here names the world coord that should
 * become the new (0, 0); the backend computes
 * `new_yaml_origin = old_yaml_origin - {x_m, y_m}`.
 */
export function resolveAbsolute(absX: number, absY: number): { x_m: number; y_m: number } {
  return { x_m: absX, y_m: absY };
}

/**
 * issue#3 — compute the CCW-positive REP-103 yaw angle (degrees, in
 * [0, 360)) from a drag-vector EXPRESSED IN WORLD COORDINATES. The
 * caller MUST supply world-frame `(startWx, startWy)` and `(endWx, endWy)`
 * — typically obtained by feeding canvas-pixel coords through
 * `viewport.canvasToWorld(...)` first (Mode-A M5 — single math SSOT;
 * pose-hint pointer math uses viewport.canvasToWorld, NOT pixelToWorld).
 *
 * `viewport.canvasToWorld` already inverts Y per the ROS map_server
 * convention (world Y increases upward), so a straight `atan2(dy, dx)`
 * on the world-frame delta gives the CCW yaw with the standard
 * mathematical convention. The output is wrapped to `[0, 360)` to
 * match the AMCL / FreeD wire convention.
 *
 * Returns `null` for a zero-length drag (start == end) — caller must
 * decide whether to treat as "no yaw committed" (path B awaiting a
 * second click) or as a parse error.
 */
export function yawFromDrag(
  startWx: number,
  startWy: number,
  endWx: number,
  endWy: number,
): number | null {
  const dx = endWx - startWx;
  const dy = endWy - startWy;
  if (dx === 0 && dy === 0) return null;
  const radians = Math.atan2(dy, dx);
  const degrees = (radians * 180) / Math.PI;
  // Wrap to [0, 360).
  const wrapped = ((degrees % 360) + 360) % 360;
  return wrapped;
}

/**
 * issue#28 — wrap a yaw value into the half-open range (-180, 180].
 *
 * Mirror of webctl `map_origin.wrap_yaw_deg`. Used by the OriginPicker
 * to display the SUBTRACT result and by `resolveYawDeltaFromPose` so
 * the operator never sees a 200° badge after a 10° pick on a 190°
 * baseline.
 *
 * Edge case: -180 reflects to +180 to keep the range half-open at the
 * lower bound (matches the backend wrap precisely).
 */
export function wrapYawDeg(value: number): number {
  if (!Number.isFinite(value)) return value;
  const span = 360;
  const min = -180;
  const max = 180;
  const shifted = ((value - min) % span + span) % span;
  let wrapped = shifted + min;
  if (wrapped === min) wrapped = max;
  return wrapped;
}

/**
 * issue#28 — compute the yaw the SPA should send to the backend given
 * the operator's typed value (degrees) and the previous baseline.
 *
 * SUBTRACT semantic mirror of `(x_m, y_m)`: the backend computes
 * `new_origin_yaw = wrap(prev_origin_yaw - typed_yaw_deg)`. The SPA
 * here computes the SAME delta so the OriginPicker preview matches
 * post-Apply state without an SSE round-trip.
 *
 * `prevOriginYawDeg` is the YAML's current `origin[2]` in degrees
 * (the SPA already converts radians → degrees on the read path).
 *
 * Pinned by `originMath.test.ts::ROTATE#1 typed=10° on origin=5° → -5°`
 * and `ROTATE#2 typed=20° on origin=-5° → -25°`.
 */
export function resolveYawDeltaFromPose(
  prevOriginYawDeg: number,
  typedYawDeg: number,
): number {
  return wrapYawDeg(prevOriginYawDeg - typedYawDeg);
}

/**
 * issue#28 — compute the desired YAW from a 2-click yaw pick. Operator
 * clicks point P1 (origin), then point P2 (along the desired +x axis);
 * we return the typed-θ value that, when applied via Apply, rotates
 * the bitmap so the (P1→P2) direction becomes the new +x.
 *
 * Sign convention (operator-locked 2026-05-05 KST after PR #84 HIL):
 *   - Backend semantic: `typed +θ` = bitmap visual CCW by θ.
 *   - For the (P1→P2) direction at world-angle β to become the new +x,
 *     the bitmap must rotate visually by -β (CW by β). This corresponds
 *     to typed value -β under the locked semantic.
 *   - We therefore return `-atan2(dy, dx)` (negated standard atan2).
 *
 * The caller MUST supply WORLD-frame coordinates (canvas → world via
 * `viewport.canvasToWorld`). World Y increases upward (ROS map_server
 * convention).
 *
 * Returns `null` when the two points are pixel-coincident — the caller
 * displays the "두 점이 너무 가깝습니다" inline error.
 */
export function twoClickToYawDeg(
  p1Wx: number,
  p1Wy: number,
  p2Wx: number,
  p2Wy: number,
  minPixelDistPx: number,
  resolutionMPerPx: number,
): number | null {
  const dxWorld = p2Wx - p1Wx;
  const dyWorld = p2Wy - p1Wy;
  // Convert world distance back to pixel distance for the proximity
  // guard. (Equivalent to the click-pixel distance because the world
  // metric is uniform in `resolution`).
  const distPx = Math.hypot(dxWorld, dyWorld) / resolutionMPerPx;
  if (distPx < minPixelDistPx) return null;
  const radians = Math.atan2(dyWorld, dxWorld);
  const degrees = (radians * 180) / Math.PI;
  // Negate for the locked semantic (typed +θ = visual CCW θ).
  return wrapYawDeg(-degrees);
}
