/**
 * PR β — shared map viewport factory.
 *
 * Sole owner of zoom + pan + min-zoom state for the shared
 * `<MapUnderlay/>` (consumed by both `/map` and `/map-edit`). The
 * factory returns an instance bound to its caller's component
 * lifetime; calling it twice (once per route) creates two
 * independent viewports per Q2 of the PR β plan. Module-scope
 * singletons would (a) leak state across `/map ↔ /map-edit`
 * navigation, (b) require manual reset between vitest cases.
 *
 * Min-zoom semantic (operator-locked Rule 2): captured ONCE from
 * `window.innerHeight` at the FIRST `setMapDims(w, h)` call. Subsequent
 * calls are NO-OPs at the FACTORY level (Mode-A M5 — `_dimsCaptured`
 * flag lives in this closure, NOT in the caller). NO `addEventListener`
 * on `'resize'` anywhere; pinned by `tests/unit/mapViewport.test.ts`.
 *
 * Pure helpers (`clampZoom`, `applyZoomStep`, `parsePercent`,
 * `panClamp`, `worldToCanvas`, `canvasToWorld`, `canvasToImagePixel`,
 * `imagePixelToCanvas`) are exported as named exports SEPARATE from
 * `createMapViewport`. They take all inputs as parameters — no
 * closure leak — so unit tests can exercise the math without a Svelte
 * mount (Mode-A M4 — single math SSOT; helpers stay pure; the factory
 * wraps them with `$state`).
 */

import {
  MAP_DEFAULT_ZOOM,
  MAP_MAX_ZOOM,
  MAP_MIN_ZOOM,
  MAP_PAN_OVERSCAN_PX,
  MAP_ZOOM_PERCENT_MAX,
  MAP_ZOOM_PERCENT_MIN_DEFAULT,
  MAP_ZOOM_STEP,
} from './constants';
import type { MapMetadata } from './protocol';

// --- Pure helpers (sole math SSOT — Mode-A M4) -------------------------

/** Clamp a zoom ratio to [min, max]. */
export function clampZoom(z: number, min: number, max: number): number {
  if (z < min) return min;
  if (z > max) return max;
  return z;
}

/**
 * Apply one (+) or (−) step. `dir > 0` zooms in, `dir < 0` zooms out.
 * The clamp is the caller's responsibility — keep this helper pure.
 */
export function applyZoomStep(z: number, dir: number): number {
  if (dir > 0) return z * MAP_ZOOM_STEP;
  if (dir < 0) return z / MAP_ZOOM_STEP;
  return z;
}

export interface ParsePercentResult {
  /** Parsed ratio (e.g. `"150"` → `1.5`). `null` on error. */
  value: number | null;
  /**
   * `null` on success. One of `'empty' | 'locale_comma' | 'not_finite'`
   * on a recoverable user-input error. Out-of-range values are
   * rendered separately (the factory clamps and renders an
   * `out_of_bound` banner — operator-friendly soft clamp, not a hard
   * reject).
   */
  error: 'empty' | 'locale_comma' | 'not_finite' | null;
}

/**
 * Parse a percent string into a zoom ratio. Mirrors the OriginPicker
 * idiom (PR #43): `type="text" inputmode="decimal"` lets us reject
 * locale-comma `1,234` explicitly so a Windows browser pasting
 * European notation does NOT silently coerce.
 *
 * Whitespace is trimmed; integer and float forms accepted; sign is
 * preserved (negative values are clamped at the factory layer per
 * Parent fold T2 — negative is operator typo, treat as clamp-to-floor).
 */
export function parsePercent(text: string | null | undefined): ParsePercentResult {
  if (text === null || text === undefined) return { value: null, error: 'empty' };
  const trimmed = String(text).trim();
  if (trimmed === '') return { value: null, error: 'empty' };
  if (trimmed.includes(',')) return { value: null, error: 'locale_comma' };
  const v = Number(trimmed);
  if (!Number.isFinite(v)) return { value: null, error: 'not_finite' };
  return { value: v / 100, error: null };
}

