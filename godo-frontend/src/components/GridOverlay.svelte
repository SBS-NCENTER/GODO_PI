<script lang="ts">
  /**
   * issue#28 — world-frame zoom-adaptive grid overlay.
   *
   * Renders a thin gray grid in the world frame. Interval per-zoom
   * follows `GRID_INTERVAL_SCHEDULE`; max lines per axis capped at
   * `GRID_MAX_LINES_PER_AXIS` to prevent tab-freeze at extreme zoom.
   */

  import {
    GRID_INTERVAL_SCHEDULE,
    GRID_LINE_COLOR,
    GRID_MAX_LINES_PER_AXIS,
  } from '../lib/constants.js';

  interface Props {
    canvas: HTMLCanvasElement | null;
    zoomPxPerMeter: number;
    worldOriginX: number;
    worldOriginY: number;
    worldWidthM: number;
    worldHeightM: number;
  }

  let {
    canvas,
    zoomPxPerMeter,
    worldOriginX,
    worldOriginY,
    worldWidthM,
    worldHeightM,
  }: Props = $props();

  function pickInterval(zoom: number) {
    for (const entry of GRID_INTERVAL_SCHEDULE) {
      if (entry.maxZoom === null) return entry;
      if (zoom <= entry.maxZoom) return entry;
    }
    // Defensive — schedule always ends with a sentinel.
    return GRID_INTERVAL_SCHEDULE[GRID_INTERVAL_SCHEDULE.length - 1];
  }

  $effect(() => {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const entry = pickInterval(zoomPxPerMeter);
    const intervalM = entry.intervalM;

    ctx.save();
    ctx.strokeStyle = GRID_LINE_COLOR;
    ctx.lineWidth = entry.lineWidthPx;

    const startX = Math.floor(worldOriginX / intervalM) * intervalM;
    const endX = worldOriginX + worldWidthM;
    let xLines = 0;
    for (let wx = startX; wx <= endX; wx += intervalM) {
      if (xLines++ > GRID_MAX_LINES_PER_AXIS) break;
      const px = (wx - worldOriginX) * zoomPxPerMeter;
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, canvas.height);
      ctx.stroke();
    }

    const startY = Math.floor(worldOriginY / intervalM) * intervalM;
    const endY = worldOriginY + worldHeightM;
    let yLines = 0;
    for (let wy = startY; wy <= endY; wy += intervalM) {
      if (yLines++ > GRID_MAX_LINES_PER_AXIS) break;
      const py = canvas.height - (wy - worldOriginY) * zoomPxPerMeter;
      ctx.beginPath();
      ctx.moveTo(0, py);
      ctx.lineTo(canvas.width, py);
      ctx.stroke();
    }

    ctx.restore();
  });
</script>

<!-- pure-canvas overlay; no DOM children -->
