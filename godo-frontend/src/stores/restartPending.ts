/**
 * RestartPending store — Track B-CONFIG (PR-CONFIG-β).
 *
 * Refresh-on-action; explicit `refresh()` is called on mount + on
 * every successful PATCH /api/config response (the tracker may have
 * touched the flag during the round-trip). The banner component also
 * subscribes directly so the UI updates without prop-drilling.
 *
 * Mode-A S5 fold: distinguishes "tracker ok + flag set" (red banner
 * "godo-tracker 재시작 필요") from "tracker unreachable + flag set"
 * (red banner "godo-tracker 시작 실패 — journalctl 확인") via the
 * separate `/api/health.tracker` field.
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet, ApiError } from '$lib/api';
import type { Health, RestartPendingResponse } from '$lib/protocol';

export interface RestartPendingState {
  pending: boolean;
  trackerOk: boolean;
}

export const restartPending: Writable<RestartPendingState> = writable({
  pending: false,
  trackerOk: true,
});

/**
 * Refresh both /api/system/restart_pending and /api/health.
 * On network/parse error the flag silently stays at the previous value
 * (no banner flicker) — operator sees other UI failures first.
 */
export async function refresh(): Promise<void> {
  let pending = false;
  let trackerOk = true;
  try {
    const r = await apiGet<RestartPendingResponse>('/api/system/restart_pending');
    pending = r.pending;
  } catch (e) {
    if (!(e instanceof ApiError)) {
      // Network error: leave the previous state.
      return;
    }
    pending = false;
  }
  try {
    const h = await apiGet<Health>('/api/health');
    trackerOk = h.tracker === 'ok';
  } catch {
    trackerOk = false;
  }
  restartPending.set({ pending, trackerOk });
}

/** Test helper. */
export function reset(): void {
  restartPending.set({ pending: false, trackerOk: true });
}
