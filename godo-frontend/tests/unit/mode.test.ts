import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { configureAuth } from '../../src/lib/api';
import { HEALTH_POLL_MS } from '../../src/lib/constants';
import { mode, refreshMode, reset, subscribeMode, trackerOk } from '../../src/stores/mode';

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

describe('mode store — subscribe + polling', () => {
  it('starts polling on first subscribe and updates trackerOk + mode', async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' }),
    );
    const unsub = subscribeMode(() => {});
    await vi.advanceTimersByTimeAsync(0);
    expect(get(trackerOk)).toBe(true);
    expect(get(mode)).toBe('Idle');
    unsub();
  });

  it('sets trackerOk=false + mode=null on /api/health network error', async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      throw new Error('network down');
    });
    const unsub = subscribeMode(() => {});
    await vi.advanceTimersByTimeAsync(0);
    expect(get(trackerOk)).toBe(false);
    expect(get(mode)).toBeNull();
    unsub();
  });
});

describe('refreshMode — issue#9 action-driven hook', () => {
  it('fires an immediate /api/health fetch on call', async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' }),
    );
    // No subscribers yet — refreshMode should still fire one fetch.
    await refreshMode();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(get(trackerOk)).toBe(true);
  });

  it('flips trackerOk false→true within HTTP RTT, not polling cadence', async () => {
    vi.useFakeTimers();
    let trackerState: 'ok' | 'unreachable' = 'unreachable';
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      jsonResp({ webctl: 'ok', tracker: trackerState, mode: trackerState === 'ok' ? 'Idle' : null }),
    );
    const unsub = subscribeMode(() => {});
    await vi.advanceTimersByTimeAsync(0);
    expect(get(trackerOk)).toBe(false);

    // Backend tracker comes up.
    trackerState = 'ok';

    // Without refreshMode the SPA would wait up to HEALTH_POLL_MS for
    // the next polling tick. Instead, simulate the action handler:
    await refreshMode();
    expect(get(trackerOk)).toBe(true);
    unsub();
  });

  it('resets polling interval phase so next tick is HEALTH_POLL_MS after refresh', async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' }),
    );
    const unsub = subscribeMode(() => {});
    await vi.advanceTimersByTimeAsync(0);
    // Half the polling cadence — original phase would have fired
    // a regular tick at HEALTH_POLL_MS from mount. We are at +50%.
    await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS / 2);
    const callsBeforeRefresh = fetchSpy.mock.calls.length;

    // Refresh now resets the phase.
    await refreshMode();
    const callsAfterRefresh = fetchSpy.mock.calls.length;
    expect(callsAfterRefresh).toBe(callsBeforeRefresh + 1);

    // Just under one full cadence later — no new tick should have
    // fired yet because the phase is now anchored to the refresh.
    await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS - 1);
    expect(fetchSpy.mock.calls.length).toBe(callsAfterRefresh);

    // Cross the cadence boundary — exactly one tick fires.
    await vi.advanceTimersByTimeAsync(2);
    expect(fetchSpy.mock.calls.length).toBe(callsAfterRefresh + 1);
    unsub();
  });

  it('works even with no active subscribers (does not start a timer)', async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' }),
    );
    await refreshMode();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    // No interval was started — advancing time should not produce
    // additional fetches.
    await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS * 5);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
