/**
 * issue#27 — LastOutput store.
 *
 * Mirror of `lastPose` store but reads the `output` branch of the
 * extended /api/last_pose/stream SSE payload (issue#27 wrap-and-version).
 * Polling fallback hits /api/last_output one-shot.
 *
 * Both stores subscribe to the SAME SSE connection (the SSEClient is
 * created per-store right now — TODO: refcount-share if connection
 * count becomes a concern). Drift between stores is fine — both unwrap
 * their own branch independently and a missing `output` key renders
 * "Final output (UDP) — unavailable" in the LastPoseCard.
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { LAST_POSE_POLL_FALLBACK_MS } from '$lib/constants';
import type { LastOutputFrame, LastPoseStreamFrame } from '$lib/protocol';
import { SSEClient } from '$lib/sse';
import { getToken } from './auth';

export const lastOutput: Writable<LastOutputFrame | null> = writable(null);

let sseClient: SSEClient | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscriberCount = 0;

function startPolling(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(() => {
    void apiGet<LastOutputFrame>('/api/last_output')
      .then((p) => lastOutput.set(p))
      .catch(() => {
        // Silent; keep last value. UI shows stale via published_mono_ns.
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
      stopPolling();
      // issue#27 wrap-and-version: payload is {pose, output}.
      const frame = payload as LastPoseStreamFrame;
      if (frame && typeof frame === 'object' && 'output' in frame) {
        lastOutput.set(frame.output);
      }
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

/**
 * Subscribe-with-side-effects: components call this in `onMount` and
 * call the returned cleanup in `onDestroy`. Refcount so multiple
 * subscribers share one SSE connection.
 */
export function subscribeLastOutput(fn: (p: LastOutputFrame | null) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startSSE();
  const unsub = lastOutput.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) {
      stopSSE();
      stopPolling();
    }
  };
}
