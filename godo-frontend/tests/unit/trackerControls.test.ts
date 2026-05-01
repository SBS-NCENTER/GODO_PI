/**
 * issue#3 — `<TrackerControls/>` "Calibrate from hint" button vitest cases.
 * Mode-B B-M2: button gating + emit semantics had no tests despite the
 * 5-line `doCalibrateFromHint` handler having a real
 * `if (!isAdmin || busy || hint === null) return;` early-out. A future
 * regression that flipped one condition would silently break gating.
 *
 * Coverage:
 * 1. hint=null → calibrate-from-hint button is disabled.
 * 2. hint set + admin → button enabled.
 * 3. click button → apiPostCalibrate called with body matching the hint.
 * 4. successful calibrate → onClearHint callback fires.
 * 5. non-admin (viewer) → button disabled even with hint set.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

// Mode store is module-level subscribed inside TrackerControls.onMount;
// stub it so the test doesn't need a live SSE subscription.
vi.mock('$stores/mode', () => ({
  subscribeMode: (_cb: (m: unknown) => void) => () => {},
  setModeOptimistic: () => {},
}));

// Avoid timer-driven health refresh during tests: stub apiGet to a
// resolved no-op so the onMount path doesn't throw.
vi.mock('$lib/api', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    apiGet: vi.fn().mockResolvedValue({ tracker: 'up' }),
  };
});

import TrackerControls from '../../src/components/TrackerControls.svelte';
import * as api from '../../src/lib/api';
import { auth } from '../../src/stores/auth';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

interface HintPoseLike {
  x_m: number;
  y_m: number;
  yaw_deg: number;
}

function mountTracker(props: {
  hint?: HintPoseLike | null;
  onClearHint?: () => void;
  role?: 'admin' | 'viewer';
}): { target: HTMLDivElement; instance: ReturnType<typeof mount> } {
  // Auth store is writable + persists to localStorage; reset between tests.
  if (props.role !== undefined) {
    auth.set({
      token: 'tok-test',
      username: 'tester',
      role: props.role,
      exp: Date.now() / 1000 + 3600,
    });
  } else {
    auth.set(null);
  }

  const target = document.createElement('div');
  document.body.appendChild(target);
  const instance = mount(TrackerControls, {
    target,
    props: {
      hint: props.hint ?? null,
      onClearHint: props.onClearHint,
    },
  });
  cleanups.push(() => {
    unmount(instance);
    target.remove();
    auth.set(null);
  });
  return { target, instance };
}

beforeEach(() => {
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

afterEach(() => {
  while (cleanups.length > 0) {
    cleanups.pop()?.();
  }
  vi.restoreAllMocks();
});

describe('TrackerControls "Calibrate from hint" (issue#3 B-M2)', () => {
  it('hint=null → calibrate-from-hint button is disabled', () => {
    const { target } = mountTracker({ hint: null, role: 'admin' });
    flushSync();
    const btn = target.querySelector<HTMLButtonElement>(
      '[data-testid="calibrate-from-hint-btn"]',
    );
    expect(btn).not.toBeNull();
    expect(btn!.disabled).toBe(true);
  });

  it('hint set + admin → button enabled', () => {
    const { target } = mountTracker({
      hint: { x_m: 1.0, y_m: 2.0, yaw_deg: 45.0 },
      role: 'admin',
    });
    flushSync();
    const btn = target.querySelector<HTMLButtonElement>(
      '[data-testid="calibrate-from-hint-btn"]',
    );
    expect(btn!.disabled).toBe(false);
  });

  it('viewer role → button disabled even with hint set', () => {
    const { target } = mountTracker({
      hint: { x_m: 1.0, y_m: 2.0, yaw_deg: 45.0 },
      role: 'viewer',
    });
    flushSync();
    const btn = target.querySelector<HTMLButtonElement>(
      '[data-testid="calibrate-from-hint-btn"]',
    );
    expect(btn!.disabled).toBe(true);
  });

  it('click button → apiPostCalibrate called with body, onClearHint fires', async () => {
    const calibSpy = vi
      .spyOn(api, 'apiPostCalibrate')
      .mockResolvedValue(null as unknown as never);
    const onClearHint = vi.fn();
    const { target } = mountTracker({
      hint: { x_m: 1.5, y_m: -2.25, yaw_deg: 90.0 },
      role: 'admin',
      onClearHint,
    });
    flushSync();
    const btn = target.querySelector<HTMLButtonElement>(
      '[data-testid="calibrate-from-hint-btn"]',
    );
    btn!.click();
    // The handler is async — flush microtasks so the catch/finally settles.
    await Promise.resolve();
    await Promise.resolve();
    flushSync();

    expect(calibSpy).toHaveBeenCalledTimes(1);
    const body = calibSpy.mock.calls[0]![0];
    expect(body).toEqual({
      seed_x_m: 1.5,
      seed_y_m: -2.25,
      seed_yaw_deg: 90.0,
    });
    expect(onClearHint).toHaveBeenCalledTimes(1);
  });

  it('apiPostCalibrate failure → onClearHint NOT called, error rendered', async () => {
    vi.spyOn(api, 'apiPostCalibrate').mockRejectedValue(
      new api.ApiError(500, { err: 'boom' }, 'boom'),
    );
    const onClearHint = vi.fn();
    const { target } = mountTracker({
      hint: { x_m: 1.0, y_m: 2.0, yaw_deg: 45.0 },
      role: 'admin',
      onClearHint,
    });
    flushSync();
    const btn = target.querySelector<HTMLButtonElement>(
      '[data-testid="calibrate-from-hint-btn"]',
    );
    btn!.click();
    await Promise.resolve();
    await Promise.resolve();
    flushSync();

    expect(onClearHint).toHaveBeenCalledTimes(0);
    const err = target.querySelector<HTMLDivElement>('[data-testid="action-error"]');
    expect(err).not.toBeNull();
    expect(err!.textContent).toMatch(/boom/);
  });
});
