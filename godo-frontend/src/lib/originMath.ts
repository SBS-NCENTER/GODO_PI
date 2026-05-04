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
 * issue#27 — SUBTRACT semantic (supersedes 2026-04-30 ADD lock).
 *
 * Operator's mental model: typed (x_m, y_m) names the world coord of
 * the point that should become the new (0, 0). The backend computes
 * `new_yaml_origin = old_yaml_origin - typed`. Frontend math here
 * resolves delta-mode input to the absolute-mode equivalent BEFORE
 * sending to the backend so the backend stays dumb (single SUBTRACT
 * formula, no UDS round-trip on the rename path, no stale-pose risk).
 *
 * `resolveDeltaFromPose` — the SPA's preferred path: typed (dx, dy) is
 * an offset vector from the current LiDAR-frame pose to the point that
 * should become the new (0, 0). Returns the absolute world coord that
 * the operator's typed delta resolves to. The backend then applies its
 * canonical SUBTRACT to produce the YAML origin update.
 *
 * Pinned by `tests/unit/originMath.test.ts::resolveDeltaFromPose subtracts`.
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
 * the angle of the (P1→P2) vector in the world frame is the new yaw.
 *
 * The caller MUST supply WORLD-frame coordinates (canvas → world via
 * `viewport.canvasToWorld`). World Y increases upward (ROS map_server
 * convention) so the vector angle is the standard atan2.
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
  return wrapYawDeg(degrees);
}
