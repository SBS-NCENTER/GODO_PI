<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { apiFetch } from '$lib/api';
  import {
    DEG_TO_RAD,
    MAP_CANVAS_MIN_HEIGHT_PX,
    MAP_CANVAS_MIN_WIDTH_PX,
    MAP_DEFAULT_ZOOM,
    MAP_HEADING_LINE_WIDTH_PX,
    MAP_MAX_ZOOM,
    MAP_MIN_ZOOM,
    MAP_POSE_COLOR,
    MAP_POSE_DOT_RADIUS_PX,
    MAP_POSE_HEADING_LEN_PX,
    MAP_SCAN_DOT_COLOR,
    MAP_SCAN_DOT_OPACITY,
    MAP_SCAN_DOT_RADIUS_PX,
    MAP_SCAN_FRESHNESS_MS,
    MAP_TRAIL_COLOR,
    MAP_TRAIL_DOT_RADIUS_RATIO,
    MAP_TRAIL_LENGTH,
    MAP_TRAIL_MAX_OPACITY,
    MAP_WHEEL_ZOOM_FACTOR,
  } from '$lib/constants';
  import type { LastPose, LastScan, MapMetadata } from '$lib/protocol';
  import { projectScanToWorld } from '$lib/scanTransform';
  import { loadMapMetadata, mapMetadata, mapMetadataError } from '$stores/mapMetadata';

  interface Props {
    pose: LastPose | null;
    mapImageUrl?: string;
    scan?: LastScan | null;
    scanOverlayOn?: boolean;
  }
  let {
    pose,
    mapImageUrl = '/api/map/image',
    scan = null,
    scanOverlayOn = false,
  }: Props = $props();

  let canvas: HTMLCanvasElement | undefined = $state();
  let img: HTMLImageElement | null = null;
  let blobUrl: string | null = null;
  let mapLoadError = $state<string | null>(null);
  let trail = $state<Array<{ x: number; y: number; yaw: number }>>([]);
  let zoom = $state(MAP_DEFAULT_ZOOM);
  let panX = $state(0);
  let panY = $state(0);
  let dragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let hoverWorld = $state<{ x: number; y: number } | null>(null);
  // Track D scale fix — subscribe to the resolution-aware metadata store.
  // While `meta === null` we render the map and pose layers (back-compat
  // for /api/map/image 404 fallback) but suppress the scan overlay (its
  // pixel math depends on width/height/origin).
  let meta = $state<MapMetadata | null>(null);
  let metaError = $state<string | null>(null);
  const _metaUnsub = mapMetadata.subscribe((v) => {
    meta = v;
  });
  const _metaErrUnsub = mapMetadataError.subscribe((v) => {
    metaError = v;
  });
  // Track D — exposed on the wrap div for e2e selector reliability
  // (Q-OQ-D9). Equals the count of scan dots actually rendered last
  // redraw, or 0 when the overlay is off / stale / hidden.
  let scanRenderedCount = $state(0);
  let scanFresh = $state(false);

  // When `pose` changes, push to trail (capped at MAP_TRAIL_LENGTH).
  // Per Mode-B M2: read `trail` inside `untrack()` so this effect has only
  // one reactive dep (`pose`) — otherwise reading + writing the same
  // `$state` is the documented Svelte 5 reactive-loop footgun.
  $effect(() => {
    if (pose && pose.valid) {
      trail = untrack(() => [
        ...trail.slice(-(MAP_TRAIL_LENGTH - 1)),
        { x: pose.x_m, y: pose.y_m, yaw: pose.yaw_deg },
      ]);
    }
  });

  // Re-render whenever pose, trail, scan, or transform changes.
  $effect(() => {
    void pose;
    void trail;
    void zoom;
    void panX;
    void panY;
    void mapImageUrl;
    void scan;
    void scanOverlayOn;
    void meta;
    void metaError;
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

  /**
   * Fetch the map PNG with the auth header attached, then turn the bytes
   * into a blob: URL so a plain `<img>`/`Image` can render it. Native
   * `<img src=...>` cannot send Authorization headers, so the direct-URL
   * approach 401s under JWT auth — see Mode-B follow-up note.
   */
  async function fetchMapImageAuthed(url: string): Promise<HTMLImageElement> {
    const resp = await apiFetch(url);
    const blob = await resp.blob();
    if (blobUrl !== null) URL.revokeObjectURL(blobUrl);
    blobUrl = URL.createObjectURL(blob);
    return loadImage(blobUrl);
  }

  /**
   * Track D scale fix — resolution-aware world↔canvas conversion.
   *
   * Math (per .claude/tmp/plan_track_d_scale_yflip.md §Math):
   *
   *   img_col = (wx - origin_x) / resolution
   *   img_row = (height - 1) - (wy - origin_y) / resolution     ← Y-flip
   *
   *   cx = canvas.width  / 2 + panX + (img_col - width  / 2) * zoom
   *   cy = canvas.height / 2 + panY + (img_row - height / 2) * zoom
   *
   * When `meta === null` (loading or fetch failed) we fall back to a
   * world-origin-centred canvas so the pose dot still renders. Scan
   * overlay rendering is gated on metadata being present (see redraw).
   */
  function worldToCanvas(wx: number, wy: number): [number, number] {
    if (!canvas) return [0, 0];
    const m = meta;
    if (!m) {
      // Back-compat fallback: a centred Cartesian world frame at 1 px/m
      // gated only on `zoom`. The pose dot still renders so an operator
      // sees SOMETHING while metadata is loading. The scan overlay is
      // suppressed in this branch (see redraw).
      return [canvas.width / 2 + panX + wx * zoom, canvas.height / 2 + panY - wy * zoom];
    }
    const imgCol = (wx - m.origin[0]) / m.resolution;
    const imgRow = m.height - 1 - (wy - m.origin[1]) / m.resolution;
    const cx = canvas.width / 2 + panX + (imgCol - m.width / 2) * zoom;
    const cy = canvas.height / 2 + panY + (imgRow - m.height / 2) * zoom;
    return [cx, cy];
  }

  function canvasToWorld(cx: number, cy: number): [number, number] {
    if (!canvas) return [0, 0];
    const m = meta;
    if (!m) {
      return [(cx - canvas.width / 2 - panX) / zoom, -(cy - canvas.height / 2 - panY) / zoom];
    }
    // Inverse algebra of worldToCanvas.
    const imgCol = (cx - canvas.width / 2 - panX) / zoom + m.width / 2;
    const imgRow = (cy - canvas.height / 2 - panY) / zoom + m.height / 2;
    const wx = imgCol * m.resolution + m.origin[0];
    const wy = (m.height - 1 - imgRow) * m.resolution + m.origin[1];
    return [wx, wy];
  }

  /**
   * Track D — polar→Cartesian world-frame transform for the scan overlay.
   * Uses the SCAN's own anchor pose (`scan.pose_*`) so the dots are
   * perfectly correlated with the AMCL pose at the moment the scan was
   * processed, regardless of `lastPose` SSE skew (Mode-A TM5 +
   * invariant (l)).
   *
   * Mode-A M3 fold: gate on `scan.valid === 1 && scan.pose_valid === 1`
   * (NOT on a magnitude-OR heuristic). When `pose_valid === 0` the
   * anchor coordinates are zeros from a non-converged AMCL run; rendering
   * those would mislead the operator.
   */
  function drawScanLayer(ctx: CanvasRenderingContext2D, s: LastScan): number {
    // Polar→Cartesian transform lives in lib/scanTransform.ts so unit
    // tests can exercise the math without a canvas mount. The validity
    // gate (Mode-A M3 — scan.valid === 1 && scan.pose_valid === 1) is
    // enforced inside `projectScanToWorld`.
    const points = projectScanToWorld(s);
    if (points.length === 0) return 0;

    ctx.fillStyle = MAP_SCAN_DOT_COLOR;
    ctx.globalAlpha = MAP_SCAN_DOT_OPACITY;
    for (const p of points) {
      const [cx, cy] = worldToCanvas(p.x, p.y);
      ctx.beginPath();
      ctx.arc(cx, cy, MAP_SCAN_DOT_RADIUS_PX, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    return points.length;
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

    // Track D — scan overlay layer (between map and trail). Gated on the
    // operator-controlled `scanOverlayOn` toggle, the freshness
    // budget (Mode-A M2 — arrival-wall-clock, NOT published_mono_ns),
    // AND the metadata being loaded (Track D scale fix — without
    // resolution/origin/height the world↔canvas math has no anchor).
    let drawnDots = 0;
    let isFresh = false;
    if (scanOverlayOn && scan && meta) {
      const arrival = scan._arrival_ms ?? 0;
      isFresh = arrival > 0 && Date.now() - arrival < MAP_SCAN_FRESHNESS_MS;
      if (isFresh) {
        drawnDots = drawScanLayer(ctx, scan);
      }
    }
    scanRenderedCount = drawnDots;
    scanFresh = isFresh;

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
  });

  /**
   * Track D scale fix (Mode-A M3) — refetch BOTH the bitmap and the
   * metadata whenever `mapImageUrl` changes. The pre-fix code only
   * fetched the bitmap inside `onMount`, so a `previewUrl` change in
   * `MapListPanel` repointed the canvas's coords to the new map but
   * left the bitmap pointed at the old one (silently mis-rendering).
   *
   * Pinned by `tests/unit/poseCanvasImageReload.test.ts`.
   */
  $effect(() => {
    void mapImageUrl;
    refetchImage();
    void loadMapMetadata(mapImageUrl);
  });

  function refetchImage(): void {
    void fetchMapImageAuthed(mapImageUrl)
      .then((i) => {
        img = i;
        mapLoadError = null;
        redraw();
      })
      .catch((e: unknown) => {
        // Surface the cause to the operator instead of silently leaving
        // the canvas blank — common cases: (a) tracker has not run a
        // mapping session yet so /api/map/image is 404, (b) auth lapsed.
        const status = (e as { status?: number })?.status;
        if (status === 404) mapLoadError = '맵 파일이 아직 없습니다.';
        else if (status === 401) mapLoadError = '인증이 만료되었습니다.';
        else mapLoadError = '맵 이미지를 불러오지 못했습니다.';
        redraw();
      });
  }

  onDestroy(() => {
    _metaUnsub();
    _metaErrUnsub();
    if (blobUrl !== null) URL.revokeObjectURL(blobUrl);
    blobUrl = null;
    img = null;
  });
</script>

<div
  class="pose-canvas-wrap"
  data-testid="pose-canvas-wrap"
  data-scan-count={scanRenderedCount}
  data-scan-fresh={scanFresh ? 'true' : 'false'}
>
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
  {#if mapLoadError}
    <div class="map-error muted" data-testid="map-error">{mapLoadError}</div>
  {/if}
  {#if metaError}
    <div class="map-error muted" data-testid="map-meta-error">
      맵 메타데이터 파싱 실패: {metaError}
    </div>
  {/if}
  {#if meta && meta.origin[2] !== 0}
    <div class="map-error muted" data-testid="map-theta-warning">
      이 맵은 회전 정보(theta)를 갖지만 SPA가 회전을 그리지 못합니다 — 좌표가 어긋날 수 있습니다.
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
  .map-error {
    position: absolute;
    top: 8px;
    left: 8px;
    background: var(--color-bg-elev);
    padding: 4px 8px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-border);
  }
</style>
