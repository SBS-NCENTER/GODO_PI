import { beforeEach, describe, expect, it } from 'vitest';
import { getClaims, isExpired } from '../../src/lib/auth';

// Build a minimal JWT-shaped string. We do NOT need a valid signature —
// `getClaims` is decode-only.
function makeToken(payload: Record<string, unknown>): string {
  const b64url = (s: string) => btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body = b64url(JSON.stringify(payload));
  return `${header}.${body}.fake-sig`;
}

describe('getClaims', () => {
  it('decodes a well-formed token', () => {
    const t = makeToken({ sub: 'ncenter', role: 'admin', iat: 100, exp: 200 });
    const c = getClaims(t);
    expect(c).not.toBeNull();
    expect(c!.sub).toBe('ncenter');
    expect(c!.role).toBe('admin');
    expect(c!.exp).toBe(200);
    expect(c!.iat).toBe(100);
  });

  it('returns null on a malformed token', () => {
    expect(getClaims('not.a.token')).toBeNull();
    expect(getClaims('only-one-segment')).toBeNull();
    expect(getClaims('')).toBeNull();
  });

  it('returns null when role is invalid', () => {
    const t = makeToken({ sub: 'x', role: 'super', iat: 1, exp: 2 });
    expect(getClaims(t)).toBeNull();
  });

  it('returns null when sub is missing', () => {
    const t = makeToken({ role: 'admin', iat: 1, exp: 2 });
    expect(getClaims(t)).toBeNull();
  });
});

describe('isExpired', () => {
  it('returns true for null token', () => {
    expect(isExpired(null)).toBe(true);
  });

  it('returns true for malformed token', () => {
    expect(isExpired('garbage')).toBe(true);
  });

  it('returns true when exp is in the past', () => {
    const t = makeToken({ sub: 'x', role: 'admin', iat: 100, exp: 200 });
    expect(isExpired(t, 300)).toBe(true);
  });

  it('returns false when exp is in the future', () => {
    const t = makeToken({ sub: 'x', role: 'admin', iat: 100, exp: 1000 });
    expect(isExpired(t, 200)).toBe(false);
  });

  it('boundary: exp == now is treated as expired', () => {
    const t = makeToken({ sub: 'x', role: 'admin', iat: 100, exp: 200 });
    expect(isExpired(t, 200)).toBe(true);
  });
});

describe('localStorage session round-trip', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('store loads what was persisted', async () => {
    // Persist a fresh non-expired token (exp 1 year out).
    const exp = Math.floor(Date.now() / 1000) + 86400 * 365;
    const token = makeToken({ sub: 'ncenter', role: 'admin', iat: 1, exp });
    const session = { token, username: 'ncenter', role: 'admin', exp };
    localStorage.setItem('godo:auth', JSON.stringify(session));

    // Re-import to trigger fresh load.
    vi_resetModules();
    const { auth } = await import('../../src/stores/auth');
    let read: { username?: string } | null = null;
    const unsub = auth.subscribe((v) => (read = v));
    unsub();
    expect(read).not.toBeNull();
    expect((read as { username: string }).username).toBe('ncenter');
  });

  it('store discards an expired persisted token', async () => {
    const exp = 100; // way in the past
    const token = makeToken({ sub: 'old', role: 'viewer', iat: 1, exp });
    localStorage.setItem(
      'godo:auth',
      JSON.stringify({ token, username: 'old', role: 'viewer', exp }),
    );

    vi_resetModules();
    const { auth } = await import('../../src/stores/auth');
    let read: unknown = 'not-set';
    const unsub = auth.subscribe((v) => (read = v));
    unsub();
    expect(read).toBeNull();
  });
});

// Helper: pull vitest's module resetter on demand to avoid the linter
// flagging unused top-level imports.
function vi_resetModules(): void {
  // Imported lazily so the file stays declarative.
  // @ts-expect-error — vi is exposed by vitest globals if enabled, but we
  //                    use the dynamic import path to keep `globals: false`.
  import('vitest').then(({ vi }) => vi.resetModules());
}
