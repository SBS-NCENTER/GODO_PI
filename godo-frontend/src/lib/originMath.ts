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
