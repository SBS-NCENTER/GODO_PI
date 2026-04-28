/**
 * Track D — scan-overlay toggle store.
 *
 * Persists in `sessionStorage` (Q-OQ-D2): same-tab reload preserves the
 * operator's choice; new tab / new operator session defaults OFF. The
 * overlay generates ~30-60 KB/s of WAN traffic on Tailscale, so OFF-by-
 * default is the defensive baseline.
 *
 * Subscribers gate the `lastScan` SSE: the SSE only opens when this
 * store flips `true` AND there is at least one subscriber. Pinned by
 * `tests/unit/lastScan.test.ts::sse_does_not_start_when_overlay_off`.
 */

import { writable, type Writable } from 'svelte/store';

const STORAGE_KEY = 'godo:scanOverlay';

function readInitial(): boolean {
  if (typeof sessionStorage === 'undefined') return false;
  try {
    return sessionStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function persist(value: boolean): void {
  if (typeof sessionStorage === 'undefined') return;
  try {
    sessionStorage.setItem(STORAGE_KEY, value ? 'true' : 'false');
  } catch {
    // sessionStorage quota / privacy mode — silently degrade to in-memory.
  }
}

export const scanOverlay: Writable<boolean> = writable(readInitial());

scanOverlay.subscribe(persist);

/** Replace the toggle state with `value`. */
export function setScanOverlay(value: boolean): void {
  scanOverlay.set(value);
}

/** Flip the toggle. */
export function toggleScanOverlay(): void {
  scanOverlay.update((v) => !v);
}

/** Test-only — clear sessionStorage entry so subsequent module imports
 * default to off. The implementation guards `sessionStorage` so this is
 * a no-op in non-browser environments. */
export function _resetScanOverlayForTests(): void {
  if (typeof sessionStorage === 'undefined') return;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
  scanOverlay.set(false);
}
