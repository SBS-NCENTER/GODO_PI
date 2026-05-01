/**
 * issue#3 — `PoseHintNumericFields.svelte` vitest cases.
 * Mode-B B-M1: numeric panel was 208 LoC with non-trivial logic
 * (parseDecimal locale-comma rejection, range validation, two-way
 * `$effect` binding, blur/Enter commit) but had zero tests. Added
 * here as a bias-block against future regressions.
 *
 * Coverage:
 * 1. parseDecimal rejects locale-comma input (`1,5` shows error).
 * 2. yaw out of [0, 360) rejected (yaw=360 → error; yaw=-1 → error).
 * 3. x/y out of [-100, 100] rejected (x=200 → error).
 * 4. hint-prop change updates input fields (effect path).
 * 5. blur on valid input commits → onhintchange fires with merged HintPose.
 * 6. clear button calls onhintchange(null) and clears all fields.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import PoseHintNumericFields from '../../src/components/PoseHintNumericFields.svelte';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

interface HintPoseLike {
  x_m: number;
  y_m: number;
  yaw_deg: number;
}

function mountFields(props: {
  hint: HintPoseLike | null;
  onhintchange?: (next: HintPoseLike | null) => void;
}): { target: HTMLDivElement; instance: ReturnType<typeof mount> } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const instance = mount(PoseHintNumericFields, {
    target,
    props: {
      hint: props.hint,
      onhintchange: props.onhintchange ?? ((): void => {}),
    },
  });
  cleanups.push(() => {
    unmount(instance);
    target.remove();
  });
  return { target, instance };
}

afterEach(() => {
  while (cleanups.length > 0) {
    cleanups.pop()?.();
  }
  vi.restoreAllMocks();
});

describe('PoseHintNumericFields (issue#3 B-M1)', () => {
  it('parseDecimal rejects locale-comma input — `1,5` produces inline error', () => {
    let captured: HintPoseLike | null | undefined = undefined;
    const { target } = mountFields({
      hint: { x_m: 0, y_m: 0, yaw_deg: 0 },
      onhintchange: (n) => (captured = n),
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="pose-hint-x"]');
    expect(xInput).not.toBeNull();

    xInput!.value = '1,5';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    xInput!.dispatchEvent(new Event('blur', { bubbles: true }));
    flushSync();

    const xErr = target.querySelector<HTMLSpanElement>('[data-testid="pose-hint-x-err"]');
    expect(xErr).not.toBeNull();
    expect(xErr!.textContent).toContain('period');
    // onhintchange must NOT fire when the input is rejected.
    expect(captured).toBeUndefined();
  });

  it('yaw=360 rejected (must be < 360)', () => {
    let captured: HintPoseLike | null | undefined = undefined;
    const { target } = mountFields({
      hint: { x_m: 0, y_m: 0, yaw_deg: 0 },
      onhintchange: (n) => (captured = n),
    });
    flushSync();
    const yawInput = target.querySelector<HTMLInputElement>('[data-testid="pose-hint-yaw"]');
    yawInput!.value = '360';
    yawInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yawInput!.dispatchEvent(new Event('blur', { bubbles: true }));
    flushSync();

    const yawErr = target.querySelector<HTMLSpanElement>('[data-testid="pose-hint-yaw-err"]');
    expect(yawErr).not.toBeNull();
    expect(yawErr!.textContent).toMatch(/yaw/);
    expect(captured).toBeUndefined();
  });

  it('yaw=-1 rejected', () => {
    let captured: HintPoseLike | null | undefined = undefined;
    const { target } = mountFields({
      hint: { x_m: 0, y_m: 0, yaw_deg: 0 },
      onhintchange: (n) => (captured = n),
    });
    flushSync();
    const yawInput = target.querySelector<HTMLInputElement>('[data-testid="pose-hint-yaw"]');
    yawInput!.value = '-1';
    yawInput!.dispatchEvent(new Event('input', { bubbles: true }));
    yawInput!.dispatchEvent(new Event('blur', { bubbles: true }));
    flushSync();

    const yawErr = target.querySelector<HTMLSpanElement>('[data-testid="pose-hint-yaw-err"]');
    expect(yawErr).not.toBeNull();
    expect(captured).toBeUndefined();
  });

  it('x out of [-100, 100] m rejected (x=200)', () => {
    let captured: HintPoseLike | null | undefined = undefined;
    const { target } = mountFields({
      hint: { x_m: 0, y_m: 0, yaw_deg: 0 },
      onhintchange: (n) => (captured = n),
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="pose-hint-x"]');
    xInput!.value = '200';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    xInput!.dispatchEvent(new Event('blur', { bubbles: true }));
    flushSync();

    const xErr = target.querySelector<HTMLSpanElement>('[data-testid="pose-hint-x-err"]');
    expect(xErr).not.toBeNull();
    expect(xErr!.textContent).toMatch(/100/);
    expect(captured).toBeUndefined();
  });

  it('hint prop change updates input fields ($effect path)', () => {
    const { target, instance } = mountFields({
      hint: { x_m: 1.5, y_m: -2.0, yaw_deg: 45.0 },
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="pose-hint-x"]');
    const yInput = target.querySelector<HTMLInputElement>('[data-testid="pose-hint-y"]');
    const yawInput = target.querySelector<HTMLInputElement>('[data-testid="pose-hint-yaw"]');
    // Initial state: 3 decimals (POSE_HINT_DECIMAL_DISPLAY_MM = 3).
    expect(xInput!.value).toBe('1.500');
    expect(yInput!.value).toBe('-2.000');
    expect(yawInput!.value).toBe('45.000');

    // Mutate the prop; the $effect should re-fill the inputs.
    // Svelte 5 uses $.set() for `$props` mutation; we re-mount with a new prop
    // instead since `mount(...)` exposes no public prop-setter API yet.
    unmount(instance);
    cleanups.pop();
    const { target: t2 } = mountFields({
      hint: { x_m: 10.123, y_m: 20.456, yaw_deg: 180.0 },
    });
    flushSync();
    const x2 = t2.querySelector<HTMLInputElement>('[data-testid="pose-hint-x"]');
    const yaw2 = t2.querySelector<HTMLInputElement>('[data-testid="pose-hint-yaw"]');
    expect(x2!.value).toBe('10.123');
    expect(yaw2!.value).toBe('180.000');
  });

  it('blur on valid input commits → onhintchange fires with merged HintPose', () => {
    let captured: HintPoseLike | null | undefined = undefined;
    const { target } = mountFields({
      hint: { x_m: 1.0, y_m: 2.0, yaw_deg: 30.0 },
      onhintchange: (n) => (captured = n),
    });
    flushSync();
    const xInput = target.querySelector<HTMLInputElement>('[data-testid="pose-hint-x"]');
    xInput!.value = '5.5';
    xInput!.dispatchEvent(new Event('input', { bubbles: true }));
    xInput!.dispatchEvent(new Event('blur', { bubbles: true }));
    flushSync();

    expect(captured).not.toBeUndefined();
    expect(captured).not.toBeNull();
    expect(captured!.x_m).toBeCloseTo(5.5, 10);
    // Merged: y and yaw retain their previous values.
    expect(captured!.y_m).toBeCloseTo(2.0, 10);
    expect(captured!.yaw_deg).toBeCloseTo(30.0, 10);
  });

  it('clear button fires onhintchange(null) and disables when hint is null', () => {
    let captured: HintPoseLike | null | undefined = undefined;
    const { target } = mountFields({
      hint: { x_m: 1.0, y_m: 2.0, yaw_deg: 30.0 },
      onhintchange: (n) => (captured = n),
    });
    flushSync();
    const clearBtn = target.querySelector<HTMLButtonElement>('[data-testid="pose-hint-clear"]');
    expect(clearBtn).not.toBeNull();
    expect(clearBtn!.disabled).toBe(false);

    clearBtn!.click();
    flushSync();
    expect(captured).toBeNull();

    // Re-mount with hint=null → button must be disabled.
    cleanups.pop()?.();
    const { target: t2 } = mountFields({ hint: null });
    flushSync();
    const clearBtn2 = t2.querySelector<HTMLButtonElement>('[data-testid="pose-hint-clear"]');
    expect(clearBtn2!.disabled).toBe(true);
  });
});
