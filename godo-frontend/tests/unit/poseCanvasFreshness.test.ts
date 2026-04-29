/**
 * Track D — freshness-gate test for PoseCanvas (Mode-A M2 fold).
 *
 * Mounts the real PoseCanvas into jsdom, feeds it a canned LastScan
 * with a current `_arrival_ms` stamp, asserts the wrap div carries
 * `data-scan-fresh="true"`. Then advances `vi.useFakeTimers()` past
 * `MAP_SCAN_FRESHNESS_MS` and re-renders; the wrap div MUST flip to
 * `data-scan-fresh="false"` with `data-scan-count="0"` because the
 * freshness gate suppresses the layer.
 *
 * The polar→Cartesian math itself is covered by
 * `poseCanvasScanLayer.test.ts`; this file pins the freshness *gate*
 * specifically (the M2 patch).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
// Track D scale fix: stub the metadata loader BEFORE importing
// PoseCanvas. The freshness test wants to control `mapMetadata`
// directly via the store; PoseCanvas's $effect would otherwise
// synchronously null the store and fetch into jsdom-stubbed
// endpoints we don't care about.
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
import { MAP_SCAN_FRESHNESS_MS } from '../../src/lib/constants';
import type { LastScan, MapMetadata } from '../../src/lib/protocol';
import { _resetMapMetadataForTests, mapMetadata } from '../../src/stores/mapMetadata';

// Track D scale fix: PoseCanvas's scan overlay is now gated on
// `mapMetadata` being non-null. Inject an identity metadata snapshot
// before each mount so the freshness gate can run end-to-end.
const _IDENTITY_META: MapMetadata = {
  image: 'studio.pgm',
  resolution: 0.05,
  origin: [0, 0, 0],
  negate: 0,
  width: 200,
  height: 100,
  source_url: '/api/map/image',
};

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

function makeFake2DContext(): CanvasRenderingContext2D {
  // Minimal stub of the 2d context API used by PoseCanvas.redraw().
  // jsdom returns null from canvas.getContext('2d') by default, which
  // makes redraw() early-return BEFORE updating scanFresh /
  // scanRenderedCount. The freshness gate test must run the full
  // redraw, so we install a no-op stub here.
  const ctx = {
    fillStyle: '',
    strokeStyle: '',
    globalAlpha: 1,
    lineWidth: 0,
    clearRect: () => {},
    drawImage: () => {},
    beginPath: () => {},
    arc: () => {},
    moveTo: () => {},
    lineTo: () => {},
    fill: () => {},
    stroke: () => {},
  };
  return ctx as unknown as CanvasRenderingContext2D;
}

beforeEach(() => {
  configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
  _resetMapMetadataForTests();
  mapMetadata.set(_IDENTITY_META);
  // Stub /api/map/image — return a plain ArrayBuffer-backed Response so
  // the onMount path's `.blob()` call works in jsdom (the Blob+stream
  // path is finicky on this Node version).
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(new Uint8Array([0x89, 0x50, 0x4e, 0x47]).buffer, {
      status: 200,
      headers: { 'content-type': 'image/png' },
    }),
  );
  // Install canvas 2d-context stub on every HTMLCanvasElement so
  // PoseCanvas.redraw() does not early-return on a null context.
  HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, contextId: string) {
    if (contextId === '2d') return makeFake2DContext();
    return null;
  } as unknown as HTMLCanvasElement['getContext'];

  // Stub URL.createObjectURL / revokeObjectURL because jsdom does not
  // implement them; PoseCanvas uses both around the blob URL.
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
});

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function makeScan(arrivalMs: number): LastScan {
  return {
    valid: 1,
    forced: 1,
    pose_valid: 1,
    iterations: 5,
    published_mono_ns: 1,
    pose_x_m: 0,
    pose_y_m: 0,
    pose_yaw_deg: 0,
    n: 1,
    angles_deg: [0],
    ranges_m: [1],
    _arrival_ms: arrivalMs,
  };
}

describe('PoseCanvas — Mode-A M2 freshness gate', () => {
  it('marks data-scan-fresh="true" while within MAP_SCAN_FRESHNESS_MS', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-29T00:00:00Z'));

    const target = document.createElement('div');
    document.body.appendChild(target);

    const component = mount(PoseCanvas, {
      target,
      props: {
        pose: null,
        scan: makeScan(Date.now()),
        scanOverlayOn: true,
      },
    });
    cleanups.push(() => unmount(component));
    flushSync();

    const wrap = target.querySelector<HTMLDivElement>('[data-testid="pose-canvas-wrap"]');
    expect(wrap).not.toBeNull();
    expect(wrap!.getAttribute('data-scan-fresh')).toBe('true');
  });

  // Mode-A S5 fold: scan arrives at t=0; metadata fetch resolves at
  // t=400ms; first redraw runs at t=400ms; data-scan-fresh stays true
  // because Date.now() - 0 = 400 < MAP_SCAN_FRESHNESS_MS (1000).
  it('Mode-A S5: scan stays fresh when metadata resolves at t=400ms (well within MAP_SCAN_FRESHNESS_MS)', () => {
    vi.useFakeTimers();
    const t0 = new Date('2026-04-29T00:00:00Z').getTime();
    vi.setSystemTime(t0);

    // Start with no metadata so the scan overlay is suppressed.
    _resetMapMetadataForTests();

    const target = document.createElement('div');
    document.body.appendChild(target);

    const component = mount(PoseCanvas, {
      target,
      props: { pose: null, scan: makeScan(t0), scanOverlayOn: true },
    });
    cleanups.push(() => unmount(component));
    flushSync();

    // Pre-meta: overlay suppressed → data-scan-count = 0.
    let wrap = target.querySelector<HTMLDivElement>('[data-testid="pose-canvas-wrap"]');
    expect(wrap!.getAttribute('data-scan-count')).toBe('0');

    // Advance to t=400ms; metadata fetch resolves; redraw runs.
    vi.advanceTimersByTime(400);
    mapMetadata.set(_IDENTITY_META);
    flushSync();

    wrap = target.querySelector<HTMLDivElement>('[data-testid="pose-canvas-wrap"]');
    // data-scan-count should now be > 0 (overlay was rendered) AND
    // data-scan-fresh should be "true" because 400 ms < 1000 ms.
    expect(Number(wrap!.getAttribute('data-scan-count') ?? 0)).toBeGreaterThan(0);
    expect(wrap!.getAttribute('data-scan-fresh')).toBe('true');
  });

  it('flips to data-scan-fresh="false" once Date.now() advances past freshness window', () => {
    vi.useFakeTimers();
    const t0 = new Date('2026-04-29T00:00:00Z').getTime();
    vi.setSystemTime(t0);

    const target = document.createElement('div');
    document.body.appendChild(target);

    // First mount: arrival at t0 → fresh.
    const c1 = mount(PoseCanvas, {
      target,
      props: { pose: null, scan: makeScan(t0), scanOverlayOn: true },
    });
    flushSync();
    let wrap = target.querySelector<HTMLDivElement>('[data-testid="pose-canvas-wrap"]');
    expect(wrap!.getAttribute('data-scan-fresh')).toBe('true');
    unmount(c1);

    // Advance system time past the freshness window. Re-mount with the
    // ORIGINAL arrival stamp; the redraw runs against the new Date.now()
    // → isFresh evaluates false → wrap div flips. We use a fresh mount
    // (not a reactive prop reassignment) because Svelte 5's `mount(...)`
    // with a plain object props does not reactively re-render on
    // mutation; the production SSE adapter also re-creates the scan
    // object on every frame, so this mirrors prod behaviour.
    vi.advanceTimersByTime(MAP_SCAN_FRESHNESS_MS + 100);
    const target2 = document.createElement('div');
    document.body.appendChild(target2);
    const c2 = mount(PoseCanvas, {
      target: target2,
      props: { pose: null, scan: makeScan(t0), scanOverlayOn: true },
    });
    cleanups.push(() => unmount(c2));
    flushSync();
    wrap = target2.querySelector<HTMLDivElement>('[data-testid="pose-canvas-wrap"]');
    expect(wrap!.getAttribute('data-scan-fresh')).toBe('false');
    expect(wrap!.getAttribute('data-scan-count')).toBe('0');
  });
});
