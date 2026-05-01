/**
 * RestartPending store — Track B-CONFIG (PR-CONFIG-β) + issue#8.
 *
 * Two refresh paths:
 *   - Action-driven `refresh()` — called from PATCH /api/config success,
 *     ServiceCard restart action, MapEdit map mutations, etc. Gives
 *     immediate UI feedback after operator actions.
 *   - Subscriber-counted polling (`subscribeRestartPending`) at
 *     `RESTART_PENDING_POLL_MS`. Backstop for issue#8: a service-restart
 *     POST returns success the moment systemctl queues the restart, but
 *     the tracker's own `clear_pending_flag()` runs later during boot;
 *     the action-driven refresh fires too early to see the cleared
 *     sentinel, so without polling the banner sticks at pending=true
 *     until a hard reload. Polling re-fetches at 1 Hz to catch the
 *     deferred clearance.
 *
 * Mode-A S5 fold: distinguishes "tracker ok + flag set" (red banner
 * "godo-tracker 재시작 필요") from "tracker unreachable + flag set"
 * (red banner "godo-tracker 시작 실패 — journalctl 확인") via the
 * separate `/api/health.tracker` field.
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet, ApiError } from '$lib/api';
import { RESTART_PENDING_POLL_MS } from '$lib/constants';
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

let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscriberCount = 0;

function startPolling(): void {
  if (pollTimer !== null) return;
  void refresh();
  pollTimer = setInterval(() => void refresh(), RESTART_PENDING_POLL_MS);
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/**
 * Subscribe with subscriber-counted always-on polling. Mirrors the
 * `subscribeMode` pattern in stores/mode.ts. The first subscriber starts
 * the polling timer; the last one to unsubscribe stops it.
 */
export function subscribeRestartPending(fn: (s: RestartPendingState) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startPolling();
  const unsub = restartPending.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) stopPolling();
  };
}

/** Test helper. */
export function reset(): void {
  restartPending.set({ pending: false, trackerOk: true });
  stopPolling();
  subscriberCount = 0;
}
