/**
 * Component-level test: `<LastPoseCard/>` (issue#2.1 — PR β.5 Map Edit
 * controls parity).
 *
 * Pins the rendered shape so a future drift in the pose-readout layout
 * (e.g. dropping `σ_xy` or `converged` chip) is caught by CI. The
 * component subscribes to the `lastPose` store; we drive the store
 * directly and assert the DOM reflects each branch:
 *   - valid + converged pose → x / y / yaw / σ_xy + converged chip.
 *   - valid + not-converged → same readout, no chip.
 *   - invalid / null         → "no valid pose yet" hint.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import LastPoseCard from '../../src/components/LastPoseCard.svelte';
import { lastPose } from '../../src/stores/lastPose';
import type { LastPose } from '../../src/lib/protocol';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

function makePose(overrides: Partial<LastPose> = {}): LastPose {
  return {
    valid: 1,
    converged: 1,
    forced: 0,
    x_m: 1.234,
    y_m: -2.345,
    yaw_deg: 45.6,
    xy_std_m: 0.012,
    yaw_std_deg: 0.5,
    iterations: 10,
    published_mono_ns: '0',
    ...overrides,
  } as LastPose;
}

beforeEach(() => {
  lastPose.set(null);
});

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
});

describe('<LastPoseCard/>', () => {
  it('renders x / y / yaw / σ_xy + converged chip when pose is valid + converged', () => {
    lastPose.set(makePose());
    const target = document.createElement('div');
    document.body.appendChild(target);
    const inst = mount(LastPoseCard, { target });
    cleanups.push(() => {
      unmount(inst);
      target.remove();
    });
    flushSync();

    const readout = target.querySelector('[data-testid="last-pose-readout"]');
    expect(readout).not.toBeNull();
    const text = readout?.textContent ?? '';
    expect(text).toContain('x:');
    expect(text).toContain('y:');
    expect(text).toContain('yaw:');
    expect(text).toContain('σ_xy:');
    expect(target.querySelector('[data-testid="last-pose-converged"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="last-pose-empty"]')).toBeNull();
  });

  it('omits the converged chip when pose is valid but not converged', () => {
    lastPose.set(makePose({ converged: 0 }));
    const target = document.createElement('div');
    document.body.appendChild(target);
    const inst = mount(LastPoseCard, { target });
    cleanups.push(() => {
      unmount(inst);
      target.remove();
    });
    flushSync();

    expect(target.querySelector('[data-testid="last-pose-readout"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="last-pose-converged"]')).toBeNull();
  });

  it('renders the "no valid pose yet" hint when the store is null', () => {
    lastPose.set(null);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const inst = mount(LastPoseCard, { target });
    cleanups.push(() => {
      unmount(inst);
      target.remove();
    });
    flushSync();

    expect(target.querySelector('[data-testid="last-pose-empty"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="last-pose-readout"]')).toBeNull();
  });

  it('renders the "no valid pose yet" hint when pose is invalid', () => {
    lastPose.set(makePose({ valid: 0 }));
    const target = document.createElement('div');
    document.body.appendChild(target);
    const inst = mount(LastPoseCard, { target });
    cleanups.push(() => {
      unmount(inst);
      target.remove();
    });
    flushSync();

    expect(target.querySelector('[data-testid="last-pose-empty"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="last-pose-readout"]')).toBeNull();
  });
});
