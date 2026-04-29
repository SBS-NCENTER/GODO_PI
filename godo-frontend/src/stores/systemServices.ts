/**
 * Track B-SYSTEM PR-2 — `/api/system/services` polling store.
 *
 * Subscribers: `routes/System.svelte`'s services panel. The store starts
 * polling on first subscribe and stops on last unsubscribe (refcounted).
 * `_arrival_ms` is stamped on every successful fetch so the page can
 * gate a stale-banner via `Date.now() - last._arrival_ms`.
 *
 * No SSE — 1 Hz polling matches the backend cache TTL
 * (`SYSTEM_SERVICES_CACHE_TTL_S = 1.0 s`); a fancier wire layer would
 * not improve operator UX given the cadence the UI actually shows.
 */

import { get, writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { SYSTEM_SERVICES_POLL_MS } from '$lib/constants';
import type { SystemServiceEntry, SystemServicesResponse } from '$lib/protocol';

export interface SystemServicesState {
  services: SystemServiceEntry[];
  _arrival_ms: number | null;
  err: string | null;
}

function emptyState(): SystemServicesState {
  return { services: [], _arrival_ms: null, err: null };
}

export const systemServices: Writable<SystemServicesState> = writable(emptyState());

let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscriberCount = 0;

async function fetchOnce(): Promise<void> {
  try {
    const body = await apiGet<SystemServicesResponse>('/api/system/services');
    systemServices.set({
      services: body.services,
      _arrival_ms: Date.now(),
      err: null,
    });
  } catch (e) {
    const err = e as Error;
    // Preserve the last good services list — operator wants stale-but-
    // visible over empty-with-error. The stale-banner renders on the
    // freshness gap.
    systemServices.update((s) => ({ ...s, err: err.message }));
  }
}

function startPolling(): void {
  if (pollTimer !== null) return;
  // Immediate fetch on mount + recurring at the cadence. T4 fold pin:
  // unit test asserts 4 fetches in 3500 ms (1 immediate + 3 ticks).
  void fetchOnce();
  pollTimer = setInterval(() => {
    void fetchOnce();
  }, SYSTEM_SERVICES_POLL_MS);
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/**
 * Subscribe-with-side-effects. Refcounted so multiple subscribers share
 * one polling timer.
 */
export function subscribeSystemServices(fn: (s: SystemServicesState) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startPolling();
  const unsub = systemServices.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) stopPolling();
  };
}

/** Test-only — current subscriber count (refcount assertions). */
export function _getSubscriberCountForTests(): number {
  return subscriberCount;
}

/** Test-only — clear the timer + reset state. */
export function _resetSystemServicesForTests(): void {
  stopPolling();
  subscriberCount = 0;
  systemServices.set(emptyState());
}

export { get };
