/**
 * issue#28 — unified overlay toggle store.
 *
 * Backs `<OverlayToggleRow>` (mounted on `/map` and `/map-edit`). Holds
 * one boolean per overlay surface. localStorage-backed so refresh
 * preserves the operator's choice; legacy v0 sessionStorage key is
 * migrated once on first read (M4 lock).
 *
 * Subscribers gate downstream effects: e.g. `<GridOverlay>` reads
 * `gridOn`, `<OriginAxisOverlay>` reads `originAxisOn`. The existing
 * `scanOverlay` store stays alive — `lidarOn` mirrors INTO it for the
 * SSE-gating pin. Removing `scanOverlay` outright would touch every
 * subscriber call site; the mirror is the minimum-surface migration.
 */

import { writable, type Writable } from 'svelte/store';

import {
  OVERLAY_LS_KEY,
  OVERLAY_LS_KEY_LEGACY_V0,
} from '../lib/constants.js';
import { setScanOverlay } from './scanOverlay.js';

export interface OverlayToggleState {
  originAxisOn: boolean;
  lidarOn: boolean;
  gridOn: boolean;
}

const DEFAULTS: OverlayToggleState = {
  originAxisOn: false,
  lidarOn: false,
  gridOn: false,
};

function readInitial(): OverlayToggleState {
  // SSR safety per N8 lock.
  if (typeof window === 'undefined') return { ...DEFAULTS };
  try {
    const raw = window.localStorage.getItem(OVERLAY_LS_KEY);
    if (raw !== null) {
      const parsed = JSON.parse(raw) as Partial<OverlayToggleState>;
      return {
        originAxisOn: !!parsed.originAxisOn,
        lidarOn: !!parsed.lidarOn,
        gridOn: !!parsed.gridOn,
      };
    }
    // M4 — migrate from legacy sessionStorage v0 key once.
    if (typeof window.sessionStorage !== 'undefined') {
      const legacy = window.sessionStorage.getItem(OVERLAY_LS_KEY_LEGACY_V0);
      if (legacy !== null) {
        const lidarOn = legacy === 'true';
        try {
          window.sessionStorage.removeItem(OVERLAY_LS_KEY_LEGACY_V0);
        } catch {
          // ignore quota errors
        }
        return { ...DEFAULTS, lidarOn };
      }
    }
  } catch {
    // localStorage missing / parse failure → defaults.
  }
  return { ...DEFAULTS };
}

function persist(state: OverlayToggleState): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(OVERLAY_LS_KEY, JSON.stringify(state));
  } catch {
    // localStorage quota / privacy mode — silently degrade to in-memory.
  }
}

export const overlayToggles: Writable<OverlayToggleState> = writable(readInitial());

overlayToggles.subscribe((state) => {
  persist(state);
  // Mirror `lidarOn` into the legacy `scanOverlay` store so the SSE
  // gate stays load-bearing (subscriber count drives lastScan SSE
  // open/close).
  setScanOverlay(state.lidarOn);
});

export function toggleOriginAxis(): void {
  overlayToggles.update((s) => ({ ...s, originAxisOn: !s.originAxisOn }));
}

export function toggleLidar(): void {
  overlayToggles.update((s) => ({ ...s, lidarOn: !s.lidarOn }));
}

export function toggleGrid(): void {
  overlayToggles.update((s) => ({ ...s, gridOn: !s.gridOn }));
}

/** Test-only — clear persisted state so subsequent module reads default
 * to OFF. */
export function _resetOverlayTogglesForTests(): void {
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.removeItem(OVERLAY_LS_KEY);
      window.sessionStorage.removeItem(OVERLAY_LS_KEY_LEGACY_V0);
    } catch {
      // ignore
    }
  }
  overlayToggles.set({ ...DEFAULTS });
}
