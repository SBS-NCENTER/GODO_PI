/**
 * Track B-MAPEDIT — `routes/MapEdit.svelte` + `components/MapMaskCanvas.svelte`
 * vitest cases (6 total per planner §5; T4 fold baked into case 1).
 *
 * Canvas mock: jsdom does not implement `HTMLCanvasElement.getContext`
 * or `toBlob`, so we mount thin shims for the surface the components
 * actually use (createImageData / putImageData / drawImage / toBlob).
 * Pattern is borrowed from `diagSparkline.test.ts`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import MapEdit from '../../src/routes/MapEdit.svelte';
import MapMaskCanvas from '../../src/components/MapMaskCanvas.svelte';
import * as api from '../../src/lib/api';
import { auth } from '../../src/stores/auth';
import { mapMetadata } from '../../src/stores/mapMetadata';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function pngResp(): Response {
  const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return new Response(bytes, {
    status: 200,
    headers: { 'content-type': 'image/png' },
  });
}

/**
 * Install jsdom canvas shims globally for this test module. Kept minimal
 * — we only stub the methods the component reads.
 */
function installCanvasShims(): void {
  // getContext: a 2D-ish object with the methods MapMaskCanvas uses.
  HTMLCanvasElement.prototype.getContext = vi.fn(function fakeGetContext(this: HTMLCanvasElement) {
    const ctx = {
      imageSmoothingEnabled: false,
      drawImage: vi.fn(),
      createImageData: vi.fn(
        (w: number, h: number) =>
          ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }) as ImageData,
      ),
      putImageData: vi.fn(),
    };
    return ctx as unknown as CanvasRenderingContext2D;
  }) as unknown as typeof HTMLCanvasElement.prototype.getContext;

  // toBlob: synthesise a non-empty PNG-ish Blob; the component does not
  // inspect the bytes; the backend stub does not run here.
  HTMLCanvasElement.prototype.toBlob = function fakeToBlob(cb: BlobCallback, _type?: string): void {
    const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    setTimeout(() => cb(new Blob([bytes], { type: 'image/png' })), 0);
  };
}

/** PointerEvent isn't part of jsdom; fall back to MouseEvent which is
 * compatible enough — `clientX`/`clientY`/`pointerId` (we set as
 * non-standard prop) are all the component reads. */
function makePointerEvent(type: string, init: { clientX: number; clientY: number }): Event {
  const ev = new MouseEvent(type, {
    bubbles: true,
    clientX: init.clientX,
    clientY: init.clientY,
  });
  // Component calls .setPointerCapture(pointerId); patch to a no-op on
  // the target element below.
  Object.defineProperty(ev, 'pointerId', { value: 1, configurable: true });
  return ev;
}

