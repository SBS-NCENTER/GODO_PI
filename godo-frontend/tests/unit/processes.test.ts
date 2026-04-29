/**
 * Track B-SYSTEM PR-B — `stores/processes.ts` unit tests.
 *
 * Covers:
 *   - refcounted SSE subscribe / unsubscribe
 *   - `_arrival_ms` stamped on every received frame (Mode-A M6)
 *   - duplicate flag propagation
 *   - SPA never sends a filter query parameter (Mode-A S1 fold)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api';
import { auth } from '../../src/stores/auth';

function makeNonExpiredToken(): string {
  // Synthetic JWT shape so `isExpired(token)` returns false (~1 h out).
  const exp = Math.floor(Date.now() / 1000) + 3600;
  const b64url = (s: string) => btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const header = b64url(JSON.stringify({ alg: 'HS256' }));
  const body = b64url(JSON.stringify({ sub: 'ncenter', role: 'admin', iat: 1, exp }));
  return `${header}.${body}.sig`;
}

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  readyState = 0;
  onmessage: ((ev: MessageEvent<string>) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  close(): void {
    this.closed = true;
    this.readyState = 2;
  }
  emit(payload: unknown): void {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(payload) }));
    }
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  // @ts-expect-error — global override for tests
  globalThis.EventSource = MockEventSource;
  Object.defineProperty(window, 'location', {
    value: { hash: '', origin: 'http://localhost' },
    writable: true,
    configurable: true,
  });
  const tok = makeNonExpiredToken();
  api.configureAuth({ getToken: () => tok, onUnauthorized: () => {} });
  auth.set({
    token: tok,
    username: 'ncenter',
    role: 'admin',
    exp: Math.floor(Date.now() / 1000) + 3600,
  });
  globalThis.fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        processes: [],
        duplicate_alert: false,
        published_mono_ns: 0,
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ),
  ) as unknown as typeof globalThis.fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  auth.set(null);
});

async function loadModule() {
  vi.resetModules();
  const mod = await import('../../src/stores/processes');
  mod._resetProcessesForTests();
  return mod;
}

describe('processes store', () => {
  it('opens SSE on first subscribe and closes on last unsub', async () => {
    const mod = await loadModule();
    expect(mod._getSubscriberCountForTests()).toBe(0);

    const unsub = mod.subscribeProcesses(() => undefined);
    expect(mod._getSubscriberCountForTests()).toBe(1);
    // SSE opens synchronously inside subscribeProcesses.
    expect(MockEventSource.instances.length).toBe(1);
    expect(MockEventSource.instances[0].closed).toBe(false);

    unsub();
    expect(mod._getSubscriberCountForTests()).toBe(0);
    expect(MockEventSource.instances[0].closed).toBe(true);
  });

  it('shares one SSE across multiple subscribers (refcounted)', async () => {
    const mod = await loadModule();

    const u1 = mod.subscribeProcesses(() => undefined);
    const u2 = mod.subscribeProcesses(() => undefined);
    expect(mod._getSubscriberCountForTests()).toBe(2);
    expect(MockEventSource.instances.length).toBe(1);

    u1();
    expect(MockEventSource.instances[0].closed).toBe(false);
    u2();
    expect(MockEventSource.instances[0].closed).toBe(true);
  });

  it('stamps _arrival_ms on every received frame (Mode-A M6)', async () => {
    const mod = await loadModule();
    vi.useFakeTimers();
    const t0 = new Date(2026, 0, 1, 12, 0, 0).getTime();
    vi.setSystemTime(t0);

    let captured: { _arrival_ms?: number } | null = null;
    const unsub = mod.subscribeProcesses((s) => (captured = s));
    const es = MockEventSource.instances[0];
    es.emit({
      processes: [],
      duplicate_alert: false,
      published_mono_ns: 1,
    });

    // Advance time and emit again — _arrival_ms should bump.
    vi.advanceTimersByTime(500);
    es.emit({
      processes: [],
      duplicate_alert: false,
      published_mono_ns: 2,
    });

    const c = captured as unknown as { _arrival_ms: number };
    expect(c._arrival_ms).toBe(t0 + 500);

    unsub();
    vi.useRealTimers();
  });

  it('duplicate_alert propagates from wire to store', async () => {
    const mod = await loadModule();
    let captured: { duplicate_alert: boolean } | null = null;
    const unsub = mod.subscribeProcesses((s) => (captured = s));
    const es = MockEventSource.instances[0];
    es.emit({
      processes: [
        {
          name: 'godo_tracker_rt',
          pid: 100,
          user: 'ncenter',
          state: 'S',
          cmdline: ['godo_tracker_rt'],
          cpu_pct: 0,
          rss_mb: 50,
          etime_s: 1,
          category: 'managed',
          duplicate: true,
        },
      ],
      duplicate_alert: true,
      published_mono_ns: 1,
    });
    const c = captured as unknown as { duplicate_alert: boolean };
    expect(c.duplicate_alert).toBe(true);
    unsub();
  });

  it('SSE URL has only the token param — never a filter query (Mode-A S1)', async () => {
    const mod = await loadModule();
    const unsub = mod.subscribeProcesses(() => undefined);
    const es = MockEventSource.instances[0];
    const url = new URL(es.url);
    expect(url.pathname).toBe('/api/system/processes/stream');
    // Only `token` is permitted — defence-in-depth pin against a future
    // writer adding `?filter=foo` to the SSE URL.
    const params = Array.from(url.searchParams.keys());
    expect(params).toEqual(['token']);
    unsub();
  });

  it('drops malformed SSE payloads silently', async () => {
    const mod = await loadModule();
    let count = 0;
    const unsub = mod.subscribeProcesses(() => count++);
    // initial empty state counts as one subscribe-time emission.
    expect(count).toBe(1);
    const es = MockEventSource.instances[0];
    // Wrong shape — no `processes` key.
    es.emit({ ok: true });
    expect(count).toBe(1); // store unchanged
    unsub();
  });
});
