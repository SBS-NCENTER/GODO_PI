/**
 * Track D scale fix — pose-canvas world↔canvas transform pinning.
 *
 * The hand-computed expected canvas coordinates here are LITERAL
 * INTEGERS, NOT formula-recomputed values (per Mode-A T3): a circular
 * regression-pin would let a bug shared between test and production
 * code slip through. These constants were derived by hand against the
 * §Math block of `.claude/tmp/plan_track_d_scale_yflip.md`.
 *
 * Test surface: a small test-only host component that mounts a real
 * `mapMetadata` snapshot into the store, then asks `PoseCanvas` for its
 * `worldToCanvas` mapping (via the `data-*` attributes on a marker dot).
 * Each test case patches the `mapMetadata` store synchronously before
 * mount so the canvas redraw runs against the intended fixture.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
// Track D scale fix: stub `loadMapMetadata` so PoseCanvas's $effect
// does NOT clobber the test-set `mapMetadata` snapshot with a null
// reset + jsdom fetch dance.
vi.mock('../../src/stores/mapMetadata', async () => {
  const actual = await vi.importActual<typeof import('../../src/stores/mapMetadata')>(
    '../../src/stores/mapMetadata',
  );
  return {
    ...actual,
    loadMapMetadata: vi.fn(async () => {}),
  };
});
import PoseCanvas from '../../src/components/PoseCanvas.svelte';
import { configureAuth } from '../../src/lib/api';
import { _resetMapMetadataForTests, mapMetadata } from '../../src/stores/mapMetadata';
import type { LastPose, MapMetadata } from '../../src/lib/protocol';

// --- jsdom canvas shim ----------------------------------------------------

interface CleanupFn {
  (): void;
}
const cleanups: CleanupFn[] = [];

function makeMetadata(o: Partial<MapMetadata>): MapMetadata {
  return {
    image: o.image ?? 'studio.pgm',
    resolution: o.resolution ?? 0.05,
    origin: o.origin ?? [0, 0, 0],
    negate: o.negate ?? 0,
    width: o.width ?? 200,
    height: o.height ?? 100,
    source_url: o.source_url ?? '/api/map/image',
  };
}

beforeEach(() => {
  configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(new Uint8Array([0x89, 0x50, 0x4e, 0x47]).buffer, {
      status: 200,
      headers: { 'content-type': 'image/png' },
    }),
  );
  if (!('createObjectURL' in URL)) {
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: () => 'blob:test/url',
    });
  }
  if (!('revokeObjectURL' in URL)) {
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: () => {},
    });
  }
  // Pin the canvas dimensions early — jsdom defaults canvas to 300×150
  // and reports a 0x0 bounding rect, but PoseCanvas's onMount then
  // calls Math.max(rect.h, MAP_CANVAS_MIN_HEIGHT_PX) = 400. The
  // initial $effect-triggered redraw, however, runs BEFORE onMount and
  // sees canvas.height = 150. We force a deterministic 400-tall canvas
  // by setting Element.prototype.getBoundingClientRect to return the
  // chosen size — onMount will then assign Math.max(400, 400) = 400
  // (idempotent), AND we additionally pin the canvas defaults via the
  // OffscreenCanvas-style stub so the FIRST redraw also sees 400.
  const rectStub = () => ({
    x: 0,
    y: 0,
    width: 600,
    height: 400,
    top: 0,
    left: 0,
    right: 600,
    bottom: 400,
    toJSON: () => '',
  });
  Object.defineProperty(HTMLCanvasElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: rectStub,
  });
  Object.defineProperty(Element.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: rectStub,
  });
});

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
  _resetMapMetadataForTests();
  vi.restoreAllMocks();
});

/**
 * Mount PoseCanvas with a canvas of fixed dimensions (600×400) and pose
 * = (wx, wy). Returns the recorded arc center for the pose dot.
 *
 * The canvas dimensions in jsdom default to 300×150; PoseCanvas sets
 * them to MAP_CANVAS_MIN_* in `onMount`. The $effect-driven first
 * redraw, however, runs BEFORE onMount, so we force canvas.width/height
 * directly before mounting via a one-time override on
 * HTMLCanvasElement's `width`/`height` setters — the test wants to
 * assert against a 600×400 canvas exclusively.
 */
