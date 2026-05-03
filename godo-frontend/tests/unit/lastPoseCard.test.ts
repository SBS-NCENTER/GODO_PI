/**
 * Component-level test: `<LastPoseCard/>` (issue#27 — 2-section card).
 *
 * Pins the rendered shape so a future drift in the pose-readout layout
 * (e.g. dropping `σ_xy` or `converged` chip, or removing the Final
 * output (UDP) section) is caught by CI. The component subscribes to
 * BOTH the `lastPose` store AND the new `lastOutput` store; we drive
 * both directly and assert the DOM reflects each branch:
 *   - both valid    → raw line + 8-channel output grid both render.
 *   - raw only      → raw line renders, output section shows "unavailable".
 *   - output only   → output grid renders, raw section shows "no pose".
 *   - both null     → both sections show their empty placeholders.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import LastPoseCard from '../../src/components/LastPoseCard.svelte';
import { lastPose } from '../../src/stores/lastPose';
import { lastOutput } from '../../src/stores/lastOutput';
import type { LastOutputFrame, LastPose } from '../../src/lib/protocol';

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

function makeOutput(overrides: Partial<LastOutputFrame> = {}): LastOutputFrame {
  return {
    valid: 1,
    x_m: 1.5,
    y_m: -2.0,
    z_m: 0.5,
    pan_deg: 42.0,
    tilt_deg: -1.0,
    roll_deg: 0.017,
    zoom: 524288.0,
    focus: 502733.0,
    published_mono_ns: 0,
    ...overrides,
  } as LastOutputFrame;
}

function mountTarget(): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const inst = mount(LastPoseCard, { target });
  cleanups.push(() => {
    unmount(inst);
    target.remove();
  });
  flushSync();
  return target;
}

beforeEach(() => {
  lastPose.set(null);
  lastOutput.set(null);
});

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
});

describe('<LastPoseCard/>', () => {
  it('renders both sections when raw pose AND output frame are valid', () => {
    lastPose.set(makePose());
    lastOutput.set(makeOutput());
    const target = mountTarget();

    const raw = target.querySelector('[data-testid="last-pose-raw"]');
    expect(raw).not.toBeNull();
    const rawText = raw?.textContent ?? '';
    expect(rawText).toContain('x:');
    expect(rawText).toContain('y:');
    expect(rawText).toContain('yaw:');
    expect(rawText).toContain('σ_xy:');
    expect(target.querySelector('[data-testid="last-pose-converged"]')).not.toBeNull();

    const output = target.querySelector('[data-testid="last-output-final"]');
    expect(output).not.toBeNull();
    const outText = output?.textContent ?? '';
    // 8 channels of the final output grid.
    expect(outText).toContain('x:');
    expect(outText).toContain('y:');
    expect(outText).toContain('z:');
    expect(outText).toContain('pan:');
    expect(outText).toContain('tilt:');
    expect(outText).toContain('roll:');
    expect(outText).toContain('zoom:');
    expect(outText).toContain('focus:');
    // Empty placeholder absent when output is valid.
    expect(target.querySelector('[data-testid="last-output-empty"]')).toBeNull();
  });

  it('omits the converged chip when raw pose is valid but not converged', () => {
    lastPose.set(makePose({ converged: 0 }));
    lastOutput.set(makeOutput());
    const target = mountTarget();
    expect(target.querySelector('[data-testid="last-pose-converged"]')).toBeNull();
  });

  it('renders raw "no valid pose yet" placeholder when only output is live', () => {
    lastPose.set(null);
    lastOutput.set(makeOutput());
    const target = mountTarget();
    expect(target.querySelector('[data-testid="last-pose-empty"]')).not.toBeNull();
    // Output section still renders.
    const output = target.querySelector('[data-testid="last-output-final"]');
    expect(output).not.toBeNull();
    expect(target.querySelector('[data-testid="last-output-empty"]')).toBeNull();
  });

  it('renders output "unavailable" placeholder when only raw is live', () => {
    lastPose.set(makePose());
    lastOutput.set(null);
    const target = mountTarget();
    expect(target.querySelector('[data-testid="last-output-empty"]')).not.toBeNull();
    // Raw section still renders.
    const raw = target.querySelector('[data-testid="last-pose-raw"]');
    expect(raw).not.toBeNull();
    expect(raw?.textContent ?? '').toContain('x:');
  });

  it('renders both empty placeholders when neither store is valid', () => {
    lastPose.set(null);
    lastOutput.set(null);
    const target = mountTarget();
    expect(target.querySelector('[data-testid="last-pose-empty"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="last-output-empty"]')).not.toBeNull();
  });

  it('renders raw "no valid pose" when pose.valid is 0 (defensive)', () => {
    lastPose.set(makePose({ valid: 0 }));
    lastOutput.set(null);
    const target = mountTarget();
    expect(target.querySelector('[data-testid="last-pose-empty"]')).not.toBeNull();
  });

  it('renders output "unavailable" when output.valid is 0 (sentinel from SSE)', () => {
    lastPose.set(makePose());
    lastOutput.set(makeOutput({ valid: 0 }));
    const target = mountTarget();
    expect(target.querySelector('[data-testid="last-output-empty"]')).not.toBeNull();
  });
});
