import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { get } from 'svelte/store';
import { configureAuth } from '../../src/lib/api';
import { config, refresh, set, reset, applyBatch } from '../../src/stores/config';
import Config from '../../src/routes/Config.svelte';
import { auth } from '../../src/stores/auth';
import { systemServices, _resetSystemServicesForTests } from '../../src/stores/systemServices';
import { CONFIG_APPLY_RESULT_MARKER_TTL_MS } from '../../src/lib/constants';

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

// ===========================================================================
// PR-C — applyBatch + Config.svelte Edit-mode state machine + tracker banner
// ===========================================================================

describe('config store — applyBatch (PR-C)', () => {
  it('all-success: 3 keys → 3 ok results, one final refresh', async () => {
    let call = 0;
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url);
      const m = (init as RequestInit | undefined)?.method ?? 'GET';
      calls.push(`${m} ${u}`);
      const c = call++;
      // Initial refresh: schema + current.
      if (c === 0) return jsonResp(FAKE_SCHEMA);
      if (c === 1) return jsonResp(FAKE_CURRENT);
      // 3 PATCHes (all 200), then post-loop refresh (schema + current),
      // then restart-pending refresh.
      if (m === 'PATCH') return jsonResp({ ok: true, reload_class: 'hot' });
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config') return jsonResp(FAKE_CURRENT);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      return jsonResp({});
    });

    await refresh();
    const results = await applyBatch({
      'smoother.deadband_mm': 12.5,
      'network.ue_port': 7000,
      'smoother.deadband_mm_2': 1, // arbitrary 3rd key for shape only
    });
    expect(results.length).toBe(3);
    expect(results.every((r) => r.ok)).toBe(true);
    // 3 PATCHes lined up in order.
    const patchCalls = calls.filter((c) => c.startsWith('PATCH '));
    expect(patchCalls.length).toBe(3);
    // Exactly one /api/config GET fired AFTER the last PATCH (the
    // post-loop refresh). The pre-call refresh fired one earlier.
    const idxs = calls.flatMap((c, i) => (c === 'GET /api/config' ? [i] : []));
    expect(idxs.length).toBeGreaterThanOrEqual(2);
  });

  it('all-failure: 3 keys → 3 fail results carrying detail, refresh still fires', async () => {
    let call = 0;
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url);
      const m = (init as RequestInit | undefined)?.method ?? 'GET';
      calls.push(`${m} ${u}`);
      const c = call++;
      if (c === 0) return jsonResp(FAKE_SCHEMA);
      if (c === 1) return jsonResp(FAKE_CURRENT);
      if (m === 'PATCH') {
        return jsonResp({ ok: false, err: 'bad_value', detail: 'out of range' }, 400);
      }
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config') return jsonResp(FAKE_CURRENT);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      return jsonResp({});
    });

    await refresh();
    const results = await applyBatch({
      'smoother.deadband_mm': 999,
      'network.ue_port': 0,
      'extra.key': 'x',
    });
    expect(results.length).toBe(3);
    expect(results.every((r) => !r.ok)).toBe(true);
    expect(results[0].error).toContain('out of range');
    // The store-level refresh still fired (post-loop GET /api/config).
    const getConfigCalls = calls.filter((c) => c === 'GET /api/config');
    expect(getConfigCalls.length).toBeGreaterThanOrEqual(2);
  });

  it('mixed: A+B succeed, C fails → 2 ok + 1 fail; current reflects partial commit', async () => {
    let call = 0;
    let patchIdx = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url);
      const m = (init as RequestInit | undefined)?.method ?? 'GET';
      const c = call++;
      if (c === 0) return jsonResp(FAKE_SCHEMA);
      if (c === 1) return jsonResp(FAKE_CURRENT);
      if (m === 'PATCH') {
        const idx = patchIdx++;
        // 0: A ok, 1: B ok, 2: C fail.
        if (idx === 2) {
          return jsonResp({ ok: false, err: 'bad_value', detail: 'C failed' }, 400);
        }
        return jsonResp({ ok: true, reload_class: 'hot' });
      }
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config') {
        // Post-loop refresh: A + B at NEW values, C at OLD value.
        return jsonResp({
          'smoother.deadband_mm': 11.0, // A new
          'network.ue_port': 7777, // B new
          // No 'extra.key' → behaves as undefined; this fixture only
          // exercises A+B's commit.
        });
      }
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      return jsonResp({});
    });

    await refresh();
    const results = await applyBatch({
      'smoother.deadband_mm': 11.0,
      'network.ue_port': 7777,
      'extra.key': 'badvalue',
    });
    expect(results.map((r) => r.ok)).toEqual([true, true, false]);
    expect(results[2].error).toContain('C failed');
    const state = get(config);
    expect(state.current['smoother.deadband_mm']).toBe(11.0);
    expect(state.current['network.ue_port']).toBe(7777);
  });

  it('iterates pending in Object.entries(pending) snapshot order', async () => {
    const seenKeys: string[] = [];
    let call = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url);
      const m = (init as RequestInit | undefined)?.method ?? 'GET';
      const c = call++;
      if (c === 0) return jsonResp(FAKE_SCHEMA);
      if (c === 1) return jsonResp(FAKE_CURRENT);
      if (m === 'PATCH') {
        const body = JSON.parse(String((init as RequestInit | undefined)?.body ?? '{}'));
        seenKeys.push(body.key);
        return jsonResp({ ok: true, reload_class: 'hot' });
      }
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config') return jsonResp(FAKE_CURRENT);
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      return jsonResp({});
    });

    await refresh();
    // Build pending in deliberate insertion order.
    const pending: Record<string, number | string> = {};
    pending['network.ue_port'] = 6666;
    pending['smoother.deadband_mm'] = 5.0;
    pending['extra.key'] = 'x';
    await applyBatch(pending);
    expect(seenKeys).toEqual(['network.ue_port', 'smoother.deadband_mm', 'extra.key']);
  });
});

