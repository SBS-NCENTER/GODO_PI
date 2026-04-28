<script lang="ts">
  /**
   * PR-DIAG — hand-rolled canvas sparkline.
   *
   * Props: `{ values, color, label, formatValue, width?, height? }`.
   * Auto-scales y-axis to data range (min..max). No external chart lib —
   * the FRONT_DESIGN §9 chart-library decision is still pending; this
   * component lets PR-DIAG ship independently (OQ-DIAG-1).
   *
   * The `formatValue` callback returns the display string for the
   * last-value chip on the right (e.g., `(v) => v.toFixed(1) + " µs"`).
   */

  import { onMount } from 'svelte';
  import { DIAG_SPARKLINE_HEIGHT_PX, DIAG_SPARKLINE_WIDTH_PX } from '$lib/constants';

  interface Props {
    values: number[];
    color: string;
    label: string;
    formatValue: (v: number) => string;
    width?: number;
    height?: number;
  }

  let {
    values,
    color,
    label,
    formatValue,
    width = DIAG_SPARKLINE_WIDTH_PX,
    height = DIAG_SPARKLINE_HEIGHT_PX,
  }: Props = $props();

  let canvas = $state<HTMLCanvasElement | null>(null);

  function draw(canvasEl: HTMLCanvasElement, vs: number[]): void {
    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
    if (vs.length === 0) return;

    let lo = Number.POSITIVE_INFINITY;
    let hi = Number.NEGATIVE_INFINITY;
    for (const v of vs) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (lo === hi) {
      // Flat line — render a single horizontal stroke at the canvas mid.
      const y = canvasEl.height / 2;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvasEl.width, y);
      ctx.stroke();
      return;
    }

    const range = hi - lo;
    const w = canvasEl.width;
    const h = canvasEl.height;
    const stepX = vs.length > 1 ? w / (vs.length - 1) : 0;

    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < vs.length; ++i) {
      const x = i * stepX;
      // Invert y so larger values are higher on screen.
      const y = h - ((vs[i] - lo) / range) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  $effect(() => {
    if (!canvas) return;
    draw(canvas, values);
  });

  onMount(() => {
    if (!canvas) return;
    canvas.width = width;
    canvas.height = height;
    draw(canvas, values);
  });

  let lastValueDisplay = $derived(values.length > 0 ? formatValue(values[values.length - 1]) : '—');
</script>

<div class="sparkline" data-testid="diag-sparkline">
  <span class="sparkline-label">{label}</span>
  <canvas bind:this={canvas} {width} {height} aria-label={label}></canvas>
  <span class="sparkline-chip" style="color: {color}">{lastValueDisplay}</span>
</div>

<style>
  .sparkline {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
  }
  .sparkline-label {
    width: 110px;
    color: var(--color-text-muted);
  }
  .sparkline-chip {
    font-variant-numeric: tabular-nums;
    font-weight: 500;
    min-width: 80px;
    text-align: right;
  }
  canvas {
    display: block;
  }
</style>
