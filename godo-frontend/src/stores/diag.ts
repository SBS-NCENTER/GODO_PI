/**
 * PR-DIAG (Track B-DIAG) — Diagnostics store.
 *
 * SSE-fed `Writable<DiagFrame | null>` plus a fixed-size sparkline ring
 * for the four time-series metrics (jitter p50/p95/p99/max + amcl rate
 * Hz + cpu temp + mem used %). Refcounted: opens SSE on the first
 * subscriber, closes on the last.
 *
 * Polling fallback at 1 Hz (DIAG_POLL_FALLBACK_MS) when SSE drops; this
 * is intentionally slower than the 5 Hz SSE cadence — Diag isn't
 * life-critical and the choppy fallback is itself a useful operator
 * signal that "something's off" (per OQ-DIAG-8).
 *
 * `_arrival_ms` is stamped on every frame on receipt (Mode-A M2 / N4
 * pattern, Track D precedent). The freshness gate in
 * `routes/Diagnostics.svelte` reads `Date.now() - frame._arrival_ms`,
 * NOT `published_mono_ns` deltas (clock-domain mismatch).
 */

import { get, writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { DIAG_POLL_FALLBACK_MS, DIAG_SPARKLINE_DEPTH } from '$lib/constants';
import type { DiagFrame } from '$lib/protocol';
import { SSEClient } from '$lib/sse';
import { getToken } from './auth';

export const diag: Writable<DiagFrame | null> = writable(null);

/** Per-metric sparkline ring. Each array is in chronological order; the
 * oldest entries are at index 0, newest at the tail. */
export interface DiagSparklineState {
  jitter_p50_ns: number[];
  jitter_p99_ns: number[];
  amcl_rate_hz: number[];
  cpu_temp_c: number[];
  mem_used_pct: number[];
}

function emptySparklines(): DiagSparklineState {
  return {
    jitter_p50_ns: [],
    jitter_p99_ns: [],
    amcl_rate_hz: [],
    cpu_temp_c: [],
    mem_used_pct: [],
  };
}

export const diagSparklines: Writable<DiagSparklineState> = writable(emptySparklines());

let sseClient: SSEClient | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscriberCount = 0;

function pushBounded(arr: number[], v: number): number[] {
  const next = [...arr, v];
  while (next.length > DIAG_SPARKLINE_DEPTH) next.shift();
  return next;
}

function stampArrival(frame: DiagFrame): DiagFrame {
  frame._arrival_ms = Date.now();
  return frame;
}

function appendToSparklines(frame: DiagFrame): void {
  diagSparklines.update((s) => {
    const next: DiagSparklineState = {
      jitter_p50_ns: pushBounded(s.jitter_p50_ns, frame.jitter?.valid ? frame.jitter.p50_ns : 0),
      jitter_p99_ns: pushBounded(s.jitter_p99_ns, frame.jitter?.valid ? frame.jitter.p99_ns : 0),
      amcl_rate_hz: pushBounded(s.amcl_rate_hz, frame.amcl_rate?.valid ? frame.amcl_rate.hz : 0),
      cpu_temp_c: pushBounded(s.cpu_temp_c, frame.resources?.cpu_temp_c ?? 0),
      mem_used_pct: pushBounded(s.mem_used_pct, frame.resources?.mem_used_pct ?? 0),
    };
    return next;
  });
}

function startPolling(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(() => {
    // Polling fallback fetches the four single-shot endpoints and stitches
    // them into a DiagFrame. The SSE adapter is the SSOT for the merged
    // shape; we mirror it here.
    void Promise.all([
      apiGet<DiagFrame['pose']>('/api/last_pose').catch(() => null),
      apiGet<DiagFrame['jitter']>('/api/system/jitter').catch(() => null),
      apiGet<DiagFrame['amcl_rate']>('/api/system/amcl_rate').catch(() => null),
      apiGet<DiagFrame['resources']>('/api/system/resources').catch(() => null),
    ]).then(([pose, jitter, amcl_rate, resources]) => {
      if (!pose || !jitter || !amcl_rate || !resources) return; // skip on partial
      const frame = stampArrival({ pose, jitter, amcl_rate, resources });
      diag.set(frame);
      appendToSparklines(frame);
    });
  }, DIAG_POLL_FALLBACK_MS);
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
    path: '/api/diag/stream',
    getToken,
    onMessage: (payload: unknown) => {
      stopPolling();
      const frame = stampArrival(payload as DiagFrame);
      diag.set(frame);
      appendToSparklines(frame);
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
 * call the returned cleanup in `onDestroy`. Refcounted so multiple
 * components share one SSE.
 */
export function subscribeDiag(fn: (f: DiagFrame | null) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startSSE();
  const unsub = diag.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) {
      stopSSE();
      stopPolling();
    }
  };
}

/** Test-only — current subscriber count (for refcount assertions). */
export function _getSubscriberCountForTests(): number {
  return subscriberCount;
}

/** Test-only — true while an SSE client is open. */
export function _isSSEOpenForTests(): boolean {
  return sseClient !== null;
}

/** Test-only — reset store + lifecycle so individual unit tests don't
 * leak state across runs. */
export function _resetDiagForTests(): void {
  stopSSE();
  stopPolling();
  subscriberCount = 0;
  diag.set(null);
  diagSparklines.set(emptySparklines());
}

// `get` re-exported so tests can read store snapshots.
export { get };
