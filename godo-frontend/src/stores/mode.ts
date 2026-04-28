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
