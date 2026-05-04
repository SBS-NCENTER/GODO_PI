/**
 * issue#28 (CR1) — `<OriginAxisOverlay>` real component-mount pin.
 *
 * Mode-B CR1 finding: `mapOverlayCoherence.test.ts` only pins a local
 * `rotateWorld()` math helper and never invokes the production Svelte
 * component. Operator-locked C7 prerequisite (pose + yaw + scan +
 * bitmap rotate together) was therefore unpinned in production code.
 *
 * This file mounts the real `<OriginAxisOverlay>` against a fake
 * `CanvasRenderingContext2D`, drives `yamlOriginYawDeg` through known
 * angles (0°, 30°, 90°, -45°), and asserts that the +x / +y stroke
 * endpoints land where the math predicts. A regression that re-routes
 * the component back to a stale yaw, or flips the canvas-Y sign, will
 * break the corresponding angle pin first.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import OriginAxisOverlay from '../../src/components/OriginAxisOverlay.svelte';

interface MoveTo { op: 'moveTo'; x: number; y: number; }
interface LineTo { op: 'lineTo'; x: number; y: number; }
interface Stroke { op: 'stroke'; style: string | CanvasGradient | CanvasPattern; }
type DrawCall = MoveTo | LineTo | Stroke;

/**
 * Build a stub `CanvasRenderingContext2D` that records `moveTo`,
 * `lineTo`, and `stroke` invocations along with the active
 * `strokeStyle` at stroke time. Used by mounted components to verify
 * the canvas-pixel coordinates produced by the rotation math.
 */
function installFakeContext(canvas: HTMLCanvasElement): { calls: DrawCall[]; ctx: CanvasRenderingContext2D } {
  const calls: DrawCall[] = [];
  const ctx = {
    strokeStyle: '#000000' as string | CanvasGradient | CanvasPattern,
    fillStyle: '#000000' as string | CanvasGradient | CanvasPattern,
    lineWidth: 1,
    font: '10px sans-serif',
    save(): void {},
    restore(): void {},
    beginPath(): void {},
    moveTo(x: number, y: number): void {
      calls.push({ op: 'moveTo', x, y });
    },
    lineTo(x: number, y: number): void {
      calls.push({ op: 'lineTo', x, y });
    },
    stroke(): void {
      calls.push({ op: 'stroke', style: ctx.strokeStyle });
    },
    arc(): void {},
    fill(): void {},
    fillText(): void {},
  } as unknown as CanvasRenderingContext2D;
  // jsdom's HTMLCanvasElement.getContext returns null without the
  // `canvas` package; install our recorder unconditionally.
  Object.defineProperty(canvas, 'getContext', {
    value: () => ctx,
    configurable: true,
  });
  return { calls, ctx };
}

interface AxisEndpoints {
  xEnd: { x: number; y: number };
  yEnd: { x: number; y: number };
  origin: { x: number; y: number };
}

/**
 * Extract the +x / +y axis endpoints from a sequence of recorded
 * draw calls. The component issues exactly two strokes:
 * (1) +x — moveTo(origin), lineTo(xEnd), stroke,
 * (2) +y — moveTo(origin), lineTo(yEnd), stroke.
 * A defensive reader returns the first MoveTo+LineTo per stroke run.
 */
function extractAxisEndpoints(calls: DrawCall[]): AxisEndpoints {
  let i = 0;
  const strokes: { move: MoveTo; line: LineTo }[] = [];
  while (i < calls.length) {
    if (calls[i].op === 'moveTo' && calls[i + 1]?.op === 'lineTo') {
      const move = calls[i] as MoveTo;
      const line = calls[i + 1] as LineTo;
      // Find the matching stroke if present (overlay strokes both axes).
      let j = i + 2;
      while (j < calls.length && calls[j].op !== 'stroke') j++;
      if (j < calls.length) {
        strokes.push({ move, line });
      }
      i = j + 1;
    } else {
      i++;
    }
  }
  if (strokes.length < 2) {
    throw new Error(`expected at least 2 strokes, got ${strokes.length}`);
  }
  const s0 = strokes[0]!;
  const s1 = strokes[1]!;
  return {
    origin: { x: s0.move.x, y: s0.move.y },
    xEnd:   { x: s0.line.x, y: s0.line.y },
    yEnd:   { x: s1.line.x, y: s1.line.y },
  };
}

let target: HTMLElement;
let canvas: HTMLCanvasElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
  canvas = document.createElement('canvas');
  canvas.width = 200;
  canvas.height = 100;
});

afterEach(() => {
  target.remove();
});

