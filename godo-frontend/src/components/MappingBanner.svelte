<script lang="ts">
  /**
   * issue#14 — Mapping in-progress banner.
   *
   * Visible when mappingStatus.state ∈ {starting, running, stopping}.
   * Hidden on idle (no banner) and on failed (the Mapping sub-tab body
   * surfaces the failure detail; a top-level "still in progress" banner
   * would mislead).
   */

  import { onDestroy, onMount } from 'svelte';
  import {
    MAPPING_STATE_RUNNING,
    MAPPING_STATE_STARTING,
    MAPPING_STATE_STOPPING,
    type MappingStatus,
  } from '$lib/protocol';
  import { subscribeMappingStatus } from '$stores/mappingStatus';

  let status = $state<MappingStatus | null>(null);
  let unsub: (() => void) | null = null;

  onMount(() => {
    unsub = subscribeMappingStatus((s) => (status = s));
  });

  onDestroy(() => unsub?.());

  let visible = $derived(
    status !== null &&
      (status.state === MAPPING_STATE_STARTING ||
        status.state === MAPPING_STATE_RUNNING ||
        status.state === MAPPING_STATE_STOPPING),
  );
</script>

{#if visible && status}
  <div class="banner" data-testid="mapping-banner" role="status">
    <span class="icon" aria-hidden="true">●</span>
    <span class="text">
      매핑 진행 중: <strong>{status.map_name ?? ''}</strong>
      {#if status.state === MAPPING_STATE_STARTING}<span class="muted"> (시작 중)</span>{/if}
      {#if status.state === MAPPING_STATE_STOPPING}<span class="muted"> (저장 중)</span>{/if}
    </span>
  </div>
{/if}

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: color-mix(in srgb, var(--color-warning, #f59e0b) 14%, var(--color-bg));
    border-left: 3px solid var(--color-warning, #f59e0b);
    color: var(--color-text);
    font-size: 0.95em;
  }
  .icon {
    color: var(--color-warning, #f59e0b);
    font-size: 0.8em;
  }
  .text {
    flex: 1;
  }
  .muted {
    opacity: 0.75;
  }
</style>
