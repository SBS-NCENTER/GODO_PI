<script lang="ts">
  /**
   * Track B-CONFIG (PR-CONFIG-β) — main config editor table.
   * Track B-CONFIG PR-C — refactored into a dumb controlled table:
   * `Config.svelte` owns `mode` + `pending` + `applyResults`. This
   * component renders rows + inputs only and emits edits via the
   * `setPending` callback. The previous on-blur PATCH path was
   * removed; Apply is page-level (memory §"How to apply", invariant
   * (z)).
   *
   * One row per schema entry (37 in production). Per-row columns:
   *   [Reload-class indicator | Key | Description | Current | Editor]
   *
   * Type-aware input:
   *   - int / double  → <input type="number" step+min+max from schema>
   *   - string        → <input type="text" maxlength=256>
   *
   * Disabled state: inputs are disabled when `mode === 'view'`, when
   * `!admin`, or when `isApplying === true`. The visual disabled style
   * is theme-aware via existing CSS.
   *
   * The schema `default` value renders as a muted `(default: …)` hint
   * under the Current value (PR-C N3 fold; long defaults wrap inside
   * the column via `word-break: break-all`).
   *
   * Per-row errors come from `applyResults[key].error` (set by the
   * Apply loop in `Config.svelte`); successful rows show a transient
   * ✓ marker until the page-level TTL clears it.
   */

  import {
    RELOAD_CLASS_HOT,
    RELOAD_CLASS_RESTART,
    RELOAD_CLASS_RECALIBRATE,
    type ConfigSchemaRow,
    type ConfigValue,
  } from '$lib/protocol';

  interface ApplyResult {
    ok: boolean;
    error?: string;
  }

  interface Props {
    admin: boolean;
    mode: 'view' | 'edit';
    isApplying: boolean;
    schema: ConfigSchemaRow[];
    current: Record<string, ConfigValue>;
    pending: Record<string, string>;
    applyResults: Record<string, ApplyResult>;
    setPending: (key: string, raw: string) => void;
    clearPending: (key: string) => void;
  }

  let {
    admin,
    mode,
    isApplying,
    schema,
    current,
    pending,
    applyResults,
    setPending,
    clearPending,
  }: Props = $props();

  function fmtCurrent(value: ConfigValue | undefined): string {
    if (value === undefined || value === null) return '—';
    if (typeof value === 'number') return String(value);
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    return value;
  }

  function reloadGlyph(rc: string): { text: string; cls: string; tooltip: string } {
    if (rc === RELOAD_CLASS_HOT) {
      return { text: '✓', cls: 'glyph-hot', tooltip: '즉시 반영' };
    }
    if (rc === RELOAD_CLASS_RESTART) {
      return { text: '!', cls: 'glyph-restart', tooltip: 'godo-tracker 재시작 필요' };
    }
    if (rc === RELOAD_CLASS_RECALIBRATE) {
      return {
        text: '!!',
        cls: 'glyph-recalibrate',
        tooltip: '재시작 + 재캘리브레이션 필요',
      };
    }
    return { text: '?', cls: 'glyph-hot', tooltip: 'unknown class' };
  }

  function inputDisabled(): boolean {
    return mode === 'view' || !admin || isApplying;
  }

  function onKeydown(e: KeyboardEvent, row: ConfigSchemaRow): void {
    if (e.key === 'Escape') {
      e.preventDefault();
      // Bug C fix: explicit Escape uses `clearPending` (drops the key,
      // box reverts to current-value display). Bare empty input via
      // `oninput` no longer drops the key — it preserves the empty
      // string so the operator can delete-and-retype mid-edit. The two
      // gestures map to two different functions.
      clearPending(row.name);
    }
  }

  function onInput(e: Event, name: string): void {
    const target = e.target as HTMLInputElement;
    setPending(name, target.value);
  }
</script>

