<script lang="ts">
  /**
   * Map Overview canvas — a thin wrapper around `<MapUnderlay/>` that
   * adds the pose+trail layer.
   *
   * PR β phasing (commit-2): MapUnderlay owns the canvas + bitmap fetch
   * + scan render path; PoseCanvas owns pose+trail state and supplies
   * a parent draw hook. Zoom + pan now live in a `mapViewport` factory
   * instance — owned either by the outer route (when supplied via the
   * `viewport` prop) or constructed locally for back-compat. The
   * wheel listener is preserved on this wrapper for one more commit;
   * commit-3 deletes it and adds `<MapZoomControls/>` to Map.svelte.
   *
   * Back-compat selectors preserved on this wrapper:
   *   - `data-testid="pose-canvas-wrap"` on the outer div (mirrors
   *     `data-scan-count` / `data-scan-fresh` from `<MapUnderlay/>`).
   *   - `data-testid="pose-canvas"` on the inner canvas (passed through
   *     to MapUnderlay via the `canvasTestId` prop).
   */
  import { untrack } from 'svelte';
  import {
    DEG_TO_RAD,
    MAP_HEADING_LINE_WIDTH_PX,
    MAP_MAX_ZOOM,
    MAP_MIN_ZOOM,
    MAP_POSE_COLOR,
    MAP_POSE_DOT_RADIUS_PX,
    MAP_POSE_HEADING_LEN_PX,
    MAP_TRAIL_COLOR,
    MAP_TRAIL_DOT_RADIUS_RATIO,
    MAP_TRAIL_LENGTH,
    MAP_TRAIL_MAX_OPACITY,
    MAP_WHEEL_ZOOM_FACTOR,
  } from '$lib/constants';
  import { createMapViewport, type MapViewport } from '$lib/mapViewport.svelte';
  import type { LastPose, LastScan } from '$lib/protocol';
  import MapUnderlay from './MapUnderlay.svelte';

  interface Props {
    pose: LastPose | null;
    mapImageUrl?: string;
    scan?: LastScan | null;
    scanOverlayOn?: boolean;
    /**
     * Optional shared viewport. When `Map.svelte` (commit-3+) wants
     * `<MapZoomControls/>` to drive the same zoom state as this canvas,
     * it creates a viewport with `createMapViewport()` and passes it
     * here. When omitted, this component creates a private one
     * (back-compat for any caller that doesn't yet supply a shared
     * viewport).
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
   * arrow.
   */
  function drawPoseLayer(
    ctx: CanvasRenderingContext2D,
    worldToCanvas: (wx: number, wy: number) => [number, number],
  ): void {
    // Trail (oldest faintest).
    for (let i = 0; i < trail.length; i++) {
      const p = trail[i]!;
      const [cx, cy] = worldToCanvas(p.x, p.y);
      const alpha = (i + 1) / trail.length;
      ctx.globalAlpha = alpha * MAP_TRAIL_MAX_OPACITY;
      ctx.fillStyle = MAP_TRAIL_COLOR;
      ctx.beginPath();
      ctx.arc(cx, cy, MAP_POSE_DOT_RADIUS_PX * MAP_TRAIL_DOT_RADIUS_RATIO, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    // Current pose.
    if (pose && pose.valid) {
      const [cx, cy] = worldToCanvas(pose.x_m, pose.y_m);
      ctx.fillStyle = MAP_POSE_COLOR;
      ctx.beginPath();
      ctx.arc(cx, cy, MAP_POSE_DOT_RADIUS_PX, 0, Math.PI * 2);
      ctx.fill();
      const yawRad = pose.yaw_deg * DEG_TO_RAD;
      const ex = cx + Math.cos(yawRad) * MAP_POSE_HEADING_LEN_PX;
      const ey = cy - Math.sin(yawRad) * MAP_POSE_HEADING_LEN_PX;
      ctx.strokeStyle = MAP_POSE_COLOR;
      ctx.lineWidth = MAP_HEADING_LINE_WIDTH_PX;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(ex, ey);
      ctx.stroke();
    }
  }

  // Wheel zoom — temporarily preserved on this wrapper for commit-2
  // (Rule 1 of PR β plan moves this to the (+/-) buttons in commit-3,
  // and the wheel listener + MAP_WHEEL_ZOOM_FACTOR constant are deleted
  // there).
  function onWheel(e: WheelEvent): void {
    e.preventDefault();
    const factor = e.deltaY < 0 ? MAP_WHEEL_ZOOM_FACTOR : 1 / MAP_WHEEL_ZOOM_FACTOR;
    const next = Math.max(MAP_MIN_ZOOM, Math.min(MAP_MAX_ZOOM, _viewport.zoom * factor));
    _viewport.setZoomFromPercent(next * 100);
  }
</script>

<div
  class="pose-canvas-wrap"
  data-testid="pose-canvas-wrap"
  data-scan-count={scanCount}
  data-scan-fresh={scanFreshOut ? 'true' : 'false'}
  onwheel={onWheel}
  role="presentation"
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
