/**
 * issue#30 — `OriginPicker.svelte` + `MapMaskCanvas` mode-prop tests.
 *
 * The pre-issue#30 absolute/delta toggle is retired (the pick-anchored
 * delta-on-top semantic is unconditional). These tests pin the new
 * Q2-locked behavior: input boxes hold a typed DELTA on top of the
 * canvas-clicked picked point; clicks do NOT pre-fill input boxes.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import OriginPicker from '../../src/components/OriginPicker.svelte';
import MapMaskCanvas from '../../src/components/MapMaskCanvas.svelte';
import type { MapEditCoordBody, OriginPatchBody } from '../../src/lib/protocol';
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
  resolutionMPerPx?: number | null;
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
      resolutionMPerPx: props.resolutionMPerPx ?? 0.05,
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

describe('OriginPicker (issue#30 — pick-anchored + delta-on-top)', () => {
  it('placeholder for empty x_m / y_m / theta inputs reads "0" (Q2 locked)', () => {
    const { target } = mountPicker({});
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    const thetaInput = target.querySelector<HTMLInputElement>(
      '[data-testid="origin-theta-input"]',
    );
    expect(xInput!.placeholder).toBe('0');
    expect(yInput!.placeholder).toBe('0');
    expect(thetaInput!.placeholder).toBe('0');
  });

  it('XY click on canvas does NOT pre-fill x_m / y_m input boxes (Q2 locked)', () => {
    const { target, instance } = mountPicker({});
    flushSync();
    const inst = instance as unknown as {
      setCandidate: (c: { x_m: number; y_m: number }) => void;
      getPickedWorld: () => { x_m: number; y_m: number } | null;
    };
    inst.setCandidate({ x_m: 0.32, y_m: -0.18 });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    // Input fields remain EMPTY (delta-on-top — click does NOT pre-fill).
    expect(xInput!.value).toBe('');
    expect(yInput!.value).toBe('');
    // Picked point captured INTERNALLY.
    const picked = inst.getPickedWorld();
    expect(picked).not.toBeNull();
    expect(picked!.x_m).toBeCloseTo(0.32, 10);
    expect(picked!.y_m).toBeCloseTo(-0.18, 10);
  });

  it('getDirtyBody returns picked_world_* from internal click state, NOT from input fields', () => {
    const { target, instance } = mountPicker({});
    flushSync();
    const inst = instance as unknown as {
      setCandidate: (c: { x_m: number; y_m: number }) => void;
      getDirtyBody: () => Omit<MapEditCoordBody, 'memo'> | null;
    };
    // Operator clicks at world (5, 0).
    inst.setCandidate({ x_m: 5, y_m: 0 });
    flushSync();
    // Operator types a delta of (1, 0).
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="origin-y-input"]');
    xInput!.value = '1';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yInput!.value = '0';
    yInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    const body = inst.getDirtyBody();
    expect(body).not.toBeNull();
    // Typed delta lives in x_m / y_m.
    expect(body!.x_m).toBeCloseTo(1, 10);
    expect(body!.y_m).toBeCloseTo(0, 10);
    // Picked-world from canvas click is separate.
    expect(body!.picked_world_x_m).toBeCloseTo(5, 10);
    expect(body!.picked_world_y_m).toBeCloseTo(0, 10);
  });

  it('Apply button enabled when picked-world set even if all input boxes empty', () => {
    const { target, instance } = mountPicker({});
    flushSync();
    const inst = instance as unknown as {
      setCandidate: (c: { x_m: number; y_m: number }) => void;
    };
    inst.setCandidate({ x_m: 1, y_m: 2 });
    flushSync();
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    expect(applyBtn!.disabled).toBe(false);
  });

  it('NaN-like input (1e9999 = Infinity) is rejected and Apply disabled', () => {
    const { target } = mountPicker({});
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    xInput!.value = '1e9999';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(xInput!.classList.contains('input-invalid')).toBe(true);
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
    expect(xInput!.classList.contains('input-invalid')).toBe(true);
    expect(applyBtn!.disabled).toBe(true);
  });

  it('Negative typed delta is allowed (Apply enabled when valid)', () => {
    const { target, instance } = mountPicker({ role: 'admin' });
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
    void instance;
  });

  it('Anon role disables Apply (button visible but disabled)', () => {
    const { target } = mountPicker({ role: null });
    flushSync();
    const applyBtn = target.querySelector<HTMLButtonElement>('[data-testid="origin-apply-btn"]');
    expect(applyBtn).not.toBeNull();
    expect(applyBtn!.disabled).toBe(true);
  });

  it('+x button increments x by step (default 0.01 m)', () => {
    const { target } = mountPicker({});
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    const xPlus = target.querySelector<HTMLButtonElement>('[data-testid="origin-x-plus"]');
    expect(xPlus).not.toBeNull();
    xInput!.value = '1.000';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    xPlus!.click();
    flushSync();
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

  it('Discard clears typed delta + picked-world + yaw P1', () => {
    const { target, instance } = mountPicker({});
    flushSync();
    const inst = instance as unknown as {
      setCandidate: (c: { x_m: number; y_m: number }) => void;
      setYawClick: (c: { x_m: number; y_m: number }) => void;
      isYawP1Pending: () => boolean;
      getPickedWorld: () => { x_m: number; y_m: number } | null;
      clearAll: () => void;
    };
    inst.setCandidate({ x_m: 1, y_m: 2 });
    inst.setYawClick({ x_m: 0, y_m: 0 });
    flushSync();
    expect(inst.getPickedWorld()).not.toBeNull();
    expect(inst.isYawP1Pending()).toBe(true);
    inst.clearAll();
    flushSync();
    expect(inst.getPickedWorld()).toBeNull();
    expect(inst.isYawP1Pending()).toBe(false);
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    expect(xInput!.value).toBe('');
  });

  it('getDirtyBody returns null when nothing dirty (no pick + no typed)', () => {
    const { instance } = mountPicker({});
    flushSync();
    const inst = instance as unknown as {
      getDirtyBody: () => unknown | null;
    };
    expect(inst.getDirtyBody()).toBeNull();
  });

  it('getDirtyBody returns body without picked_world_* when only typed delta dirty', () => {
    const { target, instance } = mountPicker({});
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="origin-x-input"]');
    xInput!.value = '0.5';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    const inst = instance as unknown as {
      getDirtyBody: () => Omit<MapEditCoordBody, 'memo'> | null;
    };
    const body = inst.getDirtyBody();
    expect(body).not.toBeNull();
    expect(body!.x_m).toBeCloseTo(0.5, 10);
    // No pick → picked_world_* omitted (backend falls back to legacy
    // round-1 collapse and emits the X-GODO-Deprecation header).
    expect('picked_world_x_m' in body!).toBe(false);
    expect('picked_world_y_m' in body!).toBe(false);
  });
});

describe('OriginPicker (issue#28 — 2-click yaw pick) [carried forward]', () => {
  function mountPickerWithRes(props: {
    role?: 'admin' | 'viewer' | null;
    resolutionMPerPx?: number | null;
  }): { target: HTMLDivElement; instance: ReturnType<typeof mount> } {
    return mountPicker({
      role: props.role,
      resolutionMPerPx: props.resolutionMPerPx ?? 0.05,
    });
  }

  it('two-click yaw pre-fills theta_deg (east cardinal → 0°)', () => {
    const { target, instance } = mountPickerWithRes({});
    flushSync();
    const inst = instance as unknown as {
      setYawClick: (c: { x_m: number; y_m: number }) => void;
    };
    inst.setYawClick({ x_m: 0, y_m: 0 });
    inst.setYawClick({ x_m: 1, y_m: 0 });
    flushSync();
    const thetaInput = target.querySelector<HTMLInputElement>(
      '[data-testid="origin-theta-input"]',
    );
    expect(thetaInput!.value).toBe('0.0');
  });

  it('second click below YAW_PICK_MIN_PIXEL_DIST_PX rejected with inline error', () => {
    const { target, instance } = mountPickerWithRes({});
    flushSync();
    const inst = instance as unknown as {
      setYawClick: (c: { x_m: number; y_m: number }) => void;
      isYawP1Pending: () => boolean;
    };
    inst.setYawClick({ x_m: 0, y_m: 0 });
    flushSync();
    expect(inst.isYawP1Pending()).toBe(true);
    inst.setYawClick({ x_m: 0.1, y_m: 0 });
    flushSync();
    const banner = target.querySelector<HTMLParagraphElement>(
      '[data-testid="origin-yaw-banner"]',
    );
    expect(banner).not.toBeNull();
    expect(banner!.textContent).toMatch(/너무 가깝습니다/);
    expect(inst.isYawP1Pending()).toBe(true);
  });
});

describe('MapMaskCanvas mode-prop split (T5 fold) [carried forward]', () => {
  it('default mode is paint and brush paint behaviour is unchanged', () => {
    const { target, instance } = mountMaskCanvas({ width: 4, height: 4 });
    flushSync();
    const layer = target.querySelector<HTMLCanvasElement>('[data-testid="mask-paint-layer"]');
    layer!.dispatchEvent(makePointerEvent('pointerdown', { clientX: 50, clientY: 50 }));
    flushSync();
    const inst = instance as unknown as {
      _testGetMaskCell: (x: number, y: number) => number;
    };
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
    for (let y = 0; y < 4; y++) {
      for (let x = 0; x < 4; x++) {
        expect(inst._testGetMaskCell(x, y)).toBe(0);
      }
    }
  });
});