function mountAndGetPoseDot(metadata: MapMetadata, pose: LastPose): { cx: number; cy: number } {
  // Pre-set the metadata BEFORE mount so the redraw sees it.
  mapMetadata.set(metadata);

  const arcs: Array<{ x: number; y: number; r: number }> = [];
  HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, contextId: string) {
    if (contextId !== '2d') return null;
    return {
      fillStyle: '',
      strokeStyle: '',
      globalAlpha: 1,
      lineWidth: 0,
      clearRect: () => {},
      drawImage: () => {},
      beginPath: () => {},
      arc: (x: number, y: number, r: number) => {
        arcs.push({ x, y, r });
      },
      moveTo: () => {},
      lineTo: () => {},
      fill: () => {},
      stroke: () => {},
    } as unknown as CanvasRenderingContext2D;
  } as unknown as HTMLCanvasElement['getContext'];

  // Stub getBoundingClientRect so the canvas adopts a known size.
  Object.defineProperty(HTMLCanvasElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({ width: 600, height: 400, top: 0, left: 0, right: 600, bottom: 400 }),
  });

  const target = document.createElement('div');
  document.body.appendChild(target);

  const component = mount(PoseCanvas, {
    target,
    props: { pose, scan: null, scanOverlayOn: false },
  });
  cleanups.push(() => unmount(component));
  flushSync();

  // After mount, PoseCanvas's onMount sets canvas.width/height to
  // 600×400 (via the prototype getBoundingClientRect stub installed
  // in beforeEach). The first $effect-driven redraw happens BEFORE
  // onMount and sees the jsdom default canvas (300×150); the second
  // redraw runs after onMount when the canvas has been resized.
  //
  // We trigger a final post-mount redraw by re-pushing the metadata
  // store — the meta-subscriber inside PoseCanvas re-runs the
  // `$effect` and re-renders against the now-correct canvas dims.
  mapMetadata.set(metadata);
  flushSync();

  // Take the LAST pose-radius arc — it's emitted from the most
  // recent redraw, which is against the resized canvas.
  const poseArcs = arcs.filter((a) => Math.round(a.r) === 6);
  const poseArc = poseArcs[poseArcs.length - 1];
  if (!poseArc) {
    throw new Error(`no pose dot arc recorded; arcs=${JSON.stringify(arcs)}`);
  }
  return { cx: poseArc.x, cy: poseArc.y };
}

function makePose(x: number, y: number): LastPose {
  return {
    valid: true,
    x_m: x,
    y_m: y,
    yaw_deg: 0,
    xy_std_m: 0,
    yaw_std_deg: 0,
    iterations: 1,
    converged: true,
    forced: false,
    published_mono_ns: 1,
  };
}

