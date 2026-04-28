<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import MapListPanel from '$components/MapListPanel.svelte';
  import PoseCanvas from '$components/PoseCanvas.svelte';
  import { formatDegrees, formatMeters } from '$lib/format';
  import type { LastPose } from '$lib/protocol';
  import { subscribeLastPose } from '$stores/lastPose';

  let pose = $state<LastPose | null>(null);
  let unsub: (() => void) | null = null;

  // Default `previewUrl` mirrors the pre-Track-E behaviour: PoseCanvas
  // fetches the active map via `/api/map/image` (resolves through the
  // `active.pgm` symlink). Selecting a non-active row in the
  // MapListPanel re-points to `/api/maps/<name>/image` for read-only
  // preview without altering the active state.
  let previewUrl = $state('/api/map/image');

  function onPreviewSelect(url: string): void {
    previewUrl = url;
  }

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
  <MapListPanel {onPreviewSelect} />
  {#if pose && pose.valid}
    <div class="muted" style="margin-bottom: 8px;" data-testid="pose-readout">
      ({formatMeters(pose.x_m)}, {formatMeters(pose.y_m)}) · {formatDegrees(pose.yaw_deg)}
    </div>
  {/if}
  <PoseCanvas {pose} mapImageUrl={previewUrl} />
</div>

<style>
  h2 {
    margin-top: 0;
  }
</style>
