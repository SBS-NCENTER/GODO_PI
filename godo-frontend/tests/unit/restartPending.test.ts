import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { configureAuth } from '../../src/lib/api';
import { RESTART_PENDING_POLL_MS } from '../../src/lib/constants';
import {
  restartPending,
  refresh,
  reset,
  subscribeRestartPending,
} from '../../src/stores/restartPending';

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
  vi.useRealTimers();
  reset();
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

describe('subscribeRestartPending — issue#8 polling backstop', () => {
  it('fires an immediate fetch when the first subscriber attaches', async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: true });
      return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
    });
    const seen: boolean[] = [];
    const unsub = subscribeRestartPending((s) => seen.push(s.pending));
    // Initial state delivered synchronously; flush microtasks for fetch.
    await vi.advanceTimersByTimeAsync(0);
    expect(get(restartPending)).toEqual({ pending: true, trackerOk: true });
    expect(seen[0]).toBe(false); // initial store value
    expect(seen.at(-1)).toBe(true); // post-fetch value
    expect(fetchSpy).toHaveBeenCalled();
    unsub();
  });

  it('re-fetches at RESTART_PENDING_POLL_MS cadence', async () => {
    vi.useFakeTimers();
    let pendingValue = true;
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: pendingValue });
      return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
    });
    const unsub = subscribeRestartPending(() => {});
    await vi.advanceTimersByTimeAsync(0); // initial fetch
    const initialCalls = fetchSpy.mock.calls.length;
    expect(get(restartPending).pending).toBe(true);

    // Server-side clearance happens between ticks (tracker booted +
    // cleared sentinel). Next polling tick should pick it up.
    pendingValue = false;
    await vi.advanceTimersByTimeAsync(RESTART_PENDING_POLL_MS);
    expect(fetchSpy.mock.calls.length).toBeGreaterThan(initialCalls);
    expect(get(restartPending).pending).toBe(false);
    unsub();
  });

  it('stops polling when the last subscriber detaches', async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
    });
    const unsub = subscribeRestartPending(() => {});
    await vi.advanceTimersByTimeAsync(0);
    const callsAtUnsub = fetchSpy.mock.calls.length;
    unsub();
    // No further fetches after unsub even if the polling interval elapses.
    await vi.advanceTimersByTimeAsync(RESTART_PENDING_POLL_MS * 3);
    expect(fetchSpy.mock.calls.length).toBe(callsAtUnsub);
  });

  it('shares one timer across multiple subscribers', async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
    });
    const unsubA = subscribeRestartPending(() => {});
    const unsubB = subscribeRestartPending(() => {});
    await vi.advanceTimersByTimeAsync(0);
    // Two subscribers, but only one initial fetch round (one /api/system/restart_pending + one /api/health).
    const restartCalls = fetchSpy.mock.calls.filter(
      (c) => String(c[0]) === '/api/system/restart_pending',
    ).length;
    expect(restartCalls).toBe(1);

    // First detach: timer must keep ticking because one subscriber remains.
    unsubA();
    await vi.advanceTimersByTimeAsync(RESTART_PENDING_POLL_MS);
    const restartCallsAfterA = fetchSpy.mock.calls.filter(
      (c) => String(c[0]) === '/api/system/restart_pending',
    ).length;
    expect(restartCallsAfterA).toBeGreaterThan(restartCalls);

    // Second detach: now timer stops.
    unsubB();
    const callsAtFullDetach = fetchSpy.mock.calls.length;
    await vi.advanceTimersByTimeAsync(RESTART_PENDING_POLL_MS * 3);
    expect(fetchSpy.mock.calls.length).toBe(callsAtFullDetach);
  });
});
