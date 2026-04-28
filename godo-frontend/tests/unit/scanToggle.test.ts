/**
 * Track D — ScanToggle component tests.
 *
 * Pins:
 *   1. Clicking the button flips the `scanOverlay` store both ways.
 *   2. Persistence round-trip: setting via the button writes to
 *      `sessionStorage`; a fresh module import reads it back.
 *   3. Freshness label states (Q-OQ-D7 style):
 *      - no scan / no _arrival_ms      → "정지됨"
 *      - arrival within fully-fresh    → "최신"
 *      - arrival within stale band     → "약간 지연됨"
 *      - arrival outside freshness ms  → "정지됨"
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { get } from 'svelte/store';
import ScanToggle from '../../src/components/ScanToggle.svelte';
import { MAP_SCAN_FRESHNESS_MS } from '../../src/lib/constants';
import type { LastScan } from '../../src/lib/protocol';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function makeScan(arrivalMs: number): LastScan {
  return {
    valid: 1,
    forced: 1,
    pose_valid: 1,
    iterations: 5,
    published_mono_ns: 1,
    pose_x_m: 0,
    pose_y_m: 0,
    pose_yaw_deg: 0,
    n: 0,
    angles_deg: [],
    ranges_m: [],
    _arrival_ms: arrivalMs,
  };
}

describe('ScanToggle', () => {
  it('clicking the button flips the scanOverlay store', async () => {
    const overlayMod = await import('../../src/stores/scanOverlay');
    overlayMod._resetScanOverlayForTests();
    expect(get(overlayMod.scanOverlay)).toBe(false);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(ScanToggle, {
      target,
      props: { scan: null },
    });
    cleanups.push(() => unmount(component));
    flushSync();

    const btn = target.querySelector<HTMLButtonElement>('[data-testid="scan-toggle-btn"]');
    expect(btn).not.toBeNull();
    btn!.click();
    flushSync();
    expect(get(overlayMod.scanOverlay)).toBe(true);
    btn!.click();
    flushSync();
    expect(get(overlayMod.scanOverlay)).toBe(false);
  });

  it('toggle state persists through sessionStorage round-trip', async () => {
    // Use the live store (no resetModules — that creates a separate
    // store instance the component never bound to).
    const overlayMod = await import('../../src/stores/scanOverlay');
    overlayMod._resetScanOverlayForTests();
    overlayMod.setScanOverlay(true);
    expect(sessionStorage.getItem('godo:scanOverlay')).toBe('true');
    overlayMod.setScanOverlay(false);
    expect(sessionStorage.getItem('godo:scanOverlay')).toBe('false');
    overlayMod.setScanOverlay(true);
    expect(get(overlayMod.scanOverlay)).toBe(true);
  });

  it('freshness label shows "정지됨" when scan has no _arrival_ms', async () => {
    const overlayMod = await import('../../src/stores/scanOverlay');
    overlayMod._resetScanOverlayForTests();
    overlayMod.setScanOverlay(true);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(ScanToggle, {
      target,
      props: { scan: null },
    });
    cleanups.push(() => unmount(component));
    flushSync();

    const badge = target.querySelector<HTMLSpanElement>('[data-testid="scan-freshness"]');
    expect(badge).not.toBeNull();
    expect(badge!.textContent?.trim()).toBe('정지됨');
  });

  it('freshness label shows "최신" within fully-fresh window', async () => {
    vi.useFakeTimers();
    const t0 = new Date('2026-04-29T00:00:00Z').getTime();
    vi.setSystemTime(t0);

    const overlayMod = await import('../../src/stores/scanOverlay');
    overlayMod._resetScanOverlayForTests();
    overlayMod.setScanOverlay(true);

    const target = document.createElement('div');
    document.body.appendChild(target);
    // Fresh arrival 50 ms ago — well inside the half-window of
    // fully-fresh.
    const scan = makeScan(t0 - 50);
    const component = mount(ScanToggle, {
      target,
      props: { scan },
    });
    cleanups.push(() => unmount(component));
    flushSync();

    const badge = target.querySelector<HTMLSpanElement>('[data-testid="scan-freshness"]');
    expect(badge!.getAttribute('data-state')).toBe('최신');
  });

  it('freshness label shows "약간 지연됨" between fully-fresh and freshness limit', async () => {
    vi.useFakeTimers();
    const t0 = new Date('2026-04-29T00:00:00Z').getTime();
    vi.setSystemTime(t0);

    const overlayMod = await import('../../src/stores/scanOverlay');
    overlayMod._resetScanOverlayForTests();
    overlayMod.setScanOverlay(true);

    const target = document.createElement('div');
    document.body.appendChild(target);
    // Arrival 700 ms ago — past the half-window (500 ms) but before
    // the freshness limit (1000 ms).
    const scan = makeScan(t0 - 700);
    const component = mount(ScanToggle, {
      target,
      props: { scan },
    });
    cleanups.push(() => unmount(component));
    flushSync();

    const badge = target.querySelector<HTMLSpanElement>('[data-testid="scan-freshness"]');
    expect(badge!.getAttribute('data-state')).toBe('약간 지연됨');
  });

  it('freshness label shows "정지됨" once arrival passes MAP_SCAN_FRESHNESS_MS', async () => {
    vi.useFakeTimers();
    const t0 = new Date('2026-04-29T00:00:00Z').getTime();
    vi.setSystemTime(t0);

    const overlayMod = await import('../../src/stores/scanOverlay');
    overlayMod._resetScanOverlayForTests();
    overlayMod.setScanOverlay(true);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const scan = makeScan(t0 - (MAP_SCAN_FRESHNESS_MS + 100));
    const component = mount(ScanToggle, {
      target,
      props: { scan },
    });
    cleanups.push(() => unmount(component));
    flushSync();

    const badge = target.querySelector<HTMLSpanElement>('[data-testid="scan-freshness"]');
    expect(badge!.getAttribute('data-state')).toBe('정지됨');
  });
});
