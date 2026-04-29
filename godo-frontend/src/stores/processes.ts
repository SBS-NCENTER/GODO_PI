/**
 * Track B-SYSTEM PR-B — `/api/system/processes/stream` SSE store.
 *
 * Refcounted: opens the SSE on first subscribe, closes on last unsub.
 * Falls back to polling `/api/system/processes` once on initial mount
 * (so a viewer who lands on the Processes sub-tab while the SSE is
 * still connecting sees data within ~1 s instead of an empty table).
 *
 * `_arrival_ms` is stamped on every received frame so the page can
 * gate a stale-banner via `Date.now() - last._arrival_ms` per
 * frontend invariant (m).
 */

import { get, writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { SSEClient } from '$lib/sse';
import type { ProcessesSnapshot } from '$lib/protocol';
import { auth } from './auth';

const EMPTY: ProcessesSnapshot = {
  processes: [],
  duplicate_alert: false,
  published_mono_ns: 0,
  _arrival_ms: undefined,
};

export const processesStore: Writable<ProcessesSnapshot> = writable(EMPTY);

let sse: SSEClient | null = null;
let subscriberCount = 0;

function startSSE(): void {
  if (sse !== null) return;
  // One initial fetch covers the gap between mount and first SSE tick.
  void apiGet<ProcessesSnapshot>('/api/system/processes')
    .then((body) => {
      processesStore.set({ ...body, _arrival_ms: Date.now() });
    })
    .catch(() => {
      // SSE will provide data shortly; no-op on initial-fetch failure.
    });
  sse = new SSEClient({
    path: '/api/system/processes/stream',
    getToken: () => get(auth)?.token ?? null,
    onMessage: (payload: unknown) => {
      // Defensive shape check — the backend pins the schema, but a
      // mid-deploy mismatch shouldn't crash the SPA.
      if (
        payload &&
        typeof payload === 'object' &&
        'processes' in payload &&
        'duplicate_alert' in payload
      ) {
        processesStore.set({
          ...(payload as ProcessesSnapshot),
          _arrival_ms: Date.now(),
        });
      }
    },
  });
  sse.open();
}

function stopSSE(): void {
  if (sse !== null) {
    sse.close();
    sse = null;
  }
}

export function subscribeProcesses(fn: (s: ProcessesSnapshot) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startSSE();
  const unsub = processesStore.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) stopSSE();
  };
}

/** Test-only — current subscriber count. */
export function _getSubscriberCountForTests(): number {
  return subscriberCount;
}

/** Test-only — clear state + close any open SSE. */
export function _resetProcessesForTests(): void {
  stopSSE();
  subscriberCount = 0;
  processesStore.set(EMPTY);
}
