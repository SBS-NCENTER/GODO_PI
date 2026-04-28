/**
 * Auth store: holds the current `{token, username, role, exp}` in
 * localStorage + a Svelte writable.
 *
 * Writes from outside this module are limited to:
 *   - `setSession(...)` after a successful login.
 *   - `clearSession()` on logout / 401 / expiry.
 *
 * Read access is via the `auth` writable's `subscribe`. Components MUST NOT
 * write to it directly.
 */

import { writable, type Writable } from 'svelte/store';
import { configureAuth } from '$lib/api';
import { getClaims, isExpired } from '$lib/auth';
import { STORAGE_KEY_TOKEN } from '$lib/constants';
import { ROLE_VIEWER, type Role } from '$lib/protocol';

export interface AuthSession {
  token: string;
  username: string;
  role: Role;
  exp: number;
}

function loadFromStorage(): AuthSession | null {
  if (typeof localStorage === 'undefined') return null;
  const raw = localStorage.getItem(STORAGE_KEY_TOKEN);
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw) as Partial<AuthSession>;
    if (
      typeof obj.token === 'string' &&
      typeof obj.username === 'string' &&
      (obj.role === 'admin' || obj.role === 'viewer') &&
      typeof obj.exp === 'number' &&
      !isExpired(obj.token)
    ) {
      return obj as AuthSession;
    }
  } catch {
    // Fall through; corrupt entry behaves like "no session".
  }
  return null;
}

function persist(session: AuthSession | null): void {
  if (typeof localStorage === 'undefined') return;
  if (session === null) localStorage.removeItem(STORAGE_KEY_TOKEN);
  else localStorage.setItem(STORAGE_KEY_TOKEN, JSON.stringify(session));
}

export const auth: Writable<AuthSession | null> = writable(loadFromStorage());

let _current: AuthSession | null = null;
auth.subscribe((s) => {
  _current = s;
  persist(s);
});

export function setSession(token: string, username: string, role: Role, exp: number): void {
  auth.set({ token, username, role, exp });
}

/**
 * Build session from a freshly-issued token by decoding its claims (no
 * server round-trip). Used when /api/auth/refresh returns just `{token,
 * exp}` and we need to keep `username/role` in sync with the new exp.
 */
export function setSessionFromToken(token: string): void {
  const claims = getClaims(token);
  if (!claims) {
    clearSession();
    return;
  }
  auth.set({
    token,
    username: claims.sub,
    role: claims.role ?? ROLE_VIEWER,
    exp: claims.exp,
  });
}

export function clearSession(): void {
  auth.set(null);
}

export function getToken(): string | null {
  return _current?.token ?? null;
}

// Wire api.ts → auth store. Done at module init so any later apiFetch call
// finds the current token.
configureAuth({
  getToken,
  onUnauthorized: clearSession,
});
