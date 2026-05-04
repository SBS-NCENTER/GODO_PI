/**
 * issue#28 HIL fix 2026-05-04 KST — overlay draw helpers.
 *
 * These pure functions render origin/axis, world-frame grid, and
 * pick preview markers via the SAME world→canvas projection that
 * `<MapUnderlay/>` uses for the bitmap and pose. Calling them
 * inside MapUnderlay's `ondraw` hook (instead of mounting separate
 * canvases) guarantees the overlays inherit pan/zoom transforms
 * automatically — no per-overlay viewport bookkeeping needed.
 *
 * Sole owner of all map-overlay drawing arithmetic. Constants live
 * in `lib/constants.ts` per the no-magic-numbers rule.
 */

import {
  AXIS_LABEL_FONT_PX,
  AXIS_LINE_WIDTH_PX,
  AXIS_X_COLOR,
  AXIS_Y_COLOR,
  GRID_INTERVAL_SCHEDULE,
  GRID_LINE_COLOR,
  GRID_MAX_LINES_PER_AXIS,
  PICK_PREVIEW_ARROW_HEAD_PX,
  PICK_PREVIEW_COLOR,
  PICK_PREVIEW_DOT_RADIUS_PX,
  PICK_PREVIEW_LINE_WIDTH_PX,
} from './constants';

export type WorldToCanvas = (wx: number, wy: number) => [number, number];

// ---------------------------------------------------------------------
// Origin + axes
// ---------------------------------------------------------------------

export interface OriginAxisParams {
  /** YAML origin yaw in degrees (CCW positive). */
  yawDeg: number;
}

/** Draw +x (red) and +y (green) axes through world (0, 0), rotated
 * by `yawDeg` (CCW). Axis lines extend ±1000 m so they reach the
 * screen edge at any reasonable zoom. */
export function drawOriginAxis(
  ctx: CanvasRenderingContext2D,
  w2c: WorldToCanvas,
  params: OriginAxisParams,
): void {
  const yawRad = (params.yawDeg * Math.PI) / 180;
  const cosY = Math.cos(yawRad);
  const sinY = Math.sin(yawRad);
  const len = 1000; // metres — long enough to clip at screen edge

  const [cx, cy] = w2c(0, 0);
  const [xPosX, xPosY] = w2c(len * cosY, len * sinY);
  const [xNegX, xNegY] = w2c(-len * cosY, -len * sinY);
  const [yPosX, yPosY] = w2c(-len * sinY, len * cosY);
  const [yNegX, yNegY] = w2c(len * sinY, -len * cosY);

  ctx.save();
  ctx.lineWidth = AXIS_LINE_WIDTH_PX;

  // +x axis (red), full line through origin
  ctx.strokeStyle = AXIS_X_COLOR;
  ctx.beginPath();
  ctx.moveTo(xNegX, xNegY);
  ctx.lineTo(xPosX, xPosY);
  ctx.stroke();

  // +y axis (green)
  ctx.strokeStyle = AXIS_Y_COLOR;
  ctx.beginPath();
  ctx.moveTo(yNegX, yNegY);
  ctx.lineTo(yPosX, yPosY);
  ctx.stroke();

  // Origin dot
  ctx.fillStyle = '#1f2937';
  ctx.beginPath();
  ctx.arc(cx, cy, 4, 0, Math.PI * 2);
  ctx.fill();

  // Labels at 1m along each axis
  ctx.font = `${AXIS_LABEL_FONT_PX}px sans-serif`;
  const [lxx, lxy] = w2c(cosY, sinY);
  const [lyx, lyy] = w2c(-sinY, cosY);
  ctx.fillStyle = AXIS_X_COLOR;
  ctx.fillText('+x', lxx + 4, lxy);
  ctx.fillStyle = AXIS_Y_COLOR;
  ctx.fillText('+y', lyx + 4, lyy);

  ctx.restore();
}

// ---------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------

