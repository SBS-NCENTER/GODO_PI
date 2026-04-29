/**
 * Track D scale fix (Mode-A M3) — pin the reactive image refetch.
 *
 * Pre-fix `PoseCanvas.svelte` only fetched the bitmap inside `onMount`,
 * so a `mapImageUrl` prop change repointed the metadata store to the
 * new map but left the canvas's bitmap pointing at the old one
 * (silently mis-rendering). The fix replaces the `onMount`-only fetch
 * with a `$effect(() => { void mapImageUrl; refetchImage(); })`.
 *
 * This test pins the call count: 1 fetch on initial mount, 2 fetches
 * after one prop change, 3 fetches after two changes — using a host
 * Svelte component that passes the URL as a reactive prop into
 * `PoseCanvas`. This is the load-bearing differentiator vs. the OLD
 * `onMount`-only behaviour (which would only fetch on a fresh mount).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import PoseCanvasHost from './_PoseCanvasHost.svelte';
import { configureAuth } from '../../src/lib/api';
import { _resetMapMetadataForTests } from '../../src/stores/mapMetadata';

interface CleanupFn {
  (): void;
}
const cleanups: CleanupFn[] = [];

beforeEach(() => {
  configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
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
  _resetMapMetadataForTests();
  vi.restoreAllMocks();
});

describe('PoseCanvas — Mode-A M3 reactive image refetch', () => {
  it('refetches the bitmap when mapImageUrl changes', () => {
    const imageFetchUrls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      // Categorize the call.
      if (url.endsWith('/image') || url === '/api/map/image') {
        imageFetchUrls.push(url);
        return new Response(new Uint8Array([0x89, 0x50, 0x4e, 0x47]).buffer, {
          status: 200,
          headers: { 'content-type': 'image/png' },
        });
      }
      if (url.endsWith('/yaml')) {
        return new Response('image: x.pgm\nresolution: 0.05\norigin: [0,0,0]\nnegate: 0\n', {
          status: 200,
          headers: { 'content-type': 'text/plain' },
        });
      }
      if (url.endsWith('/dimensions')) {
        return new Response(JSON.stringify({ width: 200, height: 100 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      return new Response('', { status: 404 });
    });

    const target = document.createElement('div');
    document.body.appendChild(target);

    // Mount the host. The host exports a `setUrl()` function whose
    // body mutates an internal `$state(url)`; PoseCanvas sees the
    // change reactively and re-runs its `$effect(() => mapImageUrl)`.
    const host = mount(PoseCanvasHost, {
      target,
      props: { pose: null, initialUrl: '/api/map/image' },
    });
    cleanups.push(() => unmount(host));
    flushSync();

    // Initial mount → 1 image fetch (the $effect fires once).
    expect(imageFetchUrls.length).toBe(1);
    expect(imageFetchUrls[0]).toBe('/api/map/image');

    const setUrl = (host as { setUrl: (s: string) => void }).setUrl;

    // First prop change.
    setUrl('/api/maps/studio_v1/image');
    flushSync();
    expect(imageFetchUrls.length).toBe(2);
    expect(imageFetchUrls[1]).toBe('/api/maps/studio_v1/image');

    // Second prop change.
    setUrl('/api/maps/studio_v2/image');
    flushSync();
    expect(imageFetchUrls.length).toBe(3);
    expect(imageFetchUrls[2]).toBe('/api/maps/studio_v2/image');
  });
});
