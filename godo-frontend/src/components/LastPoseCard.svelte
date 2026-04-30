<script lang="ts">
  /**
   * Track B-MAPEDIT (β.5) — `<LastPoseCard/>` component.
   *
   * Reusable "Last pose" card shared between `/map` (Overview sub-tab),
   * `/map-edit` (Edit sub-tab), and any future page that wants the
   * full-detail readout (x / y / yaw / σ_xy / converged chip).
   *
   * Subscribes directly to the `lastPose` store — multiple instances
   * mounted on different routes share the same store cleanly (the
   * store's SSE lifecycle is managed at the store level, not per
   * subscriber).
   *
   * Why a separate component (not a copy in each route): operator HIL
   * 2026-04-30 KST asked for the Map page to mirror the Dashboard's
   * Last pose readout. Extracting one source keeps the format aligned
   * across pages without per-page drift. Dashboard.svelte still owns
   * its own inline readout — that's a deliberate non-goal for this PR
   * (Dashboard is production-vetted; we widen the surface incrementally).
   */
  import { onDestroy, onMount } from 'svelte';
  import { formatDegrees, formatMeters } from '$lib/format';
  import type { LastPose } from '$lib/protocol';
  import { subscribeLastPose } from '$stores/lastPose';

  let pose = $state<LastPose | null>(null);
  let unsub: (() => void) | null = null;

  onMount(() => {
    unsub = subscribeLastPose((p) => (pose = p));
  });

  onDestroy(() => {
    unsub?.();
  });
</script>

<div class="card last-pose-card" data-testid="last-pose-card">
  <h3>Last pose</h3>
  {#if pose && pose.valid}
    <div class="hstack" data-testid="last-pose-readout">
      <span>x: {formatMeters(pose.x_m)}</span>
      <span>y: {formatMeters(pose.y_m)}</span>
      <span>yaw: {formatDegrees(pose.yaw_deg)}</span>
      <span class="muted">σ_xy: {formatMeters(pose.xy_std_m)}</span>
      {#if pose.converged}
        <span class="chip ok" data-testid="last-pose-converged">converged</span>
      {/if}
    </div>
  {:else}
    <div class="muted" data-testid="last-pose-empty">no valid pose yet</div>
  {/if}
</div>

<style>
  h3 {
    margin-top: 0;
  }
</style>
