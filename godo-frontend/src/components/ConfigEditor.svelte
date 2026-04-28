<script lang="ts">
  /**
   * Track B-CONFIG (PR-CONFIG-β) — main config editor table.
   *
   * One row per schema entry (37 in production). Per-row columns:
   *   [Reload-class indicator | Key | Description | Current | Editor]
   *
   * Type-aware input:
   *   - int / double  → <input type="number" step+min+max from schema>
   *   - string        → <input type="text" maxlength=256>
   *
   * Submit-on-blur or Enter; Escape cancels back to current. On 400
   * the row's value rolls back and the tracker's `detail` shows below
   * the input.
   *
   * Admin-gating: when `admin === false` (anon viewer), inputs render
   * disabled. The PATCH itself is admin-gated server-side; this is UX
   * polish only.
   */

  import { onDestroy, onMount } from 'svelte';
  import { config as configStore, refresh, set as applySet } from '$stores/config';
  import {
    RELOAD_CLASS_HOT,
    RELOAD_CLASS_RESTART,
    RELOAD_CLASS_RECALIBRATE,
    type ConfigSchemaRow,
    type ConfigValue,
  } from '$lib/protocol';

  interface Props {
    admin: boolean;
  }
  let { admin }: Props = $props();

  let schema = $state<ConfigSchemaRow[]>([]);
  let current = $state<Record<string, ConfigValue>>({});
  let errors = $state<Record<string, string>>({});
  // Per-row pending text — what's in the input box right now.
  let pending = $state<Record<string, string>>({});
  let busy = $state<Record<string, boolean>>({});
  let unsub: (() => void) | null = null;

  onMount(() => {
    unsub = configStore.subscribe((s) => {
      schema = s.schema;
      current = s.current;
      errors = s.errors;
    });
    void refresh();
  });

  onDestroy(() => {
    unsub?.();
  });

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

  // Coerce the input string into the schema's typed value before sending.
  function coerce(row: ConfigSchemaRow, raw: string): ConfigValue | null {
    const trimmed = raw.trim();
    if (row.type === 'int') {
      if (!/^-?\d+$/.test(trimmed)) return null;
      return parseInt(trimmed, 10);
    }
    if (row.type === 'double') {
      const n = Number(trimmed);
      if (Number.isNaN(n)) return null;
      return n;
    }
    return trimmed;
  }

  async function submit(row: ConfigSchemaRow): Promise<void> {
    const raw = pending[row.name] ?? fmtCurrent(current[row.name]);
    const coerced = coerce(row, raw);
    if (coerced === null) {
      errors = { ...errors, [row.name]: `bad ${row.type} literal` };
      return;
    }
    busy = { ...busy, [row.name]: true };
    try {
      await applySet(row.name, coerced);
      pending = { ...pending, [row.name]: '' };
    } catch {
      // The store already rolled back + populated `errors[key]`.
    } finally {
      busy = { ...busy, [row.name]: false };
    }
  }

  function onKeydown(e: KeyboardEvent, row: ConfigSchemaRow): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      void submit(row);
    } else if (e.key === 'Escape') {
      pending = { ...pending, [row.name]: '' };
    }
  }

  function onInput(e: Event, name: string): void {
    const target = e.target as HTMLInputElement;
    pending = { ...pending, [name]: target.value };
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
      <tr data-testid="row-{row.name}">
        <td class="col-glyph">
          <span class="glyph {glyph.cls}" title={glyph.tooltip}>{glyph.text}</span>
        </td>
        <td class="col-key"><code>{row.name}</code></td>
        <td class="col-desc">{row.description}</td>
        <td class="col-current">{fmtCurrent(current[row.name])}</td>
        <td class="col-edit">
          {#if row.type === 'int'}
            <input
              type="number"
              step="1"
              min={row.min}
              max={row.max}
              value={inputValue}
              disabled={!admin || busy[row.name]}
              oninput={(e) => onInput(e, row.name)}
              onblur={() => admin && submit(row)}
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
              disabled={!admin || busy[row.name]}
              oninput={(e) => onInput(e, row.name)}
              onblur={() => admin && submit(row)}
              onkeydown={(e) => onKeydown(e, row)}
              data-testid="input-{row.name}"
            />
          {:else}
            <input
              type="text"
              maxlength={256}
              value={inputValue}
              disabled={!admin || busy[row.name]}
              oninput={(e) => onInput(e, row.name)}
              onblur={() => admin && submit(row)}
              onkeydown={(e) => onKeydown(e, row)}
              data-testid="input-{row.name}"
            />
          {/if}
          {#if errors[row.name]}
            <div class="error" data-testid="error-{row.name}">{errors[row.name]}</div>
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
  .error {
    margin-top: var(--space-1);
    color: var(--color-error, #c62828);
    font-size: 0.85em;
  }
</style>
