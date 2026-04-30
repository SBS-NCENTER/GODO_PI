/**
 * PR β — `lib/mapViewport.svelte.ts` factory + pure-helper cases.
 *
 * The pure-helper cases (clampZoom / applyZoomStep / parsePercent /
 * panClamp / round-trip identity) exercise the math without mounting
 * Svelte (Mode-A M4 — single math SSOT; helpers stay pure).
 *
 * The factory cases pin:
 *   - setMapDims is a one-shot at the FACTORY level (Mode-A M5)
 *   - no `addEventListener('resize', ...)` is registered anywhere
 *     (operator-locked Rule 2 + Mode-A Critical)
 *   - synchronous-emit-on-subscribe at mount captures dims (Mode-A T4)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  applyZoomStep,
  canvasToImagePixel,
  clampZoom,
  createMapViewport,
  formatZoomPercent,
  imagePixelToCanvas,
  panClamp,
  parsePercent,
} from '../../src/lib/mapViewport.svelte';
import {
  MAP_MAX_ZOOM,
  MAP_PAN_OVERSCAN_PX,
  MAP_ZOOM_PERCENT_MAX,
  MAP_ZOOM_STEP,
} from '../../src/lib/constants';

beforeEach(() => {
  // Pin window.innerHeight to a known value for setMapDims tests.
  Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('clampZoom', () => {
  it('case 1: below-min clamps up', () => {
    expect(clampZoom(0.05, 0.1, 20)).toBe(0.1);
  });
  it('case 2: above-max clamps down', () => {
    expect(clampZoom(50, 0.1, 20)).toBe(20);
  });
  it('case 3: in-range passes through', () => {
    expect(clampZoom(2.5, 0.1, 20)).toBe(2.5);
  });
});

describe('applyZoomStep — Mode-A S3 exact-value pin', () => {
  it('case 4: (+) step uses MAP_ZOOM_STEP = 1.25 EXACTLY', () => {
    expect(applyZoomStep(1.0, +1)).toBe(1.25);
    expect(MAP_ZOOM_STEP).toBe(1.25);
  });
  it('case 5: (−) step uses 1 / MAP_ZOOM_STEP EXACTLY', () => {
    expect(applyZoomStep(1.0, -1)).toBe(0.8);
  });
  it('case 5b: dir = 0 is identity', () => {
    expect(applyZoomStep(1.5, 0)).toBe(1.5);
  });
});

describe('parsePercent — happy paths', () => {
  it('case 6: "150" → 1.5', () => {
    expect(parsePercent('150')).toEqual({ value: 1.5, error: null });
  });
  it('case 7 (Mode-A Critical): "1,234" → locale_comma error', () => {
    // Mirror of OriginPicker lesson — silent coercion to 1.234 is
    // the bug class PR #43 caught.
    expect(parsePercent('1,234')).toEqual({ value: null, error: 'locale_comma' });
  });
  it('case 8: "abc" → not_finite error', () => {
    expect(parsePercent('abc')).toEqual({ value: null, error: 'not_finite' });
  });
  it('case 9: trims whitespace', () => {
    expect(parsePercent(' 100 ')).toEqual({ value: 1.0, error: null });
  });
});

describe('parsePercent — Mode-A T2 boundary cases', () => {
  it('case 17: empty string → empty error', () => {
    expect(parsePercent('')).toEqual({ value: null, error: 'empty' });
  });
  it('case 17b: null → empty error', () => {
    expect(parsePercent(null)).toEqual({ value: null, error: 'empty' });
  });
  it('case 18: "0" → 0 (factory-side clamp; helper passes through)', () => {
    expect(parsePercent('0')).toEqual({ value: 0, error: null });
  });
  it('case 19: "100.5" → 1.005 (float branch accepted)', () => {
    expect(parsePercent('100.5')).toEqual({ value: 1.005, error: null });
  });
  it('case 20: "Infinity" → not_finite error', () => {
    expect(parsePercent('Infinity')).toEqual({ value: null, error: 'not_finite' });
  });
  it('case 21: "-50" → -0.5 (helper preserves sign; factory clamps)', () => {
    expect(parsePercent('-50')).toEqual({ value: -0.5, error: null });
  });
});

describe('panClamp — issue#2.2 single-case spec (intersection ≥ OVERSCAN)', () => {
  it('case 12: ridiculously-positive panX is clamped to the upper symmetric bound (large map)', () => {
    // Map 2000 × 1500 at zoom 1, viewport 800 × 600, OVERSCAN 100.
    // New formula (intersection ≥ OVERSCAN px):
    //   panX ∈ [OVERSCAN − W/2 − mw/2, W/2 − OVERSCAN + mw/2]
    //        = [100 − 400 − 1000, 400 − 100 + 1000]
    //        = [-1300, 1300]
    //   panY ∈ [OVERSCAN − H/2 − mh/2, H/2 − OVERSCAN + mh/2]
    //        = [100 − 300 − 750, 300 − 100 + 750]
    //        = [-950, 950]
    // panX = 10000 → above hi=1300 → clamp to 1300.
    // panY = 0 → inside [-950, 950] → unchanged.
    const r = panClamp(10000, 0, 2000, 1500, 800, 600, 1.0);
    expect(r.panX).toBe(1300);
    expect(r.panY).toBe(0);
  });

  it('case 12b: small map — panX/panY clamp to symmetric range (no centering)', () => {
    // Map 2000 × 1500 at zoom 0.1 → projected 200 × 150.
    //   panX ∈ [100 − 400 − 100, 400 − 100 + 100] = [-400, 400]
    //   panY ∈ [100 − 300 − 75,  300 − 100 + 75]  = [-275, 275]
    // panX = 10000 → clamp to 400; panY = 10000 → clamp to 275.
    // (This DIFFERS from the pre-issue-#2.2 behaviour which forced
    // pan=0 for small maps. The new spec lets the operator drift a
    // small map within the viewport, only pulling it back when at
    // least OVERSCAN px would be forced off-screen.)
    const r = panClamp(10000, 10000, 2000, 1500, 800, 600, 0.1);
    expect(r.panX).toBe(400);
    expect(r.panY).toBe(275);
  });

  it('case 12c: large map drag pan is symmetric (regression pin for issue#2.2 HIL bug)', () => {
    // Operator HIL 2026-04-30: at high zoom, drag-pan would stutter
    // and snap to one edge with no return. This pins the symmetry —
    // dragging right (positive panX) and left (negative panX) by the
    // same magnitude must produce mirror-image clamped results.
    const right = panClamp(50, 0, 2000, 1500, 800, 600, 1.0);
    const left = panClamp(-50, 0, 2000, 1500, 800, 600, 1.0);
    expect(right.panX).toBe(50);
    expect(left.panX).toBe(-50);
    // 50 is well within [-1300, 1300] — no clamp, drag goes through.
  });
});

describe('Mode-A M4 — round-trip identity', () => {
  it('case 13: zoom=1, pan=0, canvas=600×400, map=200×100 → identity', () => {
    const cz = imagePixelToCanvas(50, 30, 600, 400, 1, 0, 0, 200, 100);
    const back = canvasToImagePixel(cz[0], cz[1], 600, 400, 1, 0, 0, 200, 100);
    expect(back[0]).toBeCloseTo(50, 9);
    expect(back[1]).toBeCloseTo(30, 9);
  });
  it('case 14: zoom=2, pan=0, canvas=600×400, map=200×100 → identity', () => {
    const cz = imagePixelToCanvas(50, 30, 600, 400, 2, 0, 0, 200, 100);
    const back = canvasToImagePixel(cz[0], cz[1], 600, 400, 2, 0, 0, 200, 100);
    expect(back[0]).toBeCloseTo(50, 9);
    expect(back[1]).toBeCloseTo(30, 9);
  });
  it('case 15: zoom=0.5, panX=37, panY=-19 → identity', () => {
    const cz = imagePixelToCanvas(50, 30, 600, 400, 0.5, 37, -19, 200, 100);
    const back = canvasToImagePixel(cz[0], cz[1], 600, 400, 0.5, 37, -19, 200, 100);
    expect(back[0]).toBeCloseTo(50, 9);
    expect(back[1]).toBeCloseTo(30, 9);
  });
});

describe('createMapViewport — factory state', () => {
  it('case 10: setMapDims is a one-shot at the FACTORY level (Mode-A M5)', () => {
    const vp = createMapViewport();
    expect(vp.minZoom).toBeCloseTo(0.1, 9); // MAP_ZOOM_PERCENT_MIN_DEFAULT/100

    // First call captures innerHeight=800 / mapH=200 → 4.0; clamped to [MAP_MIN_ZOOM, 1.0] → 1.0.
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    vp.setMapDims(400, 200);
    expect(vp.mapWidth).toBe(400);
    expect(vp.mapHeight).toBe(200);
    expect(vp.minZoom).toBe(1.0);

    // Second call with different dims is a NO-OP at the factory level.
    Object.defineProperty(window, 'innerHeight', { value: 1200, configurable: true });
    vp.setMapDims(800, 400);
    expect(vp.mapWidth).toBe(400); // unchanged
    expect(vp.mapHeight).toBe(200); // unchanged
    expect(vp.minZoom).toBe(1.0); // unchanged
  });

  it('case 10b: setMapDims survives null→A→null→B map-switch (Mode-A M5)', () => {
    const vp = createMapViewport();
    // Simulate /map opening map A (200×100 PGM at innerHeight=800 → minZoom = 800/100=8 → clamped to 1.0).
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    vp.setMapDims(200, 100);
    expect(vp.minZoom).toBe(1.0);
    expect(vp.mapHeight).toBe(100);

    // Simulate map switch through `null → fresh-non-null` (operator
    // activates a different map via MapListPanel). The caller might
    // re-emit setMapDims with the new dims; the factory NO-OPs.
    Object.defineProperty(window, 'innerHeight', { value: 600, configurable: true });
    vp.setMapDims(400, 800);
    expect(vp.minZoom).toBe(1.0); // frozen at A's dims
    expect(vp.mapHeight).toBe(100); // frozen at A's dims
  });

  it('case 11 (Mode-A Critical): no `resize` listener registered by createMapViewport + setMapDims', () => {
    const spy = vi.spyOn(window, 'addEventListener');
    const vp = createMapViewport();
    vp.setMapDims(200, 100);
    const resizeCalls = spy.mock.calls.filter((c) => c[0] === 'resize');
    expect(resizeCalls).toHaveLength(0);
  });

  it('case 16 (Mode-A T4): synchronous setMapDims at mount captures dims', () => {
    Object.defineProperty(window, 'innerHeight', { value: 1000, configurable: true });
    const vp = createMapViewport();
    // Synchronous emission (mimics what subscribe(callback) does when the
    // store already has a value at subscribe-time).
    vp.setMapDims(200, 100);
    expect(vp.mapWidth).toBe(200);
    expect(vp.mapHeight).toBe(100);
    // minZoom = clamp(1000/100, 0.1, 1.0) = 1.0
    expect(vp.minZoom).toBe(1.0);
  });

  it('zoomIn applies MAP_ZOOM_STEP and clamps to maxZoom', () => {
    const vp = createMapViewport();
    vp.zoomIn();
    expect(vp.zoom).toBeCloseTo(1.25, 9);
    // Force near max
    for (let i = 0; i < 100; i++) vp.zoomIn();
    expect(vp.zoom).toBe(MAP_MAX_ZOOM);
  });

  it('zoomOut applies 1/MAP_ZOOM_STEP and clamps to minZoom', () => {
    const vp = createMapViewport();
    vp.zoomOut();
    expect(vp.zoom).toBeCloseTo(0.8, 9);
    for (let i = 0; i < 100; i++) vp.zoomOut();
    // After many zoom-outs, clamps to minZoom (0.1 default).
    expect(vp.zoom).toBe(vp.minZoom);
  });

  it('setZoomFromPercent clamps negative input to minZoom (Parent fold T2)', () => {
    const vp = createMapViewport();
    vp.setZoomFromPercent(-50);
    expect(vp.zoom).toBe(vp.minZoom);
  });

  it('setZoomFromPercent clamps oversize input to maxZoom', () => {
    const vp = createMapViewport();
    vp.setZoomFromPercent(MAP_ZOOM_PERCENT_MAX * 10);
    expect(vp.zoom).toBe(MAP_MAX_ZOOM);
  });

  it('setPan + panClampInPlace pulls pan back into the legal range', () => {
    const vp = createMapViewport();
    vp.setMapDims(200, 100);
    vp.setPan(99999, 99999);
    // issue#2.2 single-case spec at zoom=1, viewport 800×600, mapPx=200×100, OVERSCAN=100:
    //   panX ∈ [100 − 400 − 100, 400 − 100 + 100] = [-400, 400] → clamp to 400
    //   panY ∈ [100 − 300 − 50, 300 − 100 + 50] = [-250, 250] → clamp to 250
    vp.panClampInPlace(800, 600);
    expect(vp.panX).toBe(400);
    expect(vp.panY).toBe(250);
  });
});

describe('formatZoomPercent', () => {
  it('renders 1.0 → "100"', () => {
    expect(formatZoomPercent(1.0)).toBe('100');
  });
  it('renders 1.5 → "150"', () => {
    expect(formatZoomPercent(1.5)).toBe('150');
  });
  it('renders 0.245 → "25" (rounded; ORIGIN_DECIMAL_DISPLAY=0)', () => {
    expect(formatZoomPercent(0.245)).toBe('25');
  });
  it('checks MAP_PAN_OVERSCAN_PX is the documented 100', () => {
    expect(MAP_PAN_OVERSCAN_PX).toBe(100);
  });
});
