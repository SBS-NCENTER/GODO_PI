/**
 * issue#14 — Mapping status store. 1 Hz polling of /api/mapping/status.
 *
 * Subscribe-counted lifecycle (mirrors `subscribeMode` + `subscribeRestartPending`):
 * the first subscriber starts the polling timer, the last one stops it.
 *
 * Drives:
 *   - <MappingBanner/> at the top of every page (Starting/Running/Stopping → visible).
 *   - The Mapping sub-tab body in routes/Map.svelte.
 *   - Mode-aware gating in TrackerControls + MapEdit (L14 disabled state).
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet, ApiError } from '$lib/api';
import { MAPPING_STATUS_POLL_MS } from '$lib/constants';
import {
  MAPPING_STATE_IDLE,
  type MappingStatus,
} from '$lib/protocol';

const _idle: MappingStatus = {
  state: MAPPING_STATE_IDLE,
  map_name: null,
  container_id_short: null,
  started_at: null,
  error_detail: null,
  journal_tail_available: false,
};

export const mappingStatus: Writable<MappingStatus> = writable(_idle);

let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscriberCount = 0;

async function pollOnce(): Promise<void> {
  try {
    const s = await apiGet<MappingStatus>('/api/mapping/status');
    mappingStatus.set(s);
  } catch (e) {
    if (e instanceof ApiError) {
      // 5xx during state-file corruption etc. — fall back to Idle so
      // the banner does not stick. The next successful poll will
      // overwrite.
      mappingStatus.set(_idle);
    }
    // Network errors silently keep the previous state.
  }
}

function startPolling(): void {
  if (pollTimer !== null) return;
  void pollOnce();
  pollTimer = setInterval(() => void pollOnce(), MAPPING_STATUS_POLL_MS);
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

export function subscribeMappingStatus(fn: (s: MappingStatus) => void): () => void {
  subscriberCount++;
  if (subscriberCount === 1) startPolling();
  const unsub = mappingStatus.subscribe(fn);
  return () => {
    unsub();
    subscriberCount--;
    if (subscriberCount === 0) stopPolling();
  };
}

/** Action-driven refresh — call after POST /api/mapping/start or stop. */
export async function refreshMappingStatus(): Promise<void> {
  await pollOnce();
}

/** Test helper. */
export function reset(): void {
  mappingStatus.set(_idle);
  stopPolling();
  subscriberCount = 0;
}
