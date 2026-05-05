/**
 * issue#28.1 B6 — `overlayToggles` store v0 → v1 migration.
 *
 * The legacy v0 schema persisted only the LiDAR overlay flag in
 * `sessionStorage` under `godo.scanOverlay.v0`. v1 unified all three
 * surfaces (origin/axis, LiDAR, grid) into `localStorage` under
 * `godo.overlay.toggles.v1`. The store's `readInitial()` performs a
 * one-shot migration: when the v1 key is absent and the v0 key
 * exists, populate `lidarOn` from v0 and clear the v0 key (so the
 * migration is idempotent across page reloads). M4 lock — see
 * `overlayToggles.ts:36-65`.
 *
 * Three pins:
 *   1. v0 `'true'` migrates to `lidarOn: true`, others default.
 *   2. v0 `'false'` migrates to `lidarOn: false`, others default.
 *   3. After migration, the v0 key is cleared so subsequent reads
 *      hit the v1 key (idempotency).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import {
  OVERLAY_LS_KEY,
  OVERLAY_LS_KEY_LEGACY_V0,
} from '../../src/lib/constants';

// We import the module fresh in each test so `readInitial()` runs
// against the current storage state.
async function freshImport() {
  vi.resetModules();
  return await import('../../src/stores/overlayToggles');
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe('overlayToggles v0 → v1 migration', () => {
  it("migrates legacy v0 'true' to lidarOn=true with other defaults", async () => {
    sessionStorage.setItem(OVERLAY_LS_KEY_LEGACY_V0, 'true');
    expect(localStorage.getItem(OVERLAY_LS_KEY)).toBeNull();

    const mod = await freshImport();
    const state = get(mod.overlayToggles);
    expect(state.lidarOn).toBe(true);
    expect(state.originAxisOn).toBe(false);
    expect(state.gridOn).toBe(false);
  });

  it("migrates legacy v0 'false' to lidarOn=false with other defaults", async () => {
    sessionStorage.setItem(OVERLAY_LS_KEY_LEGACY_V0, 'false');
    const mod = await freshImport();
    const state = get(mod.overlayToggles);
    expect(state.lidarOn).toBe(false);
    expect(state.originAxisOn).toBe(false);
    expect(state.gridOn).toBe(false);
  });

  it('clears the legacy v0 key after migration (idempotency)', async () => {
    sessionStorage.setItem(OVERLAY_LS_KEY_LEGACY_V0, 'true');
    await freshImport();
    // Post-migration: legacy key gone.
    expect(sessionStorage.getItem(OVERLAY_LS_KEY_LEGACY_V0)).toBeNull();
  });
});
