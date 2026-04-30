<script lang="ts">
  /**
   * Track B-MAPEDIT — brush-mask surface.
   *
   * Owns the brush mask `Uint8ClampedArray` sized to the PGM's logical
   * `width × height`. Pointer events paint a circular kernel into the
   * mask (and into a parallel "preview" canvas for visual feedback).
   * The mask never grows when CSS pixels grow — `devicePixelRatio` is
   * isolated by mapping pointer CSS coords directly to logical mask
   * coords using the canvas's `getBoundingClientRect()` (R2 mitigation
   * + T4 fold pin).
   *
   * Exports two methods to the parent route:
   *   - `getMaskPng() -> Promise<Blob>` — PNG-encode the current mask
   *     for upload via `/api/map/edit`.
   *   - `clear()` — zero the mask + clear the preview canvas.
   *
   * SOLE owner of mask state per CODEBASE.md invariant (u). The parent
   * route holds the brush radius + Apply orchestration; this component
   * exposes neither read access nor a writable handle to the mask
   * array.
   */
  import { onMount } from 'svelte';

  interface Props {
    width: number; // logical PGM width
    height: number; // logical PGM height
    mapImageUrl: string;
    brushRadius: number;
    disabled?: boolean;
  }

  let { width, height, mapImageUrl, brushRadius, disabled = false }: Props = $props();

  let mapCanvas: HTMLCanvasElement | undefined = $state();
  let maskCanvas: HTMLCanvasElement | undefined = $state();

  // Logical mask buffer. 1 byte per cell: 0 = unpainted, 255 = painted.
  // The same array is exposed as a PNG in `getMaskPng()`.
  let mask: Uint8ClampedArray = new Uint8ClampedArray(width * height);

  // Track pointer-down state for click-and-drag painting.
  let painting = false;

  // Reactivity: rebuild the mask + redraw the underlying map when the
  // dimensions or the mapImageUrl change.
  $effect(() => {
    void width;
    void height;
    mask = new Uint8ClampedArray(width * height);
    redrawMaskCanvas();
  });

  $effect(() => {
    void mapImageUrl;
    void width;
    void height;
    if (!mapCanvas) return;
    mapCanvas.width = width;
    mapCanvas.height = height;
    const ctx = mapCanvas.getContext('2d');
    if (!ctx) return;
    const img = new Image();
    img.onload = (): void => {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(img, 0, 0, width, height);
    };
    img.src = mapImageUrl;
  });

  onMount(() => {
    if (maskCanvas) {
      maskCanvas.width = width;
      maskCanvas.height = height;
    }
    if (mapCanvas) {
      mapCanvas.width = width;
      mapCanvas.height = height;
    }
  });

  /**
   * Map a PointerEvent's CSS coordinates to LOGICAL mask coords. The
   * mask is `width × height` regardless of the CSS-rendered size or
   * `devicePixelRatio` (T4 fold). A pointer at CSS (x, y) within a
   * canvas whose CSS box is `bw × bh` lands at logical
   * `(x * width / bw, y * height / bh)`.
   */
  function pointerToLogicalCoords(ev: PointerEvent): { lx: number; ly: number } | null {
    if (!maskCanvas) return null;
    const rect = maskCanvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const lx = Math.floor(((ev.clientX - rect.left) * width) / rect.width);
    const ly = Math.floor(((ev.clientY - rect.top) * height) / rect.height);
    if (lx < 0 || lx >= width || ly < 0 || ly >= height) return null;
    return { lx, ly };
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
    painting = true;
    maskCanvas?.setPointerCapture(ev.pointerId);
    paintCircle(c.lx, c.ly, brushRadius);
  }

  function onPointerMove(ev: PointerEvent): void {
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

  // ---- exported imperative API -------------------------------------

  export function clear(): void {
    mask = new Uint8ClampedArray(width * height);
    redrawMaskCanvas();
  }

  export function getMaskPng(): Promise<Blob> {
    return new Promise((resolve, reject) => {
      // Build a temporary single-channel canvas. We use a 2D canvas in
      // RGBA mode (single-channel canvases require WebGL/OffscreenCanvas)
      // — the backend converts RGBA to "L" via Pillow if alpha is present;
      // we emit greyscale-on-RGB so the threshold path is exercised.
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
        img.data[off + 3] = 255;
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
  <canvas bind:this={mapCanvas} class="layer map-layer" data-testid="mask-map-layer"></canvas>
  <canvas
    bind:this={maskCanvas}
    class="layer mask-layer"
    data-testid="mask-paint-layer"
    onpointerdown={onPointerDown}
    onpointermove={onPointerMove}
    onpointerup={onPointerUp}
    onpointercancel={onPointerUp}
  ></canvas>
</div>

<style>
  .mask-stack {
    position: relative;
    width: 100%;
    /* Maintain the canvas aspect ratio via a CSS pad-bottom trick. The
       canvas itself is logical-pixel sized; CSS scales it. */
    display: inline-block;
    line-height: 0;
    border: 1px solid var(--color-border);
  }
  .layer {
    display: block;
    /* Render at a fixed display size; logical canvas pixels are mapped
       by the browser via image-rendering. Pixelated keeps tiles crisp. */
    width: 100%;
    height: auto;
    image-rendering: pixelated;
  }
  .mask-layer {
    position: absolute;
    inset: 0;
    cursor: crosshair;
    /* Mask layer overlays the map; pointer events are bound here. */
  }
</style>
