/**
 * issue#28 — `<MapList>` grouped tree pin.
 *
 * Pins:
 * - Pristine parent + variant children render in indented tree.
 * - Active map gets the badge.
 * - Click on a row invokes `onActivate` with the row's name.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import MapList from '../../src/components/MapList.svelte';

let target: HTMLElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  target.remove();
});

const sampleGroups = [
  {
    base: 'chroma',
    pristine: {
      name: 'chroma',
      is_active: false,
      width_px: 200,
      height_px: 100,
      resolution_m: 0.05,
    },
    variants: [
      {
        name: 'chroma.20260504-143000-wallcal01',
        is_active: true,
        width_px: 200,
        height_px: 100,
        resolution_m: 0.05,
      },
    ],
  },
];

describe('MapList', () => {
  it('derived variants render indented under pristine parent', () => {
    const onActivate = vi.fn();
    const inst = mount(MapList, {
      target,
      props: { groups: sampleGroups, onActivate },
    });
    flushSync();
    expect(target.querySelectorAll('li.group').length).toBe(1);
    expect(target.querySelector('.pristine-row')!.textContent).toContain('chroma');
    expect(target.querySelectorAll('ul.variants li').length).toBe(1);
    expect(target.querySelector('.variant-row')!.textContent).toContain('20260504-143000-wallcal01');
    unmount(inst);
  });

  it('active variant carries the badge', () => {
    const onActivate = vi.fn();
    const inst = mount(MapList, {
      target,
      props: { groups: sampleGroups, onActivate },
    });
    flushSync();
    const variantRow = target.querySelector('.variant-row')!;
    expect(variantRow.querySelector('.badge')).not.toBeNull();
    expect(variantRow.classList.contains('active')).toBe(true);
    unmount(inst);
  });

  it('row click invokes onActivate with the row name', () => {
    const onActivate = vi.fn();
    const inst = mount(MapList, {
      target,
      props: { groups: sampleGroups, onActivate },
    });
    flushSync();
    const pristineBtn = target.querySelector('.pristine-row') as HTMLButtonElement;
    pristineBtn.click();
    flushSync();
    expect(onActivate).toHaveBeenCalledWith('chroma');
    unmount(inst);
  });
});
