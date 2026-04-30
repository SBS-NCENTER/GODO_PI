/**
 * Track B-SYSTEM PR-B — `stores/resourcesExtended.ts` unit tests.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api';
import { auth } from '../../src/stores/auth';

function makeNonExpiredToken(): string {
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
  // @ts-expect-error — global override
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
        cpu_per_core: [],
        cpu_aggregate_pct: 0,
        mem_total_mb: null,
        mem_used_mb: null,
        disk_pct: null,
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
  const mod = await import('../../src/stores/resourcesExtended');
  mod._resetResourcesExtendedForTests();
  return mod;
}

describe('resourcesExtended store', () => {
  it('refcounted SSE — open on first sub, close on last unsub', async () => {
    const mod = await loadModule();
    const u1 = mod.subscribeResourcesExtended(() => undefined);
    const u2 = mod.subscribeResourcesExtended(() => undefined);
    expect(MockEventSource.instances.length).toBe(1);
    u1();
    expect(MockEventSource.instances[0].closed).toBe(false);
    u2();
    expect(MockEventSource.instances[0].closed).toBe(true);
  });

  it('stamps _arrival_ms on every successful frame (Mode-A M6)', async () => {
    const mod = await loadModule();
    vi.useFakeTimers();
    const t0 = new Date(2026, 0, 1, 12, 0, 0).getTime();
    vi.setSystemTime(t0);

    let captured: { _arrival_ms?: number; cpu_per_core: number[] } | null = null;
    const unsub = mod.subscribeResourcesExtended((s) => (captured = s));
    const es = MockEventSource.instances[0];
    es.emit({
      cpu_per_core: [10, 20, 30, 40],
      cpu_aggregate_pct: 25,
      mem_total_mb: 8000,
      mem_used_mb: 2000,
      disk_pct: 50,
      published_mono_ns: 1,
    });
    const c = captured as unknown as { _arrival_ms: number; cpu_per_core: number[] };
    expect(c._arrival_ms).toBe(t0);
    expect(c.cpu_per_core).toEqual([10, 20, 30, 40]);

    unsub();
    vi.useRealTimers();
  });

  it('nullable numeric fields render as null (no crash)', async () => {
    const mod = await loadModule();
    let captured: { mem_total_mb: number | null } | null = null;
    const unsub = mod.subscribeResourcesExtended((s) => (captured = s));
    const es = MockEventSource.instances[0];
    es.emit({
      cpu_per_core: [],
      cpu_aggregate_pct: 0,
      mem_total_mb: null,
      mem_used_mb: null,
      disk_pct: null,
      published_mono_ns: 1,
    });
    const c = captured as unknown as { mem_total_mb: number | null };
    expect(c.mem_total_mb).toBeNull();
    unsub();
  });

  it('drops malformed payloads silently', async () => {
    const mod = await loadModule();
    let count = 0;
    const unsub = mod.subscribeResourcesExtended(() => count++);
    expect(count).toBe(1); // initial state
    const es = MockEventSource.instances[0];
    es.emit({ ok: true }); // wrong shape
    expect(count).toBe(1);
    unsub();
  });
});
