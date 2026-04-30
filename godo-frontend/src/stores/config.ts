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

/** Parallel-fetch the schema + current values. Idempotent.
 *
 * `Promise.allSettled` so a 503 on `/api/config` (tracker unreachable)
 * does NOT block the schema landing in the store — the operator must
 * be able to see the 37 rows + reload-class indicators even when the
 * tracker is dead. `current` is left as `{}` in that case; the
 * `<ConfigEditor>` `fmtCurrent(undefined)` already renders "—". */
export async function refresh(): Promise<void> {
  const [schemaResult, currentResult] = await Promise.allSettled([
    apiGet<ConfigSchemaRow[]>('/api/config/schema'),
    apiGet<ConfigGetResponse>('/api/config'),
  ]);
  const schema = schemaResult.status === 'fulfilled' ? schemaResult.value : [];
  const current = currentResult.status === 'fulfilled' ? currentResult.value : {};
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

/**
 * Track B-CONFIG PR-C — per-row result of `applyBatch`.
 *
 * `ok === true`  → PATCH 200 (and the new value is in the post-loop
 *                  `/api/config` refresh).
 * `ok === false` → PATCH non-2xx OR network failure; `error` carries
 *                  the tracker's `detail` (or `'network_error'`) string
 *                  so `<ConfigEditor>` can render it inline under the
 *                  failing row.
 *
 * The wire-side `value` is intentionally NOT echoed — `applyBatch`'s
 * post-loop `refresh()` is the SSOT for the new authoritative state.
 */
export interface ApplyBatchResult {
  key: string;
  ok: boolean;
  error?: string;
}

/**
 * Best-effort sequential PATCH loop for the operator-driven Apply path
 * in PR-C (page-level Edit-mode safety gate).
 *
 * Semantics (locked by `.claude/memory/project_config_tab_edit_mode_ux.md`):
 * - One PATCH per pending key, in `Object.entries(pending)` snapshot
 *   order pinned at call time. Mode-A S1: a Map is unnecessary at the
 *   prop boundary because we snapshot the entries array up-front and
 *   iterate that — the iteration order is stable even if the caller's
 *   underlying record mutates concurrently.
 * - `await` between PATCHes so the operator-side "k of N" progress
 *   label is meaningful and the tracker is not bombarded.
 * - Each PATCH's outcome is captured in a result row; failures do NOT
 *   short-circuit the loop (memory: "Why best-effort, not all-or-
 *   nothing"). If somebody changes this to "stop on first failure"
 *   without an explicit operator re-ask, that is a regression.
 * - One final `await refresh()` after the loop so the SPA reflects the
 *   tracker's authoritative truth (mixed success leaves some keys at
 *   their new values + some at their old values, all visible in one
 *   coherent snapshot).
 * - One final fire-and-forget `refreshRestartPending()` (mirrors
 *   `set()`'s pattern; a non-hot edit may have flipped the flag).
 *
 * The caller (`Config.svelte`) is responsible for clearing the
 * succeeded keys from its local `pending` dict and for transitioning
 * View ↔ Edit based on the result aggregate.
 */
export async function applyBatch(
  pending: Record<string, ConfigValue>,
): Promise<ApplyBatchResult[]> {
  const entries = Object.entries(pending);
  const results: ApplyBatchResult[] = [];
  for (const [key, value] of entries) {
    const body: ConfigPatchBody = { key, value };
    try {
      await apiPatch<ConfigSetResult>('/api/config', body);
      results.push({ key, ok: true });
    } catch (e) {
      const detail =
        e instanceof ApiError
          ? e.body?.detail || e.body?.err || e.message
          : (e as Error)?.message || 'unknown';
      results.push({ key, ok: false, error: String(detail) });
    }
  }
  // Authoritative read of the tracker's post-loop state. Awaited because
  // Config.svelte must reflect the new truth before flipping back to
  // View mode (or staying in Edit with the failed keys still pending).
  await refresh();
  // Restart-pending flag may have flipped on any non-hot success; the
  // global banner is independent so fire-and-forget is fine.
  void refreshRestartPending();
  return results;
}

/** Test helper. Resets the store. */
export function reset(): void {
  config.set({ schema: [], current: {}, errors: {} });
}
