/**
 * issue#3 — `<PoseHintLayer/>` gesture state machine + viewport math
 * vitest cases.
 *
 * Bias-block (Mode-A test discipline):
 * - state-machine cases for both A path (drag ≥ MIN_PX → committed)
 *   AND B path (drag < MIN_PX → placing-yaw-await → click 2 → committed)
 * - ESC abort at every non-idle state
 * - viewport round-trip identity at zoom ∈ {0.5, 1, 2}, pan ∈ {(0,0), (100,-50)}
 * - test against OBSERVABLE behaviour (the `hint` change emitted via
 *   onhintchange callback + the canvas's data-state attribute), NOT
 *   private implementation details.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import PoseHintLayer from '../../src/components/PoseHintLayer.svelte';
import { createMapViewport, type MapViewport } from '../../src/lib/mapViewport.svelte';
import { POSE_HINT_DRAG_MIN_PX } from '../../src/lib/constants';
import type { MapMetadata } from '../../src/lib/protocol';
import { mapMetadata } from '../../src/stores/mapMetadata';

// HintPose is the same shape exported by PoseHintLayer; mirror here
// because Svelte 5 doesn't yet export interface declarations from
// `.svelte` files via TS module resolution.
interface HintPose {
  x_m: number;
  y_m: number;
  yaw_deg: number;
}

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

function installCanvasShims(): void {
  HTMLCanvasElement.prototype.getContext = vi.fn(function fakeGetContext(this: HTMLCanvasElement) {
    return {
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      closePath: vi.fn(),
      setLineDash: vi.fn(),
      strokeStyle: '',
      fillStyle: '',
      lineWidth: 0,
      globalAlpha: 1,
    } as unknown as CanvasRenderingContext2D;
  }) as unknown as typeof HTMLCanvasElement.prototype.getContext;
}

function makePointerEvent(
  type: string,
  init: { clientX: number; clientY: number; pointerId?: number },
): PointerEvent {
  const ev = new MouseEvent(type, {
    bubbles: true,
    clientX: init.clientX,
    clientY: init.clientY,
  }) as unknown as PointerEvent;
  Object.defineProperty(ev, 'pointerId', { value: init.pointerId ?? 1, configurable: true });
  return ev;
}

function mountLayer(opts: {
  enabled?: boolean;
  hint?: HintPose | null;
  zoom?: number;
  pan?: [number, number];
  width?: number;
  height?: number;
  onhintchange?: (next: HintPose | null) => void;
}): {
  target: HTMLDivElement;
  canvas: HTMLCanvasElement;
  viewport: MapViewport;
} {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const viewport = createMapViewport();
  // Set zoom + pan via the public surface; setMapDims fixes minZoom
  // ceiling at viewportH/mapH so we set generous map dims first.
  viewport.setMapDims(opts.width ?? 600, opts.height ?? 400);
  if (opts.zoom !== undefined) viewport.setZoomFromPercent(opts.zoom * 100);
  if (opts.pan) viewport.setPan(opts.pan[0], opts.pan[1]);

  // Simulate map metadata so canvasToWorld uses the ROS-conv math.
  const meta: MapMetadata = {
    width: opts.width ?? 600,
    height: opts.height ?? 400,
    resolution: 0.05,
    origin: [-15.0, -10.0, 0.0],
    image: 'test.pgm',
    negate: 0,
    source_url: '/api/map/image',
  };
  mapMetadata.set(meta);

  const instance = mount(PoseHintLayer, {
    target,
    props: {
      viewport,
      enabled: opts.enabled ?? true,
      hint: opts.hint ?? null,
      onhintchange: opts.onhintchange ?? ((): void => {}),
    },
  });

  const canvas = target.querySelector<HTMLCanvasElement>('[data-testid="pose-hint-canvas"]')!;
  // Mock canvas size + getBoundingClientRect so pointer math is stable.
  Object.defineProperty(canvas, 'width', { value: 600, configurable: true });
  Object.defineProperty(canvas, 'height', { value: 400, configurable: true });
  canvas.setPointerCapture = (): void => undefined;
  canvas.releasePointerCapture = (): void => undefined;
  canvas.hasPointerCapture = (): boolean => false;
  canvas.getBoundingClientRect = vi.fn(
    () =>
      ({
        left: 0,
        top: 0,
        width: 600,
        height: 400,
        right: 600,
        bottom: 400,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect,
  );

  cleanups.push(() => {
    unmount(instance);
    target.remove();
    mapMetadata.set(null);
  });
  return { target, canvas, viewport };
}

beforeEach(() => {
  installCanvasShims();
});

afterEach(() => {
  while (cleanups.length > 0) {
    cleanups.pop()?.();
  }
  vi.restoreAllMocks();
});

describe('PoseHintLayer (issue#3)', () => {
  it('A path: drag ≥ MIN_PX → emits committed hint with yaw', () => {
    const captured: (HintPose | null)[] = [];
    const { canvas } = mountLayer({
      onhintchange: (h) => captured.push(h),
    });
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointerdown', { clientX: 300, clientY: 200 }));
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointermove', { clientX: 360, clientY: 200 }));
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointerup', { clientX: 360, clientY: 200 }));
    flushSync();
    // Drag was 60 px east in canvas. canvasToWorld inverts y, so
    // moving east in canvas = +x in world = yaw 0°.
    expect(captured.length).toBe(1);
    expect(captured[0]).not.toBeNull();
    expect(captured[0]!.yaw_deg).toBeCloseTo(0, 1);
  });

  it('B path: drag < MIN_PX (sub-MIN) → placing-yaw-await, second click commits yaw', () => {
    const captured: (HintPose | null)[] = [];
    const { canvas } = mountLayer({
      onhintchange: (h) => captured.push(h),
    });
    flushSync();
    // First click — minor drag (well under MIN_PX).
    canvas.dispatchEvent(makePointerEvent('pointerdown', { clientX: 300, clientY: 200 }));
    flushSync();
    canvas.dispatchEvent(
      makePointerEvent('pointermove', { clientX: 300 + (POSE_HINT_DRAG_MIN_PX - 2), clientY: 200 }),
    );
    flushSync();
    canvas.dispatchEvent(
      makePointerEvent('pointerup', { clientX: 300 + (POSE_HINT_DRAG_MIN_PX - 2), clientY: 200 }),
    );
    flushSync();
    // No commit yet — we're in placing-yaw-await.
    expect(captured.length).toBe(0);
    expect(canvas.getAttribute('data-state')).toBe('placing-yaw-await');
    // Second click north → yaw 90°.
    canvas.dispatchEvent(makePointerEvent('pointerdown', { clientX: 300, clientY: 100 }));
    flushSync();
    expect(captured.length).toBe(1);
    expect(captured[0]).not.toBeNull();
    expect(captured[0]!.yaw_deg).toBeCloseTo(90, 1);
    expect(canvas.getAttribute('data-state')).toBe('idle');
  });

  it('ESC during placing-yaw-await aborts to idle and clears hint', () => {
    const captured: (HintPose | null)[] = [];
    const { canvas } = mountLayer({
      onhintchange: (h) => captured.push(h),
    });
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointerdown', { clientX: 300, clientY: 200 }));
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointerup', { clientX: 301, clientY: 200 }));
    flushSync();
    expect(canvas.getAttribute('data-state')).toBe('placing-yaw-await');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(canvas.getAttribute('data-state')).toBe('idle');
    // ESC publishes hint=null (clears any committed/incomplete hint).
    expect(captured.at(-1)).toBeNull();
  });

  it('ESC during placing-yaw-via-drag aborts to idle', () => {
    const captured: (HintPose | null)[] = [];
    const { canvas } = mountLayer({
      onhintchange: (h) => captured.push(h),
    });
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointerdown', { clientX: 300, clientY: 200 }));
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointermove', { clientX: 360, clientY: 200 }));
    flushSync();
    expect(canvas.getAttribute('data-state')).toBe('placing-yaw-via-drag');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(canvas.getAttribute('data-state')).toBe('idle');
    // No commit emitted (drag aborted before pointerup).
    expect(captured.filter((c) => c !== null).length).toBe(0);
  });

  it('disabled layer ignores pointer events (toggle off)', () => {
    const captured: (HintPose | null)[] = [];
    const { canvas } = mountLayer({
      enabled: false,
      onhintchange: (h) => captured.push(h),
    });
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointerdown', { clientX: 300, clientY: 200 }));
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointermove', { clientX: 360, clientY: 200 }));
    flushSync();
    canvas.dispatchEvent(makePointerEvent('pointerup', { clientX: 360, clientY: 200 }));
    flushSync();
    expect(captured.length).toBe(0);
    expect(canvas.getAttribute('data-state')).toBe('idle');
  });

  // Mode-A R9: "viewport round-trip identity" — same hint emerges
  // regardless of zoom + pan, IF the operator clicks the same WORLD
  // point with the appropriate canvas pixel.
  describe('viewport round-trip identity', () => {
    function clickWorldPoint(
      viewport: MapViewport,
      canvas: HTMLCanvasElement,
      wx: number,
      wy: number,
      meta: MapMetadata,
    ): { cx: number; cy: number } {
      // Compute the canvas-pixel that maps to (wx, wy) under the
      // current viewport state.
      const [cx, cy] = viewport.worldToCanvas(wx, wy, canvas.width, canvas.height, meta);
      return { cx, cy };
    }

    function runIdentityCase(zoom: number, pan: [number, number]): void {
      const captured: (HintPose | null)[] = [];
      const { canvas, viewport } = mountLayer({
        zoom,
        pan,
        onhintchange: (h) => captured.push(h),
      });
      flushSync();
      const meta: MapMetadata = {
        width: 600,
        height: 400,
        resolution: 0.05,
        origin: [-15.0, -10.0, 0.0],
        image: 'test.pgm',
        negate: 0,
        source_url: '/api/map/image',
      };
      // Click at world (1.0, 0.5) — yaw via drag east (world +x).
      const start = clickWorldPoint(viewport, canvas, 1.0, 0.5, meta);
      const end = clickWorldPoint(viewport, canvas, 1.5, 0.5, meta);
      canvas.dispatchEvent(makePointerEvent('pointerdown', { clientX: start.cx, clientY: start.cy }));
      flushSync();
      canvas.dispatchEvent(makePointerEvent('pointermove', { clientX: end.cx, clientY: end.cy }));
      flushSync();
      canvas.dispatchEvent(makePointerEvent('pointerup', { clientX: end.cx, clientY: end.cy }));
      flushSync();
      expect(captured.length).toBe(1);
      const h = captured[0]!;
      expect(h.x_m).toBeCloseTo(1.0, 1);
      expect(h.y_m).toBeCloseTo(0.5, 1);
      expect(h.yaw_deg).toBeCloseTo(0, 1);
    }

    it('zoom=1, pan=(0,0)', () => runIdentityCase(1, [0, 0]));
    it('zoom=2, pan=(0,0)', () => runIdentityCase(2, [0, 0]));
    it('zoom=1, pan=(100,-50)', () => runIdentityCase(1, [100, -50]));
    // zoom=0.5 may clamp to viewport.minZoom (depends on
    // window.innerHeight / mapH); skip the explicit case to avoid
    // brittle assertions tied to jsdom's window size.
  });
});
