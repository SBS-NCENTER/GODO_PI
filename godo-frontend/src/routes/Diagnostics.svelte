<script lang="ts">
  /**
   * PR-DIAG — Diagnostics page (B-DIAG row in FRONT_DESIGN §8).
   *
   * Four sub-panels (auto-grid on >=420 px columns):
   *   (a) Pose telemetry — re-uses the `lastPose` shape from DiagFrame.
   *   (b) RT-thread jitter — p50/p95/p99/max chips + p99 sparkline.
   *   (c) AMCL iteration rate + Resources — Hz chip + cpu/mem/disk.
   *   (d) Journal tail (`<JournalTail/>`).
   *
   * Stale-frame greying via `DIAG_FRESHNESS_MS` against
   * `Date.now() - frame._arrival_ms` (per Track D Mode-A M2 + PR-DIAG
   * N4 fold). Each sub-panel can also be sentinel'd individually
   * (TM9: a single sub-fetch failure leaves the others live).
   */

  import { onDestroy, onMount } from 'svelte';
  import DiagSparkline from '$components/DiagSparkline.svelte';
  import JournalTail from '$components/JournalTail.svelte';
  import {
    AMCL_RATE_PANEL_COLOR,
    DIAG_FRESHNESS_MS,
    JITTER_PANEL_COLOR,
    RESOURCES_PANEL_COLOR,
  } from '$lib/constants';
  import type { DiagFrame } from '$lib/protocol';
  import { diagSparklines, subscribeDiag, type DiagSparklineState } from '$stores/diag';

  let frame = $state<DiagFrame | null>(null);
  let sparklines = $state<DiagSparklineState>({
    jitter_p50_ns: [],
    jitter_p99_ns: [],
    amcl_rate_hz: [],
    cpu_temp_c: [],
    mem_used_pct: [],
  });
  let unsub: (() => void) | null = null;
  let unsubSparks: (() => void) | null = null;
  // Force a re-render every 1 s so the freshness gate ticks even when no
  // new frame arrives (so a stale panel actually goes grey on screen).
  let renderTick = $state(0);
  let tickTimer: ReturnType<typeof setInterval> | null = null;

  onMount(() => {
    unsub = subscribeDiag((f) => (frame = f));
    unsubSparks = diagSparklines.subscribe((s) => (sparklines = s));
    tickTimer = setInterval(() => (renderTick += 1), 1000);
  });

  onDestroy(() => {
    unsub?.();
    unsubSparks?.();
    if (tickTimer !== null) clearInterval(tickTimer);
  });

  function isStale(arrival_ms: number | undefined): boolean {
    void renderTick; // depend on the tick so the gate re-evaluates each second
    if (!arrival_ms) return true;
    return Date.now() - arrival_ms > DIAG_FRESHNESS_MS;
  }

  function fmtNs(v: number): string {
    if (Math.abs(v) >= 1_000_000) return (v / 1_000_000).toFixed(2) + ' ms';
    if (Math.abs(v) >= 1_000) return (v / 1_000).toFixed(1) + ' µs';
    return v.toFixed(0) + ' ns';
  }
  function fmtHz(v: number): string {
    return v.toFixed(2) + ' Hz';
  }
  function fmtPct(v: number): string {
    return v.toFixed(1) + ' %';
  }
  function fmtTempC(v: number): string {
    return v.toFixed(1) + ' °C';
  }
  function fmtBytes(v: number | null): string {
    if (v === null) return '—';
    const gb = v / (1 << 30);
    return gb.toFixed(2) + ' GiB';
  }

  let stale = $derived(isStale(frame?._arrival_ms));
  let pose = $derived(frame?.pose);
  let jitter = $derived(frame?.jitter);
  let amclRate = $derived(frame?.amcl_rate);
  let resources = $derived(frame?.resources);
</script>