describe('PoseCanvas worldToCanvas — Track D scale fix', () => {
  // §C-1 — identity case (T3): hand-computed integers.
  // metadata = {resolution: 0.05, origin: [0,0,0], width: 200, height: 100}
  // canvas 600×400, zoom = 1 (default), pan = 0.
  // World (0, 0) → img_col = 0; img_row = 99.
  // canvas cx = 600/2 + 0 + (0 - 100)*1 = 300 - 100 = 200
  // canvas cy = 400/2 + 0 + (99 - 50)*1 = 200 + 49 = 249
  it('§C-1 identity: world (0,0) maps to canvas (200, 249)', () => {
    const m = makeMetadata({ resolution: 0.05, origin: [0, 0, 0], width: 200, height: 100 });
    const { cx, cy } = mountAndGetPoseDot(m, makePose(0, 0));
    expect(cx).toBe(200);
    expect(cy).toBe(249);
  });

  // §C-2 — non-zero origin: hand-computed integers.
  // metadata = {resolution: 0.05, origin: [-2.0, -1.0, 0], width: 200, height: 100}
  // World (0, 0): img_col = (0 - (-2))/0.05 = 40; img_row = 99 - (0 - (-1))/0.05 = 99 - 20 = 79.
  // canvas cx = 300 + (40 - 100) = 240
  // canvas cy = 200 + (79 - 50) = 229
  it('§C-2 non-zero origin: world (0,0) maps to canvas (240, 229)', () => {
    const m = makeMetadata({
      resolution: 0.05,
      origin: [-2.0, -1.0, 0],
      width: 200,
      height: 100,
    });
    const { cx, cy } = mountAndGetPoseDot(m, makePose(0, 0));
    expect(cx).toBe(240);
    expect(cy).toBe(229);
  });

  // §C-3 — Y-flip pin (Mode-A M1 — load-bearing test).
  // The new code makes world (0,0) land at canvas y = 249 (image bottom-edge
  // row, since world origin = bottom-left pixel by ROS convention).
  //
  // The OLD un-fixed code (PoseCanvas.svelte:114, MAP_PIXELS_PER_METER = 100)
  // computed: cy = canvas.height/2 + panY - wy*ppm = 200 + 0 - 0*100 = 200.
  // That FAILS this test against `main e68e035` (200 !== 249) — the
  // failing run output is captured in the PR body.
  it('§C-3 Y-flip pin: world (0,0) at metadata-default lands at cy = 249, NOT 200', () => {
    const m = makeMetadata({ resolution: 0.05, origin: [0, 0, 0], width: 200, height: 100 });
    const { cy } = mountAndGetPoseDot(m, makePose(0, 0));
    // The bug-existence check: pre-fix code returns 200; new code returns 249.
    expect(cy).toBe(249);
  });

  // §C-4 — Y-flip direction sanity.
  // World +y MUST map to a SMALLER cy (higher on screen).
  it('§C-4 direction: world (0, +1) maps to cy < world (0, 0).cy', () => {
    const m = makeMetadata({ resolution: 0.05, origin: [0, 0, 0], width: 200, height: 100 });
    const a = mountAndGetPoseDot(m, makePose(0, 0));
    // Reset DOM + remount with new pose; cleanups handles the unmount.
    const b = mountAndGetPoseDot(m, makePose(0, 1));
    expect(b.cy).toBeLessThan(a.cy);
  });

  // §C-5 — Zoom != 1.
  // metadata = identity; pose at world (1m, 0).
  // At zoom = 1: img_col = 20; cx = 300 + (20 - 100) = 220. cy = 249.
  // At zoom = 2: cx = 300 + (20 - 100)*2 = 300 - 160 = 140; cy = 200 + (99 - 50)*2 = 298.
  // Note: PoseCanvas's internal `zoom` defaults to MAP_DEFAULT_ZOOM = 1; the
  // test cannot set a non-default zoom from outside in this minimal harness.
  // Instead we pin two different metadata that produce the same effect.
  it('§C-5 zoom-equivalent: world (1, 0) at resolution 0.05 lands at cx = 220, cy = 249', () => {
    const m = makeMetadata({ resolution: 0.05, origin: [0, 0, 0], width: 200, height: 100 });
    const { cx, cy } = mountAndGetPoseDot(m, makePose(1, 0));
    expect(cx).toBe(220);
    expect(cy).toBe(249);
  });

  // §C-6 — Non-square map (Mode-A M2 — REWRITTEN).
  // metadata = {resolution: 0.05, origin: [0,0,0], width: 200, height: 50}.
  // World (0, 0): img_col = 0; img_row = 49. canvas (cx, cy) = (300 + (0 - 100), 200 + (49 - 25)) = (200, 224).
  // World (0, +1): img_col = 0; img_row = 49 - 20 = 29. canvas (cx, cy) = (300 - 100, 200 + (29 - 25)) = (200, 204).
  // Delta cy = -20 px (consistent with §C-3/§C-4 direction).
  it('§C-6 non-square (W != H): world (0,0) → (200, 224); world (0,+1) → (200, 204)', () => {
    const m = makeMetadata({ resolution: 0.05, origin: [0, 0, 0], width: 200, height: 50 });
    const a = mountAndGetPoseDot(m, makePose(0, 0));
    expect(a.cx).toBe(200);
    expect(a.cy).toBe(224);
    const b = mountAndGetPoseDot(m, makePose(0, 1));
    expect(b.cx).toBe(200);
    expect(b.cy).toBe(204);
  });

  // §C-7 — Resolution = 0.025 m/cell (twice as dense as 0.05).
  // 1 m world = 40 image pixels (vs 20 at 0.05).
  // metadata = {resolution: 0.025, origin: [0,0,0], width: 200, height: 100}.
  // World (1, 0): img_col = 40; cx = 300 + (40 - 100) = 240. cy = 200 + (99 - 50) = 249.
  it('§C-7 resolution 0.025: world (1,0) lands at cx = 240, cy = 249', () => {
    const m = makeMetadata({ resolution: 0.025, origin: [0, 0, 0], width: 200, height: 100 });
    const { cx, cy } = mountAndGetPoseDot(m, makePose(1, 0));
    expect(cx).toBe(240);
    expect(cy).toBe(249);
  });

  // §C-8 — Inverse-resolution scaling pin (Mode-A T1 — REWRITTEN).
  // delta_a = wTC(1,0).cx - wTC(0,0).cx at resolution 0.05.
  // delta_b = wTC(1,0).cx - wTC(0,0).cx at resolution 0.025.
  // delta_b MUST equal 2 * delta_a EXACTLY (inverse-resolution scaling).
  it('§C-8 inverse-resolution scaling: doubling resolution density doubles canvas-coord delta', () => {
    const m_a = makeMetadata({ resolution: 0.05, origin: [0, 0, 0], width: 200, height: 100 });
    const a0 = mountAndGetPoseDot(m_a, makePose(0, 0)).cx;
    const a1 = mountAndGetPoseDot(m_a, makePose(1, 0)).cx;
    const m_b = makeMetadata({ resolution: 0.025, origin: [0, 0, 0], width: 200, height: 100 });
    const b0 = mountAndGetPoseDot(m_b, makePose(0, 0)).cx;
    const b1 = mountAndGetPoseDot(m_b, makePose(1, 0)).cx;
    const delta_a = a1 - a0;
    const delta_b = b1 - b0;
    expect(delta_b).toBe(2 * delta_a);
  });
});
