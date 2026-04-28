/**
 * HTTP fetch wrapper with JWT auth + uniform error handling.
 *
 * Behaviour:
 *   - Attaches `Authorization: Bearer <token>` when an auth token is set.
 *   - On 401 → clear the auth store + redirect to `/login` (unless already
 *     on the login page).
 *   - On any non-2xx → throws `ApiError` with `status` + parsed body.
 *   - Honours an `AbortSignal` from the caller; defaults to a 3 s timeout.
 *
 * No retries — operator-triggered actions should fail loudly so the SPA
 * can show a toast. SSE has its own reconnect path (see sse.ts).
 */

import { API_FETCH_TIMEOUT_MS } from './constants';
import { navigate } from './router';

export interface ApiErrorBody {
  ok?: false;
  err?: string;
  detail?: string;
}

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

// Deliberately decoupled from the Svelte store layer so this module can be
// unit-tested without instantiating the auth store. The store wires itself
// into these slots at module load.
let getToken: () => string | null = () => null;
let onUnauthorized: () => void = () => {};

export function configureAuth(opts: {
  getToken: () => string | null;
  onUnauthorized: () => void;
}): void {
  getToken = opts.getToken;
  onUnauthorized = opts.onUnauthorized;
}

function isLoginPage(): boolean {
  if (typeof window === 'undefined') return false;
  return window.location.hash.replace(/^#/, '') === '/login';
}

async function readJsonOrNull(resp: Response): Promise<ApiErrorBody | null> {
  const ctype = resp.headers.get('content-type') || '';
  if (!ctype.includes('application/json')) return null;
  try {
    return (await resp.json()) as ApiErrorBody;
  } catch {
    return null;
  }
}

export async function apiFetch(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<Response> {
  const { timeoutMs = API_FETCH_TIMEOUT_MS, headers, signal, ...rest } = init;

  const headerObj = new Headers(headers || {});
  const token = getToken();
  if (token && !headerObj.has('Authorization')) {
    headerObj.set('Authorization', `Bearer ${token}`);
  }

  // Combine caller's signal (if any) with our timeout.
  const ctrl = new AbortController();
  const timeoutId = setTimeout(() => ctrl.abort(), timeoutMs);
  if (signal) {
    if (signal.aborted) ctrl.abort();
    else signal.addEventListener('abort', () => ctrl.abort(), { once: true });
  }

  let resp: Response;
  try {
    resp = await fetch(path, { ...rest, headers: headerObj, signal: ctrl.signal });
  } catch (e) {
    clearTimeout(timeoutId);
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(0, null, 'request_aborted');
    }
    throw new ApiError(0, null, 'network_error');
  }
  clearTimeout(timeoutId);

  if (resp.status === 401) {
    onUnauthorized();
    if (!isLoginPage()) navigate('/login');
    const body = await readJsonOrNull(resp);
    throw new ApiError(401, body, body?.err || 'unauthorized');
  }
  if (!resp.ok) {
    const body = await readJsonOrNull(resp);
    throw new ApiError(resp.status, body, body?.err || `http_${resp.status}`);
  }
  return resp;
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await apiFetch(path, { ...init, method: 'GET' });
  return (await resp.json()) as T;
}

export async function apiPost<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  if (body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const resp = await apiFetch(path, {
    ...init,
    method: 'POST',
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  // Some endpoints (e.g. binary or empty 200) may not return JSON; coerce.
  const ctype = resp.headers.get('content-type') || '';
  if (!ctype.includes('application/json')) return null as T;
  return (await resp.json()) as T;
}

export async function apiPatch<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const resp = await apiFetch(path, {
    ...init,
    method: 'PATCH',
    headers,
    body: JSON.stringify(body),
  });
  return (await resp.json()) as T;
}
