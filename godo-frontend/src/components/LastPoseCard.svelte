<script lang="ts">
  /**
   * Track B-MAPEDIT (β.5) — `<LastPoseCard/>` component.
   *
   * Reusable card shared across `/dashboard`, `/map`, `/map-edit`. Two
   * sections (issue#27):
   *
   *   1. "LiDAR raw" — bolded readout from the AMCL pose store
   *      (`lastPose`). Operator-perceptible visual weight signals
   *      "this is the SLAM truth".
   *   2. "Final output (UDP)" — 8-channel readout from the new
   *      `lastOutput` store (issue#27 SSE wrap-and-version). These are
   *      the actual values being sent to UE after
   *      `udp::apply_output_transform_inplace`.
   *
   * Either store may be null/invalid independently — the card renders
   * the available section(s); a missing store renders an "unavailable"
   * placeholder so the operator knows it's a degraded path, not a
   * static UI bug.
   */
  import { onDestroy, onMount } from 'svelte';
  import { formatDegrees, formatMeters } from '$lib/format';
  import type { LastOutputFrame, LastPose } from '$lib/protocol';
  import { subscribeLastOutput } from '$stores/lastOutput';
  import { subscribeLastPose } from '$stores/lastPose';

  let pose = $state<LastPose | null>(null);
  let output = $state<LastOutputFrame | null>(null);
  let unsubPose: (() => void) | null = null;
  let unsubOutput: (() => void) | null = null;

  onMount(() => {
    unsubPose = subscribeLastPose((p) => (pose = p));
    unsubOutput = subscribeLastOutput((o) => (output = o));
  });

  onDestroy(() => {
    unsubPose?.();
    unsubOutput?.();
  });

  function fmtZoomFocus(v: number): string {
    return v.toFixed(4);
  }
</script>

<div class="card last-pose-card" data-testid="last-pose-card">
  <h3>Last pose</h3>

  <div class="section" data-testid="last-pose-raw">
    <div class="section-label muted">LiDAR raw</div>
    {#if pose && pose.valid}
      <div class="hstack mono raw-line">
        <span><strong>x:</strong> {formatMeters(pose.x_m)}</span>
        <span><strong>y:</strong> {formatMeters(pose.y_m)}</span>
        <span><strong>yaw:</strong> {formatDegrees(pose.yaw_deg)}</span>
        <span class="muted">σ_xy: {formatMeters(pose.xy_std_m)}</span>
        {#if pose.converged}
          <span class="chip ok" data-testid="last-pose-converged">converged</span>
        {/if}
      </div>
    {:else}
      <div class="muted" data-testid="last-pose-empty">no valid pose yet</div>
    {/if}
  </div>

  <div class="section" data-testid="last-output-final">
    <div class="section-label muted">Final output (UDP)</div>
    {#if output && output.valid}
      <div class="output-grid mono">
        <span>x: {formatMeters(output.x_m)}</span>
        <span>y: {formatMeters(output.y_m)}</span>
        <span>z: {formatMeters(output.z_m)}</span>
        <span>pan: {formatDegrees(output.pan_deg)}</span>
        <span>tilt: {formatDegrees(output.tilt_deg)}</span>
        <span>roll: {formatDegrees(output.roll_deg)}</span>
        <span>zoom: {fmtZoomFocus(output.zoom)}</span>
        <span>focus: {fmtZoomFocus(output.focus)}</span>
      </div>
    {:else}
      <div class="muted" data-testid="last-output-empty">
        Final output (UDP) — unavailable
      </div>
    {/if}
  </div>
</div>

<style>
  h3 {
    margin-top: 0;
  }
  .section {
    margin-top: 8px;
  }
  .section:first-of-type {
    margin-top: 4px;
  }
  .section-label {
    font-size: 0.85em;
    margin-bottom: 4px;
  }
  .raw-line {
    font-weight: 600;
  }
  .mono {
    font-family: var(--font-mono, ui-monospace, monospace);
  }
  .output-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 4px 12px;
    font-size: 0.92em;
  }
</style>
