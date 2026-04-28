<script lang="ts">
  import { MAP_SCAN_FRESHNESS_MS } from '$lib/constants';
  import type { LastScan } from '$lib/protocol';
  import { scanOverlay, toggleScanOverlay } from '$stores/scanOverlay';

  interface Props {
    scan: LastScan | null;
  }
  let { scan }: Props = $props();

  let on = $state(false);
  scanOverlay.subscribe((v) => (on = v));

  // Mode-A M2 fold: freshness uses ARRIVAL wall-clock, NOT
  // published_mono_ns (different clock domains).
  const FRESH_LABEL = '최신';
  const STALE_LABEL = '약간 지연됨';
  const FROZEN_LABEL = '정지됨';
  // Sub-window inside MAP_SCAN_FRESHNESS_MS where the scan is "fully
  // fresh" — anything between this and MAP_SCAN_FRESHNESS_MS shows
  // "약간 지연됨", and anything beyond MAP_SCAN_FRESHNESS_MS shows
  // "정지됨". Half the freshness window is a generous fully-fresh
  // band (5 ticks @ 5 Hz becomes 2.5 ticks of "최신").
  const FULLY_FRESH_WINDOW_MS = MAP_SCAN_FRESHNESS_MS / 2;

  // Tick the freshness label on a 250 ms cadence so the badge animates
  // even when no SSE frame arrives (e.g. tracker idle).
  let now = $state(Date.now());
  $effect(() => {
    const id = setInterval(() => {
      now = Date.now();
    }, 250);
    return () => clearInterval(id);
  });

  function freshnessLabel(s: LastScan | null, currentMs: number): string {
    if (!s || !s._arrival_ms) return FROZEN_LABEL;
    const ageMs = currentMs - s._arrival_ms;
    if (ageMs < FULLY_FRESH_WINDOW_MS) return FRESH_LABEL;
    if (ageMs < MAP_SCAN_FRESHNESS_MS) return STALE_LABEL;
    return FROZEN_LABEL;
  }

  // Recompute when scan changes OR on the heartbeat tick.
  let label = $derived(freshnessLabel(scan, now));
</script>

<div class="scan-toggle" data-testid="scan-toggle-wrap">
  <button
    type="button"
    class="scan-toggle-btn"
    class:on
    onclick={toggleScanOverlay}
    data-testid="scan-toggle-btn"
    aria-pressed={on}
  >
    {on ? '라이다 보기 켜짐' : '라이다 보기 꺼짐'}
  </button>
  {#if on}
    <span class="freshness muted" data-testid="scan-freshness" data-state={label}>
      {label}
    </span>
  {/if}
</div>

<style>
  .scan-toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .scan-toggle-btn {
    padding: 4px 10px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg-elev);
    color: var(--color-text);
    cursor: pointer;
  }
  .scan-toggle-btn.on {
    border-color: var(--color-accent);
    color: var(--color-accent);
  }
  .freshness {
    font-size: 0.85em;
  }
</style>