// --- Component-level state-machine + banner cases ---------------------

interface CleanupFn {
  (): void;
}
const cleanups: CleanupFn[] = [];

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
  _resetSystemServicesForTests();
});

function setSession(role: 'admin' | 'viewer'): void {
  auth.set({
    token: 'tok',
    username: 'tester',
    role,
    exp: Math.floor(Date.now() / 1000) + 3600,
  });
}

function pushTrackerService(state: string): void {
  systemServices.set({
    services: [
      {
        name: 'godo-tracker',
        active_state: state,
        sub_state: state === 'active' ? 'running' : 'dead',
        main_pid: state === 'active' ? 1234 : null,
        active_since_unix: state === 'active' ? Math.floor(Date.now() / 1000) : null,
        memory_bytes: null,
        env_redacted: {},
        env_stale: false,
      },
    ],
    _arrival_ms: Date.now(),
    err: null,
  });
}

async function waitFor<T>(getter: () => T | null, label: string, timeoutMs = 1000): Promise<T> {
  const start = Date.now();
  let v = getter();
  while (v === null) {
    if (Date.now() - start > timeoutMs) {
      throw new Error(`waitFor timeout: ${label}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 5));
    flushSync();
    v = getter();
  }
  return v;
}

function mountConfig(): HTMLDivElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(Config, { target, props: {} });
  cleanups.push(() => {
    unmount(component);
    target.remove();
  });
  return target;
}

function stubInitialRefreshOnly(): void {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
    const u = String(url);
    if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
    if (u === '/api/config') return jsonResp(FAKE_CURRENT);
    if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
    if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
    if (u === '/api/system/services') {
      return jsonResp({ services: [] });
    }
    return jsonResp({});
  });
}

describe('Config.svelte — state machine (PR-C)', () => {
  it('view → edit: anonymous viewer cannot click EDIT; admin can', async () => {
    stubInitialRefreshOnly();
    setSession('viewer');

    const target = mountConfig();
    const editBtn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="config-edit"]'),
      'config-edit button',
    );
    expect(editBtn.disabled).toBe(true);

    // Promote to admin → button becomes enabled.
    setSession('admin');
    flushSync();
    expect(editBtn.disabled).toBe(false);

    // Click EDIT → mode flips, Cancel + Apply render in place of EDIT.
    editBtn.click();
    flushSync();
    expect(target.querySelector('[data-testid="config-edit"]')).toBeNull();
    expect(target.querySelector('[data-testid="config-cancel"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="config-apply"]')).not.toBeNull();
  });

  it('cancel with no pending → straight to view, NO confirm dialog', async () => {
    stubInitialRefreshOnly();
    setSession('admin');

    const target = mountConfig();
    const editBtn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="config-edit"]'),
      'config-edit button',
    );
    editBtn.click();
    flushSync();

    const cancelBtn = target.querySelector<HTMLButtonElement>('[data-testid="config-cancel"]')!;
    cancelBtn.click();
    flushSync();

    // No confirm dialog rendered; back to view.
    expect(target.querySelector('[data-testid="confirm-dialog"]')).toBeNull();
    expect(target.querySelector('[data-testid="config-edit"]')).not.toBeNull();
  });

  it('cancel with pending → confirm dialog → confirm clears pending + back to view', async () => {
    stubInitialRefreshOnly();
    setSession('admin');

    const target = mountConfig();
    const editBtn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="config-edit"]'),
      'config-edit button',
    );
    editBtn.click();
    flushSync();

    // Type a value into one input → pending = 1.
    const input = await waitFor<HTMLInputElement>(
      () => target.querySelector<HTMLInputElement>('[data-testid="input-network.ue_port"]'),
      'network.ue_port input',
    );
    input.value = '7000';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();

    // Click Cancel → confirm dialog appears.
    const cancelBtn = target.querySelector<HTMLButtonElement>('[data-testid="config-cancel"]')!;
    cancelBtn.click();
    flushSync();
    const dialog = target.querySelector('[data-testid="confirm-dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.textContent).toContain('1개 변경사항이 폐기됩니다');

    // Click 확인 → dialog closes, mode → view, pending cleared.
    target.querySelector<HTMLButtonElement>('[data-testid="confirm-ok"]')!.click();
    flushSync();
    expect(target.querySelector('[data-testid="confirm-dialog"]')).toBeNull();
    expect(target.querySelector('[data-testid="config-edit"]')).not.toBeNull();
  });

  it('cancel with pending → confirm dialog → 취소 keeps pending + stays in edit', async () => {
    stubInitialRefreshOnly();
    setSession('admin');

    const target = mountConfig();
    const editBtn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="config-edit"]'),
      'config-edit button',
    );
    editBtn.click();
    flushSync();

    const input = await waitFor<HTMLInputElement>(
      () => target.querySelector<HTMLInputElement>('[data-testid="input-network.ue_port"]'),
      'network.ue_port input',
    );
    input.value = '7000';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();

    target.querySelector<HTMLButtonElement>('[data-testid="config-cancel"]')!.click();
    flushSync();
    expect(target.querySelector('[data-testid="confirm-dialog"]')).not.toBeNull();

    // Click 취소 (cancel button inside the dialog) → stays in Edit.
    target.querySelector<HTMLButtonElement>('[data-testid="confirm-cancel"]')!.click();
    flushSync();
    expect(target.querySelector('[data-testid="confirm-dialog"]')).toBeNull();
    expect(target.querySelector('[data-testid="config-cancel"]')).not.toBeNull();
    // Pending is preserved — the input still carries the typed value.
    const inputAfter = target.querySelector<HTMLInputElement>(
      '[data-testid="input-network.ue_port"]',
    )!;
    expect(inputAfter.value).toBe('7000');
  });

  it('apply all-success → auto returns to view; markers fade after TTL', async () => {
    vi.useFakeTimers();
    let patchSeen = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url);
      const m = (init as RequestInit | undefined)?.method ?? 'GET';
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config' && m === 'GET') {
        return jsonResp(
          patchSeen >= 2 ? { ...FAKE_CURRENT, 'network.ue_port': 7000 } : FAKE_CURRENT,
        );
      }
      if (m === 'PATCH') {
        patchSeen++;
        return jsonResp({ ok: true, reload_class: 'hot' });
      }
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      if (u === '/api/system/services') return jsonResp({ services: [] });
      return jsonResp({});
    });

    setSession('admin');
    const target = mountConfig();
    // Allow onMount → refresh() to settle.
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    target.querySelector<HTMLButtonElement>('[data-testid="config-edit"]')!.click();
    flushSync();

    const portInput = target.querySelector<HTMLInputElement>(
      '[data-testid="input-network.ue_port"]',
    )!;
    portInput.value = '7000';
    portInput.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    const dbInput = target.querySelector<HTMLInputElement>(
      '[data-testid="input-smoother.deadband_mm"]',
    )!;
    dbInput.value = '15';
    dbInput.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();

    target.querySelector<HTMLButtonElement>('[data-testid="config-apply"]')!.click();
    // Let the PATCH chain + post-loop refresh resolve.
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    // All ok → back to view.
    expect(target.querySelector('[data-testid="config-edit"]')).not.toBeNull();
    // ✓ markers visible.
    expect(target.querySelector('[data-testid="marker-network.ue_port"]')).not.toBeNull();

    // Advance past the TTL → markers gone.
    await vi.advanceTimersByTimeAsync(CONFIG_APPLY_RESULT_MARKER_TTL_MS + 10);
    flushSync();
    expect(target.querySelector('[data-testid="marker-network.ue_port"]')).toBeNull();
    vi.useRealTimers();
  });

  it('apply partial → stays in edit; failed key remains pending; ✗ + error visible', async () => {
    let patchIdx = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url);
      const m = (init as RequestInit | undefined)?.method ?? 'GET';
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config' && m === 'GET') return jsonResp(FAKE_CURRENT);
      if (m === 'PATCH') {
        const idx = patchIdx++;
        if (idx === 1) {
          return jsonResp({ ok: false, err: 'bad_value', detail: 'port out of range' }, 400);
        }
        return jsonResp({ ok: true, reload_class: 'hot' });
      }
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      if (u === '/api/system/services') return jsonResp({ services: [] });
      return jsonResp({});
    });

    setSession('admin');
    const target = mountConfig();
    const editBtn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="config-edit"]'),
      'config-edit button',
    );
    editBtn.click();
    flushSync();
    // Wait for the table rows to render (initial refresh resolves async).
    const dbInput = await waitFor<HTMLInputElement>(
      () => target.querySelector<HTMLInputElement>('[data-testid="input-smoother.deadband_mm"]'),
      'smoother.deadband_mm input',
    );
    // Type into both inputs; A succeeds, B fails.
    dbInput.value = '12';
    dbInput.dispatchEvent(new Event('input', { bubbles: true }));
    const portInput = target.querySelector<HTMLInputElement>(
      '[data-testid="input-network.ue_port"]',
    )!;
    portInput.value = '99999';
    portInput.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();

    target.querySelector<HTMLButtonElement>('[data-testid="config-apply"]')!.click();
    // Let the chain resolve.
    await new Promise((r) => setTimeout(r, 30));
    flushSync();

    // Stay in Edit (failure present).
    expect(target.querySelector('[data-testid="config-edit"]')).toBeNull();
    expect(target.querySelector('[data-testid="config-cancel"]')).not.toBeNull();
    // Failed row shows ✗ + the error detail.
    expect(target.querySelector('[data-testid="marker-network.ue_port"]')!.textContent).toContain(
      '✗',
    );
    expect(target.querySelector('[data-testid="error-network.ue_port"]')!.textContent).toContain(
      'port out of range',
    );
    // Failed key remained as pending text in the input.
    const portAfter = target.querySelector<HTMLInputElement>(
      '[data-testid="input-network.ue_port"]',
    )!;
    expect(portAfter.value).toBe('99999');
  });
});

describe('Config.svelte — tracker-inactive banner (PR-C)', () => {
  it('tracker active → no banner', async () => {
    stubInitialRefreshOnly();
    setSession('viewer');
    const target = mountConfig();
    await waitFor(() => target.querySelector('[data-testid="config-edit"]'), 'config page header');
    pushTrackerService('active');
    flushSync();
    expect(target.querySelector('[data-testid="config-tracker-banner"]')).toBeNull();
  });

  it('tracker inactive → banner with the canonical Korean string', async () => {
    stubInitialRefreshOnly();
    setSession('viewer');
    const target = mountConfig();
    await waitFor(() => target.querySelector('[data-testid="config-edit"]'), 'config page header');
    pushTrackerService('inactive');
    flushSync();
    const banner = target.querySelector('[data-testid="config-tracker-banner"]');
    expect(banner).not.toBeNull();
    expect(banner!.textContent).toContain('godo-tracker가 실행 중일 때');
  });

  it('tracker reactivation → banner disappears + refresh fires', async () => {
    let getConfigCount = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config') {
        getConfigCount++;
        return jsonResp(FAKE_CURRENT);
      }
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      if (u === '/api/system/services') return jsonResp({ services: [] });
      return jsonResp({});
    });

    setSession('viewer');
    const target = mountConfig();
    await waitFor(() => target.querySelector('[data-testid="config-edit"]'), 'config page header');
    // Step 1: tracker inactive → banner shows.
    pushTrackerService('inactive');
    flushSync();
    expect(target.querySelector('[data-testid="config-tracker-banner"]')).not.toBeNull();
    const beforeCount = getConfigCount;

    // Step 2: tracker flips to active → banner disappears + refresh fires.
    pushTrackerService('active');
    // Allow the async refresh() to dispatch.
    await new Promise((r) => setTimeout(r, 0));
    flushSync();
    expect(target.querySelector('[data-testid="config-tracker-banner"]')).toBeNull();
    expect(getConfigCount).toBeGreaterThan(beforeCount);
  });
});

describe('Config.svelte — schema default + Cancel-after-partial walkthrough (PR-C)', () => {
  it('renders (default: <value>) hint under each row', async () => {
    stubInitialRefreshOnly();
    setSession('viewer');
    const target = mountConfig();
    const hint = await waitFor<HTMLElement>(
      () => target.querySelector<HTMLElement>('[data-testid="default-network.ue_port"]'),
      'default hint for network.ue_port',
    );
    expect(hint.textContent).toContain('(default:');
    expect(hint.textContent).toContain('6666');
  });

  // Continuation of "apply partial → stays in edit": the operator now
  // clicks Cancel; pending = {C} so the confirm dialog asks "1개 변경
  // 사항이 폐기됩니다"; clicking 확인 clears pending + goes back to View.
  // Crucially, Cancel does NOT fire a PATCH (memory: "Why Cancel is
  // client-side only").
  it('cancel-after-partial-apply: discards remaining pending, no PATCH fired', async () => {
    let patchIdx = 0;
    let patchAfterApply = 0;
    let firstApplyDone = false;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url);
      const m = (init as RequestInit | undefined)?.method ?? 'GET';
      if (u === '/api/config/schema') return jsonResp(FAKE_SCHEMA);
      if (u === '/api/config' && m === 'GET') return jsonResp(FAKE_CURRENT);
      if (m === 'PATCH') {
        if (firstApplyDone) patchAfterApply++;
        const idx = patchIdx++;
        if (idx === 1) {
          return jsonResp({ ok: false, err: 'bad_value', detail: 'fail' }, 400);
        }
        return jsonResp({ ok: true, reload_class: 'hot' });
      }
      if (u === '/api/system/restart_pending') return jsonResp({ pending: false });
      if (u === '/api/health') return jsonResp({ webctl: 'ok', tracker: 'ok', mode: 'Idle' });
      if (u === '/api/system/services') return jsonResp({ services: [] });
      return jsonResp({});
    });

    setSession('admin');
    const target = mountConfig();
    const editBtn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="config-edit"]'),
      'config-edit button',
    );
    editBtn.click();
    flushSync();

    const dbInput = await waitFor<HTMLInputElement>(
      () => target.querySelector<HTMLInputElement>('[data-testid="input-smoother.deadband_mm"]'),
      'smoother.deadband_mm input',
    );
    dbInput.value = '12';
    dbInput.dispatchEvent(new Event('input', { bubbles: true }));
    const portInput = target.querySelector<HTMLInputElement>(
      '[data-testid="input-network.ue_port"]',
    )!;
    portInput.value = '99999';
    portInput.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();

    target.querySelector<HTMLButtonElement>('[data-testid="config-apply"]')!.click();
    await new Promise((r) => setTimeout(r, 30));
    flushSync();
    firstApplyDone = true;

    // Sanity: still in Edit, failed key still pending.
    expect(target.querySelector('[data-testid="config-cancel"]')).not.toBeNull();

    // Click Cancel → confirm dialog (pending=1 since A was committed).
    target.querySelector<HTMLButtonElement>('[data-testid="config-cancel"]')!.click();
    flushSync();
    const dialog = target.querySelector('[data-testid="confirm-dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.textContent).toContain('1개 변경사항이 폐기됩니다');

    target.querySelector<HTMLButtonElement>('[data-testid="confirm-ok"]')!.click();
    flushSync();

    // Back to View; no NEW PATCH fired during the cancel flow.
    expect(target.querySelector('[data-testid="config-edit"]')).not.toBeNull();
    expect(patchAfterApply).toBe(0);
  });
});
