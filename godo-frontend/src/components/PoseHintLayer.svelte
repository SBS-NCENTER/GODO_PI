<script lang="ts">
  /**
   * issue#3 — pose hint gesture + visual marker layer (Map Overview).
   *
   * Mode-A C1: this is a SIBLING DOM canvas overlaid on
   * `<MapUnderlay/>`, NOT an `ondraw` consumer of the underlay's
   * layer-3 paint slot (which is already owned by `<PoseCanvas/>`).
   * Pattern is structurally similar to `<MapMaskCanvas/>` on the Map
   * Edit sub-tab: absolute-positioned canvas, transparent except where
   * we draw the hint marker; `pointer-events: auto` only when the
   * hint toggle is ON, else `pointer-events: none` so pan / pinch /
   * mouse-hover fall through to the underlay below.
   *
   * Mode-A M5: pointer math goes through
   * `viewport.canvasToWorld(cx, cy, canvas.width, canvas.height, meta)`
   * — the zoom/pan-aware single math SSOT — NOT `pixelToWorld` from
   * `originMath.ts` (which is the static-PGM-image path used by
   * OriginPicker).
   *
   * Gesture state machine (operator-locked blended A + B):
   *   idle
   *     │  pointerdown ───────────────────────────► placing-pos
   *     │                                              │
   *     │           drag ≥ MIN_PX (path A)             │
   *     │      ┌──────────────────────────────────────┘
   *     │      ▼                                       │
   *     │  placing-yaw-via-drag  drag < MIN_PX (path B)│
   *     │      │ pointerup                             │
   *     │      ▼                                       ▼
   *     │  committed                              placing-yaw-await
   *     │                                              │ pointerup
   *     │                                              ▼
   *     │                                         committed
   *     │
   *     └─ ESC at any non-idle state → idle (clears hint)
   *
   * Hint state lives in the parent (`Map.svelte`) per Mode-A M6 — the
   * layer is unmounted on the Edit sub-tab, but the placed hint
   * survives so the common-header "Calibrate from hint" button works
   * on either sub-tab.
   *
   * R11 acceptance: when `meta.origin[2] !== 0` (rotated YAML), this
   * component still works correctly because viewport.canvasToWorld
   * also ignores theta. The existing map-theta-warning banner in
   * `<MapUnderlay/>` is the operator's signal to fix the YAML before
   * trusting any pose / hint that lands here.
   */
  import { onMount } from 'svelte';
  import {
    POSE_HINT_ARROW_COLOR,
    POSE_HINT_ARROW_HEAD_PX,
    POSE_HINT_ARROW_LENGTH_PX,
    POSE_HINT_DRAG_MIN_PX,
    POSE_HINT_MARKER_COLOR,
    POSE_HINT_MARKER_RADIUS_PX,
  } from '$lib/constants';
  import type { MapViewport } from '$lib/mapViewport.svelte';
  import { yawFromDrag } from '$lib/originMath';
  import type { MapMetadata } from '$lib/protocol';
  import { mapMetadata } from '$stores/mapMetadata';

  /** Pose-hint payload — world-frame coordinates, CCW yaw degrees [0, 360). */
  export interface HintPose {
    x_m: number;
    y_m: number;
    yaw_deg: number;
  }

  interface Props {
    /** Shared map viewport (same instance the underlay uses). */
    viewport: MapViewport;
    /**
     * Layer is enabled (toggle ON in parent). When false, pointer
     * events fall through to the underlay below for normal pan / pinch.
     */
    enabled: boolean;
    /**
     * Two-way bound hint state — owned by `Map.svelte` so the value
     * survives sub-tab switching (Mode-A M6).
     */
    hint: HintPose | null;
    /** Setter — invoked on every state-machine transition. */
    onhintchange: (next: HintPose | null) => void;
  }

  let { viewport, enabled, hint, onhintchange }: Props = $props();

  let canvas: HTMLCanvasElement | undefined = $state();
  let meta = $state<MapMetadata | null>(null);
  const _metaUnsub = mapMetadata.subscribe((v) => {
    meta = v;
    redraw();
  });

  // Gesture state machine.
  type State =
    | { kind: 'idle' }
    | { kind: 'placing-pos'; downCx: number; downCy: number; downWx: number; downWy: number }
    | {
        kind: 'placing-yaw-via-drag';
        anchorWx: number;
        anchorWy: number;
        currWx: number;
        currWy: number;
      }
    | { kind: 'placing-yaw-await'; anchorWx: number; anchorWy: number };
  let state = $state<State>({ kind: 'idle' });

  // Re-render on viewport rune / hint / state changes.
  $effect(() => {
    void viewport.zoom;
    void viewport.panX;
    void viewport.panY;
    void hint;
    void state;
    void enabled;
    redraw();
  });

  // Resize the canvas to its rendered box. Mirrors
  // `<MapUnderlay/>::onMount` so the math is stable across resizes.
  function syncCanvasSize(): void {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    if (canvas.width !== rect.width) canvas.width = rect.width;
    if (canvas.height !== rect.height) canvas.height = rect.height;
  }

  function worldToCanvas(wx: number, wy: number): [number, number] | null {
    if (!canvas) return null;
    return viewport.worldToCanvas(wx, wy, canvas.width, canvas.height, meta);
  }

  function canvasToWorld(cx: number, cy: number): [number, number] | null {
    if (!canvas) return null;
    return viewport.canvasToWorld(cx, cy, canvas.width, canvas.height, meta);
  }

  function drawArrow(
    ctx: CanvasRenderingContext2D,
    cx: number,
    cy: number,
    yawDeg: number,
  ): void {
    // Yaw is CCW [0, 360); canvas Y axis points DOWN, so we negate
    // the sin component when drawing (mirror PoseCanvas convention).
    const rad = (yawDeg * Math.PI) / 180;
    const ex = cx + Math.cos(rad) * POSE_HINT_ARROW_LENGTH_PX;
    const ey = cy - Math.sin(rad) * POSE_HINT_ARROW_LENGTH_PX;
    ctx.strokeStyle = POSE_HINT_ARROW_COLOR;
    ctx.fillStyle = POSE_HINT_ARROW_COLOR;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    // Arrow head — small triangle perpendicular to the shaft.
    const headBackX = ex - Math.cos(rad) * POSE_HINT_ARROW_HEAD_PX;
    const headBackY = ey + Math.sin(rad) * POSE_HINT_ARROW_HEAD_PX;
    const perpX = Math.sin(rad) * POSE_HINT_ARROW_HEAD_PX * 0.6;
    const perpY = Math.cos(rad) * POSE_HINT_ARROW_HEAD_PX * 0.6;
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(headBackX + perpX, headBackY + perpY);
    ctx.lineTo(headBackX - perpX, headBackY - perpY);
    ctx.closePath();
    ctx.fill();
  }

  function redraw(): void {
    if (!canvas) return;
    syncCanvasSize();
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 1) Live preview during drag-yaw (path A, mid-gesture).
    if (state.kind === 'placing-yaw-via-drag') {
      const start = worldToCanvas(state.anchorWx, state.anchorWy);
      const end = worldToCanvas(state.currWx, state.currWy);
      if (!start || !end) return;
      ctx.strokeStyle = POSE_HINT_ARROW_COLOR;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(start[0], start[1]);
      ctx.lineTo(end[0], end[1]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = POSE_HINT_MARKER_COLOR;
      ctx.beginPath();
      ctx.arc(start[0], start[1], POSE_HINT_MARKER_RADIUS_PX, 0, Math.PI * 2);
      ctx.fill();
      return;
    }

    // 2) Path B awaiting second click — anchor dot only (no arrow yet).
    if (state.kind === 'placing-yaw-await') {
      const start = worldToCanvas(state.anchorWx, state.anchorWy);
      if (!start) return;
      ctx.fillStyle = POSE_HINT_MARKER_COLOR;
      ctx.beginPath();
      ctx.arc(start[0], start[1], POSE_HINT_MARKER_RADIUS_PX, 0, Math.PI * 2);
      ctx.fill();
      return;
    }

    // 3) Committed hint — render dot + arrow.
    if (hint) {
      const at = worldToCanvas(hint.x_m, hint.y_m);
      if (!at) return;
      ctx.fillStyle = POSE_HINT_MARKER_COLOR;
      ctx.beginPath();
      ctx.arc(at[0], at[1], POSE_HINT_MARKER_RADIUS_PX, 0, Math.PI * 2);
      ctx.fill();
      drawArrow(ctx, at[0], at[1], hint.yaw_deg);
    }
  }

  // ---- pointer handlers --------------------------------------------

  function onPointerDown(ev: PointerEvent): void {
    if (!enabled) return;
    if (!canvas) return;
    if (state.kind === 'placing-yaw-await') {
      // Path B second click — finalize yaw against the placed anchor.
      const rect = canvas.getBoundingClientRect();
      const cx = ev.clientX - rect.left;
      const cy = ev.clientY - rect.top;
      const w = canvasToWorld(cx, cy);
      if (!w) return;
      const [endWx, endWy] = w;
      const yaw = yawFromDrag(state.anchorWx, state.anchorWy, endWx, endWy);
      if (yaw === null) return; // operator clicked exactly on the anchor — wait for next
      onhintchange({ x_m: state.anchorWx, y_m: state.anchorWy, yaw_deg: yaw });
      state = { kind: 'idle' };
      return;
    }
    // Begin path A or B.
    const rect = canvas.getBoundingClientRect();
    const cx = ev.clientX - rect.left;
    const cy = ev.clientY - rect.top;
    const w = canvasToWorld(cx, cy);
    if (!w) return;
    canvas.setPointerCapture(ev.pointerId);
    state = {
      kind: 'placing-pos',
      downCx: cx,
      downCy: cy,
      downWx: w[0],
      downWy: w[1],
    };
  }

  function onPointerMove(ev: PointerEvent): void {
    if (!enabled || !canvas) return;
    if (state.kind === 'placing-pos') {
      const rect = canvas.getBoundingClientRect();
      const cx = ev.clientX - rect.left;
      const cy = ev.clientY - rect.top;
      const dx = cx - state.downCx;
      const dy = cy - state.downCy;
      if (Math.hypot(dx, dy) >= POSE_HINT_DRAG_MIN_PX) {
        const w = canvasToWorld(cx, cy);
        if (!w) return;
        state = {
          kind: 'placing-yaw-via-drag',
          anchorWx: state.downWx,
          anchorWy: state.downWy,
          currWx: w[0],
          currWy: w[1],
        };
      }
      return;
    }
    if (state.kind === 'placing-yaw-via-drag') {
      const rect = canvas.getBoundingClientRect();
      const cx = ev.clientX - rect.left;
      const cy = ev.clientY - rect.top;
      const w = canvasToWorld(cx, cy);
      if (!w) return;
      state = {
        kind: 'placing-yaw-via-drag',
        anchorWx: state.anchorWx,
        anchorWy: state.anchorWy,
        currWx: w[0],
        currWy: w[1],
      };
    }
  }

  function onPointerUp(ev: PointerEvent): void {
    if (!enabled || !canvas) return;
    if (canvas.hasPointerCapture(ev.pointerId)) {
      canvas.releasePointerCapture(ev.pointerId);
    }
    if (state.kind === 'placing-pos') {
      // Drag below MIN_PX → path B awaits a second click.
      state = {
        kind: 'placing-yaw-await',
        anchorWx: state.downWx,
        anchorWy: state.downWy,
      };
      return;
    }
    if (state.kind === 'placing-yaw-via-drag') {
      const yaw = yawFromDrag(
        state.anchorWx,
        state.anchorWy,
        state.currWx,
        state.currWy,
      );
      if (yaw !== null) {
        onhintchange({ x_m: state.anchorWx, y_m: state.anchorWy, yaw_deg: yaw });
      }
      state = { kind: 'idle' };
    }
  }

  function onKeyDown(ev: KeyboardEvent): void {
    if (!enabled) return;
    if (ev.key === 'Escape' && state.kind !== 'idle') {
      ev.preventDefault();
      state = { kind: 'idle' };
      onhintchange(null);
    }
  }

  onMount(() => {
    syncCanvasSize();
    redraw();
    window.addEventListener('keydown', onKeyDown);
    return () => {
      _metaUnsub();
      window.removeEventListener('keydown', onKeyDown);
    };
  });
