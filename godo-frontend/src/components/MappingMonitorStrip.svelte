<script lang="ts">
  /**
   * issue#14 — Mapping monitor strip (Docker-only region per S1).
   *
   * Subscribes to `/api/mapping/monitor/stream` (SSE) and renders the
   * Docker-side metrics. RPi5 host stats live in the existing
   * `/api/system/resources/extended/stream` and are NOT included here
   * (operator-locked S1 amendment 2026-05-01).
   *
   * S2 — no fallback polling. When the SSE closes, freeze the last
   * frame and show "중단됨" (Stopped) badge.
   */

  import { onDestroy, onMount } from 'svelte';
  import type { MappingMonitorFrame } from '$lib/protocol';

  let frame = $state<MappingMonitorFrame | null>(null);
  let connected = $state(false);
  let stopped = $state(false);
  let evt: EventSource | null = null;

  function connect(): void {
    if (evt !== null) return;
    evt = new EventSource('/api/mapping/monitor/stream');
    evt.onopen = () => {
      connected = true;
      stopped = false;
    };
    evt.onmessage = (e: MessageEvent<string>) => {
      try {
        const f = JSON.parse(e.data) as MappingMonitorFrame;
        frame = f;
        if (f.container_state === 'no_active' || f.container_state === 'exited') {
          stopped = true;
          connected = false;
          evt?.close();
          evt = null;
        }
      } catch {
        // Parse failure — ignore frame.
      }
    };
    evt.onerror = () => {
      // Server-closed: freeze last frame, show stopped badge. No retry.
      connected = false;
      stopped = true;
      evt?.close();
      evt = null;
    };
  }

  onMount(connect);

  onDestroy(() => {
    if (evt !== null) {
      evt.close();
      evt = null;
    }
  });

  function fmtPct(v: number | null | undefined): string {
    return v == null ? '--' : v.toFixed(1) + '%';
  }
  function fmtBytes(v: number | null | undefined): string {
    if (v == null) return '--';
    const units = ['B', 'KiB', 'MiB', 'GiB'];
    let size = v;
    let i = 0;
    while (size >= 1024 && i < units.length - 1) {
      size /= 1024;
      i++;
    }
    return size.toFixed(1) + ' ' + units[i];
  }
</script>

<section class="strip" data-testid="mapping-monitor-strip">
  <header>
    <h4>Docker 컨테이너</h4>
    {#if connected}
      <span class="badge badge--ok">연결됨</span>
    {:else if stopped}
      <span class="badge badge--stopped">중단됨</span>
    {:else}
      <span class="badge badge--idle">대기 중</span>
    {/if}
  </header>
  <div class="row" class:muted={stopped}>
    <div>
      <span class="label">CPU</span>
      <span class="value">{fmtPct(frame?.container_cpu_pct)}</span>
    </div>
    <div>
      <span class="label">MEM</span>
      <span class="value">{fmtBytes(frame?.container_mem_bytes)}</span>
    </div>
    <div>
      <span class="label">NET RX</span>
      <span class="value">{fmtBytes(frame?.container_net_rx_bytes)}</span>
    </div>
    <div>
      <span class="label">NET TX</span>
      <span class="value">{fmtBytes(frame?.container_net_tx_bytes)}</span>
    </div>
    <div>
      <span class="label">DISK FREE</span>
      <span class="value">{fmtBytes(frame?.var_lib_godo_disk_avail_bytes)}</span>
    </div>
    <div>
      <span class="label">MAP SIZE</span>
      <span class="value">{fmtBytes(frame?.in_progress_map_size_bytes)}</span>
    </div>
  </div>
</section>

<style>
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
  .row.muted {
    opacity: 0.55;
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
  .badge--stopped {
    background: color-mix(in srgb, var(--color-text-muted) 18%, transparent);
    color: var(--color-text-muted);
  }
  .badge--idle {
    background: color-mix(in srgb, var(--color-warning, #f59e0b) 18%, transparent);
    color: var(--color-warning, #f59e0b);
  }
</style>
