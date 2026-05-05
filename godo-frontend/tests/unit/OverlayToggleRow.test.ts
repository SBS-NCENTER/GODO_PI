/**
 * issue#28.1 B5 — `<OverlayToggleRow>` component-mount pins.
 *
 * Sole owner of the per-overlay-surface toggle UI (mounted on
 * `/map` and `/map-edit`). Pins:
 *   1. Default mount has all three toggles unchecked.
 *   2. Clicking each input flips the corresponding store flag.
 *   3. Store changes flow back into the rendered checkboxes.
 *   4. The three toggles are independent — flipping one does not
 *      affect the other two.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { get } from 'svelte/store';

import OverlayToggleRow from '../../src/components/OverlayToggleRow.svelte';
import {
  _resetOverlayTogglesForTests,
  overlayToggles,
} from '../../src/stores/overlayToggles';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

beforeEach(() => {
  _resetOverlayTogglesForTests();
});

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
});

function mountRow(): { target: HTMLElement } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(OverlayToggleRow, { target });
  cleanups.push(() => {
    unmount(component);
    target.remove();
  });
  flushSync();
  return { target };
}

function inputs(target: HTMLElement): HTMLInputElement[] {
  return Array.from(target.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
}

describe('OverlayToggleRow', () => {
  it('mounts with all three toggles unchecked by default', () => {
    const { target } = mountRow();
    const boxes = inputs(target);
    expect(boxes).toHaveLength(3);
    for (const box of boxes) {
      expect(box.checked).toBe(false);
    }
    // Store mirror.
    expect(get(overlayToggles)).toEqual({
      originAxisOn: false,
      lidarOn: false,
      gridOn: false,
    });
  });

  it('clicking each toggle flips the corresponding store flag', () => {
    const { target } = mountRow();
    const [originBox, lidarBox, gridBox] = inputs(target);

    originBox!.click();
    flushSync();
    expect(get(overlayToggles).originAxisOn).toBe(true);
    expect(get(overlayToggles).lidarOn).toBe(false);
    expect(get(overlayToggles).gridOn).toBe(false);

    lidarBox!.click();
    flushSync();
    expect(get(overlayToggles).lidarOn).toBe(true);

    gridBox!.click();
    flushSync();
    expect(get(overlayToggles).gridOn).toBe(true);
  });

  it('store updates flow back into the checkbox `checked` props', () => {
    const { target } = mountRow();
    overlayToggles.set({ originAxisOn: true, lidarOn: false, gridOn: true });
    flushSync();
    const [originBox, lidarBox, gridBox] = inputs(target);
    expect(originBox!.checked).toBe(true);
    expect(lidarBox!.checked).toBe(false);
    expect(gridBox!.checked).toBe(true);
  });

  it('three toggles are independent — flipping one preserves the other two', () => {
    const { target } = mountRow();
    // Pre-set: lidar+grid ON, origin OFF.
    overlayToggles.set({ originAxisOn: false, lidarOn: true, gridOn: true });
    flushSync();
    const [originBox] = inputs(target);
    originBox!.click();
    flushSync();
    expect(get(overlayToggles)).toEqual({
      originAxisOn: true,
      lidarOn: true,
      gridOn: true,
    });
  });
});
