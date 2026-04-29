/**
 * Track D scale fix — `mapMetadata` store unit tests.
 *
 * Pins:
 *   1. Parallel fetch of `/api/maps/<name>/yaml` + `/api/maps/<name>/dimensions`.
 *   2. Name derivation: `/api/map/image` → `"active"`.
 *   3. Rapid name-change race (Mode-A T2 strengthened): spy on `set()`,
 *      assert v1's resolution does NOT leak into the store after v2 was
 *      issued.
 *   4. 404 surfaces as a typed error.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { configureAuth } from '../../src/lib/api';
import {
  _resetMapMetadataForTests,
  loadMapMetadata,
  mapMetadata,
  mapMetadataError,
} from '../../src/stores/mapMetadata';

const YAML_BODY_V1 = [
  'image: studio_v1.pgm',
  'resolution: 0.05',
  'origin: [0.0, 0.0, 0.0]',
  'negate: 0',
].join('\n');

const YAML_BODY_V2 = [
  'image: studio_v2.pgm',
  'resolution: 0.025',
  'origin: [-2.0, -1.0, 0.0]',
  'negate: 0',
].join('\n');

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function textResponse(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
}

beforeEach(() => {
  configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
});

afterEach(() => {
  _resetMapMetadataForTests();
  vi.restoreAllMocks();
});

describe('mapMetadata — parallel fetch', () => {
  it('parallel-fetches /api/maps/<name>/yaml + /dimensions and composes', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.endsWith('/yaml')) return textResponse(YAML_BODY_V1);
      if (url.endsWith('/dimensions')) return jsonResponse({ width: 200, height: 100 });
      throw new Error(`unexpected fetch ${url}`);
    });

    await loadMapMetadata('/api/maps/studio_v1/image');

    const m = get(mapMetadata);
    expect(m).not.toBeNull();
    expect(m!.resolution).toBe(0.05);
    expect(m!.origin).toEqual([0, 0, 0]);
    expect(m!.width).toBe(200);
    expect(m!.height).toBe(100);
    expect(m!.source_url).toBe('/api/maps/studio_v1/image');
    expect(get(mapMetadataError)).toBeNull();

    // Both endpoints called in parallel (call order is implementation
    // detail; assert by URL hits).
    const urls = fetchSpy.mock.calls.map((c) => {
      const arg = c[0];
      return typeof arg === 'string' ? arg : (arg as Request).url;
    });
    expect(urls.some((u) => u.includes('/api/maps/studio_v1/yaml'))).toBe(true);
    expect(urls.some((u) => u.includes('/api/maps/studio_v1/dimensions'))).toBe(true);
  });

  it('derives name = "active" for /api/map/image', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.endsWith('/yaml')) return textResponse(YAML_BODY_V1);
      if (url.endsWith('/dimensions')) return jsonResponse({ width: 50, height: 50 });
      throw new Error(`unexpected fetch ${url}`);
    });

    await loadMapMetadata('/api/map/image');

    const urls = fetchSpy.mock.calls.map((c) => {
      const arg = c[0];
      return typeof arg === 'string' ? arg : (arg as Request).url;
    });
    expect(urls.some((u) => u.includes('/api/maps/active/yaml'))).toBe(true);
    expect(urls.some((u) => u.includes('/api/maps/active/dimensions'))).toBe(true);
  });
});

describe('mapMetadata — Mode-A T2: rapid name change cancellation', () => {
  it('a v2 load issued before v1 settles wins, and v1 is never written into the store', async () => {
    // Resolvers controlled per-call so we can interleave.
    let resolveV1Yaml: ((r: Response) => void) | null = null;
    let resolveV1Dims: ((r: Response) => void) | null = null;
    let resolveV2Yaml: ((r: Response) => void) | null = null;
    let resolveV2Dims: ((r: Response) => void) | null = null;

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      const signal = (init as RequestInit | undefined)?.signal;
      return new Promise<Response>((resolve, reject) => {
        const onAbort = () => reject(new DOMException('aborted', 'AbortError'));
        if (signal) {
          if (signal.aborted) {
            reject(new DOMException('aborted', 'AbortError'));
            return;
          }
          signal.addEventListener('abort', onAbort);
        }
        if (url.includes('/studio_v1/yaml')) resolveV1Yaml = resolve;
        else if (url.includes('/studio_v1/dimensions')) resolveV1Dims = resolve;
        else if (url.includes('/studio_v2/yaml')) resolveV2Yaml = resolve;
        else if (url.includes('/studio_v2/dimensions')) resolveV2Dims = resolve;
      });
    });

    // Record every store transition.
    const seen: Array<unknown> = [];
    const unsub = mapMetadata.subscribe((v) => seen.push(v));

    const p1 = loadMapMetadata('/api/maps/studio_v1/image');
    // Synchronous reset to null is one expected entry.
    const p2 = loadMapMetadata('/api/maps/studio_v2/image');

    // Resolve v1 AFTER v2 was issued — production code must drop these.
    resolveV1Yaml!(textResponse(YAML_BODY_V1));
    resolveV1Dims!(jsonResponse({ width: 200, height: 100 }));
    await p1.catch(() => {}); // may reject due to abort; that is fine

    // v1 must NOT have leaked into the store at any point.
    expect(
      seen.every((v) => v === null || (v as { resolution?: number }).resolution !== 0.05),
    ).toBe(true);

    // Now resolve v2 — store ends with v2.
    resolveV2Yaml!(textResponse(YAML_BODY_V2));
    resolveV2Dims!(jsonResponse({ width: 400, height: 50 }));
    await p2;
    unsub();

    const finalState = get(mapMetadata);
    expect(finalState).not.toBeNull();
    expect(finalState!.resolution).toBe(0.025);
    expect(finalState!.width).toBe(400);
    expect(finalState!.height).toBe(50);
  });
});

describe('mapMetadata — error paths', () => {
  it('surfaces yaml_404 when YAML fetch returns 404', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.endsWith('/yaml')) return jsonResponse({ ok: false, err: 'map_not_found' }, 404);
      if (url.endsWith('/dimensions')) return jsonResponse({ width: 1, height: 1 });
      throw new Error(`unexpected fetch ${url}`);
    });

    await loadMapMetadata('/api/maps/studio_vX/image');

    expect(get(mapMetadata)).toBeNull();
    expect(get(mapMetadataError)).toBe('yaml_404');
  });

  it('surfaces a parse error when the YAML body is malformed', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.endsWith('/yaml')) return textResponse('image: x.pgm\norigin: [0,0,0]\n'); // missing resolution
      if (url.endsWith('/dimensions')) return jsonResponse({ width: 200, height: 100 });
      throw new Error(`unexpected fetch ${url}`);
    });

    await loadMapMetadata('/api/maps/studio_v1/image');

    expect(get(mapMetadata)).toBeNull();
    expect(get(mapMetadataError)).toBe('yaml_parse_missing_resolution');
  });
});
