/**
 * issue#28 — `<ApplyMemoModal>` validation pin.
 *
 * Pins:
 * - Invalid memo blocks the Apply button.
 * - Valid memo enables Apply; clicking it invokes `onApply` with the
 *   memo string.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ApplyMemoModal from '../../src/components/ApplyMemoModal.svelte';

let target: HTMLElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  target.remove();
});

describe('ApplyMemoModal', () => {
  it('invalid memo blocks Apply button', () => {
    const onApply = vi.fn();
    const onCancel = vi.fn();
    const inst = mount(ApplyMemoModal, {
      target,
      props: { open: true, onApply, onCancel },
    });
    flushSync();
    const input = target.querySelector('input[type="text"]') as HTMLInputElement;
    const buttons = Array.from(target.querySelectorAll('.actions button')) as HTMLButtonElement[];
    const applyBtn = buttons[1];
    // Empty memo → button disabled.
    expect(applyBtn.disabled).toBe(true);

    input.value = 'bad memo';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(applyBtn.disabled).toBe(true);
    unmount(inst);
  });

  it('valid memo enables Apply and clicking invokes onApply with the memo', () => {
    const onApply = vi.fn();
    const onCancel = vi.fn();
    const inst = mount(ApplyMemoModal, {
      target,
      props: { open: true, onApply, onCancel },
    });
    flushSync();
    const input = target.querySelector('input[type="text"]') as HTMLInputElement;
    input.value = 'wallcal01';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    const buttons = Array.from(target.querySelectorAll('.actions button')) as HTMLButtonElement[];
    const applyBtn = buttons[1];
    expect(applyBtn.disabled).toBe(false);
    applyBtn.click();
    flushSync();
    expect(onApply).toHaveBeenCalledWith('wallcal01');
    unmount(inst);
  });
});
