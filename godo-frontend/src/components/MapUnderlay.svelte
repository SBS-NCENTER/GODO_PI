<script lang="ts">
  /**
   * Track B-MAPEDIT — shared map underlay.
   *
   * Sole owner of the PGM-bitmap fetch + canvas mount + LiDAR scan
   * overlay render path (per CODEBASE.md invariant `(ab)`). Both `/map`
   * (Overview) and `/map-edit` (Edit sub-tab) compose this component;
   * it is the SOLE place the polar→Cartesian scan transform lands on a
   * canvas. Per-page overlays (pose+trail on Overview, brush mask +
   * origin-pick gizmo on Edit) sit on top via a parent-supplied
   * `ondraw(ctx, worldToCanvas)` hook OR a sibling DOM-level layer.
   *
   * Layer paint order (FIXED — Mode-A S1 of PR β plan):
   *   (1) PGM bitmap
   *   (2) LiDAR scan dots (gated on scanOverlayOn + freshness +
   *       mapMetadata being non-null per invariant `(n)`)
   *   (3) `ondraw` parent hook (pose+trail on Overview; null on Edit)
   *
   * Imperative API exposed via `bind:this`:
   *   - `worldToCanvas(wx, wy)` — thin passthrough to the viewport's
   *     pure helper (Mode-A M4 — single math SSOT).
   *   - `canvasToWorld(cx, cy)` — symmetric inverse.
   *
   * Zoom + pan + min-zoom state lives in the parent-supplied
   * `viewport` (commit-2). The factory captures `window.innerHeight`
   * once on the FIRST `setMapDims` call. Idempotency lives inside the
   * factory closure (Mode-A M5).
   *
   * `data-scan-count` + `data-scan-fresh` attributes are preserved on
   * the wrap div (Q-OQ-D9 selector reliability).
   */
  import { onDestroy, onMount, untrack } from 'svelte';
  import { apiFetch } from '$lib/api';
  import {
    MAP_CANVAS_MIN_HEIGHT_PX,
    MAP_CANVAS_MIN_WIDTH_PX,
    MAP_SCAN_DOT_COLOR,
    MAP_SCAN_DOT_OPACITY,
    MAP_SCAN_DOT_RADIUS_PX,
    MAP_SCAN_FRESHNESS_MS,
  } from '$lib/constants';
  import type { MapViewport } from '$lib/mapViewport.svelte';
  import type { LastScan, MapMetadata } from '$lib/protocol';
  import { projectScanToWorld } from '$lib/scanTransform';
  import { loadMapMetadata, mapMetadata, mapMetadataError } from '$stores/mapMetadata';

  interface Props {
    /** Shared map viewport instance (Mode-A M4 — single math SSOT). */
    viewport: MapViewport;
    mapImageUrl?: string;
    scan?: LastScan | null;
    scanOverlayOn?: boolean;
    /**
     * Parent-supplied draw hook called with the layer-3 paint slot.
     * `null` skips the hook (e.g. on `/map-edit` where the brush
     * layer is a sibling DOM canvas, not a same-canvas paint).
     */
    ondraw?:
      | ((
          ctx: CanvasRenderingContext2D,
          worldToCanvas: (wx: number, wy: number) => [number, number],
        ) => void)
      | null;
    /**
     * Bindable scan-render stats. Parent wrappers (e.g. `<PoseCanvas/>`)
     * mirror these onto their own `data-scan-count`/`data-scan-fresh`
     * attributes so the existing e2e + unit selectors keep working
     * without the wrapper having to query the inner DOM.
     */
    scanCount?: number;
    scanFreshOut?: boolean;
    /**
     * Optional override for the inner canvas's `data-testid`. Defaults
     * to `map-underlay-canvas`; the `<PoseCanvas/>` wrapper passes
     * `pose-canvas` so existing playwright selectors keep resolving.
     */
    canvasTestId?: string;
  }

  let {
    viewport,
    mapImageUrl = '/api/map/image',
    scan = null,
    scanOverlayOn = false,
    ondraw = null,
    scanCount = $bindable(0),
    scanFreshOut = $bindable(false),
    canvasTestId = 'map-underlay-canvas',
  }: Props = $props();

  let canvas: HTMLCanvasElement | undefined = $state();
  let img: HTMLImageElement | null = null;
  let blobUrl: string | null = null;
  let mapLoadError = $state<string | null>(null);
  let dragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let hoverWorld = $state<{ x: number; y: number } | null>(null);
  let meta = $state<MapMetadata | null>(null);
  let metaError = $state<string | null>(null);
  const _metaUnsub = mapMetadata.subscribe((v) => {
    meta = v;
    if (v) {
      // Mode-A M5 — factory-internal idempotency: every call after the
      // first is a NO-OP regardless of caller, so this is safe even if
      // map-switch routes through `null → fresh-non-null`.
      viewport.setMapDims(v.width, v.height);
    }
  });
  const _metaErrUnsub = mapMetadataError.subscribe((v) => {
    metaError = v;
  });

  // Track D — scan-render result attributes for e2e selector reliability
  // (Q-OQ-D9). 0 / false when overlay off, stale, or metadata missing.
  let scanRenderedCount = $state(0);
  let scanFresh = $state(false);

  // Re-render whenever inputs or transform change. Reading
  // `viewport.zoom`/`panX`/`panY` here registers $state subscriptions
  // (the factory exposes them via getters backed by runes).
  $effect(() => {
    void viewport.zoom;
    void viewport.panX;
    void viewport.panY;
    void mapImageUrl;
    void scan;
    void scanOverlayOn;
    void meta;
    void metaError;
    redraw();
  });

  // Re-render when a parent's `ondraw` reference changes (e.g. trail/pose
  // updates inside PoseCanvas mutate the closure each render).
  $effect(() => {
    void ondraw;
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

  async function fetchMapImageAuthed(url: string): Promise<HTMLImageElement> {
    const resp = await apiFetch(url);
    const blob = await resp.blob();
    if (blobUrl !== null) URL.revokeObjectURL(blobUrl);
    blobUrl = URL.createObjectURL(blob);
    return loadImage(blobUrl);
  }

  /**
   * Track D scale fix — resolution-aware world↔canvas conversion.
   * Math (per .claude/tmp/plan_track_d_scale_yflip.md §Math):
   *
   *   img_col = (wx - origin_x) / resolution
   *   img_row = (height - 1) - (wy - origin_y) / resolution     ← Y-flip
   *
   *   cx = canvas.width  / 2 + panX + (img_col - width  / 2) * zoom
   *   cy = canvas.height / 2 + panY + (img_row - height / 2) * zoom
   *
   * Implementation lives in `lib/mapViewport.svelte.ts::worldToCanvas`
   * (a pure helper); this method is a thin passthrough that supplies
   * the canvas dims (Mode-A M4 — single math SSOT).
   */
  export function worldToCanvas(wx: number, wy: number): [number, number] {
    if (!canvas) return [0, 0];
    return viewport.worldToCanvas(wx, wy, canvas.width, canvas.height, meta);
  }

  export function canvasToWorld(cx: number, cy: number): [number, number] {
    if (!canvas) return [0, 0];
    return viewport.canvasToWorld(cx, cy, canvas.width, canvas.height, meta);
  }

  function drawScanLayer(ctx: CanvasRenderingContext2D, s: LastScan): number {
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

    const zoom = viewport.zoom;
    const panX = viewport.panX;
    const panY = viewport.panY;

    // Layer 1 — PGM bitmap.
    if (img) {
      const w = img.naturalWidth * zoom;
      const h = img.naturalHeight * zoom;
      ctx.drawImage(img, canvas.width / 2 + panX - w / 2, canvas.height / 2 + panY - h / 2, w, h);
    }

    // Layer 2 — LiDAR scan dots.
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
    scanCount = drawnDots;
    scanFreshOut = isFresh;

    // Layer 3 — parent-supplied overlay hook (pose+trail on Overview;
    // null on Edit). Hook runs against the SAME canvas with the SAME
    // worldToCanvas projection; no z-index gymnastics needed.
    if (ondraw) {
      ondraw(ctx, worldToCanvas);
    }
  }

  // --- pan-by-drag ---------------------------------------------------

  function onMouseDown(e: MouseEvent): void {
    dragging = true;
    dragStartX = e.clientX - viewport.panX;
    dragStartY = e.clientY - viewport.panY;
  }
  function onMouseUp(): void {
    dragging = false;
  }
  function onMouseMove(e: MouseEvent): void {
    if (dragging) {
      viewport.setPan(e.clientX - dragStartX, e.clientY - dragStartY);
      // Pan-clamp every drag-move so the projected map cannot retreat
      // past `MAP_PAN_OVERSCAN_PX` on any side. The clamp is a no-op
      // when the projected box is smaller than the viewport on both
      // axes (smaller-axis case forces pan=0; see Q7 / Mode-A M1).
      if (canvas) {
        viewport.panClampInPlace(canvas.width, canvas.height);
      }
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

  // --- mount / unmount -----------------------------------------------

  onMount(() => {
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(rect.width, MAP_CANVAS_MIN_WIDTH_PX);
      canvas.height = Math.max(rect.height, MAP_CANVAS_MIN_HEIGHT_PX);
    }
  });

  /**
   * Track D scale fix (Mode-A M3) — refetch BOTH the bitmap and the
   * metadata whenever `mapImageUrl` changes. Pinned by
   * `tests/unit/poseCanvasImageReload.test.ts`.
   */
  $effect(() => {
    void mapImageUrl;
    refetchImage();
    void loadMapMetadata(mapImageUrl);
  });

  function refetchImage(): void {
    void fetchMapImageAuthed(mapImageUrl)
      .then((i) => {
        // Mode-B M2 lesson — read+write the same `$state` inside a
        // single effect uses `untrack` to avoid a reactive loop.
        untrack(() => {
          img = i;
          mapLoadError = null;
          redraw();
        });
      })
      .catch((e: unknown) => {
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
  class="map-underlay-wrap"
  data-testid="map-underlay-wrap"
  data-scan-count={scanRenderedCount}
  data-scan-fresh={scanFresh ? 'true' : 'false'}
>
  <canvas
    bind:this={canvas}
    data-testid={canvasTestId}
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
  .map-underlay-wrap {
    position: relative;
    width: 100%;
    height: 100%;
    display: block;
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
