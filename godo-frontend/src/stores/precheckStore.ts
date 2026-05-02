/**
 * issue#16 — Mapping pre-check store. 1 Hz polling of
 * `/api/mapping/precheck` while the mapping coordinator is in `idle`.
 *
 * Mirrors the `mappingStatus.ts` lifecycle pattern but adds a
 * caller-supplied name accessor so the URL query string can change
 * between polls without re-subscribing. The MapMapping.svelte page is
 * the sole subscriber; it calls `precheckStore.start(() => name)` in
 * onMount and `stop()` in onDestroy.
 *
 * Spec memory: `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';
import { MAPPING_STATUS_POLL_MS } from '$lib/constants';
import type { PrecheckResult } from '$lib/protocol';

const _empty: PrecheckResult = {
  ready: false,
  checks: [],
};

export const precheckStore: Writable<PrecheckResult> = writable(_empty);

let pollTimer: ReturnType<typeof setInterval> | null = null;
let _getName: (() => string) | null = null;

async function pollOnce(): Promise<void> {
  const name = _getName ? _getName() : '';
  // Empty name → omit the query so the backend treats it as pending.
  const path = name
    ? `/api/mapping/precheck?${new URLSearchParams({ name }).toString()}`
    : '/api/mapping/precheck';
  try {
    const r = await apiGet<PrecheckResult>(path);
    if (pollTimer === null) return;
    precheckStore.set(r);
  } catch {
    // Network errors / 5xx silently leave the previous payload — at
    // 1 Hz the SPA must not toast on every transient blip. Stale
    // payload cleared on next successful tick.
  }
}

/**
 * Begin polling. `getName` is called on each tick to pull the current
 * operator-typed name; this lets `MapMapping.svelte` change the name
 * via reactive state without restarting the timer.
 */
export function start(getName: () => string): void {
  _getName = getName;
  if (pollTimer !== null) return;
  void pollOnce();
  pollTimer = setInterval(() => void pollOnce(), MAPPING_STATUS_POLL_MS);
}

/** Stop polling and clear the timer. Called on component teardown. */
export function stop(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/** Test helper — reset internal state between tests. */
export function reset(): void {
  precheckStore.set(_empty);
  stop();
  _getName = null;
}