/**
 * Clamp pan so the map's projected bounding box overlaps the viewport
 * by at least `MAP_PAN_OVERSCAN_PX` on every side.
 *
 * Two-case spec (Mode-A M1 + Parent fold Q7):
 *   - **Smaller-than-viewport axis** — the projected map width on that
 *     axis is smaller than the viewport. Center it (pan = 0). Operator
 *     cannot lose the map by panning a small map off-screen.
 *   - **Larger-than-viewport axis** — the projected map width is
 *     bigger. Clamp the pan so the projected box keeps `OVERSCAN_PX`
 *     overlap with the viewport. The operator can pan freely so long
 *     as the map's bounding box does not retreat further than 100 px
 *     past either edge.
 *
 * The underlay draws around the canvas center, so the map's bounding
 * box (in canvas-CSS coords) is `[cx0, cx1] = [W/2 + panX - mw/2,
 * W/2 + panX + mw/2]` where `mw = mapPx * zoom`. Constraint:
 *
 *   cx1 ≥ OVERSCAN  →  panX ≥ OVERSCAN - W/2 - mw/2 + W
 *                  →  panX ≥ OVERSCAN - W/2 - mw/2 + W   (= W/2 + OVERSCAN - mw/2 ... wait)
 *
 * Algebra (re-derived cleanly):
 *
 *   right edge cx1 = W/2 + panX + mw/2  ≤  W − OVERSCAN
 *     →  panX ≤ W/2 − OVERSCAN − mw/2
 *
 *   left  edge cx0 = W/2 + panX − mw/2  ≥  OVERSCAN
 *     →  panX ≥ OVERSCAN + mw/2 − W/2
 *
 * Symmetric range. When `mw < W` (smaller axis), the two bounds cross
 * over (lower > upper) — the centered position pan = 0 is the only
 * point inside both — so we force pan = 0. Same algebra for Y.
 */
export function panClamp(
  panX: number,
  panY: number,
  mapPx: number,
  mapPy: number,
  viewportW: number,
  viewportH: number,
  zoom: number,
): { panX: number; panY: number } {
  const mw = mapPx * zoom;
  const mh = mapPy * zoom;

  let outX: number;
  if (mw + 2 * MAP_PAN_OVERSCAN_PX <= viewportW) {
    // Smaller (or equal-with-room) axis — center the map.
    outX = 0;
  } else {
    const lo = MAP_PAN_OVERSCAN_PX + mw / 2 - viewportW / 2;
    const hi = viewportW / 2 - MAP_PAN_OVERSCAN_PX - mw / 2;
    if (panX < lo) outX = lo;
    else if (panX > hi) outX = hi;
    else outX = panX;
  }

  let outY: number;
  if (mh + 2 * MAP_PAN_OVERSCAN_PX <= viewportH) {
    outY = 0;
  } else {
    const lo = MAP_PAN_OVERSCAN_PX + mh / 2 - viewportH / 2;
    const hi = viewportH / 2 - MAP_PAN_OVERSCAN_PX - mh / 2;
    if (panY < lo) outY = lo;
    else if (panY > hi) outY = hi;
    else outY = panY;
  }

  return { panX: outX, panY: outY };
}

/**
 * World → canvas-CSS coordinates. The math mirrors PoseCanvas's
 * pre-PR-β implementation (now MapUnderlay's instance method, kept as
 * a passthrough). When `meta === null` we fall back to a centered
 * Cartesian frame so the parent's `ondraw` hook still has a meaningful
 * projection during metadata load.
 *
 * (Mode-A M4 — pure helper; the underlay calls this with its own
 * `(canvas.width, canvas.height)` as parameters. No closure leaks.)
 */
export function worldToCanvas(
  wx: number,
  wy: number,
  canvasW: number,
  canvasH: number,
  zoom: number,
  panX: number,
  panY: number,
  meta: MapMetadata | null,
): [number, number] {
  if (!meta) {
    return [canvasW / 2 + panX + wx * zoom, canvasH / 2 + panY - wy * zoom];
  }
  const imgCol = (wx - meta.origin[0]) / meta.resolution;
  const imgRow = meta.height - 1 - (wy - meta.origin[1]) / meta.resolution;
  const cx = canvasW / 2 + panX + (imgCol - meta.width / 2) * zoom;
  const cy = canvasH / 2 + panY + (imgRow - meta.height / 2) * zoom;
  return [cx, cy];
}

