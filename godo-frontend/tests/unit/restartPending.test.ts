import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { configureAuth } from '../../src/lib/api';
import { restartPending, refresh, reset } from '../../src/stores/restartPending';

beforeEach(() => {
  configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
  reset();
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

describe('restartPending store', () => {
  it('sets pending=true and trackerOk=true when both endpoints agree', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: true });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      throw new Error('unexpected url');
    });
    await refresh();
    expect(get(restartPending)).toEqual({ pending: true, trackerOk: true });
  });

  it('sets trackerOk=false when /api/health says tracker unreachable', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: true });
      return jsonResp({ webctl: 'ok', tracker: 'unreachable', mode: null });
    });
    await refresh();
    expect(get(restartPending)).toEqual({ pending: true, trackerOk: false });
  });

  it('sets pending=false when the flag endpoint says false', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
    });
    await refresh();
    expect(get(restartPending)).toEqual({ pending: false, trackerOk: true });
  });

  it('falls back to pending=false + trackerOk=false on dual API error', async () => {
    // Pre-seed the store with pending=true.
    restartPending.set({ pending: true, trackerOk: true });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      // ApiError-shaped 5xx: webctl returned a JSON error body.
      return new Response(JSON.stringify({ ok: false, err: 'down' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      });
    });
    await refresh();
    // Both endpoints failed → flag is reset to "not pending" + tracker
    // marked unreachable. Banner will not render in that case.
    expect(get(restartPending)).toEqual({ pending: false, trackerOk: false });
  });
});
