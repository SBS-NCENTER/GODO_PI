<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import MapListPanel from '$components/MapListPanel.svelte';
  import PoseCanvas from '$components/PoseCanvas.svelte';
  import ScanToggle from '$components/ScanToggle.svelte';
  import { formatDegrees, formatMeters } from '$lib/format';
  import type { LastPose, LastScan } from '$lib/protocol';
  import { subscribeLastPose } from '$stores/lastPose';
  import { subscribeLastScan } from '$stores/lastScan';
  import { scanOverlay } from '$stores/scanOverlay';

  let pose = $state<LastPose | null>(null);
  let scan = $state<LastScan | null>(null);
  let scanOn = $state(false);
  let unsub: (() => void) | null = null;
  let unsubScan: (() => void) | null = null;
  let unsubOverlay: (() => void) | null = null;

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
    // Track D — subscribe to the LastScan store; lifecycle is managed
    // by the store (gated on the scanOverlay flag). When the overlay
    // flag is off the store does not even open the SSE.
    unsubScan = subscribeLastScan((s) => (scan = s));
    unsubOverlay = scanOverlay.subscribe((v) => (scanOn = v));
  });

  onDestroy(() => {
    unsub?.();
    unsubScan?.();
    unsubOverlay?.();
  });
</script>

<div data-testid="map-page">
  <div class="breadcrumb">GODO &gt; Map</div>
  <h2>Map</h2>
  <MapListPanel {onPreviewSelect} />
  <div class="map-toolbar">
    <ScanToggle {scan} />
  </div>
  {#if pose && pose.valid}
    <div class="muted" style="margin-bottom: 8px;" data-testid="pose-readout">
      ({formatMeters(pose.x_m)}, {formatMeters(pose.y_m)}) · {formatDegrees(pose.yaw_deg)}
    </div>
  {/if}
  <PoseCanvas {pose} mapImageUrl={previewUrl} {scan} scanOverlayOn={scanOn} />
</div>

<style>
  h2 {
    margin-top: 0;
  }
  .map-toolbar {
    display: flex;
    justify-content: flex-end;
    margin: 8px 0;
  }
</style>
