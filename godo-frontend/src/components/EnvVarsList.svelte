<script lang="ts">
  /**
   * Track B-SYSTEM PR-2 — collapsible env-var list for ServiceStatusCard.
   *
   * Renders KEY=VALUE lines under a `<details>` collapse. Values that
   * equal the redaction placeholder get a `(secret)` suffix label and
   * a muted color class so the operator can tell at a glance which
   * keys were filtered.
   */

  import { REDACTED_PLACEHOLDER } from '$lib/protocol';

  interface Props {
    env: Record<string, string>;
  }
  let { env }: Props = $props();

  // Sort keys alphabetically so two snapshots that differ only in dict
  // iteration order render identically.
  let keys = $derived(Object.keys(env).sort());

  function isRedacted(value: string): boolean {
    return value === REDACTED_PLACEHOLDER;
  }
</script>

<details class="env-list" data-testid="env-vars-list">
  <summary class="muted">Environment ({keys.length})</summary>
  {#if keys.length === 0}
    <div class="muted env-empty" data-testid="env-empty">(none)</div>
  {:else}
    <ul>
      {#each keys as key (key)}
        <li class:redacted={isRedacted(env[key])} data-testid={`env-row-${key}`}>
          <span class="key">{key}</span>
          <span class="eq">=</span>
          <span class="value">{env[key]}</span>
          {#if isRedacted(env[key])}
            <span class="muted secret-tag" data-testid={`env-secret-${key}`}>(secret)</span>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</details>

<style>
  .env-list {
    margin-top: 8px;
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
  }
  .env-list summary {
    cursor: pointer;
  }
  .env-list ul {
    margin: 6px 0 0;
    padding-left: 0;
    list-style: none;
  }
  .env-list li {
    padding: 2px 0;
    word-break: break-all;
  }
  .env-list li.redacted .value {
    color: var(--color-text-muted);
    font-style: italic;
  }
  .key {
    font-weight: 600;
  }
  .eq {
    margin: 0 4px;
    color: var(--color-text-muted);
  }
  .secret-tag {
    margin-left: 6px;
    font-size: 0.85em;
  }
  .env-empty {
    margin-top: 6px;
  }
</style>
