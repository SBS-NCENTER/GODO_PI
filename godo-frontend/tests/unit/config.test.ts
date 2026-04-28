import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { configureAuth } from '../../src/lib/api';
import { config, refresh, set, reset } from '../../src/stores/config';

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

const FAKE_SCHEMA = [
  {
    name: 'smoother.deadband_mm',
    type: 'double',
    min: 0,
    max: 200,
    default: '10.0',
    reload_class: 'hot',
    description: 'Deadband on translation (mm).',
  },
  {
    name: 'network.ue_port',
    type: 'int',
    min: 1,
    max: 65535,
    default: '6666',
    reload_class: 'restart',
    description: 'UE receiver UDP port.',
  },
];

const FAKE_CURRENT = {
  'smoother.deadband_mm': 10.0,
  'network.ue_port': 6666,
};

describe('config store', () => {
  it('refresh() parallel-fetches schema + current and updates the store', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config') return jsonResp(FAKE_CURRENT);
      throw new Error('unexpected url ' + u);
    });

    await refresh();

    const state = get(config);
    expect(state.schema).toEqual(FAKE_SCHEMA);
    expect(state.current).toEqual(FAKE_CURRENT);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('set() optimistic-updates then refetches /api/config on success', async () => {
    let call = 0;
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url);
      calls.push(`${(init as RequestInit | undefined)?.method ?? 'GET'} ${u}`);
      const c = call++;
      if (c === 0) return jsonResp(FAKE_SCHEMA); // refresh: schema
      if (c === 1) return jsonResp(FAKE_CURRENT); // refresh: current
      if (c === 2) return jsonResp({ ok: true, reload_class: 'hot' }); // PATCH
      if (c === 3) {
        // refetch /api/config after PATCH
        return jsonResp({ ...FAKE_CURRENT, 'smoother.deadband_mm': 12.5 });
      }
      // restartPending refresh fires `/api/system/restart_pending` +
      // `/api/health` after PATCH success — return the canned shape.
      const lastUrl = String(calls[calls.length - 1]).split(' ')[1];
      if (lastUrl === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (lastUrl === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      return jsonResp({});
    });

    await refresh();
    const result = await set('smoother.deadband_mm', 12.5);

    expect(result).toEqual({ ok: true, reload_class: 'hot' });
    const state = get(config);
    expect(state.current['smoother.deadband_mm']).toBe(12.5);
    expect(state.errors['smoother.deadband_mm'] || '').toBe('');
    // The first 4 calls happen synchronously inside `set()`; the
    // restart-pending refresh is fire-and-forget so we just check
    // that PATCH + refetch landed.
    const head = calls.slice(0, 4);
    expect(head).toEqual([
      'GET /api/config/schema',
      'GET /api/config',
      'PATCH /api/config',
      'GET /api/config',
    ]);
  });

  it('set() rolls back optimistic value + records error on PATCH 400', async () => {
    let call = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      const c = call++;
      if (c === 0) return jsonResp(FAKE_SCHEMA);
      if (c === 1) return jsonResp(FAKE_CURRENT);
      // PATCH → 400
      return jsonResp({ ok: false, err: 'bad_value', detail: 'out of range' }, 400);
    });

    await refresh();
    await expect(set('smoother.deadband_mm', 9999)).rejects.toThrow();

    const state = get(config);
    // Rolled back to the pre-set value.
    expect(state.current['smoother.deadband_mm']).toBe(10.0);
    // Error text from tracker's `detail`.
    expect(state.errors['smoother.deadband_mm']).toContain('out of range');
  });

  it('set() handles network error gracefully (rollback + error message)', async () => {
    let call = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      const c = call++;
      if (c === 0) return jsonResp(FAKE_SCHEMA);
      if (c === 1) return jsonResp(FAKE_CURRENT);
      // PATCH → throw (network down)
      throw new TypeError('network failure');
    });

    await refresh();
    await expect(set('smoother.deadband_mm', 12.5)).rejects.toThrow();
    const state = get(config);
    expect(state.current['smoother.deadband_mm']).toBe(10.0);
    expect(state.errors['smoother.deadband_mm']).not.toBe('');
  });
});
