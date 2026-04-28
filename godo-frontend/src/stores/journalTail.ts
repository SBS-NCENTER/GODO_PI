/**
 * PR-DIAG (Track B-DIAG) — JournalTail store.
 *
 * Manual-refresh on-demand (NOT polled). Operator clicks the refresh
 * button → store calls `/api/logs/tail?unit=…&n=…` and updates state.
 */

import { writable, type Writable } from 'svelte/store';
import { apiGet } from '$lib/api';

export interface JournalTailState {
  unit: string | null;
  lines: string[];
  loading: boolean;
  error: string | null;
  lastFetchedMs: number | null;
}

function emptyState(): JournalTailState {
  return {
    unit: null,
    lines: [],
    loading: false,
    error: null,
    lastFetchedMs: null,
  };
}

export const journalTail: Writable<JournalTailState> = writable(emptyState());

export async function refreshJournalTail(unit: string, n: number): Promise<void> {
  journalTail.update((s) => ({ ...s, unit, loading: true, error: null }));
  try {
    const lines = await apiGet<string[]>(`/api/logs/tail?unit=${encodeURIComponent(unit)}&n=${n}`);
    journalTail.set({
      unit,
      lines,
      loading: false,
      error: null,
      lastFetchedMs: Date.now(),
    });
  } catch (e) {
    journalTail.update((s) => ({
      ...s,
      loading: false,
      error: e instanceof Error ? e.message : String(e),
    }));
  }
}

/** Test-only — reset to fresh state. */
export function _resetJournalTailForTests(): void {
  journalTail.set(emptyState());
}
