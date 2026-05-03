/**
 * LastPose store: SSE-fed when subscribed; polling fallback when SSE drops.
 *
 * Components that need pose data subscribe to `lastPose`. The store itself
 * owns the SSEClient lifecycle — it opens on first subscribe and closes
 * on last unsubscribe.
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { LAST_POSE_POLL_FALLBACK_MS } from '$lib/constants';
import type { LastPose, LastPoseStreamFrame } from '$lib/protocol';
import { SSEClient } from '$lib/sse';
import { getToken } from './auth';

export const lastPose: Writable<LastPose | null> = writable(null);

let sseClient: SSEClient | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscriberCount = 0;

function startPolling(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(() => {
    void apiGet<LastPose>('/api/last_pose')
      .then((p) => lastPose.set(p))
      .catch(() => {
        // Silent; the store keeps its last value. UI components can show
        // "stale" using their own age heuristic on `published_mono_ns`.
      });
  }, LAST_POSE_POLL_FALLBACK_MS);
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
    path: '/api/last_pose/stream',
    getToken,
    onMessage: (payload: unknown) => {
      // Per Mode-B M1: any successful frame disarms the polling fallback.
      // EventSource auto-reconnects, so a transient backend bounce that
      // armed the poller will leave us double-fetching otherwise.
      stopPolling();
      // issue#27 wrap-and-version: payload is {pose, output}; unwrap
      // the pose branch. Backwards compat: the one-shot /api/last_pose
      // endpoint still returns flat LastPose, so the polling-fallback
      // path needs no change.
      if (payload && typeof payload === 'object' && 'pose' in (payload as object)) {
        const frame = payload as LastPoseStreamFrame;
        lastPose.set(frame.pose);
      } else {
        lastPose.set(payload as LastPose);
      }
    },
    onError: () => {
      // Fall back to polling until SSE recovers; `stopPolling` runs on
      // the next successful frame OR on last-unsubscribe.
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

/**
 * Subscribe-with-side-effects: components call this in `onMount` and call
 * the returned cleanup in `onDestroy`. We refcount so multiple components
 * share one SSE connection.
 */
export function subscribeLastPose(fn: (p: LastPose | null) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startSSE();
  const unsub = lastPose.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) {
      stopSSE();
      stopPolling();
    }
  };
}
