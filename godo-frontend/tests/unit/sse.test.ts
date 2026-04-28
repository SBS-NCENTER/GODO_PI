import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SSEClient } from '../../src/lib/sse';

// --- Minimal EventSource mock ----------------------------------------
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
  // Test-only helpers:
  emit(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>);
  }
  fireError(): void {
    this.onerror?.(new Event('error'));
  }
}

function makeNonExpiredToken(): string {
  // exp 1 day in the future
  const exp = Math.floor(Date.now() / 1000) + 86400;
  const b64url = (s: string) => btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const header = b64url(JSON.stringify({ alg: 'HS256' }));
  const body = b64url(JSON.stringify({ sub: 'x', role: 'admin', iat: 1, exp }));
  return `${header}.${body}.sig`;
}

function makeExpiredToken(): string {
  const b64url = (s: string) => btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const header = b64url(JSON.stringify({ alg: 'HS256' }));
  const body = b64url(JSON.stringify({ sub: 'x', role: 'admin', iat: 1, exp: 100 }));
  return `${header}.${body}.sig`;
}

beforeEach(() => {
  MockEventSource.instances = [];
  // Install mock EventSource.
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

describe('SSEClient', () => {
  it('open() returns false when no token', () => {
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => null,
      onMessage: () => {},
      visibilityHandbrake: false,
    });
    expect(client.open()).toBe(false);
    expect(MockEventSource.instances).toHaveLength(0);
  });

  it('open() returns false when token is expired', () => {
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => makeExpiredToken(),
      onMessage: () => {},
      visibilityHandbrake: false,
    });
    expect(client.open()).toBe(false);
  });

  it('open() opens EventSource with token in URL query', () => {
    const t = makeNonExpiredToken();
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => t,
      onMessage: () => {},
      visibilityHandbrake: false,
    });
    expect(client.open()).toBe(true);
    expect(MockEventSource.instances).toHaveLength(1);
    const es = MockEventSource.instances[0]!;
    expect(es.url).toContain('/api/last_pose/stream');
    expect(es.url).toContain('token=' + encodeURIComponent(t));
  });

  it('parses JSON messages and forwards to onMessage', () => {
    const onMessage = vi.fn();
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => makeNonExpiredToken(),
      onMessage,
      visibilityHandbrake: false,
    });
    client.open();
    MockEventSource.instances[0]!.emit({ x_m: 1.0 });
    expect(onMessage).toHaveBeenCalledWith({ x_m: 1.0 });
  });

  it('drops malformed JSON frames silently', () => {
    const onMessage = vi.fn();
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => makeNonExpiredToken(),
      onMessage,
      visibilityHandbrake: false,
    });
    client.open();
    const es = MockEventSource.instances[0]!;
    // Emit raw garbage rather than going through the JSON helper.
    es.onmessage?.({ data: 'not-json' } as MessageEvent<string>);
    expect(onMessage).not.toHaveBeenCalled();
  });

  it('close() closes the underlying EventSource', () => {
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => makeNonExpiredToken(),
      onMessage: () => {},
      visibilityHandbrake: false,
    });
    client.open();
    expect(MockEventSource.instances[0]!.closed).toBe(false);
    client.close();
    expect(MockEventSource.instances[0]!.closed).toBe(true);
  });

  it('after close(), open() is a no-op', () => {
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => makeNonExpiredToken(),
      onMessage: () => {},
      visibilityHandbrake: false,
    });
    client.open();
    client.close();
    expect(client.open()).toBe(false);
  });

  it('on error with expired token, closes (no reopen)', () => {
    let token = makeNonExpiredToken();
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => token,
      onMessage: () => {},
      visibilityHandbrake: false,
    });
    client.open();
    const es = MockEventSource.instances[0]!;
    // Token expires before next reconnect.
    token = makeExpiredToken();
    es.fireError();
    expect(client.isOpen).toBe(false);
  });

  it('visibility hidden closes the EventSource; visible reopens', () => {
    const t = makeNonExpiredToken();
    const client = new SSEClient({
      path: '/api/last_pose/stream',
      getToken: () => t,
      onMessage: () => {},
      visibilityHandbrake: true,
    });
    client.open();
    const first = MockEventSource.instances[0]!;
    expect(first.closed).toBe(false);

    // Simulate hidden.
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(first.closed).toBe(true);

    // Simulate visible.
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[1]!.closed).toBe(false);
  });
});
