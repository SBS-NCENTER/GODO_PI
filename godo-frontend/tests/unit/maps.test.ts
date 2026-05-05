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
  it('refresh() GETs /api/maps and flattens groups into the store', async () => {
    const pristine1 = { name: 'studio_v1', size_bytes: 1024, mtime_unix: 1.0, is_active: true };
    const pristine2 = { name: 'studio_v2', size_bytes: 2048, mtime_unix: 2.0, is_active: false };
    const groupedResp = {
      groups: [
        { base: 'studio_v1', pristine: pristine1, variants: [] },
        { base: 'studio_v2', pristine: pristine2, variants: [] },
      ],
    };
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResp(groupedResp));

    const list = await refresh();

    expect(list).toEqual([pristine1, pristine2]);
    expect(get(maps)).toEqual([pristine1, pristine2]);
    expect(fetchSpy).toHaveBeenCalledOnce();
    const url = fetchSpy.mock.calls[0]![0] as string;
    expect(url).toBe('/api/maps');
  });

  // issue#28.1 — server response is `{groups: MapGroup[]}` only; the
  // legacy `flat` key was hard-removed. Pin: the store derives the
  // flat list from groups (pristine + variants).
  it('refresh() flattens pristine + variants from the grouped response', async () => {
    const pristine = { name: 'studio_v1', size_bytes: 1024, mtime_unix: 1.0, is_active: true };
    const variant = {
      name: 'studio_v1.20260504-1430-wallcal',
      size_bytes: 1024,
      mtime_unix: 2.0,
      is_active: false,
    };
    const groupedResp = {
      groups: [{ base: 'studio_v1', pristine, variants: [variant] }],
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResp(groupedResp));

    const list = await refresh();

    expect(list).toEqual([pristine, variant]);
    expect(get(maps)).toEqual([pristine, variant]);
  });

  it('activate(name) POSTs to /api/maps/<name>/activate and triggers refresh', async () => {
    const p1 = { name: 'studio_v1', size_bytes: 1024, mtime_unix: 1.0, is_active: false };
    const p2 = { name: 'studio_v2', size_bytes: 2048, mtime_unix: 2.0, is_active: true };
    const groupedResp = {
      groups: [
        { base: 'studio_v1', pristine: p1, variants: [] },
        { base: 'studio_v2', pristine: p2, variants: [] },
      ],
    };
    let call = 0;
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      call++;
      if (call === 1) {
        return jsonResp({ ok: true, restart_required: true });
      }
      return jsonResp(groupedResp);
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

    expect(get(maps)).toEqual([p1, p2]);
  });

  it('remove(name) DELETEs /api/maps/<name> and triggers refresh', async () => {
    const p1 = { name: 'studio_v1', size_bytes: 1024, mtime_unix: 1.0, is_active: true };
    const groupedResp = {
      groups: [{ base: 'studio_v1', pristine: p1, variants: [] }],
    };
    let call = 0;
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      call++;
      if (call === 1) {
        return jsonResp({ ok: true });
      }
      return jsonResp(groupedResp);
    });

    await remove('studio_v2');

    const firstUrl = fetchSpy.mock.calls[0]![0] as string;
    expect(firstUrl).toBe('/api/maps/studio_v2');
    const firstInit = fetchSpy.mock.calls[0]![1] as RequestInit;
    expect(firstInit.method).toBe('DELETE');

    expect(get(maps)).toEqual([p1]);
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
