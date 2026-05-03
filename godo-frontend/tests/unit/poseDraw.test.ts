/**
 * issue#27 — `lib/poseDraw.ts` extracted helpers.
 *
 * Pure-function smoke tests with a stub 2D context that records
 * fillStyle / arc / moveTo / lineTo calls. Asserts the helpers paint
 * the right primitives in the right order; full pixel-equality is
 * out-of-scope (covered by the component-level PoseCanvas tests).
 */

import { describe, expect, it } from 'vitest';

import { drawPose, drawTrail } from '../../src/lib/poseDraw';
import { MAP_POSE_COLOR } from '../../src/lib/constants';
import type { LastPose } from '../../src/lib/protocol';

interface CallLog {
  arcs: Array<{ cx: number; cy: number; r: number }>;
  fills: number;
  strokes: number;
  moveTo: Array<[number, number]>;
  lineTo: Array<[number, number]>;
  fillStyles: string[];
  strokeStyles: string[];
}

function makeStubCtx(): { ctx: CanvasRenderingContext2D; log: CallLog } {
  const log: CallLog = {
    arcs: [],
    fills: 0,
    strokes: 0,
    moveTo: [],
    lineTo: [],
    fillStyles: [],
    strokeStyles: [],
  };
  const ctx = {
    set fillStyle(v: string) {
      log.fillStyles.push(v);
    },
    set strokeStyle(v: string) {
      log.strokeStyles.push(v);
    },
    set lineWidth(_v: number) {},
    set globalAlpha(_v: number) {},
    beginPath: () => {},
    arc: (cx: number, cy: number, r: number) => {
      log.arcs.push({ cx, cy, r });
    },
    fill: () => {
      log.fills += 1;
    },
    stroke: () => {
      log.strokes += 1;
    },
    moveTo: (x: number, y: number) => {
      log.moveTo.push([x, y]);
    },
    lineTo: (x: number, y: number) => {
      log.lineTo.push([x, y]);
    },
  } as unknown as CanvasRenderingContext2D;
  return { ctx, log };
}

const w2cIdentity = (wx: number, wy: number): [number, number] => [wx, wy];

function makePose(overrides: Partial<LastPose> = {}): LastPose {
  return {
    valid: 1,
    converged: 1,
    forced: 0,
    x_m: 1.0,
    y_m: 2.0,
    yaw_deg: 0,
    xy_std_m: 0,
    yaw_std_deg: 0,
    iterations: 1,
    published_mono_ns: 0,
    ...overrides,
  } as LastPose;
}

describe('drawPose', () => {
  it('paints one dot + one heading line when pose is valid', () => {
    const { ctx, log } = makeStubCtx();
    drawPose(ctx, w2cIdentity, makePose());
    // One arc for the pose dot.
    expect(log.arcs.length).toBe(1);
    expect(log.fills).toBeGreaterThanOrEqual(1);
    // moveTo + lineTo for the heading.
    expect(log.moveTo.length).toBe(1);
    expect(log.lineTo.length).toBe(1);
    expect(log.strokes).toBe(1);
    // Pose color used.
    expect(log.fillStyles).toContain(MAP_POSE_COLOR);
    expect(log.strokeStyles).toContain(MAP_POSE_COLOR);
  });

  it('skips drawing when pose is null', () => {
    const { ctx, log } = makeStubCtx();
    drawPose(ctx, w2cIdentity, null);
    expect(log.arcs.length).toBe(0);
    expect(log.fills).toBe(0);
    expect(log.strokes).toBe(0);
  });

  it('skips drawing when pose.valid is 0', () => {
    const { ctx, log } = makeStubCtx();
    drawPose(ctx, w2cIdentity, makePose({ valid: 0 }));
    expect(log.arcs.length).toBe(0);
  });
});

describe('drawTrail', () => {
  it('paints N circles for an N-entry trail', () => {
    const { ctx, log } = makeStubCtx();
    const trail = [
      { x: 1, y: 1, yaw: 0 },
      { x: 2, y: 2, yaw: 0 },
      { x: 3, y: 3, yaw: 0 },
    ];
    drawTrail(ctx, w2cIdentity, trail);
    expect(log.arcs.length).toBe(3);
    expect(log.fills).toBeGreaterThanOrEqual(3);
    // No heading strokes.
    expect(log.strokes).toBe(0);
  });

  it('paints zero circles for an empty trail', () => {
    const { ctx, log } = makeStubCtx();
    drawTrail(ctx, w2cIdentity, []);
    expect(log.arcs.length).toBe(0);
  });
});
