<script lang="ts">
  /**
   * PR-DIAG — JournalTail panel.
   *
   * Hardcoded allow-list mirror of `services.ALLOWED_SERVICES`
   * (per OQ-DIAG-3). Drift detected by inspection during code review;
   * the webctl-side rejects a non-listed unit anyway (defense in depth).
   *
   * `n` input clamped client-side to LOGS_TAIL_MAX_N_MIRROR; the server's
   * Pydantic Field(le=...) is the authoritative cap.
   */

  import { LOGS_TAIL_DEFAULT_N, LOGS_TAIL_MAX_N_MIRROR } from '$lib/constants';
  import { journalTail, refreshJournalTail, type JournalTailState } from '$stores/journalTail';

  // Mode-A invariant (m): hardcoded mirror of services.ALLOWED_SERVICES.
  const ALLOWED_UNITS = ['godo-tracker', 'godo-webctl', 'godo-irq-pin'];

  let unit = $state<string>(ALLOWED_UNITS[0]);
  let n = $state<number>(LOGS_TAIL_DEFAULT_N);
  let state = $state<JournalTailState>({
    unit: null,
    lines: [],
    loading: false,
    error: null,
    lastFetchedMs: null,
  });

  $effect(() => {
    const unsub = journalTail.subscribe((s) => (state = s));
    return unsub;
  });

  function clampN(v: number): number {
    if (!Number.isFinite(v) || v < 1) return 1;
    if (v > LOGS_TAIL_MAX_N_MIRROR) return LOGS_TAIL_MAX_N_MIRROR;
    return Math.floor(v);
  }

  async function onRefresh(): Promise<void> {
    n = clampN(n);
    await refreshJournalTail(unit, n);
  }
</script>

<div class="journal-panel" data-testid="journal-tail">
  <div class="journal-toolbar">
    <label>
      Unit:
      <select bind:value={unit} data-testid="journal-unit">
        {#each ALLOWED_UNITS as u (u)}
          <option value={u}>{u}</option>
        {/each}
      </select>
    </label>
    <label>
      n:
      <input
        type="number"
        min="1"
        max={LOGS_TAIL_MAX_N_MIRROR}
        bind:value={n}
        data-testid="journal-n"
      />
    </label>
    <button
      type="button"
      onclick={() => void onRefresh()}
      disabled={state.loading}
      data-testid="journal-refresh"
    >
      {state.loading ? '불러오는 중...' : 'Refresh'}
    </button>
    {#if state.lastFetchedMs}
      <span class="journal-meta" data-testid="journal-last-fetched">
        last refreshed: {new Date(state.lastFetchedMs).toLocaleTimeString()}
      </span>
    {/if}
  </div>
  {#if state.error}
    <div class="journal-error" data-testid="journal-error">{state.error}</div>
  {:else if state.lines.length === 0 && !state.loading}
    <div class="journal-empty" data-testid="journal-empty">Refresh를 눌러 로그를 불러오세요.</div>
  {:else}
    <pre class="journal-body" data-testid="journal-body">{state.lines.join('\n')}</pre>
  {/if}
</div>

<style>
  .journal-panel {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .journal-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .journal-toolbar input {
    width: 80px;
  }
  .journal-meta {
    color: var(--color-text-muted);
    font-size: 12px;
  }
  .journal-error {
    color: var(--color-warning-fg);
    background: var(--color-warning-bg);
    padding: 8px;
    border-radius: var(--radius-sm);
    font-family: monospace;
  }
  .journal-empty {
    color: var(--color-text-muted);
    font-style: italic;
  }
  .journal-body {
    background: var(--color-bg-elev);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 8px;
    font-family: monospace;
    font-size: 12px;
    max-height: 320px;
    overflow: auto;
    white-space: pre;
    margin: 0;
  }
</style>
