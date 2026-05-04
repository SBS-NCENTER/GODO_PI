import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { configureAuth } from '../../src/lib/api';
import {
  InvalidMapName,
  activate,
  isValidMapName,
  maps,
  refresh,
  remove,
} from '../../src/stores/maps';

beforeEach(() => {
  configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
  maps.set([]);
  Object.defineProperty(window, 'location', {
    value: { hash: '#/', origin: 'http://localhost' },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('maps store', () => {
  it('refresh() GETs /api/maps and updates the store', async () => {
    const fakeList = [
      { name: 'studio_v1', size_bytes: 1024, mtime_unix: 1.0, is_active: true },
      { name: 'studio_v2', size_bytes: 2048, mtime_unix: 2.0, is_active: false },
    ];
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResp(fakeList));

    const list = await refresh();

    expect(list).toEqual(fakeList);
    expect(get(maps)).toEqual(fakeList);
    expect(fetchSpy).toHaveBeenCalledOnce();
    const url = fetchSpy.mock.calls[0]![0] as string;
    expect(url).toBe('/api/maps');
  });

  // issue#28 (HIL fix) — server response shape changed from `MapEntry[]`
  // to `{groups, flat}`. Operator HIL on PR #81 caught the SPA showing
  // an empty map list because the store assigned the entire object to
  // a `Writable<MapEntry[]>`. This pin guards the new extraction path.
  it('refresh() extracts `flat` from issue#28 grouped response shape', async () => {
    const flat = [
      { name: 'studio_v1', size_bytes: 1024, mtime_unix: 1.0, is_active: true },
      {
        name: 'studio_v1.20260504-1430-wallcal',
        size_bytes: 1024,
        mtime_unix: 2.0,
        is_active: false,
      },
    ];
    const groupedResp = {
      groups: [{ pristine: flat[0], variants: [flat[1]] }],
      flat,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResp(groupedResp));

    const list = await refresh();

    expect(list).toEqual(flat);
    expect(get(maps)).toEqual(flat);
  });

  it('activate(name) POSTs to /api/maps/<name>/activate and triggers refresh', async () => {
    const fakeList = [
      { name: 'studio_v1', size_bytes: 1024, mtime_unix: 1.0, is_active: false },
      { name: 'studio_v2', size_bytes: 2048, mtime_unix: 2.0, is_active: true },
    ];
    let call = 0;
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      call++;
      if (call === 1) {
        return jsonResp({ ok: true, restart_required: true });
      }
      return jsonResp(fakeList);
    });

    const resp = await activate('studio_v2');
    expect(resp).toEqual({ ok: true, restart_required: true });

    const firstUrl = fetchSpy.mock.calls[0]![0] as string;
    expect(firstUrl).toBe('/api/maps/studio_v2/activate');
    const firstInit = fetchSpy.mock.calls[0]![1] as RequestInit;
    expect(firstInit.method).toBe('POST');

    // Second call is the refresh.
    const secondUrl = fetchSpy.mock.calls[1]![0] as string;
    expect(secondUrl).toBe('/api/maps');

    expect(get(maps)).toEqual(fakeList);
  });

  it('remove(name) DELETEs /api/maps/<name> and triggers refresh', async () => {
    const fakeList = [{ name: 'studio_v1', size_bytes: 1024, mtime_unix: 1.0, is_active: true }];
    let call = 0;
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      call++;
      if (call === 1) {
        return jsonResp({ ok: true });
      }
      return jsonResp(fakeList);
    });

    await remove('studio_v2');

    const firstUrl = fetchSpy.mock.calls[0]![0] as string;
    expect(firstUrl).toBe('/api/maps/studio_v2');
    const firstInit = fetchSpy.mock.calls[0]![1] as RequestInit;
    expect(firstInit.method).toBe('DELETE');

    expect(get(maps)).toEqual(fakeList);
  });

  it('activate() rejects path-traversal name client-side without issuing the request', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    await expect(activate('../etc/passwd')).rejects.toThrow(InvalidMapName);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('remove() rejects empty name client-side without issuing the request', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    await expect(remove('')).rejects.toThrow(InvalidMapName);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('isValidMapName accepts good names and rejects path-traversal corpus', () => {
    expect(isValidMapName('studio_v1')).toBe(true);
    expect(isValidMapName('a')).toBe(true);
    expect(isValidMapName('a'.repeat(64))).toBe(true);
    // 2026-04-29: dot mid-stem and parens are now allowed.
    expect(isValidMapName('04.29_1')).toBe(true);
    expect(isValidMapName('studio(1)')).toBe(true);
    // Rejection corpus — string literals, not parametrize. Each call's
    // failure message names exactly which input slipped through.
    expect(isValidMapName('')).toBe(false);
    expect(isValidMapName('..')).toBe(false);
    expect(isValidMapName('foo/bar')).toBe(false);
    expect(isValidMapName('.hidden')).toBe(false);  // leading dot still rejected
    expect(isValidMapName('a'.repeat(65))).toBe(false);
  });
});
