<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    DEG_TO_RAD,
    MAP_CANVAS_MIN_HEIGHT_PX,
    MAP_CANVAS_MIN_WIDTH_PX,
    MAP_DEFAULT_ZOOM,
    MAP_HEADING_LINE_WIDTH_PX,
    MAP_MAX_ZOOM,
    MAP_MIN_ZOOM,
    MAP_PIXELS_PER_METER,
    MAP_POSE_COLOR,
    MAP_POSE_DOT_RADIUS_PX,
    MAP_POSE_HEADING_LEN_PX,
    MAP_TRAIL_COLOR,
    MAP_TRAIL_DOT_RADIUS_RATIO,
    MAP_TRAIL_LENGTH,
    MAP_TRAIL_MAX_OPACITY,
    MAP_WHEEL_ZOOM_FACTOR,
  } from '$lib/constants';
  import type { LastPose } from '$lib/protocol';

  interface Props {
    pose: LastPose | null;
    mapImageUrl?: string;
  }
  let { pose, mapImageUrl = '/api/map/image' }: Props = $props();

  let canvas: HTMLCanvasElement | undefined = $state();
  let img: HTMLImageElement | null = null;
  let trail = $state<Array<{ x: number; y: number; yaw: number }>>([]);
  let zoom = $state(MAP_DEFAULT_ZOOM);
  let panX = $state(0);
  let panY = $state(0);
  let dragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let hoverWorld = $state<{ x: number; y: number } | null>(null);

  // When `pose` changes, push to trail (capped at MAP_TRAIL_LENGTH).
  $effect(() => {
    if (pose && pose.valid) {
      trail = [
        ...trail.slice(-(MAP_TRAIL_LENGTH - 1)),
        { x: pose.x_m, y: pose.y_m, yaw: pose.yaw_deg },
      ];
    }
  });

  // Re-render whenever pose, trail, or transform changes.
  $effect(() => {
    void pose;
    void trail;
    void zoom;
    void panX;
    void panY;
    void mapImageUrl;
    redraw();
  });

  function loadImage(url: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = reject;
      i.src = url;
    });
  }

  function worldToCanvas(wx: number, wy: number): [number, number] {
    if (!canvas) return [0, 0];
    // World origin at canvas center; +y world = up.
    const ppm = zoom * MAP_PIXELS_PER_METER;
    const cx = canvas.width / 2 + panX + wx * ppm;
    const cy = canvas.height / 2 + panY - wy * ppm;
    return [cx, cy];
  }

  function canvasToWorld(cx: number, cy: number): [number, number] {
    if (!canvas) return [0, 0];
    const ppm = zoom * MAP_PIXELS_PER_METER;
    const wx = (cx - canvas.width / 2 - panX) / ppm;
    const wy = -(cy - canvas.height / 2 - panY) / ppm;
    return [wx, wy];
  }

  function redraw(): void {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (img) {
      const w = img.naturalWidth * zoom;
      const h = img.naturalHeight * zoom;
      ctx.drawImage(img, canvas.width / 2 + panX - w / 2, canvas.height / 2 + panY - h / 2, w, h);
    }

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
      // Heading arrow.
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

  function onWheel(e: WheelEvent): void {
    e.preventDefault();
    const factor = e.deltaY < 0 ? MAP_WHEEL_ZOOM_FACTOR : 1 / MAP_WHEEL_ZOOM_FACTOR;
    zoom = Math.max(MAP_MIN_ZOOM, Math.min(MAP_MAX_ZOOM, zoom * factor));
  }

  function onMouseDown(e: MouseEvent): void {
    dragging = true;
    dragStartX = e.clientX - panX;
    dragStartY = e.clientY - panY;
  }
  function onMouseUp(): void {
    dragging = false;
  }
  function onMouseMove(e: MouseEvent): void {
    if (dragging) {
      panX = e.clientX - dragStartX;
      panY = e.clientY - dragStartY;
    }
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const [wx, wy] = canvasToWorld(e.clientX - rect.left, e.clientY - rect.top);
      hoverWorld = { x: wx, y: wy };
    }
  }
  function onMouseLeave(): void {
    dragging = false;
    hoverWorld = null;
  }

  onMount(() => {
    if (canvas) {
      // Set canvas dimensions to its display size on mount.
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(rect.width, MAP_CANVAS_MIN_WIDTH_PX);
      canvas.height = Math.max(rect.height, MAP_CANVAS_MIN_HEIGHT_PX);
    }
    void loadImage(mapImageUrl)
      .then((i) => {
        img = i;
        redraw();
      })
      .catch(() => {
        // No map yet — render only pose layer.
        redraw();
      });
  });

  onDestroy(() => {
    img = null;
  });
</script>

<div class="pose-canvas-wrap" data-testid="pose-canvas-wrap">
  <canvas
    bind:this={canvas}
    data-testid="pose-canvas"
    onwheel={onWheel}
    onmousedown={onMouseDown}
    onmouseup={onMouseUp}
    onmousemove={onMouseMove}
    onmouseleave={onMouseLeave}
  ></canvas>
  {#if hoverWorld}
    <div class="hover-coord muted" data-testid="hover-coord">
      ({hoverWorld.x.toFixed(2)} m, {hoverWorld.y.toFixed(2)} m)
    </div>
  {/if}
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
  canvas {
    width: 100%;
    height: 100%;
    cursor: grab;
    display: block;
  }
  canvas:active {
    cursor: grabbing;
  }
  .hover-coord {
    position: absolute;
    bottom: 8px;
    right: 8px;
    background: var(--color-bg-elev);
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-border);
  }
</style>
