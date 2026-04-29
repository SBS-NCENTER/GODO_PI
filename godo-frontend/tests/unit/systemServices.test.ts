/**
 * Unit tests for `stores/systemServices.ts` — refcounted polling store.
 *
 * T4 fold: poll cadence assertion uses `vi.useFakeTimers()` and asserts
 * EXACTLY 4 fetches in 3500 ms (1 immediate + 3 ticks at 1000/2000/3000
 * ms). NOT `≥4`.
 *
 * T5 fold: clears_timer_on_unmount asserts `vi.getTimerCount() === 0`
 * after the last subscriber unsubscribes.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let originalFetch: typeof globalThis.fetch;

import('../../src/stores/systemServices').then(() => undefined);

beforeEach(() => {
  originalFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.useRealTimers();
});

async function loadModule() {
  vi.resetModules();
  const mod = await import('../../src/stores/systemServices');
  mod._resetSystemServicesForTests();
  return mod;
}

function mockFetchSuccess() {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        services: [
          {
            name: 'godo-tracker',
            active_state: 'active',
            sub_state: 'running',
            main_pid: 1234,
            active_since_unix: 1714397472,
            memory_bytes: 53477376,
            env_redacted: { GODO_LOG_DIR: '/var/log/godo', JWT_SECRET: '<redacted>' },
          },
        ],
      }),
      {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      },
    ),
  );
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  return fetchMock;
}

describe('systemServices store', () => {
  it('opens polling on first subscribe and stops on last unsub', async () => {
    const mod = await loadModule();
    const fetchMock = mockFetchSuccess();
    vi.useFakeTimers();

    expect(mod._getSubscriberCountForTests()).toBe(0);

    const unsub = mod.subscribeSystemServices(() => undefined);
    expect(mod._getSubscriberCountForTests()).toBe(1);
    // Immediate fetch — flush microtasks only (don't advance setInterval).
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    unsub();
    expect(mod._getSubscriberCountForTests()).toBe(0);
  });

  it('polls /api/system/services at 1 Hz — exactly 4 fetches in 3500 ms (T4 fold)', async () => {
    const mod = await loadModule();
    const fetchMock = mockFetchSuccess();
    vi.useFakeTimers();

    const unsub = mod.subscribeSystemServices(() => undefined);
    // Immediate fetch counts as #1.
    await vi.advanceTimersByTimeAsync(0);
    // Advance 3500 ms → 3 more ticks at 1000 / 2000 / 3000.
    await vi.advanceTimersByTimeAsync(3500);

    expect(fetchMock).toHaveBeenCalledTimes(4);

    unsub();
  });

  it('clears the timer on unmount (T5 fold — getTimerCount === 0)', async () => {
    const mod = await loadModule();
    mockFetchSuccess();
    vi.useFakeTimers();

    const unsub = mod.subscribeSystemServices(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    unsub();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('stamps _arrival_ms on every successful fetch', async () => {
    const mod = await loadModule();
    mockFetchSuccess();
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 0, 1, 12, 0, 0));

    let captured: ReturnType<typeof mod.get<typeof mod.systemServices>> | null = null;
    const unsub = mod.subscribeSystemServices((s) => (captured = s));
    await vi.advanceTimersByTimeAsync(0);

    // typescript: captured is now the populated state.
    const c = captured as unknown as { _arrival_ms: number | null; services: unknown[] };
    expect(c._arrival_ms).not.toBeNull();
    expect(c.services.length).toBe(1);

    unsub();
  });

  it('preserves last-good services list on fetch error', async () => {
    const mod = await loadModule();
    // First call succeeds, second errors out.
    let calls = 0;
    const fetchMock = vi.fn().mockImplementation(() => {
      calls++;
      if (calls === 1) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              services: [
                {
                  name: 'godo-tracker',
                  active_state: 'active',
                  sub_state: 'running',
                  main_pid: 1,
                  active_since_unix: 0,
                  memory_bytes: 0,
                  env_redacted: {},
                },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ ok: false, err: 'boom' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
    vi.useFakeTimers();

    let captured: { services: unknown[]; err: string | null } | null = null;
    const unsub = mod.subscribeSystemServices((s) => (captured = s as unknown as typeof captured));
    await vi.advanceTimersByTimeAsync(0); // first fetch
    await vi.advanceTimersByTimeAsync(1000); // second fetch — errors

    const c = captured as unknown as { services: unknown[]; err: string | null };
    expect(c.services.length).toBe(1); // last-good preserved
    expect(c.err).not.toBeNull();

    unsub();
  });
});
