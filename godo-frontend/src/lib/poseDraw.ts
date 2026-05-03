/**
 * issue#27 — pose-layer drawing helpers (extracted from PoseCanvas).
 *
 * Two pure-function consumers:
 *   - <PoseCanvas/> on /map (Overview): draws trail + pose+heading.
 *   - <MapEdit/> on /map-edit (Edit sub-tab): draws pose+heading only,
 *     no trail.
 *
 * The functions take everything they need as parameters — no closures,
 * no module-scope state — so they can be unit-tested with a synthetic
 * 2D context (vitest pinned by `tests/unit/poseDraw.test.ts`).
 *
 * `worldToCanvas` matches `<MapUnderlay/>::worldToCanvas` — supplied by
 * the layer-3 paint hook (the underlay invokes `ondraw(ctx, w2c)`
 * passing its own projection).
 */

import {
  DEG_TO_RAD,
  MAP_HEADING_LINE_WIDTH_PX,
  MAP_POSE_COLOR,
  MAP_POSE_DOT_RADIUS_PX,
  MAP_POSE_HEADING_LEN_PX,
  MAP_TRAIL_COLOR,
  MAP_TRAIL_DOT_RADIUS_RATIO,
  MAP_TRAIL_MAX_OPACITY,
} from './constants';
import type { LastPose } from './protocol';

/**
 * Draw the current-pose dot + heading arrow at world coords. Skips
 * silently when `pose` is null or `pose.valid` is false.
 *
 * Yaw convention: CCW-positive degrees, [0, 360); canvas Y axis points
 * DOWN, so we negate the sin component when projecting the arrow tip.
 */
export function drawPose(
  ctx: CanvasRenderingContext2D,
  worldToCanvas: (wx: number, wy: number) => [number, number],
  pose: LastPose | null,
): void {
  if (!pose || !pose.valid) return;
  const [cx, cy] = worldToCanvas(pose.x_m, pose.y_m);
  ctx.fillStyle = MAP_POSE_COLOR;
  ctx.beginPath();
  ctx.arc(cx, cy, MAP_POSE_DOT_RADIUS_PX, 0, Math.PI * 2);
  ctx.fill();
  const yawRad = pose.yaw_deg * DEG_TO_RAD;
  const ex = cx + Math.cos(yawRad) * MAP_POSE_HEADING_LEN_PX;
  const ey = cy - Math.sin(yawRad) * MAP_POSE_HEADING_LEN_PX;
  ctx.strokeStyle = MAP_POSE_COLOR;
  ctx.lineWidth = MAP_HEADING_LINE_WIDTH_PX;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(ex, ey);
  ctx.stroke();
}

/**
 * Draw the trail (oldest-faintest history dots). Empty array → no-op.
 * Each entry is `{x, y, yaw}` where `yaw` is unused for the trail
 * (only the dot is drawn) but kept for API parity with the Overview
 * trail buffer.
 */
export function drawTrail(
  ctx: CanvasRenderingContext2D,
  worldToCanvas: (wx: number, wy: number) => [number, number],
  trail: ReadonlyArray<{ x: number; y: number; yaw: number }>,
): void {
  if (trail.length === 0) return;
  for (let i = 0; i < trail.length; i++) {
    const p = trail[i]!;
    const [cx, cy] = worldToCanvas(p.x, p.y);
    const alpha = (i + 1) / trail.length;
    ctx.globalAlpha = alpha * MAP_TRAIL_MAX_OPACITY;
    ctx.fillStyle = MAP_TRAIL_COLOR;
    ctx.beginPath();
    ctx.arc(cx, cy, MAP_POSE_DOT_RADIUS_PX * MAP_TRAIL_DOT_RADIUS_RATIO, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}