/** Inverse of `worldToCanvas`. */
export function canvasToWorld(
  cx: number,
  cy: number,
  canvasW: number,
  canvasH: number,
  zoom: number,
  panX: number,
  panY: number,
  meta: MapMetadata | null,
): [number, number] {
  if (!meta) {
    return [(cx - canvasW / 2 - panX) / zoom, -(cy - canvasH / 2 - panY) / zoom];
  }
  const imgCol = (cx - canvasW / 2 - panX) / zoom + meta.width / 2;
  const imgRow = (cy - canvasH / 2 - panY) / zoom + meta.height / 2;
  const wx = imgCol * meta.resolution + meta.origin[0];
  const wy = (meta.height - 1 - imgRow) * meta.resolution + meta.origin[1];
  return [wx, wy];
}

/**
 * Canvas-CSS → underlay-image-pixel coords. Used by `<MapMaskCanvas/>`
 * to invert the viewport transform on a pointer event before mapping
 * into logical mask cells.
 *
 * `mapW` / `mapH` are the underlay PGM's logical dimensions (NOT the
 * canvas-CSS dimensions). The underlay draws the bitmap at
 * `imgCol = px` (no resolution scaling — that's the world-frame
 * helper's job). So the inverse is the same algebra without the
 * resolution+origin step.
 */
export function canvasToImagePixel(
  cx: number,
  cy: number,
  canvasW: number,
  canvasH: number,
  zoom: number,
  panX: number,
  panY: number,
  mapW: number,
  mapH: number,
): [number, number] {
  const px = (cx - canvasW / 2 - panX) / zoom + mapW / 2;
  const py = (cy - canvasH / 2 - panY) / zoom + mapH / 2;
  return [px, py];
}

/** Round-trip companion of `canvasToImagePixel` (for tests + sanity). */
export function imagePixelToCanvas(
  px: number,
  py: number,
  canvasW: number,
  canvasH: number,
  zoom: number,
  panX: number,
  panY: number,
  mapW: number,
  mapH: number,
): [number, number] {
  const cx = canvasW / 2 + panX + (px - mapW / 2) * zoom;
  const cy = canvasH / 2 + panY + (py - mapH / 2) * zoom;
  return [cx, cy];
}

// --- Factory -----------------------------------------------------------

export interface MapViewport {
  /** Current zoom ratio (1.0 = native). */
  readonly zoom: number;
  /** Current pan offset (CSS pixels in canvas frame). */
  readonly panX: number;
  readonly panY: number;
  /**
   * Effective minimum zoom ratio. Initialised at
   * `MAP_ZOOM_PERCENT_MIN_DEFAULT / 100` and frozen at first
   * `setMapDims` call to `clamp(viewportH / mapH, MAP_MIN_ZOOM, 1.0)`.
   */
  readonly minZoom: number;
  readonly maxZoom: number;
  /** PGM logical dimensions captured at first `setMapDims` (or 0 if
   * not yet captured). */
  readonly mapWidth: number;
  readonly mapHeight: number;

  /** (+) button — multiply zoom by `MAP_ZOOM_STEP`, clamp. */
  zoomIn(): void;
  /** (−) button — divide zoom by `MAP_ZOOM_STEP`, clamp. */
  zoomOut(): void;
  /** Numeric-input apply path. Negative → clamp to minZoom. */
  setZoomFromPercent(percent: number): void;
  /** Programmatic pan write (drag handlers). */
  setPan(panX: number, panY: number): void;
  /**
   * One-shot at the FACTORY level: the first call captures
   * `window.innerHeight` AT THAT MOMENT and freezes minZoom; every
   * subsequent call is a NO-OP regardless of caller.
   */
  setMapDims(width: number, height: number): void;

  // --- pure-helper passthroughs (Mode-A M4 — single math SSOT) ---
  worldToCanvas(
    wx: number,
    wy: number,
    canvasW: number,
    canvasH: number,
    meta: MapMetadata | null,
  ): [number, number];
  canvasToWorld(
    cx: number,
    cy: number,
    canvasW: number,
    canvasH: number,
    meta: MapMetadata | null,
  ): [number, number];
  canvasToImagePixel(cx: number, cy: number, canvasW: number, canvasH: number): [number, number];
  imagePixelToCanvas(px: number, py: number, canvasW: number, canvasH: number): [number, number];
  panClampInPlace(viewportW: number, viewportH: number): void;
}

