<script lang="ts">
  /**
   * Track B-SYSTEM PR-B — Extended resources sub-tab.
   *
   * Three widgets, all bars + numbers (no SVG, no rings — operator
   * decision 2026-04-30 06:38 KST):
   *   - per-core CPU bars (one row per observed core)
   *   - mem bar (used vs total MiB)
   *   - disk bar (pct used)
   *
   * Null-tolerant: backend can yield null for any field if the source
   * is missing (e.g. /proc/meminfo unreadable in a stripped container).
   */

  import { CPU_BAR_HEIGHT_PX } from '$lib/constants';
  import type { ExtendedResources } from '$lib/protocol';

  interface Props {
    snapshot: ExtendedResources;
  }

  const { snapshot }: Props = $props();

  function fmtPct(v: number | null): string {
    return v !== null ? v.toFixed(1) + ' %' : '—';
  }
  function fmtMb(v: number | null): string {
    if (v === null) return '—';
    if (v >= 1024) return (v / 1024).toFixed(2) + ' GiB';
    return v.toFixed(0) + ' MiB';
  }
  function clampPct(v: number | null): number {
    if (v === null) return 0;
    return Math.max(0, Math.min(100, v));
  }
</script>

<div class="resource-bars" data-testid="resource-bars">
  <section class="widget" data-testid="rb-per-core">
    <h4>Per-core CPU</h4>
    {#if snapshot.cpu_per_core.length === 0}
      <div class="muted">CPU per-core 데이터를 읽을 수 없습니다.</div>
    {:else}
      {#each snapshot.cpu_per_core as pct, i (i)}
        <div class="bar-row" data-testid={`rb-core-${i}`}>
          <span class="label">cpu{i}</span>
          <div class="bar" style:height="{CPU_BAR_HEIGHT_PX}px">
            <div class="bar-fill" style:width="{clampPct(pct)}%"></div>
          </div>
          <span class="value">{fmtPct(pct)}</span>
        </div>
      {/each}
      <div class="bar-row aggregate" data-testid="rb-cpu-aggregate">
        <span class="label">avg</span>
        <div class="bar" style:height="{CPU_BAR_HEIGHT_PX}px">
          <div class="bar-fill agg" style:width="{clampPct(snapshot.cpu_aggregate_pct)}%"></div>
        </div>
        <span class="value">{fmtPct(snapshot.cpu_aggregate_pct)}</span>
      </div>
    {/if}
  </section>

  <section class="widget" data-testid="rb-mem">
    <h4>Memory</h4>
    <div class="bar-row" data-testid="rb-mem-row">
      <span class="label">used</span>
      <div class="bar" style:height="{CPU_BAR_HEIGHT_PX}px">
        <div
          class="bar-fill"
          style:width="{snapshot.mem_total_mb && snapshot.mem_used_mb !== null
            ? Math.max(0, Math.min(100, (100 * snapshot.mem_used_mb) / snapshot.mem_total_mb))
            : 0}%"
        ></div>
      </div>
      <span class="value">
        {fmtMb(snapshot.mem_used_mb)} / {fmtMb(snapshot.mem_total_mb)}
      </span>
    </div>
  </section>

  <section class="widget" data-testid="rb-disk">
    <h4>Disk</h4>
    <div class="bar-row" data-testid="rb-disk-row">
      <span class="label">used</span>
      <div class="bar" style:height="{CPU_BAR_HEIGHT_PX}px">
        <div class="bar-fill" style:width="{clampPct(snapshot.disk_pct)}%"></div>
      </div>
      <span class="value">{fmtPct(snapshot.disk_pct)}</span>
    </div>
  </section>
</div>

<style>
  .resource-bars {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .widget {
    background: var(--color-bg-elev);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: var(--space-3);
  }
  .widget h4 {
    margin: 0 0 var(--space-2);
    font-size: var(--font-size-md);
    color: var(--color-text-muted);
    font-weight: normal;
  }
  .bar-row {
    display: grid;
    grid-template-columns: 56px 1fr 100px;
    gap: var(--space-2);
    align-items: center;
    margin-bottom: var(--space-1);
    font-size: var(--font-size-sm);
    font-variant-numeric: tabular-nums;
  }
  .bar-row.aggregate {
    margin-top: var(--space-2);
    padding-top: var(--space-2);
    border-top: 1px solid var(--color-border);
  }
  .bar {
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    background: var(--color-accent);
    transition: width 200ms linear;
  }
  .bar-fill.agg {
    background: var(--color-status-warn);
  }
  .label {
    color: var(--color-text-muted);
    font-family: var(--font-mono);
  }
  .value {
    text-align: right;
    color: var(--color-text);
  }
  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-sm);
    font-style: italic;
  }
</style>
