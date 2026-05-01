import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  apiFetch,
  apiGet,
  apiPost,
  apiPostCalibrate,
  configureAuth,
} from '../../src/lib/api';

let onUnauth: ReturnType<typeof vi.fn>;
let token: string | null;

beforeEach(() => {
  token = null;
  onUnauth = vi.fn();
  configureAuth({ getToken: () => token, onUnauthorized: onUnauth });
  // Stub window.location.hash to avoid AbortError side-effects in jsdom.
  Object.defineProperty(window, 'location', {
    value: { hash: '#/', origin: 'http://localhost' },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('apiFetch', () => {
  it('attaches Authorization header when token is set', async () => {
    token = 'tok123';
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    await apiFetch('/api/health');
    const init = fetchSpy.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get('Authorization')).toBe('Bearer tok123');
  });

  it('does not attach Authorization when token is absent', async () => {
    token = null;
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }),
      );
    await apiFetch('/api/health');
    const init = fetchSpy.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get('Authorization')).toBeNull();
  });

  it('on 401 calls onUnauthorized and throws ApiError', async () => {
    token = 'tok';
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: false, err: 'token_invalid' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      }),
    );
    await expect(apiFetch('/api/protected')).rejects.toThrow(ApiError);
    expect(onUnauth).toHaveBeenCalledOnce();
  });

  it('on 5xx throws ApiError with parsed body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: false, err: 'tracker_unreachable' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      }),
    );
    try {
      await apiFetch('/api/health');
      throw new Error('should not reach');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.status).toBe(503);
      expect(err.body?.err).toBe('tracker_unreachable');
    }
  });

  it('on network error throws ApiError with status 0', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('net'));
    try {
      await apiFetch('/api/health');
      throw new Error('should not reach');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.status).toBe(0);
      expect(err.message).toBe('network_error');
    }
  });

  it('apiPost serialises JSON body and sets Content-Type', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    await apiPost('/api/auth/login', { username: 'a', password: 'b' });
    const [, init] = fetchSpy.mock.calls[0]!;
    const headers = (init as RequestInit).headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect((init as RequestInit).body).toBe('{"username":"a","password":"b"}');
  });

  it('apiGet returns parsed JSON', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ webctl: 'ok', tracker: 'ok', mode: 'Idle' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    const data = await apiGet<{ mode: string }>('/api/health');
    expect(data.mode).toBe('Idle');
  });

  it('on 200 with no JSON content-type returns null from apiPost', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('', { status: 200, headers: { 'content-type': 'text/plain' } }),
    );
    const r = await apiPost('/api/calibrate');
    expect(r).toBeNull();
  });

  // --- issue#3 — apiPostCalibrate body / no-body distinction --------
  it('apiPostCalibrate(undefined) emits no body and no Content-Type', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    await apiPostCalibrate();
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe('/api/calibrate');
    expect((init as RequestInit).method).toBe('POST');
    // body undefined → no JSON body in the fetch call.
    expect((init as RequestInit).body).toBeUndefined();
    const headers = (init as RequestInit).headers as Headers;
    expect(headers.get('Content-Type')).toBeNull();
  });

  it('apiPostCalibrate(body) sends JSON body with all-or-none seed fields', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    await apiPostCalibrate({
      seed_x_m: 1.5,
      seed_y_m: -2.25,
      seed_yaw_deg: 90.0,
    });
    const [, init] = fetchSpy.mock.calls[0]!;
    expect((init as RequestInit).body).toBe(
      '{"seed_x_m":1.5,"seed_y_m":-2.25,"seed_yaw_deg":90}',
    );
    const headers = (init as RequestInit).headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('explicit AbortSignal aborts the request', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
          });
        }),
    );
    const ctrl = new AbortController();
    const promise = apiFetch('/api/slow', { signal: ctrl.signal });
    ctrl.abort();
    await expect(promise).rejects.toMatchObject({ status: 0 });
  });
});
