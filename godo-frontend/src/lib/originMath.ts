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
 * Resolve a delta-mode `(dx, dy)` to absolute world coords using the
 * ADD sign convention (operator-locked 2026-04-30 KST, see
 * `.claude/memory/project_map_edit_origin_rotation.md`):
 *
 *   new_origin = current_origin + (dx, dy)
 *
 * Operator phrasing: "실제 원점 위치는 여기서 (x, y)만큼 더 간 곳".
 * Pinned by `tests/unit/originMath.test.ts::resolveDelta adds`.
 */
export function resolveDelta(
  currentOrigin: OriginXyTheta,
  dx: number,
  dy: number,
): { x_m: number; y_m: number } {
  return {
    x_m: currentOrigin[0] + dx,
    y_m: currentOrigin[1] + dy,
  };
}

/**
 * Identity wrapper for absolute-mode input. Exists for symmetry with
 * `resolveDelta` so the call sites (`OriginPicker.svelte`, the apply
 * handler) read uniformly regardless of mode and tests can pin the
 * shape contract.
 */
export function resolveAbsolute(absX: number, absY: number): { x_m: number; y_m: number } {
  return { x_m: absX, y_m: absY };
}
