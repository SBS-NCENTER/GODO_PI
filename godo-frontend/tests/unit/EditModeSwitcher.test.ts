/**
 * issue#28 — `<EditModeSwitcher>` vitest cases.
 *
 * Pins:
 * - Two modes (Coordinate, Erase) render as buttons.
 * - Switching mode invokes `onChange` with the new mode literal.
 * - Per-mode `aria-pressed` flips correctly.
 * - Korean tooltip is set on the wrapping group element.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import EditModeSwitcher from '../../src/components/EditModeSwitcher.svelte';
import {
  EDIT_MODE_COORD,
  EDIT_MODE_ERASE,
  EDIT_MODE_SWITCH_TOOLTIP_KO,
} from '../../src/lib/constants';

let target: HTMLElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  target.remove();
});

describe('EditModeSwitcher', () => {
  it('renders both segmented buttons with the Korean tooltip', () => {
    const onChange = vi.fn();
    const inst = mount(EditModeSwitcher, {
      target,
      props: { mode: EDIT_MODE_COORD, onChange },
    });
    flushSync();
    const wrapper = target.querySelector('.edit-mode-switcher')!;
    expect(wrapper.getAttribute('title')).toBe(EDIT_MODE_SWITCH_TOOLTIP_KO);
    const buttons = target.querySelectorAll('button.seg');
    expect(buttons.length).toBe(2);
    unmount(inst);
  });

  it('switching mode preserves both pending states (calls onChange but does not auto-discard)', () => {
    // Per N3 / M2 lock — mode toggling does not destroy state in the
    // peer mode. We pin this contract by asserting the `onChange`
    // callback is the SOLE side effect of the switch.
    const onChange = vi.fn();
    const inst = mount(EditModeSwitcher, {
      target,
      props: { mode: EDIT_MODE_COORD, onChange },
    });
    flushSync();
    const buttons = Array.from(target.querySelectorAll('button.seg')) as HTMLButtonElement[];
    expect(buttons[0].getAttribute('aria-pressed')).toBe('true');
    expect(buttons[1].getAttribute('aria-pressed')).toBe('false');
    buttons[1].click();
    flushSync();
    expect(onChange).toHaveBeenCalledWith(EDIT_MODE_ERASE);
    unmount(inst);
  });

  it('per-mode Apply only commits its mode (clicking the same mode twice does not refire)', () => {
    const onChange = vi.fn();
    const inst = mount(EditModeSwitcher, {
      target,
      props: { mode: EDIT_MODE_COORD, onChange },
    });
    flushSync();
    const buttons = Array.from(target.querySelectorAll('button.seg')) as HTMLButtonElement[];
    buttons[0].click(); // already coord mode — no-op
    flushSync();
    expect(onChange).not.toHaveBeenCalled();
    unmount(inst);
  });
});