<div data-testid="diag-page">
  <div class="breadcrumb">GODO &gt; Diagnostics</div>
  <h2>Diagnostics</h2>

  {#if stale}
    <div class="stale-banner" data-testid="diag-stale-banner" role="status">
      마지막 진단 프레임이 {DIAG_FRESHNESS_MS / 1000}초 이상 갱신되지 않았습니다.
    </div>
  {/if}

  <div class="panels">
    <!-- (a) Pose -->
    <section class="panel" data-testid="panel-pose" class:stale>
      <h3>Pose</h3>
      {#if pose && pose.valid}
        <div class="kv-grid">
          <span>x</span><span>{pose.x_m.toFixed(3)} m</span>
          <span>y</span><span>{pose.y_m.toFixed(3)} m</span>
          <span>yaw</span><span>{pose.yaw_deg.toFixed(2)}°</span>
          <span>xy_std</span><span>{(pose.xy_std_m * 1000).toFixed(1)} mm</span>
          <span>iters</span><span>{pose.iterations}</span>
          <span>converged</span><span>{pose.converged ? 'yes' : 'no'}</span>
        </div>
      {:else}
        <div class="panel-empty" data-testid="panel-pose-empty">AMCL pose unavailable.</div>
      {/if}
    </section>

    <!-- (b) Jitter -->
    <section class="panel" data-testid="panel-jitter" class:stale>
      <h3>RT thread jitter</h3>
      {#if jitter && jitter.valid}
        <div class="kv-grid">
          <span>p50</span><span>{fmtNs(jitter.p50_ns)}</span>
          <span>p95</span><span>{fmtNs(jitter.p95_ns)}</span>
          <span>p99</span><span>{fmtNs(jitter.p99_ns)}</span>
          <span>max</span><span>{fmtNs(jitter.max_ns)}</span>
          <span>mean</span><span>{fmtNs(jitter.mean_ns)}</span>
          <span>samples</span><span>{jitter.sample_count}</span>
        </div>
        <div class="sparklines">
          <DiagSparkline
            values={sparklines.jitter_p99_ns}
            color={JITTER_PANEL_COLOR}
            label="p99 (12 s)"
            formatValue={fmtNs}
          />
        </div>
      {:else}
        <div class="panel-empty" data-testid="panel-jitter-empty">
          RT thread jitter unavailable.
        </div>
      {/if}
    </section>

    <!-- (c) AMCL rate + resources -->
    <section class="panel" data-testid="panel-amcl-rate" class:stale>
      <h3>AMCL iteration rate &amp; resources</h3>
      {#if amclRate && amclRate.valid}
        <div class="kv-grid">
          <span>rate</span><span>{fmtHz(amclRate.hz)}</span>
          <span>total iters</span><span>{amclRate.total_iteration_count}</span>
        </div>
      {:else}
        <div class="panel-empty" data-testid="panel-amcl-rate-empty">
          AMCL rate is 0 Hz (Idle: LiDAR is parked by design).
        </div>
      {/if}
      <div class="sparklines">
        <DiagSparkline
          values={sparklines.amcl_rate_hz}
          color={AMCL_RATE_PANEL_COLOR}
          label="rate (12 s)"
          formatValue={fmtHz}
        />
        <DiagSparkline
          values={sparklines.cpu_temp_c}
          color={RESOURCES_PANEL_COLOR}
          label="cpu temp (12 s)"
          formatValue={fmtTempC}
        />
        <DiagSparkline
          values={sparklines.mem_used_pct}
          color={RESOURCES_PANEL_COLOR}
          label="mem used (12 s)"
          formatValue={fmtPct}
        />
      </div>
      {#if resources}
        <div class="kv-grid">
          <span>cpu temp</span>
          <span>{resources.cpu_temp_c !== null ? fmtTempC(resources.cpu_temp_c) : '—'}</span>
          <span>mem</span>
          <span
            >{resources.mem_used_pct !== null ? fmtPct(resources.mem_used_pct) : '—'} of
            {fmtBytes(resources.mem_total_bytes)}</span
          >
          <span>disk</span>
          <span
            >{resources.disk_used_pct !== null ? fmtPct(resources.disk_used_pct) : '—'} of
            {fmtBytes(resources.disk_total_bytes)}</span
          >
        </div>
      {/if}
    </section>

    <!-- (d) Journal tail -->
    <section class="panel panel-wide" data-testid="panel-journal">
      <h3>Journal tail</h3>
      <JournalTail />
    </section>
  </div>
</div>

<style>
  h2 {
    margin-top: 0;
  }
  .panels {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 12px;
    margin-top: 12px;
  }
  .panel {
    background: var(--color-bg-elev);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 12px;
  }
  .panel-wide {
    grid-column: 1 / -1;
  }
  .panel.stale {
    opacity: 0.6;
  }
  .panel h3 {
    margin: 0 0 8px;
    font-size: 16px;
  }
  .kv-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 4px 12px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
  .panel-empty {
    color: var(--color-text-muted);
    font-style: italic;
    padding: 8px 0;
  }
  .sparklines {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .stale-banner {
    margin: 0 0 12px;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
    background: var(--color-warning-bg);
    color: var(--color-warning-fg);
    border: 1px solid var(--color-warning-border);
    font-size: 14px;
  }
</style>
