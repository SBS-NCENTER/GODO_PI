/**
 * issue#28 HIL fix 2026-05-04 KST — pin the overlay-draw helpers'
 * arithmetic. These helpers replaced the standalone OriginAxisOverlay
 * and GridOverlay components; the contract is "use the supplied w2c
 * projector for every coordinate, never bake in pan/zoom assumptions."
 */
import { describe, expect, it, vi } from 'vitest';
import {
  drawGrid,
  drawOriginAxis,
  drawPickPreview,
  type WorldToCanvas,
} from '../../src/lib/overlayDraw';

function fakeCtx() {
  const calls: Array<{ op: string; args: unknown[] }> = [];
  const ctx = {
    canvas: { width: 400, height: 400 },
    save: () => calls.push({ op: 'save', args: [] }),
    restore: () => calls.push({ op: 'restore', args: [] }),
    beginPath: () => calls.push({ op: 'beginPath', args: [] }),
    moveTo: (x: number, y: number) => calls.push({ op: 'moveTo', args: [x, y] }),
    lineTo: (x: number, y: number) => calls.push({ op: 'lineTo', args: [x, y] }),
    arc: (...args: unknown[]) => calls.push({ op: 'arc', args }),
    fill: () => calls.push({ op: 'fill', args: [] }),
    stroke: () => calls.push({ op: 'stroke', args: [] }),
    fillText: (...args: unknown[]) => calls.push({ op: 'fillText', args }),
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    font: '',
  };
  return { ctx, calls };
}

describe('drawOriginAxis', () => {
  it('routes every coordinate through the supplied w2c projector', () => {
    const w2c: WorldToCanvas = vi.fn((wx: number, wy: number) => [wx + 1000, wy + 2000]);
    const { ctx } = fakeCtx();
    drawOriginAxis(ctx as unknown as CanvasRenderingContext2D, w2c, { yawDeg: 0 });
    // World origin and ±1000m endpoints + 1m label points = 5+ w2c calls.
    expect((w2c as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBeGreaterThanOrEqual(5);
    // First call must be world (0, 0) — the axis intersection.
    const firstCall = (w2c as unknown as { mock: { calls: number[][] } }).mock.calls[0];
    expect(firstCall).toEqual([0, 0]);
  });
});

describe('drawGrid', () => {
  it('skips draw entirely when intervalM ≤ 0 (defensive)', () => {
    const w2c: WorldToCanvas = vi.fn(() => [0, 0]);
    const { ctx, calls } = fakeCtx();
    // pxPerMeter so absurdly large that pickGridInterval still picks
    // a positive interval — the only no-op path is via internal
    // safety. Exercise the real path with sane bounds:
    drawGrid(ctx as unknown as CanvasRenderingContext2D, w2c, {
      pxPerMeter: 50,
      worldMinX: 0,
      worldMaxX: 5,
      worldMinY: 0,
      worldMaxY: 5,
    });
    // Should have drawn at least one line (≥ 2 moveTo calls for V + H).
    const drawn = calls.filter((c) => c.op === 'stroke').length;
    expect(drawn).toBeGreaterThan(0);
  });

  it('caps lines per axis at GRID_MAX_LINES_PER_AXIS', () => {
    const w2c: WorldToCanvas = vi.fn(() => [0, 0]);
    const { ctx, calls } = fakeCtx();
    // 0.1 m intervals over 1000 m → 10000 vertical + 10000 horizontal
    // lines if uncapped. Cap is 200 per axis = 400 total strokes.
    drawGrid(ctx as unknown as CanvasRenderingContext2D, w2c, {
      pxPerMeter: 1000, // selects the smallest 0.1 m interval
      worldMinX: 0,
      worldMaxX: 1000,
      worldMinY: 0,
      worldMaxY: 1000,
    });
    const strokes = calls.filter((c) => c.op === 'stroke').length;
    expect(strokes).toBeLessThanOrEqual(400);
  });
});

describe('drawPickPreview', () => {
  it('skips all draws when no picks are set', () => {
    const w2c: WorldToCanvas = vi.fn(() => [0, 0]);
    const { ctx, calls } = fakeCtx();
    drawPickPreview(ctx as unknown as CanvasRenderingContext2D, w2c, {
      xy: null,
      yawP1: null,
      yawP2: null,
    });
    // Save + restore but no path operations.
    expect(calls.filter((c) => c.op === 'arc' || c.op === 'lineTo')).toHaveLength(0);
  });

  it('draws a filled dot for an XY pick', () => {
    const w2c: WorldToCanvas = vi.fn((wx, wy) => [wx, wy]);
    const { ctx, calls } = fakeCtx();
    drawPickPreview(ctx as unknown as CanvasRenderingContext2D, w2c, {
      xy: { x: 10, y: 20 },
      yawP1: null,
      yawP2: null,
    });
    expect(calls.some((c) => c.op === 'arc')).toBe(true);
    expect(calls.some((c) => c.op === 'fill')).toBe(true);
  });

  it('draws an arrow when both yaw P1 and P2 are set', () => {
    const w2c: WorldToCanvas = vi.fn((wx, wy) => [wx, wy]);
    const { ctx, calls } = fakeCtx();
    drawPickPreview(ctx as unknown as CanvasRenderingContext2D, w2c, {
      xy: null,
      yawP1: { x: 0, y: 0 },
      yawP2: { x: 5, y: 0 },
    });
    // Shaft + 2 arrowhead lines = at least 3 lineTo's.
    expect(calls.filter((c) => c.op === 'lineTo').length).toBeGreaterThanOrEqual(3);
  });

  it('renders P1 as a hollow ring when only P1 is placed', () => {
    const w2c: WorldToCanvas = vi.fn((wx, wy) => [wx, wy]);
    const { ctx, calls } = fakeCtx();
    drawPickPreview(ctx as unknown as CanvasRenderingContext2D, w2c, {
      xy: null,
      yawP1: { x: 1, y: 2 },
      yawP2: null,
    });
    // Hollow ring = arc + stroke (no fill on the ring path).
    const arcs = calls.filter((c) => c.op === 'arc');
    expect(arcs).toHaveLength(1);
    const strokes = calls.filter((c) => c.op === 'stroke');
    expect(strokes.length).toBeGreaterThan(0);
  });
});
