/**
 * Component-level test: `MapListPanel` activate-dialog hide-button gate.
 *
 * Mode-A M4 contract (per the plan and the Mode-B reviewer's recommendation):
 * when the SPA is loaded from a NON-loopback hostname (e.g. an operator
 * hits the URL from a studio PC, not the kiosk on `127.0.0.1`), the
 * activate-confirm dialog MUST hide the primary "godo-tracker 재시작"
 * button entirely — only `재시작하지 않음` (secondary) and `취소` (cancel)
 * render. A small placeholder span with the `로컬 kiosk에서만 가능` tooltip
 * fills the slot where the primary button would have been.
 *
 * The pure-logic store tests live in `maps.test.ts`. This file mounts
 * the real component into jsdom (via Svelte 5's built-in `mount` API —
 * no `@testing-library/svelte` dependency added) and exercises the
 * actual render path so a regression in `MapListPanel.svelte`'s
 * `isLoopbackHost()` predicate or in `ConfirmDialog`'s `showPrimary`
 * prop wiring will fail this test.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import MapListPanel from '../../src/components/MapListPanel.svelte';
import { configureAuth } from '../../src/lib/api';
import { auth } from '../../src/stores/auth';
import { maps } from '../../src/stores/maps';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

beforeEach(() => {
  // Wire the api layer to a known token so `apiGet('/api/maps')` is
  // happy. The test never inspects the token; we only need a non-null
  // value to exercise the same code path the production app runs.
  configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });

  // Clear the module-singleton stores between tests so a previous
  // mount's data does not bleed into the next one.
  maps.set([]);
  auth.set(null);

  // Stub fetch so the `onMount → refresh()` call in `MapListPanel`
  // resolves with a deterministic two-row list — one active, one not.
  // We click the activate button on the NON-active row so the dialog
  // opens without hitting any "already active" branch.
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify([
        {
          name: 'studio_v1',
          size_bytes: 16,
          mtime_unix: 1.0,
          is_active: true,
          width_px: 200,
          height_px: 200,
          resolution_m: 0.05,
        },
        {
          name: 'studio_v2',
          size_bytes: 16,
          mtime_unix: 2.0,
          is_active: false,
          width_px: 400,
          height_px: 400,
          resolution_m: 0.025,
        },
      ]),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ),
  );
});

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
  vi.restoreAllMocks();
});

function setHostname(hostname: string): void {
  // jsdom's window.location is read-only on `.hostname` directly, but
  // the whole `location` object can be replaced. We preserve the other
  // fields the SPA reads (origin, hash) so router code does not break.
  Object.defineProperty(window, 'location', {
    value: { hostname, origin: `http://${hostname}`, hash: '#/' },
    writable: true,
    configurable: true,
  });
}

function setAdminSession(): void {
  auth.set({
    token: 'tok',
    username: 'ncenter',
    role: 'admin',
    exp: Math.floor(Date.now() / 1000) + 3600,
  });
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

async function mountAndOpenActivateDialog(): Promise<HTMLDivElement> {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(MapListPanel, { target, props: {} });
  cleanups.push(() => {
    unmount(component);
    target.remove();
  });

  // `onMount → refresh()` is an async fetch + store update. Use a
  // bounded poll to wait for the table row to render — race-free vs.
  // fixed micro-tick counts under jsdom.
  const activateBtn = await waitFor<HTMLButtonElement>(
    () => target.querySelector<HTMLButtonElement>('[data-testid="map-activate-studio_v2"]'),
    'activate button for studio_v2',
  );
  // The button is disabled when role !== 'admin' OR is_active. We set
  // the admin session above and target the non-active row, so the
  // button is enabled here.
  expect(activateBtn.disabled).toBe(false);
  activateBtn.click();
  flushSync();

  return target;
}

describe('MapListPanel — activate-dialog hide-button gate (M4)', () => {
  it('hides the primary button when window.location.hostname is non-loopback', async () => {
    setHostname('192.168.1.50');
    setAdminSession();

    const target = await mountAndOpenActivateDialog();

    // Dialog opened — sanity check.
    expect(target.querySelector('[data-testid="confirm-dialog"]')).not.toBeNull();
    // Cancel + secondary render.
    expect(target.querySelector('[data-testid="confirm-cancel"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="confirm-secondary"]')).not.toBeNull();
    // Primary is hidden; placeholder with the loopback-only tooltip
    // takes its slot.
    expect(target.querySelector('[data-testid="confirm-ok"]')).toBeNull();
    const placeholder = target.querySelector<HTMLSpanElement>(
      '[data-testid="confirm-primary-hidden"]',
    );
    expect(placeholder).not.toBeNull();
    expect(placeholder!.getAttribute('title')).toContain('로컬 kiosk에서만 가능');
  });

  it('shows the primary button when window.location.hostname is loopback', async () => {
    // Companion sanity case — the same mount on `127.0.0.1` MUST render
    // the primary button. Without this we cannot tell whether the
    // hide-case test above is asserting "the button is gone" or "the
    // button never existed in the first place".
    setHostname('127.0.0.1');
    setAdminSession();

    const target = await mountAndOpenActivateDialog();

    expect(target.querySelector('[data-testid="confirm-dialog"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="confirm-ok"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="confirm-primary-hidden"]')).toBeNull();
  });
});

describe('MapListPanel — map dimensions cell (operator UX 2026-05-02)', () => {
  it('renders W×H px (X.X×Y.Y m) for entries with both dims and resolution', async () => {
    setHostname('127.0.0.1');
    setAdminSession();

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(MapListPanel, { target, props: {} });
    cleanups.push(() => {
      unmount(component);
      target.remove();
    });
    await waitFor(
      () => target.querySelector('[data-testid="map-dims-studio_v1"]'),
      'studio_v1 dims cell',
    );
    // 200×200 px @ 0.05 m/cell → 10.0×10.0 m
    const v1 = target.querySelector<HTMLTableCellElement>(
      '[data-testid="map-dims-studio_v1"]',
    );
    expect(v1).not.toBeNull();
    expect(v1!.textContent).toMatch(/200×200 px/);
    expect(v1!.textContent).toMatch(/10\.0×10\.0 m/);

    // 400×400 px @ 0.025 m/cell → 10.0×10.0 m (high-res of same area)
    const v2 = target.querySelector<HTMLTableCellElement>(
      '[data-testid="map-dims-studio_v2"]',
    );
    expect(v2).not.toBeNull();
    expect(v2!.textContent).toMatch(/400×400 px/);
    expect(v2!.textContent).toMatch(/10\.0×10\.0 m/);
  });

  it('renders W×H px alone when resolution is null (graceful degradation)', async () => {
    setHostname('127.0.0.1');
    setAdminSession();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            name: 'studio_no_res',
            size_bytes: 16,
            mtime_unix: 1.0,
            is_active: false,
            width_px: 100,
            height_px: 50,
            resolution_m: null,
          },
        ]),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(MapListPanel, { target, props: {} });
    cleanups.push(() => {
      unmount(component);
      target.remove();
    });
    const cell = await waitFor<HTMLTableCellElement>(
      () => target.querySelector<HTMLTableCellElement>('[data-testid="map-dims-studio_no_res"]'),
      'no-resolution dims cell',
    );
    expect(cell.textContent!.trim()).toBe('100×50 px');
  });

  it('renders em-dash when both dims are null', async () => {
    setHostname('127.0.0.1');
    setAdminSession();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            name: 'studio_corrupt_pgm',
            size_bytes: 0,
            mtime_unix: 1.0,
            is_active: false,
            width_px: null,
            height_px: null,
            resolution_m: null,
          },
        ]),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(MapListPanel, { target, props: {} });
    cleanups.push(() => {
      unmount(component);
      target.remove();
    });
    const cell = await waitFor<HTMLTableCellElement>(
      () => target.querySelector<HTMLTableCellElement>(
        '[data-testid="map-dims-studio_corrupt_pgm"]',
      ),
      'corrupt-pgm dims cell',
    );
    expect(cell.textContent!.trim()).toBe('—');
  });
});
