/**
 * Track D — LastScan store: SSE-fed when subscribed AND scan-overlay is
 * on; polling fallback when SSE drops. Mirrors `stores/lastPose.ts`
 * structurally; the gating-on-overlay-flip is the Track D-specific
 * lifecycle bit (the tracker's UDS server is never queried for scans
 * unless an operator has flipped the toggle on — invariant (l)).
 *
 * Mode-A M2 fold: every SSE frame that arrives via this store has its
 * `_arrival_ms` field stamped at `Date.now()` BEFORE the store emits
 * to subscribers. The freshness gate in PoseCanvas reads
 * `Date.now() - frame._arrival_ms`, NOT `published_mono_ns` deltas
 * (clock-domain mismatch).
 */

import { get, writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { LAST_SCAN_POLL_FALLBACK_MS } from '$lib/constants';
import type { LastScan } from '$lib/protocol';
import { SSEClient } from '$lib/sse';
import { getToken } from './auth';
import { scanOverlay } from './scanOverlay';

export const lastScan: Writable<LastScan | null> = writable(null);

let sseClient: SSEClient | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscriberCount = 0;
let overlayUnsub: (() => void) | null = null;
let overlayOn = false;

function stampArrival(scan: LastScan): LastScan {
  // Mode-A M2: stamp wall-clock arrival time on every frame so the
  // freshness gate is computed in a single clock domain (browser ms).
  scan._arrival_ms = Date.now();
  return scan;
}

function startPolling(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(() => {
    void apiGet<LastScan>('/api/last_scan')
      .then((s) => lastScan.set(stampArrival(s)))
      .catch(() => {
        // Silent — store keeps last value; freshness gate dims the overlay.
      });
  }, LAST_SCAN_POLL_FALLBACK_MS);
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startSSE(): void {
  if (sseClient !== null) return;
  sseClient = new SSEClient({
    path: '/api/last_scan/stream',
    getToken,
    onMessage: (payload: unknown) => {
      // Successful frame disarms polling fallback (mirrors lastPose store
      // discipline).
      stopPolling();
      const scan = payload as LastScan;
      lastScan.set(stampArrival(scan));
    },
    onError: () => {
      startPolling();
    },
  });
  const opened = sseClient.open();
  if (!opened) {
    sseClient = null;
    startPolling();
  }
}

function stopSSE(): void {
  if (sseClient !== null) {
    sseClient.close();
    sseClient = null;
  }
}

function ensureLifecycle(): void {
  if (subscriberCount > 0 && overlayOn) {
    startSSE();
  } else {
    stopSSE();
    stopPolling();
    // Clear the store so a stale overlay does not flash when the operator
    // toggles back on.
    lastScan.set(null);
  }
}

function attachOverlayWatch(): void {
  if (overlayUnsub !== null) return;
  overlayUnsub = scanOverlay.subscribe((on) => {
    overlayOn = on;
    ensureLifecycle();
  });
}

function detachOverlayWatch(): void {
  if (overlayUnsub !== null) {
    overlayUnsub();
    overlayUnsub = null;
  }
}

/**
 * Subscribe-with-side-effects: components call this in `onMount` and call
 * the returned cleanup in `onDestroy`. Refcounted so multiple components
 * share one SSE; gated on the `scanOverlay` store flipping `true`.
 */
export function subscribeLastScan(fn: (s: LastScan | null) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) {
    overlayOn = get(scanOverlay);
    attachOverlayWatch();
    ensureLifecycle();
  }
  const unsub = lastScan.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) {
      stopSSE();
      stopPolling();
      detachOverlayWatch();
      lastScan.set(null);
    }
  };
}

/** Test-only — reset store + lifecycle so individual unit tests don't
 * leak SSEClient state across runs. */
export function _resetLastScanForTests(): void {
  stopSSE();
  stopPolling();
  detachOverlayWatch();
  subscriberCount = 0;
  overlayOn = false;
  lastScan.set(null);
}
