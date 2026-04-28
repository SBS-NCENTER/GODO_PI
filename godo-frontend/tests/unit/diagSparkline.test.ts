import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushSync, unmount } from 'svelte';

import DiagSparkline from '../../src/components/DiagSparkline.svelte';

interface Recorder {
  moveTo: number;
  lineTo: number;
  stroke: number;
  clearRect: number;
}

function recordingCtx(): { ctx: CanvasRenderingContext2D; rec: Recorder } {
  const rec: Recorder = { moveTo: 0, lineTo: 0, stroke: 0, clearRect: 0 };
  const ctx = {
    moveTo: vi.fn(() => {
      rec.moveTo += 1;
    }),
    lineTo: vi.fn(() => {
      rec.lineTo += 1;
    }),
    stroke: vi.fn(() => {
      rec.stroke += 1;
    }),
    clearRect: vi.fn(() => {
      rec.clearRect += 1;
    }),
    beginPath: vi.fn(),
    set strokeStyle(_v: string) {},
    set lineWidth(_v: number) {},
  } as unknown as CanvasRenderingContext2D;
  return { ctx, rec };
}

let target: HTMLDivElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  document.body.removeChild(target);
  vi.restoreAllMocks();
});

describe('DiagSparkline', () => {
  it('renders nothing onto an empty values array', () => {
    const { ctx, rec } = recordingCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(
      () => ctx,
    ) as unknown as typeof HTMLCanvasElement.prototype.getContext;
    const cmp = mount(DiagSparkline, {
      target,
      props: {
        values: [],
        color: '#000',
        label: 'lbl',
        formatValue: (v: number) => String(v),
      },
    });
    flushSync();
    expect(rec.lineTo).toBe(0);
    expect(rec.moveTo).toBe(0);
    unmount(cmp);
  });

  it('renders a flat horizontal stroke when all values are equal', () => {
    const { ctx, rec } = recordingCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(
      () => ctx,
    ) as unknown as typeof HTMLCanvasElement.prototype.getContext;
    const cmp = mount(DiagSparkline, {
      target,
      props: {
        values: [3, 3, 3, 3],
        color: '#000',
        label: 'lbl',
        formatValue: (v: number) => String(v),
      },
    });
    flushSync();
    // One moveTo + one lineTo for the flat-line branch.
    expect(rec.moveTo).toBeGreaterThanOrEqual(1);
    expect(rec.lineTo).toBeGreaterThanOrEqual(1);
    expect(rec.stroke).toBeGreaterThanOrEqual(1);
    unmount(cmp);
  });

  it('renders a polyline of moveTo + (n-1) lineTo per draw call', () => {
    const { ctx, rec } = recordingCtx();
    HTMLCanvasElement.prototype.getContext = vi.fn(
      () => ctx,
    ) as unknown as typeof HTMLCanvasElement.prototype.getContext;
    const cmp = mount(DiagSparkline, {
      target,
      props: {
        values: [1, 2, 3, 4, 5],
        color: '#000',
        label: 'lbl',
        formatValue: (v: number) => String(v),
      },
    });
    flushSync();
    // The component draws on both onMount AND the $effect that depends
    // on values, so the recorder may see the polyline twice. Assert the
    // 1:(n-1) shape ratio rather than the absolute count, which is
    // robust to Svelte 5's effect scheduling.
    expect(rec.moveTo).toBeGreaterThanOrEqual(1);
    expect(rec.lineTo).toBe(rec.moveTo * 4); // (5 - 1) lineTo per draw
    unmount(cmp);
  });

  it('renders the label and last-value chip from formatValue', () => {
    const cmp = mount(DiagSparkline, {
      target,
      props: {
        values: [10, 20, 30],
        color: '#abc',
        label: 'p99',
        formatValue: (v: number) => v.toFixed(0) + ' ns',
      },
    });
    flushSync();
    expect(target.textContent).toContain('p99');
    expect(target.textContent).toContain('30 ns');
    unmount(cmp);
  });

  it('renders the chip as "—" when values is empty', () => {
    const cmp = mount(DiagSparkline, {
      target,
      props: {
        values: [],
        color: '#abc',
        label: 'p99',
        formatValue: (v: number) => v.toFixed(0) + ' ns',
      },
    });
    flushSync();
    expect(target.textContent).toContain('—');
    unmount(cmp);
  });
});
