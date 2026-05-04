/**
 * issue#28 — `<GridOverlay>` interval-schedule pin + component-mount pin.
 *
 * Schedule pins exercise the `pickInterval` lookup against the static
 * `GRID_INTERVAL_SCHEDULE` so any future schedule edit surfaces in CI.
 *
 * Component-mount pins (CR1 fix) mount the real `<GridOverlay>` against
 * a fake `CanvasRenderingContext2D` and assert that the recorded
 * `moveTo` / `lineTo` calls correspond to the world-frame grid expected
 * for the given props. A regression that detaches the grid from the
 * world-frame projection (e.g. drawing in screen coords or ignoring
 * `worldOriginX`) breaks the mount pins, not the math pins.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import GridOverlay from '../../src/components/GridOverlay.svelte';
import { GRID_INTERVAL_SCHEDULE } from '../../src/lib/constants';

function pickIntervalFromSchedule(zoom: number) {
  for (const entry of GRID_INTERVAL_SCHEDULE) {
    if (entry.maxZoom === null) return entry;
    if (zoom <= entry.maxZoom) return entry;
  }
  return GRID_INTERVAL_SCHEDULE[GRID_INTERVAL_SCHEDULE.length - 1];
}

describe('GridOverlay interval schedule', () => {
  it('selects 5 m grid for very low zoom (< 0.3 px/m)', () => {
    const e = pickIntervalFromSchedule(0.1)!;
    expect(e.intervalM).toBe(5);
  });

  it('selects 1 m grid for moderate zoom', () => {
    const e = pickIntervalFromSchedule(0.5)!;
    expect(e.intervalM).toBe(1);
  });

  it('selects 0.5 m grid for higher zoom', () => {
    const e = pickIntervalFromSchedule(2)!;
    expect(e.intervalM).toBe(0.5);
  });

  it('selects 0.1 m grid as catch-all sentinel for extreme zoom', () => {
    const e = pickIntervalFromSchedule(100)!;
    expect(e.intervalM).toBe(0.1);
    expect(e.maxZoom).toBeNull();
  });

  it('schedule has a non-empty catch-all sentinel as the trailing entry', () => {
    const last = GRID_INTERVAL_SCHEDULE[GRID_INTERVAL_SCHEDULE.length - 1]!;
    expect(last.maxZoom).toBeNull();
  });
});

interface MoveTo { op: 'moveTo'; x: number; y: number; }
interface LineTo { op: 'lineTo'; x: number; y: number; }
interface Stroke { op: 'stroke'; }
type DrawCall = MoveTo | LineTo | Stroke;

function installFakeContext(canvas: HTMLCanvasElement): { calls: DrawCall[] } {
  const calls: DrawCall[] = [];
  const ctx = {
    strokeStyle: '#000000' as string,
    lineWidth: 1,
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
      calls.push({ op: 'stroke' });
    },
  } as unknown as CanvasRenderingContext2D;
  Object.defineProperty(canvas, 'getContext', {
    value: () => ctx,
    configurable: true,
  });
  return { calls };
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

describe('GridOverlay component-mount', () => {
  it('draws vertical lines at world-frame x positions on integer-meter grid', () => {
    const { calls } = installFakeContext(canvas);
    // zoom = 100 px/m → schedule picks 0.1 m interval (catch-all
    // sentinel). Use a smaller world to keep line counts manageable.
    // Use zoom=1 px/m → 1 m grid (entry index 1).
    const inst = mount(GridOverlay, {
      target,
      props: {
        canvas,
        zoomPxPerMeter: 1,
        worldOriginX: 0,
        worldOriginY: 0,
        worldWidthM: 5,
        worldHeightM: 3,
      },
    });
    flushSync();
    // Vertical lines: x=0,1,2,3,4,5 → 6 lines, each = moveTo(px,0) + lineTo(px,canvas.height) + stroke.
    const verticalMoves = (calls.filter((c) => c.op === 'moveTo') as MoveTo[])
      .filter((c) => c.y === 0);
    const xs = verticalMoves.map((m) => m.x).sort((a, b) => a - b);
    expect(xs).toEqual([0, 1, 2, 3, 4, 5]);
    unmount(inst);
  });

  it('draws horizontal lines flipped per canvas-Y convention', () => {
    const { calls } = installFakeContext(canvas);
    const inst = mount(GridOverlay, {
      target,
      props: {
        canvas,
        zoomPxPerMeter: 1,
        worldOriginX: 0,
        worldOriginY: 0,
        worldWidthM: 2,
        worldHeightM: 3,
      },
    });
    flushSync();
    // Horizontal lines: y=0,1,2,3 in world → canvas py = 100, 99, 98, 97.
    const horizontalMoves = (calls.filter((c) => c.op === 'moveTo') as MoveTo[])
      .filter((c) => c.x === 0 && c.y !== 0); // exclude (0,0) which is the vertical at x=0
    const pys = horizontalMoves.map((m) => m.y).sort((a, b) => b - a);
    // World y = 0 maps to canvas py = canvas.height = 100. With world
    // y starting at floor(0 / 1) = 0 and ending at <= 3, expected pys
    // are [100, 99, 98, 97].
    expect(pys).toContain(100);
    expect(pys).toContain(99);
    expect(pys).toContain(98);
    expect(pys).toContain(97);
    unmount(inst);
  });

  it('shifts grid lines when worldOriginX changes (world-frame anchored)', () => {
    const a = installFakeContext(canvas);
    const inst1 = mount(GridOverlay, {
      target,
      props: {
        canvas,
        zoomPxPerMeter: 1,
        worldOriginX: 0,
        worldOriginY: 0,
        worldWidthM: 3,
        worldHeightM: 3,
      },
    });
    flushSync();
    const xsA = (a.calls.filter((c) => c.op === 'moveTo') as MoveTo[])
      .filter((c) => c.y === 0)
      .map((c) => c.x)
      .sort((a, b) => a - b);
    unmount(inst1);

    const canvas2 = document.createElement('canvas');
    canvas2.width = 200;
    canvas2.height = 100;
    const b = installFakeContext(canvas2);
    const inst2 = mount(GridOverlay, {
      target,
      props: {
        canvas: canvas2,
        zoomPxPerMeter: 1,
        worldOriginX: 0.5,
        worldOriginY: 0,
        worldWidthM: 3,
        worldHeightM: 3,
      },
    });
    flushSync();
    const xsB = (b.calls.filter((c) => c.op === 'moveTo') as MoveTo[])
      .filter((c) => c.y === 0)
      .map((c) => c.x)
      .sort((a, b) => a - b);
    unmount(inst2);

    // worldOriginX shifted by +0.5 m → grid lines shift by -0.5 px in
    // canvas coords (the world meter-marks land 0.5 m to the LEFT of
    // their previous canvas positions, i.e. lower px values). The set
    // of canvas x positions changes accordingly.
    expect(xsA).not.toEqual(xsB);
    // Pin the math: the FIRST visible vertical line for run B is at
    // floor(worldOriginX / intervalM) * intervalM = 0 in world coords;
    // canvas px = (0 - 0.5) * 1 = -0.5.
    expect(xsB[0]).toBeCloseTo(-0.5, 6);
  });
});