export interface GridParams {
  /** Effective px-per-meter in the canvas (factors in viewport zoom
   * AND the bitmap's resolution). Used to pick the zoom-adaptive
   * interval from `GRID_INTERVAL_SCHEDULE`. */
  pxPerMeter: number;
  /** World-frame visible bounds (compute from canvas corners via
   * inverse worldToCanvas before calling). The grid only draws lines
   * inside this rectangle, capped at `GRID_MAX_LINES_PER_AXIS`. */
  worldMinX: number;
  worldMaxX: number;
  worldMinY: number;
  worldMaxY: number;
  /** HIL fix 2026-05-04 KST — grid rotation in degrees (CCW). Grid
   * lines align with the +x and +y axes of the same rotated frame
   * the axis overlay uses, so they always look "stuck to" the
   * yamlOriginYawDeg direction. Default 0 = world-axis-aligned. */
  yawDeg?: number;
}

interface GridScheduleEntry {
  intervalM: number;
  lineWidthPx: number;
}

function pickGridInterval(pxPerMeter: number): GridScheduleEntry {
  for (const e of GRID_INTERVAL_SCHEDULE) {
    if (e.maxZoom === null || pxPerMeter < e.maxZoom * 100) {
      return { intervalM: e.intervalM, lineWidthPx: e.lineWidthPx };
    }
  }
  return { intervalM: 1, lineWidthPx: 1 };
}

/** Draw a grid (lines parallel to the +x and +y axes of a frame
 * rotated by `yawDeg` from the world frame). At yawDeg=0 the grid
 * is world-axis-aligned; at yawDeg=30° the grid lines align with
 * the rotated axes the operator sees in the axis overlay. All
 * lines project through `w2c` so they pan/zoom with the underlay. */
export function drawGrid(
  ctx: CanvasRenderingContext2D,
  w2c: WorldToCanvas,
  params: GridParams,
): void {
  const { intervalM, lineWidthPx } = pickGridInterval(params.pxPerMeter);
  if (!(intervalM > 0)) return;

  const yawRad = ((params.yawDeg ?? 0) * Math.PI) / 180;
  const cosY = Math.cos(yawRad);
  const sinY = Math.sin(yawRad);

  // Inverse-rotate the visible world bounds into the rotated local
  // frame so we know which line indices fall inside the viewport.
  // local = R(-yaw) · world ⇒ (lx, ly) = (wx*cos+wy*sin, -wx*sin+wy*cos).
  const corners: Array<[number, number]> = [
    [params.worldMinX, params.worldMinY],
    [params.worldMinX, params.worldMaxY],
    [params.worldMaxX, params.worldMinY],
    [params.worldMaxX, params.worldMaxY],
  ];
  const localXs = corners.map(([wx, wy]) => wx * cosY + wy * sinY);
  const localYs = corners.map(([wx, wy]) => -wx * sinY + wy * cosY);
  const localMinX = Math.min(...localXs);
  const localMaxX = Math.max(...localXs);
  const localMinY = Math.min(...localYs);
  const localMaxY = Math.max(...localYs);

  ctx.save();
  ctx.strokeStyle = GRID_LINE_COLOR;
  ctx.lineWidth = lineWidthPx;

  // Forward-rotation helper: world = R(yaw) · local.
  const localToWorld = (lx: number, ly: number): [number, number] => [
    lx * cosY - ly * sinY,
    lx * sinY + ly * cosY,
  ];

  // Lines parallel to rotated +y (constant local x)
  const startX = Math.ceil(localMinX / intervalM) * intervalM;
  let drawnX = 0;
  for (let lx = startX; lx <= localMaxX; lx += intervalM) {
    if (drawnX++ >= GRID_MAX_LINES_PER_AXIS) break;
    const [w0x, w0y] = localToWorld(lx, localMinY);
    const [w1x, w1y] = localToWorld(lx, localMaxY);
    const [c0x, c0y] = w2c(w0x, w0y);
    const [c1x, c1y] = w2c(w1x, w1y);
    ctx.beginPath();
    ctx.moveTo(c0x, c0y);
    ctx.lineTo(c1x, c1y);
    ctx.stroke();
  }
  // Lines parallel to rotated +x (constant local y)
  const startY = Math.ceil(localMinY / intervalM) * intervalM;
  let drawnY = 0;
  for (let ly = startY; ly <= localMaxY; ly += intervalM) {
    if (drawnY++ >= GRID_MAX_LINES_PER_AXIS) break;
    const [w0x, w0y] = localToWorld(localMinX, ly);
    const [w1x, w1y] = localToWorld(localMaxX, ly);
    const [c0x, c0y] = w2c(w0x, w0y);
    const [c1x, c1y] = w2c(w1x, w1y);
    ctx.beginPath();
    ctx.moveTo(c0x, c0y);
    ctx.lineTo(c1x, c1y);
    ctx.stroke();
  }
  ctx.restore();
}

