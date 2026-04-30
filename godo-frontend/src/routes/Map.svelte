<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import MapListPanel from '$components/MapListPanel.svelte';
  import MapZoomControls from '$components/MapZoomControls.svelte';
  import PoseCanvas from '$components/PoseCanvas.svelte';
  import ScanToggle from '$components/ScanToggle.svelte';
  import { MAP_SUBTAB_EDIT, MAP_SUBTAB_OVERVIEW } from '$lib/constants';
  import { formatDegrees, formatMeters } from '$lib/format';
  import { createMapViewport } from '$lib/mapViewport.svelte';
  import type { LastPose, LastScan } from '$lib/protocol';
  import { navigate, route } from '$lib/router';
  import { subscribeLastPose } from '$stores/lastPose';
  import { subscribeLastScan } from '$stores/lastScan';
  import { scanOverlay } from '$stores/scanOverlay';
  import MapEdit from './MapEdit.svelte';

  // Per-route viewport instance (Q2 — operator navigating /map ↔
  // /map-edit gets a fresh viewport). Shared between `<PoseCanvas/>`
  // and `<MapZoomControls/>` so the buttons drive the same zoom state.
  const viewport = createMapViewport();

  let pose = $state<LastPose | null>(null);
  let scan = $state<LastScan | null>(null);
  let scanOn = $state(false);
  let unsub: (() => void) | null = null;
  let unsubScan: (() => void) | null = null;
  let unsubOverlay: (() => void) | null = null;
  let unsubRoute: (() => void) | null = null;

  // Default `previewUrl` mirrors the pre-Track-E behaviour: PoseCanvas
  // fetches the active map via `/api/map/image` (resolves through the
  // `active.pgm` symlink). Selecting a non-active row in the
  // MapListPanel re-points to `/api/maps/<name>/image` for read-only
  // preview without altering the active state.
  let previewUrl = $state('/api/map/image');

  // Sub-tab is URL-backed: `/map` -> Overview, `/map-edit` -> Edit. The
  // Edit sub-tab hosts the brush-erase mask editor (formerly the
  // top-level /map-edit page; the route still resolves here, just with
  // the Edit sub-tab pre-selected).
  let activeSubtab = $state<string>(MAP_SUBTAB_OVERVIEW);

  function pathToSubtab(path: string): string {
    return path === '/map-edit' ? MAP_SUBTAB_EDIT : MAP_SUBTAB_OVERVIEW;
  }

  function selectSubtab(key: string): void {
    if (key === activeSubtab) return;
    navigate(key === MAP_SUBTAB_EDIT ? '/map-edit' : '/map');
  }

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
    unsubRoute = route.subscribe((p) => (activeSubtab = pathToSubtab(p)));
  });

  onDestroy(() => {
    unsub?.();
    unsubScan?.();
    unsubOverlay?.();
    unsubRoute?.();
  });
</script>

<div data-testid="map-page">
  <div class="breadcrumb">
    GODO &gt; Map{activeSubtab === MAP_SUBTAB_EDIT ? ' &gt; Edit' : ''}
  </div>
  <h2>Map</h2>

  <div class="subtabs" role="tablist" data-testid="map-subtabs">
    <button
      class="subtab"
      class:active={activeSubtab === MAP_SUBTAB_OVERVIEW}
      role="tab"
      aria-selected={activeSubtab === MAP_SUBTAB_OVERVIEW}
      onclick={() => selectSubtab(MAP_SUBTAB_OVERVIEW)}
      data-testid="map-subtab-overview">Overview</button
    >
    <button
      class="subtab"
      class:active={activeSubtab === MAP_SUBTAB_EDIT}
      role="tab"
      aria-selected={activeSubtab === MAP_SUBTAB_EDIT}
      onclick={() => selectSubtab(MAP_SUBTAB_EDIT)}
      data-testid="map-subtab-edit">Edit</button
    >
  </div>

  {#if activeSubtab === MAP_SUBTAB_OVERVIEW}
    <MapListPanel {onPreviewSelect} />
    <div class="map-toolbar">
      <ScanToggle {scan} />
    </div>
    {#if pose && pose.valid}
      <div class="muted" style="margin-bottom: 8px;" data-testid="pose-readout">
        ({formatMeters(pose.x_m)}, {formatMeters(pose.y_m)}) · {formatDegrees(pose.yaw_deg)}
      </div>
    {/if}
    <div class="canvas-stack">
      <PoseCanvas {viewport} {pose} mapImageUrl={previewUrl} {scan} scanOverlayOn={scanOn} />
      <MapZoomControls {viewport} />
    </div>
  {:else if activeSubtab === MAP_SUBTAB_EDIT}
    <MapEdit />
  {/if}
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
  /* PR β — wraps the underlay canvas so `<MapZoomControls/>` can sit
     in the top-left absolutely-positioned slot WITHOUT overlapping the
     `<MapListPanel/>` or the pose readout above. */
  .canvas-stack {
    position: relative;
  }
  /* Sub-tab styling mirrors System.svelte (PR-B Processes / Extended
     resources) so the visual idiom is consistent across the SPA. */
  .subtabs {
    display: flex;
    gap: 0;
    margin: 12px 0;
    border-bottom: 1px solid var(--color-border);
  }
  .subtab {
    background: none;
    border: none;
    padding: 8px 16px;
    cursor: pointer;
    color: var(--color-text-muted);
    font-size: 14px;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .subtab:hover {
    color: var(--color-text);
  }
  .subtab.active {
    color: var(--color-text);
    border-bottom-color: var(--color-accent);
  }
</style>
