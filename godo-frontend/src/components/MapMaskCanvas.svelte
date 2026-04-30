<script lang="ts">
  /**
   * Track B-MAPEDIT — brush-mask surface.
   *
   * Owns the brush mask `Uint8ClampedArray` sized to the PGM's logical
   * `width × height`. Pointer events paint a circular kernel into the
   * mask. The mask never grows when CSS pixels grow — `devicePixelRatio`
   * is isolated by mapping pointer CSS coords directly to logical mask
   * coords using the canvas's `getBoundingClientRect()` (R2 mitigation
   * + T4 fold pin).
   *
   * issue#2.3 (post-PR-β HIL fix): the mask layer is now sized to the
   * underlay's IMAGE RECT and CSS-transformed by `viewport.zoom + pan`.
   * The previous self-contained map-layer is dropped — `<MapUnderlay/>`
   * owns ALL underlay rendering (PGM bitmap + scan overlay). The mask
   * layer is transparent except where painted, so scan dots render
   * through. Pointer events: paint / origin-pick still go to mask
   * layer; pinch zoom (wheel + ctrlKey) is forwarded to the viewport.
   *
   * Exports two methods to the parent route:
   *   - `getMaskPng() -> Promise<Blob>` — PNG-encode the current mask
   *     for upload via `/api/map/edit`.
   *   - `clear()` — zero the mask + clear the canvas.
   *
   * SOLE owner of mask state per CODEBASE.md invariant (u). The parent
   * route holds the brush radius + Apply orchestration; this component
   * exposes neither read access nor a writable handle to the mask
   * array.
   *
   * Track B-MAPEDIT-2 mode-prop split (per invariant (aa)): the
   * `mode: 'paint' | 'origin-pick'` prop (default `'paint'`)
   * disambiguates pointer-event behaviour. In `'origin-pick'` mode
   * pointer-down emits `oncoordpick(lx, ly)` with logical PGM coords
   * and the mask buffer is NOT touched — invariant (u) holds because
   * mask state is byte-identical to a paint-mode no-op pointer event.
   */
  import { onMount } from 'svelte';
  import { MAP_PINCH_DELTA_PX_PER_STEP, MAP_ZOOM_STEP } from '$lib/constants';
  import type { MapViewport } from '$lib/mapViewport.svelte';

  interface Props {
    width: number; // logical PGM width
    height: number; // logical PGM height
    mapImageUrl: string;
    brushRadius: number;
    disabled?: boolean;
    mode?: 'paint' | 'origin-pick';
    oncoordpick?: (lx: number, ly: number) => void;
    /**
     * Optional shared viewport (PR β commit 4). When supplied, pointer
     * events use `viewport.canvasToImagePixel(...)` to invert the
     * underlay's zoom + pan before mapping to logical mask cells. When
     * omitted (back-compat for any caller that does not yet share a
     * viewport), the math collapses to the pre-PR-β
     * `getBoundingClientRect()` form which is identity at zoom=1.
     */
    viewport?: MapViewport;
  }

  let {
    width,
    height,
    mapImageUrl,
    brushRadius,
    disabled = false,
    mode = 'paint',
    oncoordpick,
    viewport,
  }: Props = $props();

  let maskCanvas: HTMLCanvasElement | undefined = $state();

  // Logical mask buffer. 1 byte per cell: 0 = unpainted, 255 = painted.
  // The same array is exposed as a PNG in `getMaskPng()`.
  let mask: Uint8ClampedArray = new Uint8ClampedArray(width * height);

  // Track pointer-down state for click-and-drag painting.
  let painting = false;

  // Reactivity: rebuild the mask when dimensions change.
  $effect(() => {
    void width;
    void height;
    mask = new Uint8ClampedArray(width * height);
    redrawMaskCanvas();
  });

  // mapImageUrl is no longer consumed inside this component (PR β /
  // issue#2.3 — `<MapUnderlay/>` is the sole owner of underlay PGM
  // rendering). The prop is retained for back-compat with callers that
  // pre-date PR β; future cleanup may drop it.
  $effect(() => {
    void mapImageUrl;
  });

  onMount(() => {
    if (maskCanvas) {
      maskCanvas.width = width;
      maskCanvas.height = height;
    }
  });

  /**
   * Map a PointerEvent's CSS coordinates to LOGICAL mask coords.
   *
   * issue#2.3 simplification: the mask layer is now CSS-positioned at
   * the underlay's IMAGE RECT (sized `width × height` logical pixels,
   * CSS-transformed by `viewport.zoom` + pan). So `getBoundingClientRect`
   * already reflects the visual rect of the image; the conversion is
   * a simple proportional mapping `cssX * width / rect.width`. The
   * viewport math is no longer needed inside this function — the CSS
   * transform handles it (T4 fold's DPR-isolation pin survives because
   * the mask buffer is still `width × height` independent of CSS size).
   */
  function pointerToLogicalCoords(ev: PointerEvent): { lx: number; ly: number } | null {
    if (!maskCanvas) return null;
    const rect = maskCanvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const cssX = ev.clientX - rect.left;
    const cssY = ev.clientY - rect.top;

    const lx = (cssX * width) / rect.width;
    const ly = (cssY * height) / rect.height;

    const flx = Math.floor(lx);
    const fly = Math.floor(ly);
    if (flx < 0 || flx >= width || fly < 0 || fly >= height) return null;
    return { lx: flx, ly: fly };
  }

  function paintCircle(cx: number, cy: number, radius: number): void {
    const r2 = radius * radius;
    const x0 = Math.max(0, cx - radius);
    const x1 = Math.min(width - 1, cx + radius);
    const y0 = Math.max(0, cy - radius);
    const y1 = Math.min(height - 1, cy + radius);
    for (let y = y0; y <= y1; y++) {
      const dy = y - cy;
      for (let x = x0; x <= x1; x++) {
        const dx = x - cx;
        if (dx * dx + dy * dy <= r2) {
          mask[y * width + x] = 255;
        }
      }
    }
    redrawMaskCanvas();
  }

  function redrawMaskCanvas(): void {
    if (!maskCanvas) return;
    const ctx = maskCanvas.getContext('2d');
    if (!ctx) return;
    // ImageData is RGBA; semi-transparent red over painted cells.
    const img = ctx.createImageData(width, height);
    for (let i = 0; i < mask.length; i++) {
      const off = i * 4;
      if (mask[i] > 0) {
        img.data[off] = 198; // R (#c62828)
        img.data[off + 1] = 40;
        img.data[off + 2] = 40;
        img.data[off + 3] = 140; // ~55% alpha
      } else {
        img.data[off + 3] = 0; // transparent
      }
    }
    ctx.putImageData(img, 0, 0);
  }

  function onPointerDown(ev: PointerEvent): void {
    if (disabled) return;
    const c = pointerToLogicalCoords(ev);
    if (!c) return;
    if (mode === 'origin-pick') {
      // Track B-MAPEDIT-2: emit logical coords, do NOT touch the mask
      // buffer. Invariant (u) holds — mask state is byte-identical to
      // a paint-mode no-op.
      oncoordpick?.(c.lx, c.ly);
      return;
    }
    painting = true;
    maskCanvas?.setPointerCapture(ev.pointerId);
    paintCircle(c.lx, c.ly, brushRadius);
  }

  function onPointerMove(ev: PointerEvent): void {
    if (mode === 'origin-pick') return; // no drag-paint in origin-pick mode
    if (!painting || disabled) return;
    const c = pointerToLogicalCoords(ev);
    if (!c) return;
    paintCircle(c.lx, c.ly, brushRadius);
  }

  function onPointerUp(ev: PointerEvent): void {
    painting = false;
    if (maskCanvas?.hasPointerCapture(ev.pointerId)) {
      maskCanvas.releasePointerCapture(ev.pointerId);
    }
  }

  /**
   * issue#2.3 — forward trackpad pinch (wheel + ctrlKey) from the mask
   * layer to the shared viewport. Without this, mask-layer captures the
   * wheel event and the operator's pinch never reaches MapUnderlay's
   * onWheel handler (the mask layer sits ON TOP of the underlay).
   * Mirror of `MapUnderlay.svelte::onWheel` — same ctrlKey gate, same
   * fractional sensitivity. Plain scroll (no ctrlKey) is allowed to
   * propagate as page scroll.
   */
  function onWheel(ev: WheelEvent): void {
    if (!ev.ctrlKey || !viewport) return;
    ev.preventDefault();
    if (ev.deltaY === 0) return;
    const stepFraction = -ev.deltaY / MAP_PINCH_DELTA_PX_PER_STEP;
    const factor = Math.pow(MAP_ZOOM_STEP, stepFraction);
    viewport.setZoomFromPercent(viewport.zoom * factor * 100);
  }

  // ---- CSS-side layout for the mask layer (issue#2.3) --------------
  // The mask layer is sized to logical image pixels (`width × height`)
  // and CSS-transformed by the shared viewport (zoom + pan), so it
  // visually tracks the underlay's PGM render exactly. Centered via
  // top:50% / left:50% and `translate(-50%, -50%)` so the transform
  // origin is the box center (matches the underlay's centered draw).
  const maskTransform = $derived(() => {
    const z = viewport ? viewport.zoom : 1;
    const px = viewport ? viewport.panX : 0;
    const py = viewport ? viewport.panY : 0;
    return `translate(-50%, -50%) translate(${px}px, ${py}px) scale(${z})`;
  });

  // ---- exported imperative API -------------------------------------

  export function clear(): void {
    mask = new Uint8ClampedArray(width * height);
    redrawMaskCanvas();
  }

  export function getMaskPng(): Promise<Blob> {
    return new Promise((resolve, reject) => {
      // Build a temporary RGBA canvas. The backend's decoder takes the
      // alpha-as-paint branch first when an alpha channel is present
      // (map_edit.py:177-181), so alpha MUST track the paint signal:
      // unpainted -> alpha=0 (not paint), painted -> alpha=255 (paint).
      // Setting alpha=255 unconditionally would mark every pixel as
      // painted and nuke the entire map on Apply. RGB tracks alpha so
      // the greyscale-threshold fallback (img.convert("L")) also works.
      const c = document.createElement('canvas');
      c.width = width;
      c.height = height;
      const ctx = c.getContext('2d');
      if (!ctx) {
        reject(new Error('mask_canvas_2d_unavailable'));
        return;
      }
      const img = ctx.createImageData(width, height);
      for (let i = 0; i < mask.length; i++) {
        const off = i * 4;
        const v = mask[i] > 0 ? 255 : 0;
        img.data[off] = v;
        img.data[off + 1] = v;
        img.data[off + 2] = v;
        img.data[off + 3] = v;
      }
      ctx.putImageData(img, 0, 0);
      c.toBlob((blob) => {
        if (!blob) {
          reject(new Error('mask_blob_failed'));
          return;
        }
        resolve(blob);
      }, 'image/png');
    });
  }

  // Test-only access used by vitest cases. NOT part of the public
  // contract — components MUST NOT read this. Pinned by invariant (u)
  // (sole owner discipline). The Svelte 5 `export` from a `<script>`
  // block becomes a property on the component instance.
  export function _testGetMaskCell(x: number, y: number): number {
    return mask[y * width + x] ?? 0;
  }
