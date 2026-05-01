/**
 * Mode store: polled from /api/health at HEALTH_POLL_MS.
 *
 * `mode` is null when health hasn't replied yet OR when the tracker is
 * unreachable.
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { HEALTH_POLL_MS } from '$lib/constants';
import type { Health, Mode } from '$lib/protocol';

export const mode: Writable<Mode | null> = writable(null);
export const trackerOk: Writable<boolean> = writable(false);

let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscriberCount = 0;

async function pollOnce(): Promise<void> {
  try {
    const h = await apiGet<Health>('/api/health');
    mode.set(h.mode ?? null);
    trackerOk.set(h.tracker === 'ok');
  } catch {
    mode.set(null);
    trackerOk.set(false);
  }
}

function startPolling(): void {
  if (pollTimer !== null) return;
  void pollOnce();
  pollTimer = setInterval(() => void pollOnce(), HEALTH_POLL_MS);
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

export function subscribeMode(fn: (m: Mode | null) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startPolling();
  const unsub = mode.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) stopPolling();
  };
}

/**
 * Optimistic update from a button-click handler (e.g. POST /api/live
 * returns the new mode immediately; we set it before the next poll lands
 * so the chip flips without a 1 s lag).
 */
export function setModeOptimistic(m: Mode): void {
  mode.set(m);
}

/**
 * issue#9 — action-driven refresh + polling phase realignment.
 *
 * Service-action handlers (Start / Stop / Restart for godo-tracker)
 * call this so the App.svelte tracker-down banner ("godo-tracker가
 * 응답하지 않습니다") reflects the new tracker state within HTTP RTT
 * instead of waiting up to HEALTH_POLL_MS for the next regular tick.
 *
 * Mirrors PR #45 / PR #59's pattern of pairing an immediate refresh
 * with the polling backstop. Also resets the interval phase so the
 * NEXT scheduled poll is HEALTH_POLL_MS after this refresh — keeps
 * polling deterministic relative to the operator's last action and
 * eliminates the prior emergent dependency on mount-time phase.
 *
 * Caveat: an immediate /api/health probe right after `systemctl
 * start/restart` returns will typically still see tracker="unreachable"
 * because the tracker is still booting. The benefit is for Stop (banner
 * shows immediately) and for catching the transient unreachable window
 * during a Restart bounce. Steady-state up-detection is still bounded
 * by the polling cadence.
 */
export async function refreshMode(): Promise<void> {
  await pollOnce();
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = setInterval(() => void pollOnce(), HEALTH_POLL_MS);
  }
}

/** Test helper. */
export function reset(): void {
  mode.set(null);
  trackerOk.set(false);
  stopPolling();
  subscriberCount = 0;
}
