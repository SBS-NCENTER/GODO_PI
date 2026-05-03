<script lang="ts">
  /**
   * Map Overview canvas — a thin wrapper around `<MapUnderlay/>` that
   * adds the pose+trail layer.
   *
   * PR β phasing (commit-3 final): MapUnderlay owns the canvas + bitmap
   * fetch + scan render path; PoseCanvas owns pose+trail state and
   * supplies a parent draw hook. Zoom + pan live in a `mapViewport`
   * factory instance — owned by the outer route (`Map.svelte`) which
   * shares it with `<MapZoomControls/>`. **No wheel listener.** The
   * `MAP_WHEEL_ZOOM_FACTOR` constant was deleted in this commit; a
   * writer reintroducing wheel zoom fails Mode-A Critical per
   * CODEBASE.md invariant `(ab)`.
   *
   * Back-compat selectors preserved on this wrapper:
   *   - `data-testid="pose-canvas-wrap"` on the outer div (mirrors
   *     `data-scan-count` / `data-scan-fresh` from `<MapUnderlay/>`).
   *   - `data-testid="pose-canvas"` on the inner canvas (passed through
   *     to MapUnderlay via the `canvasTestId` prop).
   */
  import { untrack } from 'svelte';
  import { MAP_TRAIL_LENGTH } from '$lib/constants';
  import { createMapViewport, type MapViewport } from '$lib/mapViewport.svelte';
  import { drawPose, drawTrail } from '$lib/poseDraw';
  import type { LastPose, LastScan } from '$lib/protocol';
  import MapUnderlay from './MapUnderlay.svelte';

  interface Props {
    pose: LastPose | null;
    mapImageUrl?: string;
    scan?: LastScan | null;
    scanOverlayOn?: boolean;
    /**
     * Optional shared viewport. `Map.svelte` creates one with
     * `createMapViewport()` and passes it to BOTH this canvas and
     * `<MapZoomControls/>` so the buttons drive the same zoom state.
     * Test-only callers can omit it and rely on a private fallback.
     */
    viewport?: MapViewport;
  }
  let {
    pose,
    mapImageUrl = '/api/map/image',
    scan = null,
    scanOverlayOn = false,
    viewport,
  }: Props = $props();

  const _viewport: MapViewport = viewport ?? createMapViewport();

  let trail = $state<Array<{ x: number; y: number; yaw: number }>>([]);

  // Mirror underlay's scan stats so the existing e2e + unit selectors
  // anchored on the wrap div continue to resolve.
  let scanCount = $state(0);
  let scanFreshOut = $state(false);

  // When `pose` changes, push to trail (capped at MAP_TRAIL_LENGTH).
  // Per Mode-B M2: read `trail` inside `untrack()` so this effect has
  // only one reactive dep (`pose`).
  $effect(() => {
    if (pose && pose.valid) {
      trail = untrack(() => [
        ...trail.slice(-(MAP_TRAIL_LENGTH - 1)),
        { x: pose.x_m, y: pose.y_m, yaw: pose.yaw_deg },
      ]);
    }
  });

  /**
   * Layer-3 paint hook — called by `<MapUnderlay/>` after the bitmap +
   * scan layers, against the SAME canvas + projection. Renders the
   * trail (faint history dots) and the current-pose dot + heading
   * arrow via the shared `lib/poseDraw` helpers (issue#27 — extracted).
   */
  function drawPoseLayer(
    ctx: CanvasRenderingContext2D,
    worldToCanvas: (wx: number, wy: number) => [number, number],
  ): void {
    drawTrail(ctx, worldToCanvas, trail);
    drawPose(ctx, worldToCanvas, pose);
  }
</script>

<div
  class="pose-canvas-wrap"
  data-testid="pose-canvas-wrap"
  data-scan-count={scanCount}
  data-scan-fresh={scanFreshOut ? 'true' : 'false'}
>
  <MapUnderlay
    viewport={_viewport}
    {mapImageUrl}
    {scan}
    {scanOverlayOn}
    bind:scanCount
    bind:scanFreshOut
    canvasTestId="pose-canvas"
    ondraw={drawPoseLayer}
  />
</div>

<style>
  .pose-canvas-wrap {
    position: relative;
    width: 100%;
    height: 600px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg-elev);
    overflow: hidden;
  }
</style>
