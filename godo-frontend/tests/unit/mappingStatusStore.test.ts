/**
 * issue#14 — mappingStatus store: subscribe/unsubscribe lifecycle +
 * polling cadence + transitions.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MAPPING_STATE_IDLE, MAPPING_STATE_RUNNING } from '../../src/lib/protocol';

describe('mappingStatus store', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          state: MAPPING_STATE_IDLE,
          map_name: null,
          container_id_short: null,
          started_at: null,
          error_detail: null,
          journal_tail_available: false,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    // Reset module state between tests.
    const m = await import('../../src/stores/mappingStatus');
    m.reset();
  });

  afterEach(async () => {
    const m = await import('../../src/stores/mappingStatus');
    m.reset();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('starts polling on first subscribe and emits idle frame', async () => {
    const m = await import('../../src/stores/mappingStatus');
    const seen: string[] = [];
    const unsub = m.subscribeMappingStatus((s) => seen.push(s.state));
    // Wait for first poll's microtask + macrotask.
    await vi.runOnlyPendingTimersAsync();
    expect(seen).toContain(MAPPING_STATE_IDLE);
    unsub();
  });

  it('updates store when fetch returns running state', async () => {
    const m = await import('../../src/stores/mappingStatus');
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          state: MAPPING_STATE_RUNNING,
          map_name: 'studio_v1',
          container_id_short: 'abc',
          started_at: '2026-05-01T15:00:00Z',
          error_detail: null,
          journal_tail_available: false,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const seen: string[] = [];
    const unsub = m.subscribeMappingStatus((s) => seen.push(s.state));
    await vi.runOnlyPendingTimersAsync();
    expect(seen).toContain(MAPPING_STATE_RUNNING);
    unsub();
  });

  it('stops polling when last subscriber drops', async () => {
    const m = await import('../../src/stores/mappingStatus');
    const fetchMock = vi.mocked(fetch);
    const unsub = m.subscribeMappingStatus(() => {});
    await vi.runOnlyPendingTimersAsync();
    const calls1 = fetchMock.mock.calls.length;
    unsub();
    // Advance the polling interval — no new fetches expected.
    vi.advanceTimersByTime(5000);
    await vi.runOnlyPendingTimersAsync();
    const calls2 = fetchMock.mock.calls.length;
    expect(calls2).toBe(calls1);
  });
});
