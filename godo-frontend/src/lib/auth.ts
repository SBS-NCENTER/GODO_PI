/**
 * Auth helpers — login / logout / refresh / decode-only token claims.
 *
 * Token storage lives in `stores/auth.ts`; this module is the wire-layer
 * (POST + decode) shared by both the store and any component that needs
 * to display claims without subscribing to the store.
 */

import { apiPost } from './api';
import type { LoginResponse, RefreshResponse, Role } from './protocol';

export interface DecodedClaims {
  sub: string;
  role: Role;
  exp: number;
  iat: number;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  return apiPost<LoginResponse>('/api/auth/login', { username, password });
}

export async function logout(): Promise<void> {
  // Server is stateless JWT — just acknowledges. Caller is expected to
  // clear local storage regardless of the response status.
  try {
    await apiPost<{ ok: true }>('/api/auth/logout');
  } catch {
    // Best-effort; the local clear happens unconditionally upstream.
  }
}

export async function refresh(): Promise<RefreshResponse> {
  return apiPost<RefreshResponse>('/api/auth/refresh');
}

/**
 * Decode-only JWT claim parser. Does NOT verify the signature — the
 * server is the SSOT for trust. Used for "Logged in as X" display.
 *
 * Returns null on a malformed token.
 */
export function getClaims(token: string): DecodedClaims | null {
  if (!token) return null;
  const parts = token.split('.');
  const expectedSegments = 3;
  if (parts.length !== expectedSegments) return null;
  try {
    const payloadB64 = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
    const padded = payloadB64 + '=='.slice(0, (4 - (payloadB64.length % 4)) % 4);
    const json = atob(padded);
    const obj = JSON.parse(json) as Record<string, unknown>;
    if (
      typeof obj.sub === 'string' &&
      (obj.role === 'admin' || obj.role === 'viewer') &&
      typeof obj.exp === 'number' &&
      typeof obj.iat === 'number'
    ) {
      return { sub: obj.sub, role: obj.role, exp: obj.exp, iat: obj.iat };
    }
    return null;
  } catch {
    return null;
  }
}

/** Returns true when the token has expired (or is null/malformed). */
export function isExpired(token: string | null, nowUnixSec?: number): boolean {
  if (!token) return true;
  const claims = getClaims(token);
  if (!claims) return true;
  const now = nowUnixSec ?? Math.floor(Date.now() / 1000);
  return claims.exp <= now;
}
