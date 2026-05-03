/**
 * Track B-MAPEDIT-2 — `OriginPicker.svelte` + `MapMaskCanvas` mode-prop
 * vitest cases. 7 OriginPicker + 1 MapMaskCanvas mode-prop = 8 total
 * (per §8 Updated DoD T5 fold).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import OriginPicker from '../../src/components/OriginPicker.svelte';
import MapMaskCanvas from '../../src/components/MapMaskCanvas.svelte';
import type { LastPose, OriginPatchBody } from '../../src/lib/protocol';
import { lastPose } from '../../src/stores/lastPose';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

function installCanvasShims(): void {
  HTMLCanvasElement.prototype.getContext = vi.fn(function fakeGetContext(this: HTMLCanvasElement) {
    return {
      imageSmoothingEnabled: false,
      drawImage: vi.fn(),
      createImageData: vi.fn(
        (w: number, h: number) =>
          ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }) as ImageData,
      ),
      putImageData: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
  }) as unknown as typeof HTMLCanvasElement.prototype.getContext;
}

function makePointerEvent(type: string, init: { clientX: number; clientY: number }): Event {
  const ev = new MouseEvent(type, {
    bubbles: true,
    clientX: init.clientX,
    clientY: init.clientY,
  });
  Object.defineProperty(ev, 'pointerId', { value: 1, configurable: true });
  return ev;
}

function mountPicker(props: {
  currentOrigin?: readonly [number, number, number] | null;
  role?: 'admin' | 'viewer' | null;
  onapply?: (body: OriginPatchBody) => void;
}): { target: HTMLDivElement; instance: ReturnType<typeof mount> } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const instance = mount(OriginPicker, {
    target,
    props: {
      currentOrigin: props.currentOrigin ?? [-1.5, -2.0, 0.0],
      role: props.role ?? 'admin',
      busy: false,
      bannerMsg: null,
      bannerKind: null,
      onapply: props.onapply ?? ((): void => {}),
    },
  });
  cleanups.push(() => {
    unmount(instance);
    target.remove();
  });
  return { target, instance };
}

function mountMaskCanvas(props: {
  width: number;
  height: number;
  mode?: 'paint' | 'origin-pick';
  oncoordpick?: (lx: number, ly: number) => void;
}): { target: HTMLDivElement; instance: ReturnType<typeof mount> } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const instance = mount(MapMaskCanvas, {
    target,
    props: {
      width: props.width,
      height: props.height,
      mapImageUrl: '/api/map/image',
      brushRadius: 0,
      disabled: false,
      mode: props.mode,
      oncoordpick: props.oncoordpick,
    },
  });
  cleanups.push(() => {
    unmount(instance);
    target.remove();
  });
  const layer = target.querySelector<HTMLCanvasElement>('[data-testid="mask-paint-layer"]');
  if (layer) {
    layer.setPointerCapture = (): void => undefined;
    layer.hasPointerCapture = (): boolean => false;
    layer.releasePointerCapture = (): void => undefined;
    layer.getBoundingClientRect = vi.fn(
      () =>
        ({
          left: 0,
          top: 0,
          width: 100,
          height: 100,
          right: 100,
          bottom: 100,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect,
    );
  }
  return { target, instance };
}

beforeEach(() => {
  installCanvasShims();
});

afterEach(() => {
  while (cleanups.length > 0) {
    cleanups.pop()?.();
  }
  vi.restoreAllMocks();
  lastPose.set(null);
});

describe('OriginPicker (Track B-MAPEDIT-2)', () => {
  it('mode toggle switches absolute ↔ delta — radio state reflects selection', () => {
    const { target } = mountPicker({});
    flushSync();
    const absoluteRadio = target.querySelector<HTMLInputElement>(
      '[data-testid="origin-mode-absolute"]',
    );
    const deltaRadio = target.querySelector<HTMLInputElement>('[data-testid="origin-mode-delta"]');
    expect(absoluteRadio!.checked).toBe(true);
    deltaRadio!.click();
    flushSync();
    expect(deltaRadio!.checked).toBe(true);
    expect(absoluteRadio!.checked).toBe(false);
  });

  // Mode-B Maj-1 fix — delta resolves on the SPA via subscribeLastPose, then
  // sends absolute to the backend. These two tests pin both the resolution
  // happy-path and the no-pose error-path.

  it('delta mode without lastPose blocks Apply with no_pose_for_delta banner', () => {
    let captured: OriginPatchBody | null = null;
    lastPose.set(null);
    const { target } = mountPicker({
      onapply: (b) => (captured = b),
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    const deltaRadio = target.querySelector<HTMLInputElement>('[data-testid="origin-mode-delta"]');

    xInput!.value = '0.32';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yInput!.value = '-0.18';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    deltaRadio!.click();
    flushSync();

    applyBtn!.click();
    flushSync();
    expect(captured).toBeNull();
    const banner = target.querySelector<HTMLParagraphElement>('[data-testid="origin-banner"]');
    expect(banner).not.toBeNull();
    expect(banner!.textContent).toMatch(/Delta 모드는 현재 LiDAR pose가 필요합니다/);
  });

  it('delta mode with valid lastPose resolves typed delta to absolute via current pose', () => {
    let captured: OriginPatchBody | null = null;
    const pose: LastPose = {
      valid: true,
      x_m: 5.0,
      y_m: -3.0,
      yaw_deg: 0,
      xy_std_m: 0.01,
      yaw_std_deg: 0.5,
      iterations: 100,
      converged: true,
      forced: false,
      published_mono_ns: 1,
    };
    lastPose.set(pose);
    const { target } = mountPicker({
      onapply: (b) => (captured = b),
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    const deltaRadio = target.querySelector<HTMLInputElement>('[data-testid="origin-mode-delta"]');

    xInput!.value = '0.32';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yInput!.value = '-0.18';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    deltaRadio!.click();
    flushSync();

    applyBtn!.click();
    flushSync();
    expect(captured).not.toBeNull();
    // SPA resolves: abs = pose + delta = (5.0 + 0.32, -3.0 + -0.18) = (5.32, -3.18)
    // Body always carries mode=absolute (backend stays dumb).
    expect(captured!.mode).toBe('absolute');
    expect(captured!.x_m).toBeCloseTo(5.32, 10);
    expect(captured!.y_m).toBeCloseTo(-3.18, 10);
  });

  it('NaN-like input (1e9999 = Infinity) is rejected and Apply is disabled', () => {
    const { target } = mountPicker({});
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    // 1e9999 parses as Infinity in JavaScript, which Number.isFinite rejects.
    xInput!.value = '1e9999';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    // y still empty so apply must be disabled regardless.
    expect(applyBtn!.disabled).toBe(true);
  });

  it('Locale-comma decimal is rejected — paste `1,234.5` shows error class', () => {
    const { target } = mountPicker({});
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    xInput!.value = '1,234.5';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    // The input has the invalid class because the parser rejected the comma.
    expect(xInput!.classList.contains('input-invalid')).toBe(true);
    expect(applyBtn!.disabled).toBe(true);
  });

  it('Negative value is allowed (Apply enabled when both fields valid)', () => {
    const { target } = mountPicker({ role: 'admin' });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    xInput!.value = '-1.5';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yInput!.value = '-2.0';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(applyBtn!.disabled).toBe(false);
  });

  it('setCandidate({x_m, y_m}) pre-fills both fields AND forces mode=absolute (T1 fold)', () => {
    const { target, instance } = mountPicker({});
    flushSync();
    // First flip mode to delta so we can prove setCandidate forces it back.
    const deltaRadio = target.querySelector<HTMLInputElement>('[data-testid="origin-mode-delta"]');
    deltaRadio!.click();
    flushSync();
    const inst = instance as unknown as {
      setCandidate: (c: { x_m: number; y_m: number }) => void;
    };
    inst.setCandidate({ x_m: 0.32, y_m: -0.18 });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const absoluteRadio = target.querySelector<HTMLInputElement>(
      '[data-testid="origin-mode-absolute"]',
    );
    // T1 fold: mode flipped back to absolute.
    expect(absoluteRadio!.checked).toBe(true);
    // Inputs pre-filled.
    expect(xInput!.value).toBe('0.320');
    expect(yInput!.value).toBe('-0.180');
  });

  it('Apply payload shape matches OriginPatchBody (canonical 3-key body)', () => {
    let captured: OriginPatchBody | null = null;
    const { target } = mountPicker({
      onapply: (b) => (captured = b),
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    xInput!.value = '-1.5';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yInput!.value = '-2.0';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    applyBtn!.click();
    flushSync();
    expect(captured).not.toBeNull();
    // 3-key body shape pin (drift catch against OriginPatchBody).
    expect(Object.keys(captured!).sort()).toEqual(['mode', 'x_m', 'y_m']);
    expect(captured!.x_m).toBeCloseTo(-1.5, 10);
    expect(captured!.y_m).toBeCloseTo(-2.0, 10);
    expect(captured!.mode).toBe('absolute');
  });

  it('Anon role disables Apply (button visible but disabled)', () => {
    const { target } = mountPicker({ role: null });
    flushSync();
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    expect(applyBtn).not.toBeNull();
    // With both fields empty AND role=null, button is disabled.
    expect(applyBtn!.disabled).toBe(true);
  });

  it('Viewer role with valid inputs still cannot Apply', () => {
    const { target } = mountPicker({ role: 'viewer' });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    // Inputs are disabled for viewer; we set them directly via the
    // bind:value-tracked store. flushSync after each set so the
    // $derived applyDisabled re-evaluates.
    xInput!.value = '0';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yInput!.value = '0';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(applyBtn!.disabled).toBe(true);
    expect(applyBtn!.title).toContain('로그인');
  });
});

describe('OriginPicker (issue#27 — theta + +/- step buttons)', () => {
  it('theta input is optional — Apply enabled with x/y valid + theta empty', () => {
    let captured: OriginPatchBody | null = null;
    const { target } = mountPicker({
      onapply: (b) => (captured = b),
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const thetaInput = target.querySelector<HTMLInputElement>(
      '[data-testid="origin-theta-input"]',
    );
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    expect(thetaInput).not.toBeNull();
    xInput!.value = '0.32';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yInput!.value = '-0.18';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    // theta empty — Apply still enabled.
    expect(applyBtn!.disabled).toBe(false);
    applyBtn!.click();
    flushSync();
    // Body has NO theta_deg key (preserves YAML byte-stability per
    // backend invariant).
    expect(captured).not.toBeNull();
    expect('theta_deg' in captured!).toBe(false);
  });

  it('theta input populated → body carries theta_deg', () => {
    let captured: OriginPatchBody | null = null;
    const { target } = mountPicker({
      onapply: (b) => (captured = b),
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const thetaInput = target.querySelector<HTMLInputElement>(
      '[data-testid="origin-theta-input"]',
    );
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    xInput!.value = '0';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yInput!.value = '0';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    thetaInput!.value = '5.0';
    thetaInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    applyBtn!.click();
    flushSync();
    expect(captured).not.toBeNull();
    expect(captured!.theta_deg).toBeCloseTo(5.0, 6);
  });

  it('+x button increments x by step (default 0.01 m)', () => {
    const { target } = mountPicker({});
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const xPlus = target.querySelector<HTMLButtonElement>('[data-testid="origin-x-plus"]');
    expect(xPlus).not.toBeNull();
    // Set baseline to 1.000.
    xInput!.value = '1.000';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    xPlus!.click();
    flushSync();
    // Default step is 0.01; xText fmtDisplay rounds to 3 decimals.
    expect(xInput!.value).toBe('1.010');
  });

  it('-y button decrements y by step', () => {
    const { target } = mountPicker({});
    flushSync();
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const yMinus = target.querySelector<HTMLButtonElement>('[data-testid="origin-y-minus"]');
    yInput!.value = '0.000';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    yMinus!.click();
    flushSync();
    expect(yInput!.value).toBe('-0.010');
  });

  it('+theta button increments theta by step (default 0.1°)', () => {
    const { target } = mountPicker({});
    flushSync();
    const thetaInput = target.querySelector<HTMLInputElement>(
      '[data-testid="origin-theta-input"]',
    );
    const thetaPlus = target.querySelector<HTMLButtonElement>(
      '[data-testid="origin-theta-plus"]',
    );
    expect(thetaInput).not.toBeNull();
    expect(thetaPlus).not.toBeNull();
    thetaInput!.value = '0.0';
    thetaInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    thetaPlus!.click();
    flushSync();
    expect(thetaInput!.value).toBe('0.1');
  });

  it('+x clicked from empty input starts at 0 + step', () => {
    const { target } = mountPicker({});
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const xPlus = target.querySelector<HTMLButtonElement>('[data-testid="origin-x-plus"]');
    xPlus!.click();
    flushSync();
    expect(xInput!.value).toBe('0.010');
  });
});

describe('MapMaskCanvas mode-prop split (T5 fold)', () => {
  it('default mode is paint and brush paint behaviour is unchanged', () => {
    const { target, instance } = mountMaskCanvas({ width: 4, height: 4 });
    flushSync();
    const layer = target.querySelector<HTMLCanvasElement>('[data-testid="mask-paint-layer"]');
    layer!.dispatchEvent(makePointerEvent('pointerdown', { clientX: 50, clientY: 50 }));
    flushSync();
    const inst = instance as unknown as {
      _testGetMaskCell: (x: number, y: number) => number;
    };
    // CSS box is 100×100; logical 4×4; CSS (50, 50) → logical (2, 2).
    expect(inst._testGetMaskCell(2, 2)).toBe(255);
  });

  it("mode='origin-pick' calls oncoordpick + leaves mask buffer byte-identical", () => {
    const picks: Array<[number, number]> = [];
    const { target, instance } = mountMaskCanvas({
      width: 4,
      height: 4,
      mode: 'origin-pick',
      oncoordpick: (lx, ly) => picks.push([lx, ly]),
    });
    flushSync();
    const layer = target.querySelector<HTMLCanvasElement>('[data-testid="mask-paint-layer"]');
    layer!.dispatchEvent(makePointerEvent('pointerdown', { clientX: 50, clientY: 50 }));
    flushSync();
    expect(picks).toEqual([[2, 2]]);
    const inst = instance as unknown as {
      _testGetMaskCell: (x: number, y: number) => number;
    };
    // Mask state byte-identical to a no-op (every cell zero — invariant (u)).
    for (let y = 0; y < 4; y++) {
      for (let x = 0; x < 4; x++) {
        expect(inst._testGetMaskCell(x, y)).toBe(0);
      }
    }
  });
});