</script>

<div class="mask-stack">
  <canvas
    bind:this={maskCanvas}
    class="mask-layer {mode === 'origin-pick' ? 'origin-pick' : ''}"
    data-testid="mask-paint-layer"
    style="width: {width}px; height: {height}px; transform: {maskTransform()};"
    onpointerdown={onPointerDown}
    onpointermove={onPointerMove}
    onpointerup={onPointerUp}
    onpointercancel={onPointerUp}
    onwheel={onWheel}
  ></canvas>
</div>

<style>
  /* issue#2.3 — `<MapUnderlay/>` owns the underlay PGM + scan render
     path; this component contributes ONLY the brush mask + pointer
     events. The wrap fills the parent's `.mask-overlay` slot but is
     transparent and pointer-events: none — events fall through to the
     underlay below for drag-pan + hover, EXCEPT inside the mask layer
     (which captures paint / origin-pick / pinch). */
  .mask-stack {
    position: absolute;
    inset: 0;
    pointer-events: none;
    overflow: hidden;
  }
  .mask-layer {
    /* Sized to logical image pixels and centered. The CSS transform
       (translate −50% −50% then translate(panX, panY) then scale(zoom))
       places the mask-layer at the EXACT same screen rect as the
       underlay's PGM render — see MapUnderlay's draw call site. */
    position: absolute;
    left: 50%;
    top: 50%;
    transform-origin: center;
    /* image-rendering: pixelated keeps mask cells crisp at any zoom. */
    image-rendering: pixelated;
    cursor: crosshair;
    pointer-events: auto;
    /* Soft edge so operators see where the mask-layer ends vs the
       transparent surrounding area. */
    outline: 1px dashed color-mix(in srgb, var(--color-border) 50%, transparent);
  }
  .mask-layer.origin-pick {
    /* `cell` cursor signals "pick a point" affordance to the operator
       (Track B-MAPEDIT-2 mode-prop split). */
    cursor: cell;
  }
</style>
