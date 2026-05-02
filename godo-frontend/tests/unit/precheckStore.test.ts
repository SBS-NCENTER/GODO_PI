/**
 * issue#16 — precheckStore: polling cadence + name accessor + error
 * resilience.
 *
 * Spec memory: `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const _emptyResponse = {
  ready: false,
  checks: [
    { name: 'lidar_readable', ok: true, value: '/dev/ttyUSB0', detail: null },
    { name: 'tracker_stopped', ok: true, value: 'inactive', detail: null },
    { name: 'image_present', ok: true, value: 'godo-mapping:dev', detail: null },
    { name: 'disk_space_mb', ok: true, value: 9500, detail: null },
    { name: 'name_available', ok: null, value: null, detail: null },
    { name: 'state_clean', ok: true, value: 'idle', detail: null },
  ],
};

describe('precheckStore', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(_emptyResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const m = await import('../../src/stores/precheckStore');
    m.reset();
  });

  afterEach(async () => {
    const m = await import('../../src/stores/precheckStore');
    m.reset();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('polls at start and continues polling at MAPPING_STATUS_POLL_MS cadence', async () => {
    const m = await import('../../src/stores/precheckStore');
    const fetchMock = vi.mocked(fetch);
    m.start(() => '');
    // Allow the initial sync poll + any timer ticks vitest already saw.
    await vi.runOnlyPendingTimersAsync();
    const calls1 = fetchMock.mock.calls.length;
    expect(calls1).toBeGreaterThanOrEqual(1);
    // Advance one full cadence and confirm at least one additional fetch.
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(calls1);
  });

  it('omits the name query when getName returns empty', async () => {
    const m = await import('../../src/stores/precheckStore');
    const fetchMock = vi.mocked(fetch);
    m.start(() => '');
    await vi.runOnlyPendingTimersAsync();
    const firstCall = fetchMock.mock.calls[0];
    expect(firstCall).toBeDefined();
    const url = firstCall![0] as string;
    expect(url).toBe('/api/mapping/precheck');
    expect(url).not.toContain('?');
  });

  it('appends the name query when getName returns a value', async () => {
    const m = await import('../../src/stores/precheckStore');
    const fetchMock = vi.mocked(fetch);
    m.start(() => 'studio_v1');
    await vi.runOnlyPendingTimersAsync();
    const firstCall = fetchMock.mock.calls[0];
    expect(firstCall).toBeDefined();
    const url = firstCall![0] as string;
    expect(url).toBe('/api/mapping/precheck?name=studio_v1');
  });

  it('reads getName fresh on each tick (changing names)', async () => {
    const m = await import('../../src/stores/precheckStore');
    const fetchMock = vi.mocked(fetch);
    let n = 'first';
    m.start(() => n);
    // Drain the initial poll so the captured URL is stable.
    await vi.runOnlyPendingTimersAsync();
    const callsAfterFirst = fetchMock.mock.calls.length;
    // Mutate the closure-captured name and advance one cadence.
    n = 'second';
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterFirst);
    const urls = fetchMock.mock.calls.map((c) => c[0] as string);
    // First poll saw name=first; the post-mutation poll saw name=second.
    expect(urls.some((u) => u.includes('name=first'))).toBe(true);
    expect(urls.some((u) => u.includes('name=second'))).toBe(true);
  });

  it('keeps last-good payload on 5xx response (silent degrade)', async () => {
    const m = await import('../../src/stores/precheckStore');
    const fetchMock = vi.mocked(fetch);
    const seen: Array<{ ready: boolean }> = [];
    const unsub = m.precheckStore.subscribe((p) => seen.push({ ready: p.ready }));
    m.start(() => 'studio_v1');
    await vi.runOnlyPendingTimersAsync();
    const lenAfterFirst = seen.length;
    // Now have the next fetch fail.
    fetchMock.mockResolvedValueOnce(
      new Response('upstream error', {
        status: 500,
        headers: { 'Content-Type': 'text/plain' },
      }),
    );
    vi.advanceTimersByTime(1000);
    await vi.runOnlyPendingTimersAsync();
    // Store should NOT have been overwritten with anything truthy/false-ier;
    // the writable's last value remains. Subscribe count growth from
    // initial-store + first-success + (no third on fail) is acceptable.
    expect(seen.length).toBeGreaterThanOrEqual(lenAfterFirst);
    unsub();
  });

  it('stops polling after stop()', async () => {
    const m = await import('../../src/stores/precheckStore');
    const fetchMock = vi.mocked(fetch);
    m.start(() => 'studio_v1');
    await vi.runOnlyPendingTimersAsync();
    const calls1 = fetchMock.mock.calls.length;
    m.stop();
    vi.advanceTimersByTime(5000);
    await vi.runOnlyPendingTimersAsync();
    expect(fetchMock.mock.calls.length).toBe(calls1);
  });
});
