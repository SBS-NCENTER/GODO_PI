<script lang="ts">
  /**
   * issue#16 HIL hot-fix (2026-05-02 KST) — RPi5 host monitor strip.
   *
   * Mirrors MappingMonitorStrip's compact numeric layout so the two
   * panels align in vertical height inside the Mapping sub-tab's
   * monitor grid. Operator HIL: ResourceBars (per-core bars + memory
   * bar + disk bar) was visually too tall and animation-heavy compared
   * to the Docker container strip; numbers-only mirrors the operator's
   * triage shape.
   *
   * Subscribes to the existing refcounted `resourcesExtended` SSE
   * store (no new endpoint, no new backend code — frontend-only).
   */

  import { onDestroy, onMount } from 'svelte';
  import type { ExtendedResources } from '$lib/protocol';
  import { subscribeResourcesExtended } from '$stores/resourcesExtended';

  let snapshot = $state<ExtendedResources>({
    cpu_per_core: [],
    cpu_aggregate_pct: 0,
    mem_total_mb: null,
    mem_used_mb: null,
    disk_pct: null,
    published_mono_ns: 0,
    _arrival_ms: undefined,
  });
  let unsub: (() => void) | null = null;

  onMount(() => {
    unsub = subscribeResourcesExtended((s: ExtendedResources) => (snapshot = s));
  });

  onDestroy(() => {
    unsub?.();
  });

  function fmtPct(v: number | null | undefined): string {
    return v == null ? '--' : v.toFixed(1) + '%';
  }
  function fmtMem(used: number | null, total: number | null): string {
    if (used === null || total === null) return '--';
    const usedGiB = used / 1024;
    const totalGiB = total / 1024;
    return `${usedGiB.toFixed(2)} / ${totalGiB.toFixed(2)} GiB`;
  }
</script>

<section class="strip" data-testid="mapping-host-strip">
  <header>
    <h4>RPi5 호스트</h4>
    <span class="badge badge--ok">실시간</span>
  </header>
  <div class="row">
    <div>
      <span class="label">CPU avg</span>
      <span class="value">{fmtPct(snapshot.cpu_aggregate_pct)}</span>
    </div>
    {#each snapshot.cpu_per_core as pct, i (i)}
      <div>
        <span class="label">cpu{i}</span>
        <span class="value">{fmtPct(pct)}</span>
      </div>
    {/each}
    <div>
      <span class="label">MEM</span>
      <span class="value">{fmtMem(snapshot.mem_used_mb, snapshot.mem_total_mb)}</span>
    </div>
    <div>
      <span class="label">DISK</span>
      <span class="value">{fmtPct(snapshot.disk_pct)}</span>
    </div>
  </div>
</section>

<style>
  /* Visual parity with MappingMonitorStrip — same border, padding,
     row-flex, label/value typography. Heights line up inside the
     monitor grid by construction. */
  .strip {
    margin: var(--space-2) 0;
    padding: var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
  }
  header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  .row > div {
    display: flex;
    flex-direction: column;
    min-width: 80px;
  }
  .label {
    font-size: 0.75em;
    color: var(--color-text-muted);
  }
  .value {
    font-family: var(--font-mono, monospace);
  }
  .badge {
    padding: 2px 6px;
    border-radius: 999px;
    font-size: 0.75em;
  }
  .badge--ok {
    background: color-mix(in srgb, var(--color-success, #16a34a) 18%, transparent);
    color: var(--color-success, #16a34a);
  }
</style>
