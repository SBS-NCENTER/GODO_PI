/**
 * Track B-MAPEDIT-2 — `lib/originMath.ts` vitest cases.
 *
 * Issue#27 SUBTRACT semantic (supersedes 2026-04-30 ADD lock).
 * `resolveDeltaFromPose` resolves operator delta → absolute world coord
 * frontend-side (the backend then SUBTRACTs to update YAML).
 */

import { describe, expect, it } from 'vitest';

import {
  pixelToWorld,
  resolveAbsolute,
  resolveDeltaFromPose,
  yawFromDrag,
} from '../../src/lib/originMath';

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

describe('originMath.resolveDeltaFromPose (issue#27 SUBTRACT — frontend resolution)', () => {
  it('resolveDeltaFromPose adds delta to current pose to get absolute world coord', () => {
    // SPA path: typed (dx, dy) is an offset vector from the current
    // LiDAR-frame pose to the point that should become the new (0, 0).
    // Frontend resolves to the absolute world coord BEFORE sending to
    // the backend; backend then SUBTRACTs to update YAML origin.
    const out = resolveDeltaFromPose({ x_m: 12.87, y_m: 15.49 }, 0.32, -0.18);
    expect(out.x_m).toBeCloseTo(12.87 + 0.32, 10);
    expect(out.y_m).toBeCloseTo(15.49 + (-0.18), 10);
  });

  it('zero delta returns the current pose unchanged', () => {
    const out = resolveDeltaFromPose({ x_m: 1.0, y_m: 2.0 }, 0, 0);
    expect(out).toEqual({ x_m: 1.0, y_m: 2.0 });
  });

  it('resolveAbsolute is identity-shaped (passthrough)', () => {
    const out = resolveAbsolute(0.32, -0.18);
    expect(out).toEqual({ x_m: 0.32, y_m: -0.18 });
  });
});

describe('originMath SUBTRACT semantic (issue#27, operator HIL pins)', () => {
  // PICK#2 + PICK#3 historical data points (operator HIL 2026-05-03 KST).
  // The pins here mirror the Python regression tests in
  // godo-webctl/tests/test_map_origin.py:
  //   test_apply_origin_edit_absolute_subtracts_pose_pick_{2,3}
  //
  // SPA path: operator types absolute (the world coord of the point
  // that should become the new (0, 0)). Backend computes new YAML
  // origin = old YAML origin - typed.
  it('PICK#2 — typed=(7.86, 18.34) on old_pose=(12.87, 15.49) → expected new_pose ≈ (5.01, -2.85)', () => {
    const oldPose = { x_m: 12.87, y_m: 15.49 };
    const typed = { x_m: 7.86, y_m: 18.34 };
    const newPose = { x_m: oldPose.x_m - typed.x_m, y_m: oldPose.y_m - typed.y_m };
    expect(newPose.x_m).toBeCloseTo(5.01, 2);
    expect(newPose.y_m).toBeCloseTo(-2.85, 2);
  });

  it('PICK#3 — typed=(10.32, 28.86) on old_pose=(18.72, 25.27) → expected new_pose ≈ (8.40, -3.59)', () => {
    const oldPose = { x_m: 18.72, y_m: 25.27 };
    const typed = { x_m: 10.32, y_m: 28.86 };
    const newPose = { x_m: oldPose.x_m - typed.x_m, y_m: oldPose.y_m - typed.y_m };
    expect(newPose.x_m).toBeCloseTo(8.40, 2);
    expect(newPose.y_m).toBeCloseTo(-3.59, 2);
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