</script>

<canvas
  bind:this={canvas}
  class="pose-hint-canvas {enabled ? 'enabled' : 'disabled'}"
  data-testid="pose-hint-canvas"
  data-state={state.kind}
  onpointerdown={onPointerDown}
  onpointermove={onPointerMove}
  onpointerup={onPointerUp}
  onpointercancel={onPointerUp}
></canvas>
{#if enabled && state.kind === 'placing-yaw-await'}
  <div class="pose-hint-affordance" data-testid="pose-hint-affordance">
    이제 방향을 클릭하세요
  </div>
{/if}

<style>
  .pose-hint-canvas {
    /* Sibling DOM canvas — absolute over the underlay. Transparent
       background; only the marker + arrow paint. The Map.svelte
       container is `position: relative`, so `inset: 0` fills it. */
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    z-index: 2; /* above MapUnderlay's PGM + scan layers */
    /* Operator-locked Rule 1: NO wheel listener registered (Mode-A
       anti-regression test). Scroll/pinch falls through to the
       underlay below regardless of the toggle state. */
  }
  .pose-hint-canvas.enabled {
    cursor: crosshair;
    pointer-events: auto;
  }
  .pose-hint-canvas.disabled {
    cursor: inherit;
    pointer-events: none;
  }
  .pose-hint-affordance {
    /* Operator-locked S5: visual hint badge during path B's await. */
    position: absolute;
    bottom: 8px;
    left: 8px;
    z-index: 3;
    background: var(--color-bg-elev);
    color: var(--color-text);
    padding: 4px 8px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-border);
    font-size: 13px;
  }
</style>
