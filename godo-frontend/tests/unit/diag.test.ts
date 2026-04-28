import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

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
  emit(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>);
  }
  fireError(): void {
    this.onerror?.(new Event('error'));
  }
}

function makeNonExpiredToken(): string {
  const exp = Math.floor(Date.now() / 1000) + 86400;
  const b64url = (s: string) => btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const header = b64url(JSON.stringify({ alg: 'HS256' }));
  const body = b64url(JSON.stringify({ sub: 'x', role: 'admin', iat: 1, exp }));
  return `${header}.${body}.sig`;
}

function cannedFrame(): Record<string, unknown> {
  return {
    pose: {
      valid: 1,
      x_m: 0,
      y_m: 0,
      yaw_deg: 0,
      xy_std_m: 0,
      yaw_std_deg: 0,
      iterations: 1,
      converged: 1,
      forced: 0,
      published_mono_ns: 1_000_000_000,
    },
    jitter: {
      valid: 1,
      p50_ns: 100,
      p95_ns: 500,
      p99_ns: 1000,
      max_ns: 2000,
      mean_ns: 200,
      sample_count: 1024,
      published_mono_ns: 1_000_000_000,
    },
    amcl_rate: {
      valid: 1,
      hz: 10,
      last_iteration_mono_ns: 1_000_000_000,
      total_iteration_count: 5,
      published_mono_ns: 1_000_000_001,
    },
    resources: {
      cpu_temp_c: 50,
      mem_used_pct: 25,
      mem_total_bytes: 1 << 30,
      mem_avail_bytes: 1 << 29,
      disk_used_pct: 41,
      disk_total_bytes: 1 << 35,
      disk_avail_bytes: 1 << 33,
      published_mono_ns: 1_000_000_002,
    },
  };
}

async function freshImport() {
  vi.resetModules();
  const auth = await import('../../src/stores/auth');
  vi.spyOn(auth, 'getToken').mockReturnValue(makeNonExpiredToken());
  const diag = await import('../../src/stores/diag');
  return { diag };
}

beforeEach(() => {
  sessionStorage.clear();
  MockEventSource.instances = [];
  // @ts-expect-error — global override for tests
  globalThis.EventSource = MockEventSource;
  Object.defineProperty(window, 'location', {
    value: { hash: '', origin: 'http://localhost' },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('diag store', () => {
  it('subscribe returns an unsub function', async () => {
    const { diag } = await freshImport();
    const unsub = diag.subscribeDiag(() => {});
    expect(typeof unsub).toBe('function');
    unsub();
    diag._resetDiagForTests();
  });

  it('sse opens on first subscribe and closes on last unsubscribe', async () => {
    const { diag } = await freshImport();
    const u1 = diag.subscribeDiag(() => {});
    expect(MockEventSource.instances).toHaveLength(1);
    const u2 = diag.subscribeDiag(() => {});
    expect(MockEventSource.instances).toHaveLength(1);
    u1();
    expect(MockEventSource.instances[0]!.closed).toBe(false);
    u2();
    expect(MockEventSource.instances[0]!.closed).toBe(true);
    diag._resetDiagForTests();
  });

  it('does not open SSE when there are no subscribers', async () => {
    const { diag } = await freshImport();
    expect(diag._isSSEOpenForTests()).toBe(false);
    expect(MockEventSource.instances).toHaveLength(0);
    diag._resetDiagForTests();
  });

  it('stamps _arrival_ms on every received frame', async () => {
    const { diag } = await freshImport();
    let received: Record<string, unknown> | null = null;
    const unsub = diag.subscribeDiag((f) => {
      if (f) received = f as unknown as Record<string, unknown>;
    });
    const t0 = Date.now();
    MockEventSource.instances[0]!.emit(cannedFrame());
    expect(received).not.toBeNull();
    const arrival = (received as unknown as { _arrival_ms: number })._arrival_ms;
    expect(arrival).toBeGreaterThanOrEqual(t0);
    expect(arrival).toBeLessThanOrEqual(Date.now());
    unsub();
    diag._resetDiagForTests();
  });

  it('appends to all five sparkline rings on each frame', async () => {
    const { diag } = await freshImport();
    const unsub = diag.subscribeDiag(() => {});
    MockEventSource.instances[0]!.emit(cannedFrame());
    MockEventSource.instances[0]!.emit(cannedFrame());
    const sparks = get(diag.diagSparklines);
    expect(sparks.jitter_p50_ns).toHaveLength(2);
    expect(sparks.jitter_p99_ns).toHaveLength(2);
    expect(sparks.amcl_rate_hz).toHaveLength(2);
    expect(sparks.cpu_temp_c).toHaveLength(2);
    expect(sparks.mem_used_pct).toHaveLength(2);
    unsub();
    diag._resetDiagForTests();
  });

  it('sparkline ring drops oldest at depth', async () => {
    const { diag } = await freshImport();
    const { DIAG_SPARKLINE_DEPTH } = await import('../../src/lib/constants');
    const unsub = diag.subscribeDiag(() => {});
    for (let i = 0; i < DIAG_SPARKLINE_DEPTH + 5; ++i) {
      const f = cannedFrame() as Record<string, unknown>;
      // Stamp a unique p50 per frame so we can assert the dropped end.
      (f.jitter as { p50_ns: number }).p50_ns = i;
      MockEventSource.instances[0]!.emit(f);
    }
    const sparks = get(diag.diagSparklines);
    expect(sparks.jitter_p50_ns).toHaveLength(DIAG_SPARKLINE_DEPTH);
    // Earliest five values were dropped.
    expect(sparks.jitter_p50_ns[0]).toBe(5);
    unsub();
    diag._resetDiagForTests();
  });

  it('starts polling fallback on SSE onerror', async () => {
    vi.useFakeTimers();
    try {
      const { diag } = await freshImport();
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(cannedFrame().pose), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      );
      const unsub = diag.subscribeDiag(() => {});
      MockEventSource.instances[0]!.fireError();
      // Advance fake timers past DIAG_POLL_FALLBACK_MS = 1000.
      await vi.advanceTimersByTimeAsync(1100);
      expect(fetchSpy).toHaveBeenCalled();
      const calledPaths = fetchSpy.mock.calls.map((c) => String(c[0]));
      expect(calledPaths.some((p) => p.includes('/api/last_pose'))).toBe(true);
      unsub();
      diag._resetDiagForTests();
    } finally {
      vi.useRealTimers();
    }
  });

  it('reset clears store + sparklines + subscriber count', async () => {
    const { diag } = await freshImport();
    const unsub = diag.subscribeDiag(() => {});
    MockEventSource.instances[0]!.emit(cannedFrame());
    expect(get(diag.diag)).not.toBeNull();
    diag._resetDiagForTests();
    expect(get(diag.diag)).toBeNull();
    expect(diag._getSubscriberCountForTests()).toBe(0);
    unsub();
  });
});