/** Create a fresh viewport instance. Per-route, not module-scope. */
export function createMapViewport(): MapViewport {
  let _zoom = $state(MAP_DEFAULT_ZOOM);
  let _panX = $state(0);
  let _panY = $state(0);
  let _minZoom = $state(MAP_ZOOM_PERCENT_MIN_DEFAULT / 100);
  let _mapW = $state(0);
  let _mapH = $state(0);
  // Factory-internal idempotency (Mode-A M5). NOT exposed to callers.
  let _dimsCaptured = false;

  return {
    get zoom() {
      return _zoom;
    },
    get panX() {
      return _panX;
    },
    get panY() {
      return _panY;
    },
    get minZoom() {
      return _minZoom;
    },
    get maxZoom() {
      return MAP_MAX_ZOOM;
    },
    get mapWidth() {
      return _mapW;
    },
    get mapHeight() {
      return _mapH;
    },

    zoomIn(): void {
      _zoom = clampZoom(applyZoomStep(_zoom, +1), _minZoom, MAP_MAX_ZOOM);
    },
    zoomOut(): void {
      _zoom = clampZoom(applyZoomStep(_zoom, -1), _minZoom, MAP_MAX_ZOOM);
    },
    setZoomFromPercent(percent: number): void {
      // Negative → clamp to minZoom (Parent fold T2 — negative is
      // operator typo, treat as clamp-to-floor).
      const ratio = percent / 100;
      _zoom = clampZoom(ratio, _minZoom, MAP_MAX_ZOOM);
    },
    setPan(panX: number, panY: number): void {
      _panX = panX;
      _panY = panY;
    },
    setMapDims(width: number, height: number): void {
      // Mode-A M5 — factory-internal idempotency. The caller cannot
      // accidentally re-trigger min-zoom recomputation by routing the
      // metadata through null → fresh-non-null.
      if (_dimsCaptured) return;
      if (width <= 0 || height <= 0) return; // defensive guard
      _dimsCaptured = true;
      _mapW = width;
      _mapH = height;
      // Capture window.innerHeight ONCE and compute the floor.
      // Server-side renders (jsdom) supply a default of 768; tests
      // override via `Object.defineProperty(window, 'innerHeight', ...)`.
      const viewportH =
        typeof window !== 'undefined' && Number.isFinite(window.innerHeight)
          ? window.innerHeight
          : 0;
      if (viewportH > 0) {
        // Floor zoom = ratio at which mapHeight × zoom == viewportH.
        // Hard-clamp to [MAP_MIN_ZOOM, 1.0] so an absurdly small viewport
        // doesn't push minZoom above the natural-size starting zoom.
        const candidate = viewportH / height;
        _minZoom = clampZoom(candidate, MAP_MIN_ZOOM, 1.0);
      }
      // Re-clamp the current zoom now that the floor may have moved.
      _zoom = clampZoom(_zoom, _minZoom, MAP_MAX_ZOOM);
    },

    worldToCanvas(wx, wy, canvasW, canvasH, meta) {
      return worldToCanvas(wx, wy, canvasW, canvasH, _zoom, _panX, _panY, meta);
    },
    canvasToWorld(cx, cy, canvasW, canvasH, meta) {
      return canvasToWorld(cx, cy, canvasW, canvasH, _zoom, _panX, _panY, meta);
    },
    canvasToImagePixel(cx, cy, canvasW, canvasH) {
      return canvasToImagePixel(cx, cy, canvasW, canvasH, _zoom, _panX, _panY, _mapW, _mapH);
    },
    imagePixelToCanvas(px, py, canvasW, canvasH) {
      return imagePixelToCanvas(px, py, canvasW, canvasH, _zoom, _panX, _panY, _mapW, _mapH);
    },
    panClampInPlace(viewportW, viewportH): void {
      const c = panClamp(_panX, _panY, _mapW, _mapH, viewportW, viewportH, _zoom);
      _panX = c.panX;
      _panY = c.panY;
    },
  };
}

/**
 * Format a zoom ratio as an integer percentage string for the
 * `<MapZoomControls/>` numeric input. `1.0` → `"100"`, `0.245` → `"25"`.
 */
export function formatZoomPercent(zoom: number): string {
  return String(Math.round(zoom * 100));
}

/** Re-export so consumers can pin the exact value. Kept as a value
 * (not a re-export of the constant) so a writer can't sneak in an
 * override via tree-shaking. */
export const _MAP_ZOOM_STEP_FOR_TESTS = MAP_ZOOM_STEP;
export const _MAP_ZOOM_PERCENT_MAX_FOR_TESTS = MAP_ZOOM_PERCENT_MAX;
