/**
 * Track D scale fix — map-metadata store.
 *
 * Composes the YAML parser (`mapYaml.parseMapYaml`) with a parallel
 * dimensions fetch (`/api/maps/<name>/dimensions`) so the SPA's
 * `PoseCanvas` can do resolution-aware world↔canvas math.
 *
 * Lifecycle:
 *   - `loadMapMetadata(mapImageUrl)` derives the map name from the URL,
 *     fetches `/api/maps/<name>/yaml` AND `/api/maps/<name>/dimensions`
 *     in parallel, parses both, and writes the combined struct to
 *     `mapMetadata`.
 *   - On rapid name change, an in-flight `AbortController` cancels the
 *     previous fetches so the store ends up with the LATEST request's
 *     value (T2: spy on `set()` proves cancellation, not naive
 *     last-writer-wins).
 *   - On any failure, writes `null` to `mapMetadata` and sets
 *     `mapMetadataError` to a typed reason; the canvas falls back to a
 *     "loading / failed" gate and does not render the overlay.
 *
 * Module discipline (per plan §Module ownership):
 *   - This file is the SOLE composer of YAML + dimensions; PoseCanvas
 *     does NOT call `parseMapYaml` directly.
 *   - This file does NOT touch the canvas, the auth store, or
 *     `lastScan` — strict store-layer responsibilities.
 */

import { writable, type Writable } from 'svelte/store';
import { apiFetch, apiGet } from '$lib/api';
import { parseMapYaml, MapYamlParseError } from '$lib/mapYaml';
import type { MapDimensions, MapMetadata } from '$lib/protocol';

export const mapMetadata: Writable<MapMetadata | null> = writable(null);
export const mapMetadataError: Writable<string | null> = writable(null);

// Tracks the in-flight load so a later `loadMapMetadata` can abort the
// previous fetches AND ignore their resolution. AbortController alone
// is not sufficient because jsdom's fetch sometimes resolves the
// promise even after `.abort()` — we double-gate via the
// `_currentLoadId` token.
let _currentAbort: AbortController | null = null;
let _currentLoadId = 0;

/**
 * Derive the map name from `mapImageUrl` per the SPA convention:
 *
 *   /api/maps/<name>/image → <name>
 *   /api/map/image          → "active"
 *
 * Anything else falls back to `"active"` so the store still issues a
 * coherent fetch pair against the active symlink pair.
 */
function nameFromImageUrl(url: string): string {
  const m = /\/api\/maps\/([^/]+)\/image$/.exec(url);
  if (m) return decodeURIComponent(m[1] ?? 'active');
  return 'active';
}

export async function loadMapMetadata(mapImageUrl: string): Promise<void> {
  // Abort any previous load.
  if (_currentAbort !== null) {
    _currentAbort.abort();
  }
  const abort = new AbortController();
  _currentAbort = abort;
  _currentLoadId += 1;
  const myLoadId = _currentLoadId;

  // Synchronously clear the previous metadata so a stale snapshot does
  // not leak into a redraw against the new image.
  mapMetadata.set(null);
  mapMetadataError.set(null);

  const name = nameFromImageUrl(mapImageUrl);
  const yamlPath = `/api/maps/${encodeURIComponent(name)}/yaml`;
  const dimsPath = `/api/maps/${encodeURIComponent(name)}/dimensions`;

  let yamlText: string;
  let dims: MapDimensions;

  try {
    const [yamlResp, dimsObj] = await Promise.all([
      apiFetch(yamlPath, { signal: abort.signal }),
      apiGet<MapDimensions>(dimsPath, { signal: abort.signal }),
    ]);
    yamlText = await yamlResp.text();
    dims = dimsObj;
  } catch (e) {
    if (myLoadId !== _currentLoadId) return; // superseded
    const status = (e as { status?: number })?.status;
    if (status === 404) {
      // Distinguish which sub-fetch 404'd is not free without two
      // separate requests; the SPA shows a single banner regardless.
      mapMetadataError.set('yaml_404');
    } else if (e instanceof MapYamlParseError) {
      mapMetadataError.set(`yaml_parse_${e.reason}`);
    } else {
      mapMetadataError.set('fetch_failed');
    }
    return;
  }

  if (myLoadId !== _currentLoadId) return; // superseded after fetch

  try {
    const parsed = parseMapYaml(yamlText);
    mapMetadata.set({
      ...parsed,
      width: dims.width,
      height: dims.height,
      source_url: mapImageUrl,
    });
  } catch (e) {
    if (e instanceof MapYamlParseError) {
      mapMetadataError.set(`yaml_parse_${e.reason}`);
    } else {
      mapMetadataError.set('parse_failed');
    }
  }
}

export function _resetMapMetadataForTests(): void {
  if (_currentAbort !== null) {
    _currentAbort.abort();
    _currentAbort = null;
  }
  _currentLoadId = 0;
  mapMetadata.set(null);
  mapMetadataError.set(null);
}