<table class="config-table" data-testid="config-table">
  <thead>
    <tr>
      <th class="col-glyph"></th>
      <th class="col-key">Key</th>
      <th class="col-desc">Description</th>
      <th class="col-current">Current</th>
      <th class="col-edit">Edit</th>
    </tr>
  </thead>
  <tbody>
    {#each schema as row (row.name)}
      {@const glyph = reloadGlyph(row.reload_class)}
      {@const inputValue = pending[row.name] ?? fmtCurrent(current[row.name])}
      {@const result = applyResults[row.name]}
      <tr data-testid="row-{row.name}">
        <td class="col-glyph">
          <span class="glyph {glyph.cls}" title={glyph.tooltip}>{glyph.text}</span>
        </td>
        <td class="col-key"><code>{row.name}</code></td>
        <td class="col-desc">{row.description}</td>
        <td class="col-current">
          <div class="current-value">{fmtCurrent(current[row.name])}</div>
          <div class="default-hint" data-testid="default-{row.name}">
            (default: {row.default})
          </div>
        </td>
        <td class="col-edit">
          {#if row.type === 'int'}
            <input
              type="number"
              step="1"
              min={row.min}
              max={row.max}
              value={inputValue}
              disabled={inputDisabled()}
              oninput={(e) => onInput(e, row.name)}
              onkeydown={(e) => onKeydown(e, row)}
              data-testid="input-{row.name}"
            />
          {:else if row.type === 'double'}
            <input
              type="number"
              step="any"
              min={row.min}
              max={row.max}
              value={inputValue}
              disabled={inputDisabled()}
              oninput={(e) => onInput(e, row.name)}
              onkeydown={(e) => onKeydown(e, row)}
              data-testid="input-{row.name}"
            />
          {:else}
            <input
              type="text"
              maxlength={256}
              value={inputValue}
              disabled={inputDisabled()}
              oninput={(e) => onInput(e, row.name)}
              onkeydown={(e) => onKeydown(e, row)}
              data-testid="input-{row.name}"
            />
          {/if}
          {#if result?.ok}
            <span class="marker marker-ok" data-testid="marker-{row.name}">✓</span>
          {:else if result && !result.ok}
            <span class="marker marker-fail" data-testid="marker-{row.name}">✗</span>
          {/if}
          {#if result && !result.ok && result.error}
            <div class="error" data-testid="error-{row.name}">{result.error}</div>
          {/if}
        </td>
      </tr>
    {/each}
  </tbody>
</table>

<style>
  .config-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92em;
  }
  thead th {
    text-align: left;
    padding: var(--space-2);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg-elev);
  }
  tbody td {
    padding: var(--space-2);
    border-bottom: 1px solid var(--color-border);
    vertical-align: top;
  }
  .col-glyph {
    width: 2em;
  }
  .col-key {
    width: 18em;
  }
  .col-current {
    width: 10em;
    color: var(--color-text-muted);
  }
  /* Edit column is sized to roughly match Current (operator UX request
     2026-05-02 KST — long values like /var/lib/godo/maps/active.pgm were
     getting truncated in the input box because the browser was giving
     all the slack to .col-desc). col-edit input itself is width:100% of
     this cell, so the cell width drives the input width. */
  .col-edit {
    width: 11em;
  }
  /* Description fills the remaining horizontal space; the slight cap
     here prevents long descriptions from squeezing the Edit cell on
     narrow viewports. */
  .col-desc {
    max-width: 28em;
  }
  .current-value {
    color: var(--color-text);
  }
  .default-hint {
    margin-top: 2px;
    color: var(--color-text-muted);
    font-size: 0.85em;
    word-break: break-all;
    max-width: 100%;
  }
  .col-edit input {
    width: 100%;
    box-sizing: border-box;
    padding: var(--space-1) var(--space-2);
    background: var(--color-bg);
    color: var(--color-text);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm, 4px);
  }
  .col-edit input:disabled {
    color: var(--color-text-muted);
    background: var(--color-bg-elev);
    cursor: not-allowed;
  }
  .glyph {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.5em;
    height: 1.5em;
    border-radius: 999px;
    font-weight: 700;
    font-size: 0.85em;
    cursor: help;
  }
  .glyph-hot {
    background: var(--color-bg-elev);
    color: var(--color-text-muted);
    border: 1px solid var(--color-border);
  }
  .glyph-restart,
  .glyph-recalibrate {
    background: var(--color-error, #c62828);
    color: white;
  }
  .marker {
    display: inline-block;
    margin-left: var(--space-2);
    font-weight: 700;
  }
  .marker-ok {
    color: var(--color-status-ok, #2e7d32);
  }
  .marker-fail {
    color: var(--color-error, #c62828);
  }
  .error {
    margin-top: var(--space-1);
    color: var(--color-error, #c62828);
    font-size: 0.85em;
  }
</style>
