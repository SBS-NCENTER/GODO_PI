/**
 * Config store — Track B-CONFIG (PR-CONFIG-β).
 *
 * Refresh-on-action only (mirrors maps store pattern, Mode-A N6 — no
 * periodic polling). The store re-fetches:
 *   (a) explicit `refresh()` (Config page mount),
 *   (b) post-`set(key, value)` (authoritative read from tracker).
 *
 * Optimistic update + rollback on PATCH error: the SPA flips the local
 * value immediately for snappier UX, then either confirms via refresh
 * on 200 or rolls back to the pre-set snapshot on 400. Per-row error
 * text (`detail` from tracker) is surfaced via `errors[key]` so
 * <ConfigEditor> can render an inline message under the input.
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet, apiPatch, ApiError } from '$lib/api';
import type {
  ConfigGetResponse,
  ConfigPatchBody,
  ConfigSchemaRow,
  ConfigSetResult,
  ConfigValue,
} from '$lib/protocol';
import { refresh as refreshRestartPending } from './restartPending';

export interface ConfigState {
  schema: ConfigSchemaRow[];
  current: ConfigGetResponse;
  errors: Record<string, string>;
}

export const config: Writable<ConfigState> = writable({
  schema: [],
  current: {},
  errors: {},
});

let _state: ConfigState = { schema: [], current: {}, errors: {} };
config.subscribe((s) => {
  _state = s;
});

/** Parallel-fetch the schema + current values. Idempotent. */
export async function refresh(): Promise<void> {
  const [schema, current] = await Promise.all([
    apiGet<ConfigSchemaRow[]>('/api/config/schema'),
    apiGet<ConfigGetResponse>('/api/config'),
  ]);
  config.set({ schema, current, errors: {} });
}

/**
 * Apply a single edit. Optimistic UI: the local store updates first,
 * then PATCH; on 400 the value rolls back to the pre-set snapshot and
 * the tracker's `detail` text appears in `errors[key]`.
 */
export async function set(key: string, value: ConfigValue): Promise<ConfigSetResult> {
  const previous = _state.current[key];
  // Optimistic flip + clear any previous error for this key.
  config.update((s) => ({
    ...s,
    current: { ...s.current, [key]: value },
    errors: { ...s.errors, [key]: '' },
  }));
  const body: ConfigPatchBody = { key, value };
  try {
    const resp = await apiPatch<ConfigSetResult>('/api/config', body);
    // Authoritative refresh of the values dict (tracker may have
    // round-tripped through the schema's type coercion). The schema
    // never changes within a tracker boot, so we re-fetch only
    // /api/config, not /api/config/schema.
    const current = await apiGet<ConfigGetResponse>('/api/config');
    config.update((s) => ({ ...s, current }));
    // Refresh the restart-pending banner: a non-hot edit will have
    // touched the flag tracker-side. Fire-and-forget — the banner
    // either appears on the next subscriber tick or stays clean.
    void refreshRestartPending();
    return resp;
  } catch (e) {
    // Rollback the optimistic flip and surface the tracker error text.
    const detail = e instanceof ApiError ? e.body?.detail || e.body?.err || e.message : 'unknown';
    config.update((s) => ({
      ...s,
      current: { ...s.current, [key]: previous },
      errors: { ...s.errors, [key]: String(detail) },
    }));
    throw e;
  }
}

/** Test helper. Resets the store. */
export function reset(): void {
  config.set({ schema: [], current: {}, errors: {} });
}
