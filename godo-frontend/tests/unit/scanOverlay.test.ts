import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

// We import the module fresh in each test so the `readInitial()` runs
// against the current sessionStorage state.
async function freshImport() {
  vi.resetModules();
  return await import('../../src/stores/scanOverlay');
}

beforeEach(() => {
  // jsdom provides sessionStorage; clear it explicitly so prior test
  // residue cannot bleed across cases.
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('scanOverlay store', () => {
  it('default state is off when sessionStorage is empty', async () => {
    const mod = await freshImport();
    expect(get(mod.scanOverlay)).toBe(false);
  });

  it('persists on set to sessionStorage', async () => {
    const mod = await freshImport();
    mod.setScanOverlay(true);
    expect(sessionStorage.getItem('godo:scanOverlay')).toBe('true');
    mod.setScanOverlay(false);
    expect(sessionStorage.getItem('godo:scanOverlay')).toBe('false');
  });

  it('restores from sessionStorage on init', async () => {
    sessionStorage.setItem('godo:scanOverlay', 'true');
    const mod = await freshImport();
    expect(get(mod.scanOverlay)).toBe(true);
  });

  it('toggleScanOverlay flips state both ways', async () => {
    const mod = await freshImport();
    expect(get(mod.scanOverlay)).toBe(false);
    mod.toggleScanOverlay();
    expect(get(mod.scanOverlay)).toBe(true);
    mod.toggleScanOverlay();
    expect(get(mod.scanOverlay)).toBe(false);
  });
});
