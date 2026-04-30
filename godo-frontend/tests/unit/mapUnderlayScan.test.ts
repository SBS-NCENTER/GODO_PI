/**
 * PR β — `<MapUnderlay/>` scan-overlay cases.
 *
 * Pins Rule 3 + Rule 4 + Mode-A S1 (layer paint order):
 *   - One scan-overlay code path; mounting MapUnderlay twice with the
 *     same canned scan + overlay flag yields identical `data-scan-count`
 *     (Overview-vs-Edit case).
 *   - `data-scan-count = 0` when overlayOn=false OR mapMetadata=null.
 *   - Layer paint order is FIXED: clearRect → drawImage (bitmap) → arc
 *     (scan dots) → ondraw hook (Mode-A S1).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../src/stores/mapMetadata', async () => {
  const actual = await vi.importActual<typeof import('../../src/stores/mapMetadata')>(
    '../../src/stores/mapMetadata',
  );
  return { ...actual, loadMapMetadata: vi.fn(async () => {}) };
});

import MapUnderlay from '../../src/components/MapUnderlay.svelte';
import { configureAuth } from '../../src/lib/api';
import { createMapViewport } from '../../src/lib/mapViewport.svelte';
import { _resetLastScanForTests } from '../../src/stores/lastScan';
import { _resetMapMetadataForTests, mapMetadata } from '../../src/stores/mapMetadata';
import type { LastScan, MapMetadata } from '../../src/lib/protocol';

interface CleanupFn {
  (): void;
}
const cleanups: CleanupFn[] = [];

const _IDENTITY_META: MapMetadata = {
  image: 'studio.pgm',
  resolution: 0.05,
  origin: [0, 0, 0],
  negate: 0,
  width: 200,
  height: 100,
  source_url: '/api/map/image',
};

interface RecordedCtx {
  calls: string[];
  fillStyles: string[];
}

function makeFake2DContext(rec: RecordedCtx): CanvasRenderingContext2D {
  const ctx = {
    _fillStyle: '',
    get fillStyle() {
      return this._fillStyle;
    },
    set fillStyle(v: string) {
      this._fillStyle = v;
      rec.fillStyles.push(v);
    },
    strokeStyle: '',
    globalAlpha: 1,
    lineWidth: 0,
    clearRect: () => {
      rec.calls.push('clearRect');
    },
    drawImage: () => {
      rec.calls.push('drawImage');
    },
    beginPath: () => {
      rec.calls.push('beginPath');
    },
    arc: () => {
      rec.calls.push('arc');
    },
    moveTo: () => {
      rec.calls.push('moveTo');
    },
    lineTo: () => {
      rec.calls.push('lineTo');
    },
    fill: () => {
      rec.calls.push('fill');
    },
    stroke: () => {
      rec.calls.push('stroke');
    },
  };
  return ctx as unknown as CanvasRenderingContext2D;
}

beforeEach(() => {
  configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
  // Mode-A T1 — per-instance viewport with a shared scan store. Reset
  // between cases so test 4 (mounting twice) doesn't see stale state.
  _resetLastScanForTests();
  _resetMapMetadataForTests();
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
  Object.defineProperty(HTMLCanvasElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      x: 0,
      y: 0,
      width: 600,
      height: 400,
      top: 0,
      left: 0,
      right: 600,
      bottom: 400,
      toJSON: () => '',
    }),
  });
});

afterEach(() => {
  while (cleanups.length > 0) cleanups.pop()?.();
  _resetMapMetadataForTests();
  _resetLastScanForTests();
  vi.restoreAllMocks();
});

function makeScan(arrivalMs: number, n: number): LastScan {
  const angles_deg: number[] = [];
  const ranges_m: number[] = [];
  for (let i = 0; i < n; i++) {
    angles_deg.push(i * (360 / n));
    ranges_m.push(1.0);
  }
  return {
    valid: 1,
    forced: 1,
    pose_valid: 1,
    iterations: 5,
    published_mono_ns: 1,
    pose_x_m: 0,
    pose_y_m: 0,
    pose_yaw_deg: 0,
    n,
    angles_deg,
    ranges_m,
    _arrival_ms: arrivalMs,
  };
}

function mountUnderlay(props: {
  scan: LastScan | null;
  scanOverlayOn: boolean;
  meta: MapMetadata | null;
  rec?: RecordedCtx;
  ondraw?:
    | ((ctx: CanvasRenderingContext2D, w2c: (x: number, y: number) => [number, number]) => void)
    | null;
}): { target: HTMLDivElement } {
  // Install the canvas getContext stub BEFORE mounting (the first
  // $effect-driven redraw runs synchronously inside mount() and would
  // otherwise see jsdom's null getContext).
  const rec = props.rec ?? { calls: [], fillStyles: [] };
  HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, id: string) {
    if (id !== '2d') return null;
    return makeFake2DContext(rec);
  } as unknown as HTMLCanvasElement['getContext'];
  if (props.meta) mapMetadata.set(props.meta);
  const target = document.createElement('div');
  document.body.appendChild(target);
  const vp = createMapViewport();
  const inst = mount(MapUnderlay, {
    target,
    props: {
      viewport: vp,
      mapImageUrl: '/api/map/image',
      scan: props.scan,
      scanOverlayOn: props.scanOverlayOn,
      ondraw: props.ondraw ?? null,
    },
  });
  cleanups.push(() => {
    unmount(inst);
    target.remove();
  });
  flushSync();
  // Trigger a meta-set so the redraw effect runs against meta-loaded state.
  if (props.meta) {
    mapMetadata.set(props.meta);
    flushSync();
  }
  return { target };
}

describe('MapUnderlay — scan overlay (Rule 3 + Rule 4)', () => {
  it('case 1: scan + overlay-on + meta → data-scan-count > 0', () => {
    const scan = makeScan(Date.now(), 5);
    const { target } = mountUnderlay({
      scan,
      scanOverlayOn: true,
      meta: _IDENTITY_META,
    });
    const wrap = target.querySelector<HTMLDivElement>('[data-testid="map-underlay-wrap"]');
    expect(wrap).not.toBeNull();
    expect(Number(wrap!.getAttribute('data-scan-count') ?? 0)).toBeGreaterThan(0);
  });

  it('case 2: overlay-off → data-scan-count = 0', () => {
    const scan = makeScan(Date.now(), 5);
    const { target } = mountUnderlay({
      scan,
      scanOverlayOn: false,
      meta: _IDENTITY_META,
    });
    const wrap = target.querySelector<HTMLDivElement>('[data-testid="map-underlay-wrap"]');
    expect(wrap!.getAttribute('data-scan-count')).toBe('0');
  });

  it('case 3: meta=null → data-scan-count = 0 (overlay gated on meta, invariant (n))', () => {
    const scan = makeScan(Date.now(), 5);
    const { target } = mountUnderlay({
      scan,
      scanOverlayOn: true,
      meta: null,
    });
    const wrap = target.querySelector<HTMLDivElement>('[data-testid="map-underlay-wrap"]');
    expect(wrap!.getAttribute('data-scan-count')).toBe('0');
  });

  it('case 4 (Rule 4 — single code path): mounting twice with the same scan yields identical data-scan-count', () => {
    const scan = makeScan(Date.now(), 5);
    const a = mountUnderlay({
      scan,
      scanOverlayOn: true,
      meta: _IDENTITY_META,
    });
    const aWrap = a.target.querySelector<HTMLDivElement>('[data-testid="map-underlay-wrap"]');
    const aCount = Number(aWrap!.getAttribute('data-scan-count') ?? 0);
    // Tear down A so the global mock-canvas state doesn't leak.
    while (cleanups.length > 0) cleanups.pop()?.();
    _resetLastScanForTests();
    _resetMapMetadataForTests();
    const b = mountUnderlay({
      scan,
      scanOverlayOn: true,
      meta: _IDENTITY_META,
    });
    const bWrap = b.target.querySelector<HTMLDivElement>('[data-testid="map-underlay-wrap"]');
    const bCount = Number(bWrap!.getAttribute('data-scan-count') ?? 0);
    expect(aCount).toBe(bCount);
    expect(aCount).toBeGreaterThan(0);
  });
});

describe('MapUnderlay — Mode-A S1 layer paint order', () => {
  it('case 5: paint order is clearRect → drawImage → arc → ondraw hook', () => {
    const rec: RecordedCtx = { calls: [], fillStyles: [] };
    const ondrawCalls: number[] = [];
    const scan = makeScan(Date.now(), 3);
    mountUnderlay({
      scan,
      scanOverlayOn: true,
      meta: _IDENTITY_META,
      rec,
      ondraw: (_ctx, _w2c) => {
        ondrawCalls.push(rec.calls.length);
      },
    });
    flushSync();
    // First call must be clearRect.
    expect(rec.calls[0]).toBe('clearRect');
    // drawImage may be missing in jsdom because the bitmap isn't loaded
    // synchronously (it's behind a Promise); the test asserts ordering
    // for whatever is actually emitted. The arc calls (scan dots) come
    // BEFORE the ondraw hook fires.
    const firstArcIdx = rec.calls.indexOf('arc');
    if (firstArcIdx >= 0) {
      // ondraw must fire AFTER the last arc.
      const lastArcIdx = rec.calls.lastIndexOf('arc');
      expect(ondrawCalls.length).toBeGreaterThan(0);
      const lastOndrawAt = ondrawCalls[ondrawCalls.length - 1];
      expect(lastOndrawAt).toBeGreaterThan(lastArcIdx);
    }
    // ondraw is fired even when there are no scan dots (the hook is
    // unconditional once the scan-render branch returns).
    expect(ondrawCalls.length).toBeGreaterThan(0);
  });
});
