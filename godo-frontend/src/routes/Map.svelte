<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import PoseCanvas from '$components/PoseCanvas.svelte';
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

<div data-testid="map-page">
  <div class="breadcrumb">GODO &gt; Map</div>
  <h2>Map</h2>
  {#if pose && pose.valid}
    <div class="muted" style="margin-bottom: 8px;" data-testid="pose-readout">
      ({formatMeters(pose.x_m)}, {formatMeters(pose.y_m)}) · {formatDegrees(pose.yaw_deg)}
    </div>
  {/if}
  <PoseCanvas {pose} />
</div>

<style>
  h2 {
    margin-top: 0;
  }
</style>