describe('OriginAxisOverlay component-mount', () => {
  // canvas diagonal length used by the component for axis line length.
  const len = Math.hypot(200, 100);

  function expectAxisDirections(
    eps: AxisEndpoints,
    yawDeg: number,
    cx: number,
    cy: number,
  ): void {
    const yawRad = (yawDeg * Math.PI) / 180;
    // World +x in canvas coords = (cosθ, -sinθ) * len.
    const dxX = Math.cos(yawRad) * len;
    const dyX = -Math.sin(yawRad) * len;
    // World +y in canvas coords = (-sinθ, -cosθ) * len.
    const dxY = -Math.sin(yawRad) * len;
    const dyY = -Math.cos(yawRad) * len;

    expect(eps.origin.x).toBeCloseTo(cx, 6);
    expect(eps.origin.y).toBeCloseTo(cy, 6);
    expect(eps.xEnd.x).toBeCloseTo(cx + dxX, 6);
    expect(eps.xEnd.y).toBeCloseTo(cy + dyX, 6);
    expect(eps.yEnd.x).toBeCloseTo(cx + dxY, 6);
    expect(eps.yEnd.y).toBeCloseTo(cy + dyY, 6);
  }

  it('yaw = 0° — +x lies along canvas +x; +y along canvas -y (Y-flip)', () => {
    const { calls } = installFakeContext(canvas);
    const inst = mount(OriginAxisOverlay, {
      target,
      props: {
        canvas,
        zoomPxPerMeter: 10,
        worldOriginX: 0,
        worldOriginY: 0,
        yamlOriginX: 0,
        yamlOriginY: 0,
        yamlOriginYawDeg: 0,
      },
    });
    flushSync();
    const eps = extractAxisEndpoints(calls);
    // origin at world (0,0), worldOrigin (0,0), zoom 10 → cx=0, cy=canvas.height-0=100.
    expectAxisDirections(eps, 0, 0, 100);
    unmount(inst);
  });

  it('yaw = 30° — endpoints rotate per cosθ/sinθ', () => {
    const { calls } = installFakeContext(canvas);
    const inst = mount(OriginAxisOverlay, {
      target,
      props: {
        canvas,
        zoomPxPerMeter: 5,
        worldOriginX: -1,
        worldOriginY: -1,
        yamlOriginX: 0,
        yamlOriginY: 0,
        yamlOriginYawDeg: 30,
      },
    });
    flushSync();
    const eps = extractAxisEndpoints(calls);
    // cx = (0 - -1) * 5 = 5, cy = 100 - (0 - -1) * 5 = 95.
    expectAxisDirections(eps, 30, 5, 95);
    unmount(inst);
  });

  it('yaw = 90° — +x rotates onto canvas -y axis (visually upward)', () => {
    const { calls } = installFakeContext(canvas);
    const inst = mount(OriginAxisOverlay, {
      target,
      props: {
        canvas,
        zoomPxPerMeter: 10,
        worldOriginX: 0,
        worldOriginY: 0,
        yamlOriginX: 0,
        yamlOriginY: 0,
        yamlOriginYawDeg: 90,
      },
    });
    flushSync();
    const eps = extractAxisEndpoints(calls);
    expectAxisDirections(eps, 90, 0, 100);
    // Sanity: at +90° the +x axis endpoint dy ≈ -len (upward), dx ≈ 0.
    expect(eps.xEnd.x - eps.origin.x).toBeCloseTo(0, 6);
    expect(eps.xEnd.y - eps.origin.y).toBeCloseTo(-len, 6);
    unmount(inst);
  });

  it('yaw = -45° — endpoints follow CW-rotated cosθ/sinθ', () => {
    const { calls } = installFakeContext(canvas);
    const inst = mount(OriginAxisOverlay, {
      target,
      props: {
        canvas,
        zoomPxPerMeter: 10,
        worldOriginX: 0,
        worldOriginY: 0,
        yamlOriginX: 0,
        yamlOriginY: 0,
        yamlOriginYawDeg: -45,
      },
    });
    flushSync();
    const eps = extractAxisEndpoints(calls);
    expectAxisDirections(eps, -45, 0, 100);
    unmount(inst);
  });

  it('rotation by Δyaw shifts +x endpoint by exactly the rotated direction (yaw drives draw)', () => {
    // Drift catch: mount once at 10°, capture endpoints; mount again at
    // 70°; verify the two endpoint sets differ by exactly Δyaw=60° per
    // the rotation math. A regression that hard-codes yaw or stops
    // re-rendering on prop change would yield identical endpoints.
    const a = installFakeContext(canvas);
    const inst1 = mount(OriginAxisOverlay, {
      target,
      props: {
        canvas,
        zoomPxPerMeter: 10,
        worldOriginX: 0,
        worldOriginY: 0,
        yamlOriginX: 0,
        yamlOriginY: 0,
        yamlOriginYawDeg: 10,
      },
    });
    flushSync();
    const epsA = extractAxisEndpoints(a.calls);
    unmount(inst1);

    const canvas2 = document.createElement('canvas');
    canvas2.width = 200;
    canvas2.height = 100;
    const b = installFakeContext(canvas2);
    const inst2 = mount(OriginAxisOverlay, {
      target,
      props: {
        canvas: canvas2,
        zoomPxPerMeter: 10,
        worldOriginX: 0,
        worldOriginY: 0,
        yamlOriginX: 0,
        yamlOriginY: 0,
        yamlOriginYawDeg: 70,
      },
    });
    flushSync();
    const epsB = extractAxisEndpoints(b.calls);
    unmount(inst2);

    // Same origin point in both runs.
    expect(epsB.origin.x).toBeCloseTo(epsA.origin.x, 6);
    expect(epsB.origin.y).toBeCloseTo(epsA.origin.y, 6);
    // The +x endpoint of run B equals run A's endpoint rotated by +60°
    // about the origin, with canvas Y flipped (so the rotation in
    // canvas coords is `-Δyaw`).
    const dxA = epsA.xEnd.x - epsA.origin.x;
    const dyA = epsA.xEnd.y - epsA.origin.y;
    const deltaRad = (60 * Math.PI) / 180;
    const c = Math.cos(deltaRad);
    const s = Math.sin(deltaRad);
    // Canvas-Y-flipped rotation: x' = c*x + s*y; y' = -s*x + c*y
    // (because the world rotation with Y-flip becomes a clockwise
    // rotation in canvas coords).
    const expectedDx = c * dxA + s * dyA;
    const expectedDy = -s * dxA + c * dyA;
    const dxB = epsB.xEnd.x - epsB.origin.x;
    const dyB = epsB.xEnd.y - epsB.origin.y;
    expect(dxB).toBeCloseTo(expectedDx, 5);
    expect(dyB).toBeCloseTo(expectedDy, 5);
  });
});
