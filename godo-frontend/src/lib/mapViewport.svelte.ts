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
 * Clamp pan so at least `MAP_PAN_OVERSCAN_PX` of the map's projected
 * bounding box remains visible inside the viewport on every axis.
 *
 * Single-case spec (issue#2.2 fix — operator HIL 2026-04-30 KST):
 *
 *   The map's bounding box in canvas-CSS coords is
 *     `[cx0, cx1] = [W/2 + panX - mw/2, W/2 + panX + mw/2]`
 *   where `mw = mapPx * zoom`. The viewport is `[0, W]`.
 *
 *   For (map ∩ viewport) to have at least OVERSCAN px of overlap:
 *     - map's right edge cx1 ≥ OVERSCAN
 *         →  panX ≥ OVERSCAN − W/2 − mw/2
 *     - map's left  edge cx0 ≤ W − OVERSCAN
 *         →  panX ≤ W/2 − OVERSCAN + mw/2
 *
 *   This gives `panX ∈ [OVERSCAN − W/2 − mw/2, W/2 − OVERSCAN + mw/2]`,
 *   which always has `lo ≤ hi` (lo − hi = 2·OVERSCAN − mw − W ≤ 0 for
 *   any non-negative mw) so the formula is valid for ALL map sizes:
 *
 *     - Tiny map: range width ≈ W; operator can drift the map
 *       most of the viewport before it is pulled back.
 *     - Map-as-big-as-viewport: range width ≈ W; same.
 *     - Large map: range width = W + 2·(mw − OVERSCAN); operator can
 *       pan the map by `(mw − W)/2 + OVERSCAN` past either edge.
 *
 * Why the previous "fits inside viewport with OVERSCAN borders" spec
 * was wrong: at zoom levels where `mw > W − 2·OVERSCAN` the lo/hi
 * bounds invert (lo > hi) and EVERY panX gets snapped to one of the
 * two — the symptom operator HIL flagged was "툭툭 끊기면서 맵이 반
 * 정도 밑으로 내려가버려. 다시 안올라와" (drag stutters then snaps
 * to one edge with no return path). Pin: see
 * `mapViewport.test.ts::panClamp large map drag pan symmetric`.
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

  const loX = MAP_PAN_OVERSCAN_PX - viewportW / 2 - mw / 2;
  const hiX = viewportW / 2 - MAP_PAN_OVERSCAN_PX + mw / 2;
  const outX = panX < loX ? loX : panX > hiX ? hiX : panX;

  const loY = MAP_PAN_OVERSCAN_PX - viewportH / 2 - mh / 2;
  const hiY = viewportH / 2 - MAP_PAN_OVERSCAN_PX + mh / 2;
  const outY = panY < loY ? loY : panY > hiY ? hiY : panY;

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
    setMapDims(
      width: number,
      height: number,
      canvasW?: number,
      canvasH?: number,
    ): void {
      // Mode-A M5 — factory-internal idempotency. The caller cannot
      // accidentally re-trigger min-zoom recomputation by routing the
      // metadata through null → fresh-non-null.
      if (_dimsCaptured) return;
      if (width <= 0 || height <= 0) return; // defensive guard
      _dimsCaptured = true;
      _mapW = width;
      _mapH = height;
      // Operator UX 2026-05-02 KST follow-up: the previous fix used
      // window.innerHeight / innerWidth (full window) but the actual
      // map canvas is smaller — topbar / breadcrumb / Map header /
      // sub-tab nav take up vertical space, sidebar takes horizontal.
      // Result: minZoom was set so the map exactly fit the *window*
      // (e.g. 1080px tall) but the actual canvas is ~800px → 280px
      // overflow at the bottom; operator saw the map with the bottom
      // asymmetrically clipped.
      //
      // Fix: the caller (MapUnderlay.svelte onMount + ResizeObserver
      // bootstrap) measures the real canvas via getBoundingClientRect
      // and passes it through. Falls back to window.* only when the
      // caller hasn't provided concrete canvas dims (e.g. a unit test
      // that doesn't render a real DOM).
      //
      // Issue#13-cand context: post the SLAM default 0.05 → 0.025 m/cell
      // bump, mapping containers emit 4× larger PGMs, making the
      // overflow obvious for the first time.
      const fitW =
        canvasW !== undefined && Number.isFinite(canvasW) && canvasW > 0
          ? canvasW
          : typeof window !== 'undefined' && Number.isFinite(window.innerWidth)
            ? window.innerWidth
            : 0;
      const fitH =
        canvasH !== undefined && Number.isFinite(canvasH) && canvasH > 0
          ? canvasH
          : typeof window !== 'undefined' && Number.isFinite(window.innerHeight)
            ? window.innerHeight
            : 0;
      if (fitH > 0 && fitW > 0) {
        const candidateH = fitH / height;
        const candidateW = fitW / width;
        // Floor = min(width-fit, height-fit) so the rendered map fits
        // both axes at minZoom. Hard-clamp to [MAP_MIN_ZOOM, 1.0] so an
        // absurdly small viewport doesn't push minZoom above native.
        const candidate = Math.min(candidateH, candidateW);
        _minZoom = clampZoom(candidate, MAP_MIN_ZOOM, 1.0);
      }
      // Auto-fit on first load: start at the floor zoom (NOT 1.0).
      // Operator's "기본값 100%일 때 전체적으로 봤으면 좋겠어" intent:
      // first presentation must fit the canvas without requiring a drag.
      _zoom = clampZoom(_minZoom, _minZoom, MAP_MAX_ZOOM);
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
