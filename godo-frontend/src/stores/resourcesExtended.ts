/**
 * Track B-SYSTEM PR-B — `/api/system/resources/extended/stream` SSE store.
 *
 * Same refcounted-SSE pattern as `processes.ts`. `_arrival_ms` stamped
 * per frame.
 */

import { get, writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { SSEClient } from '$lib/sse';
import type { ExtendedResources } from '$lib/protocol';
import { auth } from './auth';

const EMPTY: ExtendedResources = {
  cpu_per_core: [],
  cpu_aggregate_pct: 0,
  mem_total_mb: null,
  mem_used_mb: null,
  disk_pct: null,
  published_mono_ns: 0,
  _arrival_ms: undefined,
};

export const resourcesExtendedStore: Writable<ExtendedResources> = writable(EMPTY);

let sse: SSEClient | null = null;
let subscriberCount = 0;

function startSSE(): void {
  if (sse !== null) return;
  void apiGet<ExtendedResources>('/api/system/resources/extended')
    .then((body) => {
      resourcesExtendedStore.set({ ...body, _arrival_ms: Date.now() });
    })
    .catch(() => {
      // SSE will catch up on the next tick.
    });
  sse = new SSEClient({
    path: '/api/system/resources/extended/stream',
    getToken: () => get(auth)?.token ?? null,
    onMessage: (payload: unknown) => {
      if (
        payload &&
        typeof payload === 'object' &&
        'cpu_per_core' in payload &&
        'cpu_aggregate_pct' in payload
      ) {
        resourcesExtendedStore.set({
          ...(payload as ExtendedResources),
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

export function subscribeResourcesExtended(fn: (s: ExtendedResources) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startSSE();
  const unsub = resourcesExtendedStore.subscribe(fn);
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
export function _resetResourcesExtendedForTests(): void {
  stopSSE();
  subscriberCount = 0;
  resourcesExtendedStore.set(EMPTY);
}