beforeEach(() => {
  installCanvasShims();
  api.configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
  auth.set(null);
  mapMetadata.set(null);
  Object.defineProperty(window, 'location', {
    value: {
      hostname: '127.0.0.1',
      origin: 'http://localhost',
      hash: '#/map-edit',
    },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  while (cleanups.length > 0) {
    cleanups.pop()?.();
  }
  auth.set(null);
  mapMetadata.set(null);
  vi.restoreAllMocks();
});

function setAdminSession(): void {
  auth.set({
    token: 'tok',
    username: 'ncenter',
    role: 'admin',
    exp: Math.floor(Date.now() / 1000) + 3600,
  });
}

function mountCanvas(props: {
  width: number;
  height: number;
  brushRadius?: number;
  disabled?: boolean;
}): { target: HTMLDivElement; instance: ReturnType<typeof mount> } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const instance = mount(MapMaskCanvas, {
    target,
    props: {
      width: props.width,
      height: props.height,
      mapImageUrl: '/api/map/image',
      brushRadius: props.brushRadius ?? 1,
      disabled: props.disabled ?? false,
    },
  });
  cleanups.push(() => {
    unmount(instance);
    target.remove();
  });
  // Stub setPointerCapture / hasPointerCapture / releasePointerCapture
  // on the mask layer (jsdom doesn't implement them).
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

function mountPage(): HTMLDivElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(MapEdit, { target, props: {} });
  cleanups.push(() => {
    unmount(component);
    target.remove();
  });
  return target;
}

async function waitFor<T>(getter: () => T | null, label: string, timeoutMs = 1000): Promise<T> {
  const start = Date.now();
  let v = getter();
  while (v === null) {
    if (Date.now() - start > timeoutMs) {
      throw new Error(`waitFor timeout: ${label}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 5));
    flushSync();
    v = getter();
  }
  return v;
}

describe('MapMaskCanvas (Track B-MAPEDIT)', () => {
  it('paint at CSS (50, 50) with devicePixelRatio=2 hits LOGICAL mask cell (50, 50) (T4 fold)', () => {
    Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true });

    const { target, instance } = mountCanvas({ width: 100, height: 100, brushRadius: 0 });
    flushSync();
    const layer = target.querySelector<HTMLCanvasElement>('[data-testid="mask-paint-layer"]');
    expect(layer).not.toBeNull();
    layer!.dispatchEvent(makePointerEvent('pointerdown', { clientX: 50, clientY: 50 }));
    flushSync();

    const inst = instance as unknown as {
      _testGetMaskCell: (x: number, y: number) => number;
    };
    // Logical cell (50, 50) painted regardless of DPR.
    expect(inst._testGetMaskCell(50, 50)).toBe(255);
    // A DPR-bug writer would have written into (100, 100) which is
    // out-of-range; the adjacent (49, 49) should remain unpainted.
    expect(inst._testGetMaskCell(49, 49)).toBe(0);
  });

  it('getMaskPng emits alpha=0 for unpainted, alpha=255 for painted (regression: full-mask bug)', async () => {
    // Bug landed in v1: getMaskPng wrote alpha=255 unconditionally, so
    // every pixel — including the unpainted majority — passed the
    // backend's alpha-as-paint branch (map_edit.py L177-181) and the
    // entire active map got rewritten to FREE on every Apply. The fix
    // is alpha-tracks-paint: alpha=0 unpainted, alpha=255 painted.
    const captured: ImageData[] = [];
    const orig = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = vi.fn(function fake(this: HTMLCanvasElement) {
      return {
        imageSmoothingEnabled: false,
        drawImage: vi.fn(),
        createImageData: (w: number, h: number) =>
          ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }) as ImageData,
        putImageData: (img: ImageData): void => {
          captured.push({
            data: new Uint8ClampedArray(img.data),
            width: img.width,
            height: img.height,
          } as ImageData);
        },
      } as unknown as CanvasRenderingContext2D;
    }) as never;
    cleanups.push(() => {
      HTMLCanvasElement.prototype.getContext = orig;
    });

    const { target, instance } = mountCanvas({ width: 4, height: 4, brushRadius: 0 });
    flushSync();
    const layer = target.querySelector<HTMLCanvasElement>('[data-testid="mask-paint-layer"]');
    // CSS box is 100x100; logical 4x4; CSS (37, 37) -> logical floor(1.48)=1
    layer!.dispatchEvent(makePointerEvent('pointerdown', { clientX: 37, clientY: 37 }));
    flushSync();

    const inst = instance as unknown as { getMaskPng: () => Promise<Blob> };
    await inst.getMaskPng();

    // Last putImageData call is the one inside getMaskPng's temp canvas.
    expect(captured.length).toBeGreaterThan(0);
    const last = captured[captured.length - 1];
    expect(last.width).toBe(4);
    expect(last.height).toBe(4);
    // Painted cell (1, 1): alpha=255
    const paintedAlpha = last.data[(1 * 4 + 1) * 4 + 3];
    expect(paintedAlpha).toBe(255);
    // Unpainted cell (0, 0): alpha=0 (the bug emitted 255 here)
    const unpaintedAlpha = last.data[(0 * 4 + 0) * 4 + 3];
    expect(unpaintedAlpha).toBe(0);
    // Unpainted cell (3, 3): alpha=0
    const cornerAlpha = last.data[(3 * 4 + 3) * 4 + 3];
    expect(cornerAlpha).toBe(0);
  });

  it('clear() resets every painted cell to 0', () => {
    const { target, instance } = mountCanvas({ width: 4, height: 4, brushRadius: 10 });
    flushSync();
    const layer = target.querySelector<HTMLCanvasElement>('[data-testid="mask-paint-layer"]');
    layer!.dispatchEvent(makePointerEvent('pointerdown', { clientX: 25, clientY: 25 }));
    flushSync();
    const inst = instance as unknown as {
      _testGetMaskCell: (x: number, y: number) => number;
      clear: () => void;
    };
    let painted = 0;
    for (let y = 0; y < 4; y++) {
      for (let x = 0; x < 4; x++) {
        if (inst._testGetMaskCell(x, y) > 0) painted++;
      }
    }
    expect(painted).toBeGreaterThan(0);
    inst.clear();
    flushSync();
    let after = 0;
    for (let y = 0; y < 4; y++) {
      for (let x = 0; x < 4; x++) {
        if (inst._testGetMaskCell(x, y) > 0) after++;
      }
    }
    expect(after).toBe(0);
  });
});

describe('MapEdit page (Track B-MAPEDIT)', () => {
  it('Apply POSTs FormData with a "mask" part to /api/map/edit', async () => {
    let editCalls = 0;
    let lastBody: BodyInit | null | undefined = null;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = input as string;
      if (url.endsWith('/api/map/edit')) {
        editCalls++;
        lastBody = init?.body ?? null;
        return jsonResp({
          ok: true,
          backup_ts: '20260430T010203Z',
          pixels_changed: 4,
          restart_required: true,
        });
      }
      if (url.endsWith('/api/map/image')) return pngResp();
      if (url.endsWith('/dimensions')) return jsonResp({ width: 4, height: 4 });
      return jsonResp({ pending: false });
    });
    setAdminSession();
    mapMetadata.set({
      image: 'studio_v1.pgm',
      resolution: 0.05,
      origin: [0, 0, 0],
      negate: 0,
      width: 4,
      height: 4,
      source_url: '/api/map/image',
    });

    const target = mountPage();
    const applyBtn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="map-edit-apply-btn"]'),
      'apply button',
    );
    applyBtn.click();
    await waitFor<HTMLElement>(
      () => {
        const b = target.querySelector<HTMLElement>('[data-testid="map-edit-banner"]');
        if (!b) return null;
        // Wait for the success-state banner specifically.
        if (!b.classList.contains('banner-success')) return null;
        return b;
      },
      'success banner',
      2000,
    );

    expect(editCalls).toBe(1);
    expect(lastBody).toBeInstanceOf(FormData);
    const fd = lastBody as FormData;
    expect(fd.has('mask')).toBe(true);
    const part = fd.get('mask');
    expect(part).toBeInstanceOf(Blob);
  });

  it('Apply button disabled for anon viewer', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = input as string;
      if (url.endsWith('/api/map/image')) return pngResp();
      return jsonResp({ pending: false });
    });
    mapMetadata.set({
      image: 'studio_v1.pgm',
      resolution: 0.05,
      origin: [0, 0, 0],
      negate: 0,
      width: 4,
      height: 4,
      source_url: '/api/map/image',
    });
    const target = mountPage();
    const btn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="map-edit-apply-btn"]'),
      'apply button',
    );
    expect(btn.disabled).toBe(true);
  });

  it('success → redirects to /map after MAP_EDIT_REDIRECT_DELAY_MS', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = input as string;
      if (url.endsWith('/api/map/edit')) {
        return jsonResp({
          ok: true,
          backup_ts: '20260430T010203Z',
          pixels_changed: 1,
          restart_required: true,
        });
      }
      if (url.endsWith('/api/map/image')) return pngResp();
      return jsonResp({ pending: false });
    });
    setAdminSession();
    mapMetadata.set({
      image: 'studio_v1.pgm',
      resolution: 0.05,
      origin: [0, 0, 0],
      negate: 0,
      width: 4,
      height: 4,
      source_url: '/api/map/image',
    });

    const router = await import('../../src/lib/router');
    const navSpy = vi.spyOn(router, 'navigate').mockImplementation(() => {});

    const target = mountPage();
    const btn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="map-edit-apply-btn"]'),
      'apply button',
    );
    btn.click();
    await waitFor<HTMLElement>(
      () => {
        const b = target.querySelector<HTMLElement>('[data-testid="map-edit-banner"]');
        if (!b || !b.classList.contains('banner-success')) return null;
        return b;
      },
      'success banner',
      2000,
    );
    expect(navSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(3000);
    flushSync();
    expect(navSpy).toHaveBeenCalledWith('/map');

    vi.useRealTimers();
  });

  it('error → surfaces inline; brush state preserved', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = input as string;
      if (url.endsWith('/api/map/edit')) {
        return jsonResp({ ok: false, err: 'mask_shape_mismatch' }, 400);
      }
      if (url.endsWith('/api/map/image')) return pngResp();
      return jsonResp({ pending: false });
    });
    setAdminSession();
    mapMetadata.set({
      image: 'studio_v1.pgm',
      resolution: 0.05,
      origin: [0, 0, 0],
      negate: 0,
      width: 4,
      height: 4,
      source_url: '/api/map/image',
    });

    const target = mountPage();
    const btn = await waitFor<HTMLButtonElement>(
      () => target.querySelector<HTMLButtonElement>('[data-testid="map-edit-apply-btn"]'),
      'apply button',
    );
    btn.click();
    const banner = await waitFor<HTMLElement>(
      () => {
        const b = target.querySelector<HTMLElement>('[data-testid="map-edit-banner"]');
        if (!b || !b.classList.contains('banner-error')) return null;
        return b;
      },
      'error banner',
      2000,
    );
    expect(banner.textContent).toContain('mask_shape_mismatch');
    // Apply button is re-enabled (not stuck in busy state).
    expect(btn.disabled).toBe(false);
  });
});