// ---------------------------------------------------------------------
// Pick previews
// ---------------------------------------------------------------------

export interface PickPreviewParams {
  /** Picked XY origin in world coords (operator clicked once in
   * Coord-XY sub-mode). `null` when no XY pick has been made. */
  xy: { x: number; y: number } | null;
  /** Picked Yaw vector (P1 → P2) in world coords. Either point can
   * be `null`. When only `p1` is set, render a half-finished marker
   * (operator placed P1 but is still waiting to place P2). */
  yawP1: { x: number; y: number } | null;
  yawP2: { x: number; y: number } | null;
}

/** Draw orange preview markers for any picks the operator has made
 * but not yet Applied. Cleared by parent when the OriginPicker's
 * dirty state goes back to clean (Apply / Discard). */
export function drawPickPreview(
  ctx: CanvasRenderingContext2D,
  w2c: WorldToCanvas,
  params: PickPreviewParams,
): void {
  ctx.save();
  ctx.fillStyle = PICK_PREVIEW_COLOR;
  ctx.strokeStyle = PICK_PREVIEW_COLOR;
  ctx.lineWidth = PICK_PREVIEW_LINE_WIDTH_PX;

  if (params.xy) {
    const [cx, cy] = w2c(params.xy.x, params.xy.y);
    ctx.beginPath();
    ctx.arc(cx, cy, PICK_PREVIEW_DOT_RADIUS_PX, 0, Math.PI * 2);
    ctx.fill();
  }

  if (params.yawP1 && !params.yawP2) {
    // Half-finished: P1 placed, awaiting P2. Render P1 as a hollow
    // dot to distinguish from the filled XY pick.
    const [px, py] = w2c(params.yawP1.x, params.yawP1.y);
    ctx.beginPath();
    ctx.arc(px, py, PICK_PREVIEW_DOT_RADIUS_PX, 0, Math.PI * 2);
    ctx.stroke();
  } else if (params.yawP1 && params.yawP2) {
    const [p1x, p1y] = w2c(params.yawP1.x, params.yawP1.y);
    const [p2x, p2y] = w2c(params.yawP2.x, params.yawP2.y);
    // Shaft
    ctx.beginPath();
    ctx.moveTo(p1x, p1y);
    ctx.lineTo(p2x, p2y);
    ctx.stroke();
    // Arrowhead at P2
    const dx = p2x - p1x;
    const dy = p2y - p1y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    // Two arrowhead lines at ±25° from the shaft direction.
    const aHead = PICK_PREVIEW_ARROW_HEAD_PX;
    const cosA = Math.cos((25 * Math.PI) / 180);
    const sinA = Math.sin((25 * Math.PI) / 180);
    const lx = -aHead * (ux * cosA - uy * sinA);
    const ly = -aHead * (uy * cosA + ux * sinA);
    const rx = -aHead * (ux * cosA + uy * sinA);
    const ry = -aHead * (uy * cosA - ux * sinA);
    ctx.beginPath();
    ctx.moveTo(p2x, p2y);
    ctx.lineTo(p2x + lx, p2y + ly);
    ctx.moveTo(p2x, p2y);
    ctx.lineTo(p2x + rx, p2y + ry);
    ctx.stroke();
    // Origin marker on P1
    ctx.beginPath();
    ctx.arc(p1x, p1y, PICK_PREVIEW_DOT_RADIUS_PX * 0.6, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}
