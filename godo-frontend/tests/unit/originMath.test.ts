/**
 * Track B-MAPEDIT-2 — `lib/originMath.ts` vitest cases.
 *
 * 6 cases per planner §5.3 + Mode-A M4 fold (Y-flip uses `height - 1 - py`,
 * NOT `height - py`). Sign convention is ADD (operator-locked 2026-04-30 KST).
 */

import { describe, expect, it } from 'vitest';

import { pixelToWorld, resolveAbsolute, resolveDelta, yawFromDrag } from '../../src/lib/originMath';

describe('originMath.pixelToWorld (M4 fold — Y-flip uses height-1-py)', () => {
  it('center pixel of a 200x100 map at resolution 0.05 returns world (0, 0)', () => {
    // dims = 200x100, resolution = 0.05, origin = [-5, -2.5, 0]
    // For world (0, 0): img_col = (0 - (-5)) / 0.05 = 100
    //                   img_row = (height - 1) - (0 - (-2.5)) / 0.05 = 99 - 50 = 49
    // So clicking at (100, 49) returns world (0, 0).
    const out = pixelToWorld(100, 49, { width: 200, height: 100 }, 0.05, [-5, -2.5, 0]);
    expect(out.world_x).toBeCloseTo(0, 10);
    expect(out.world_y).toBeCloseTo(0, 10);
  });

  it('top-left pixel (0, 0) returns (origin[0], origin[1] + (height-1)*resolution)', () => {
    // PGM origin is top-left; world Y increases upward; so the TOP edge of
    // the image is at world_y = origin[1] + (height - 1) * resolution.
    const out = pixelToWorld(0, 0, { width: 200, height: 100 }, 0.05, [-5, -2.5, 0]);
    expect(out.world_x).toBeCloseTo(-5, 10);
    expect(out.world_y).toBeCloseTo(-2.5 + 99 * 0.05, 10);
  });

  it('bottom-left pixel (0, height-1) returns exactly (origin[0], origin[1])', () => {
    // Bottom row (py = height - 1) lands at the world origin Y per ROS
    // map_server convention. M4 fold drift catch: a writer who drops the
    // `-1` would land at `origin[1] + resolution` (wrong by one cell).
    const out = pixelToWorld(0, 99, { width: 200, height: 100 }, 0.05, [-5, -2.5, 0]);
    expect(out.world_x).toBeCloseTo(-5, 10);
    expect(out.world_y).toBeCloseTo(-2.5, 10);
  });

  it('handles negative origin values', () => {
    const out = pixelToWorld(40, 50, { width: 100, height: 100 }, 0.1, [-2, -3, 0]);
    expect(out.world_x).toBeCloseTo(-2 + 40 * 0.1, 10);
    expect(out.world_y).toBeCloseTo(-3 + (100 - 1 - 50) * 0.1, 10);
  });
});

describe('originMath.resolveDelta (ADD sign convention pin)', () => {
  it('resolveDelta adds — operator-locked ADD: new_origin = current + (dx, dy)', () => {
    // Drift catch: if a future writer flips to SUBTRACT, this fails. The
    // wrong direction would silently shift the origin by 2× the typed
    // offset (Mode-A M2 caught this against the spec memory's literal
    // "subtract" wording vs. the example "ADD" semantics).
    const out = resolveDelta([1.0, 2.0, 0], 0.32, -0.18);
    expect(out.x_m).toBeCloseTo(1.32, 10);
    expect(out.y_m).toBeCloseTo(1.82, 10);
  });

  it('resolveAbsolute is identity-shaped (passthrough)', () => {
    const out = resolveAbsolute(0.32, -0.18);
    expect(out).toEqual({ x_m: 0.32, y_m: -0.18 });
  });
});

describe('originMath.yawFromDrag (issue#3 — CCW REP-103 [0, 360))', () => {
  // World-frame deltas — caller has already passed clicks through
  // viewport.canvasToWorld (which applies the ROS Y-flip). So +X is
  // east, +Y is north, atan2 gives standard CCW math angle.
  it('east  → 0°', () => {
    expect(yawFromDrag(0, 0, 1, 0)).toBeCloseTo(0, 6);
  });
  it('north → 90°', () => {
    expect(yawFromDrag(0, 0, 0, 1)).toBeCloseTo(90, 6);
  });
  it('west  → 180°', () => {
    expect(yawFromDrag(0, 0, -1, 0)).toBeCloseTo(180, 6);
  });
  it('south → 270° (atan2(-1, 0) = -90° → wraps to 270°)', () => {
    expect(yawFromDrag(0, 0, 0, -1)).toBeCloseTo(270, 6);
  });
  it('NE diagonal → 45°', () => {
    expect(yawFromDrag(0, 0, 1, 1)).toBeCloseTo(45, 6);
  });
  it('NW diagonal → 135°', () => {
    expect(yawFromDrag(0, 0, -1, 1)).toBeCloseTo(135, 6);
  });
  it('SW diagonal → 225° (atan2(-1, -1) = -135° → wraps)', () => {
    expect(yawFromDrag(0, 0, -1, -1)).toBeCloseTo(225, 6);
  });
  it('SE diagonal → 315° (atan2(-1, 1) = -45° → wraps)', () => {
    expect(yawFromDrag(0, 0, 1, -1)).toBeCloseTo(315, 6);
  });
  it('zero-length drag returns null', () => {
    expect(yawFromDrag(0, 0, 0, 0)).toBeNull();
    expect(yawFromDrag(1, 1, 1, 1)).toBeNull();
  });
  it('translation invariance — drag from (5,5) east is still 0°', () => {
    expect(yawFromDrag(5, 5, 6, 5)).toBeCloseTo(0, 6);
  });
});
