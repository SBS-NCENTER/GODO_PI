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

function cannedScan(): Record<string, unknown> {
  return {
    valid: 1,
    forced: 0,
    pose_valid: 1,
    iterations: 5,
    published_mono_ns: 1_000_000_000,
    pose_x_m: 0,
    pose_y_m: 0,
    pose_yaw_deg: 0,
    n: 1,
    angles_deg: [0],
    ranges_m: [1],
  };
}

async function freshImport() {
  vi.resetModules();
  // Stub out the auth store's getToken so SSEClient.open() succeeds.
  const auth = await import('../../src/stores/auth');
  vi.spyOn(auth, 'getToken').mockReturnValue(makeNonExpiredToken());
  const overlay = await import('../../src/stores/scanOverlay');
  const scan = await import('../../src/stores/lastScan');
  return { overlay, scan };
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

describe('lastScan store', () => {
  it('subscribe returns an unsub function', async () => {
    const { scan } = await freshImport();
    const unsub = scan.subscribeLastScan(() => {});
    expect(typeof unsub).toBe('function');
    unsub();
    scan._resetLastScanForTests();
  });

  it('does not start SSE while overlay is off', async () => {
    const { scan } = await freshImport();
    // Overlay defaults off; subscribing must NOT open an EventSource.
    const unsub = scan.subscribeLastScan(() => {});
    expect(MockEventSource.instances).toHaveLength(0);
    unsub();
    scan._resetLastScanForTests();
  });

  it('starts SSE when overlay flips to on with a live subscriber', async () => {
    const { overlay, scan } = await freshImport();
    const unsub = scan.subscribeLastScan(() => {});
    expect(MockEventSource.instances).toHaveLength(0);
    overlay.setScanOverlay(true);
    expect(MockEventSource.instances).toHaveLength(1);
    unsub();
    scan._resetLastScanForTests();
  });

  it('stops SSE when overlay flips back to off', async () => {
    const { overlay, scan } = await freshImport();
    const unsub = scan.subscribeLastScan(() => {});
    overlay.setScanOverlay(true);
    expect(MockEventSource.instances[0]!.closed).toBe(false);
    overlay.setScanOverlay(false);
    expect(MockEventSource.instances[0]!.closed).toBe(true);
    unsub();
    scan._resetLastScanForTests();
  });

  it('stamps _arrival_ms on every received frame (Mode-A M2)', async () => {
    const { overlay, scan } = await freshImport();
    let received: Record<string, unknown> | null = null;
    const unsub = scan.subscribeLastScan((s) => {
      if (s) received = s as unknown as Record<string, unknown>;
    });
    overlay.setScanOverlay(true);
    const t0 = Date.now();
    MockEventSource.instances[0]!.emit(cannedScan());
    expect(received).not.toBeNull();
    const arrival = (received as unknown as { _arrival_ms: number })._arrival_ms;
    expect(arrival).toBeGreaterThanOrEqual(t0);
    expect(arrival).toBeLessThanOrEqual(Date.now());
    unsub();
    scan._resetLastScanForTests();
  });

  it('multiple subscribers share one SSE; closes on last unsub', async () => {
    const { overlay, scan } = await freshImport();
    overlay.setScanOverlay(true);
    const u1 = scan.subscribeLastScan(() => {});
    const u2 = scan.subscribeLastScan(() => {});
    expect(MockEventSource.instances).toHaveLength(1);
    u1();
    expect(MockEventSource.instances[0]!.closed).toBe(false);
    u2();
    expect(MockEventSource.instances[0]!.closed).toBe(true);
    scan._resetLastScanForTests();
  });

  it('starts polling fallback on SSE onerror', async () => {
    vi.useFakeTimers();
    try {
      const { overlay, scan } = await freshImport();
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(cannedScan()), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      );
      const unsub = scan.subscribeLastScan(() => {});
      overlay.setScanOverlay(true);
      // Trigger an error event on the underlying ES.
      MockEventSource.instances[0]!.fireError();
      // Advance fake timers past LAST_SCAN_POLL_FALLBACK_MS = 1000.
      await vi.advanceTimersByTimeAsync(1100);
      expect(fetchSpy).toHaveBeenCalled();
      const url = fetchSpy.mock.calls[0]![0];
      expect(String(url)).toContain('/api/last_scan');
      unsub();
      scan._resetLastScanForTests();
    } finally {
      vi.useRealTimers();
    }
  });

  it('store reset clears any cached scan', async () => {
    const { overlay, scan } = await freshImport();
    const unsub = scan.subscribeLastScan(() => {});
    overlay.setScanOverlay(true);
    MockEventSource.instances[0]!.emit(cannedScan());
    expect(get(scan.lastScan)).not.toBeNull();
    scan._resetLastScanForTests();
    expect(get(scan.lastScan)).toBeNull();
    unsub();
  });
});
