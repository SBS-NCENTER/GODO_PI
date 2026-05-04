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


describe('originMath.wrapYawDeg (issue#28 — (-180, 180] half-open)', () => {
  it('passes values already in range', async () => {
    const { wrapYawDeg } = await import('../../src/lib/originMath');
    expect(wrapYawDeg(0)).toBe(0);
    expect(wrapYawDeg(45)).toBe(45);
    expect(wrapYawDeg(180)).toBe(180);
    expect(wrapYawDeg(-90)).toBe(-90);
  });
  it('wraps overflow to (-180, 180]', async () => {
    const { wrapYawDeg } = await import('../../src/lib/originMath');
    expect(wrapYawDeg(190)).toBe(-170);
    expect(wrapYawDeg(360)).toBe(0);
  });
  it('reflects -180 to +180 (half-open at lower bound)', async () => {
    const { wrapYawDeg } = await import('../../src/lib/originMath');
    expect(wrapYawDeg(-180)).toBe(180);
    expect(wrapYawDeg(-185)).toBe(175);
  });
});

describe('originMath.resolveYawDeltaFromPose (issue#28 ROTATE pins)', () => {
  it('ROTATE#1 typed=10° on origin=5° → new=-5°', async () => {
    const { resolveYawDeltaFromPose } = await import('../../src/lib/originMath');
    expect(resolveYawDeltaFromPose(5, 10)).toBeCloseTo(-5, 6);
  });
  it('ROTATE#2 typed=20° on origin=-5° → new=-25° (no 2x drift)', async () => {
    const { resolveYawDeltaFromPose } = await import('../../src/lib/originMath');
    expect(resolveYawDeltaFromPose(-5, 20)).toBeCloseTo(-25, 6);
  });
});

describe('originMath.twoClickToYawDeg (issue#28 — 2-click yaw pick)', () => {
  it('twoClickToYawDeg simple cardinal east → 0°', async () => {
    const { twoClickToYawDeg } = await import('../../src/lib/originMath');
    expect(twoClickToYawDeg(0, 0, 10, 0, 8, 0.05)).toBeCloseTo(0, 6);
  });
  it('twoClickToYawDeg simple cardinal north → 90°', async () => {
    const { twoClickToYawDeg } = await import('../../src/lib/originMath');
    expect(twoClickToYawDeg(0, 0, 0, 10, 8, 0.05)).toBeCloseTo(90, 6);
  });
  it('twoClickToYawDeg ignores length (scaling P1→P2 by 10× yields same yaw)', async () => {
    const { twoClickToYawDeg } = await import('../../src/lib/originMath');
    const a = twoClickToYawDeg(0, 0, 1, 1, 8, 0.05);
    const b = twoClickToYawDeg(0, 0, 10, 10, 8, 0.05);
    expect(a).toBeCloseTo(b ?? -1, 6);
  });
  it('twoClickToYawDeg returns null when clicks are coincident (jitter guard)', async () => {
    const { twoClickToYawDeg } = await import('../../src/lib/originMath');
    expect(twoClickToYawDeg(0, 0, 0, 0, 8, 0.05)).toBeNull();
  });
  it('twoClickToYawDeg returns null when clicks are within min pixel distance', async () => {
    const { twoClickToYawDeg } = await import('../../src/lib/originMath');
    // 0.1 m at 0.05 m/px = 2 px (below the 8 px threshold).
    expect(twoClickToYawDeg(0, 0, 0.1, 0, 8, 0.05)).toBeNull();
  });
});

// --- issue#30 — pristineWorldToPixel + composeCumulative -----------------

describe('issue#30 — pristineWorldToPixel (yaw-aware mirror of Python)', () => {
  it('yaw=0 collapses to simple form', async () => {
    const { pristineWorldToPixel } = await import('../../src/lib/originMath');
    const r = pristineWorldToPixel(2.5, 1.0, 0.5, -0.5, 0, 100, 80, 0.05);
    expect(r.i_p).toBeCloseTo((2.5 - 0.5) / 0.05, 10);
    expect(r.j_p_top).toBeCloseTo(80 - 1 - (1.0 - -0.5) / 0.05, 10);
  });

  it('yaw=1.604: targeting (oxP, oyP) lands on bottom-left pixel', async () => {
    const { pristineWorldToPixel } = await import('../../src/lib/originMath');
    const r = pristineWorldToPixel(-9.575, -8.75, -9.575, -8.75, 1.604, 200, 200, 0.05);
    expect(r.i_p).toBeCloseTo(0, 9);
    expect(r.j_p_top).toBeCloseTo(199, 9);
  });

  it('mirror parity with Python — hand-computed reference values across yaw sweep [N-B3]', async () => {
    // Hand-computed reference values pinning the math contract.
    // Same formula as Python `godo_webctl.map_transform.pristine_world_to_pixel`:
    //   dx = cumTx - oxP; dy = cumTy - oyP
    //   localX = cos(-θ)·dx - sin(-θ)·dy
    //   localY = sin(-θ)·dx + cos(-θ)·dy
    //   i_p = localX / res; j_p_top = HP - 1 - localY / res
    const { pristineWorldToPixel } = await import('../../src/lib/originMath');

    // Fixture: 100×100 bitmap, origin (-1, -1), res=0.05, target world (0, 0).
    // dx = 1, dy = 1.
    const oxP = -1;
    const oyP = -1;
    const cumTx = 0;
    const cumTy = 0;
    const HP = 100;
    const res = 0.05;

    // Reference compute: with dx=dy=1,
    //   localX = cos(-yaw) − sin(-yaw)
    //   localY = sin(-yaw) + cos(-yaw)
    //   i_p   = localX / res
    //   j_p_top = (HP - 1) - localY / res
    function ref(yaw: number): { ip: number; jp: number } {
      const c = Math.cos(-yaw);
      const s = Math.sin(-yaw);
      const localX = c - s;
      const localY = s + c;
      return { ip: localX / res, jp: HP - 1 - localY / res };
    }
    const yaws = [0, 0.5, 1.604, Math.PI / 2, Math.PI, -Math.PI / 3];
    const cases = yaws.map((y) => ({ yaw: y, ...ref(y), label: 'yaw=' + y }));
    // Spot pin yaw=0: localX=1, localY=1 → i_p=20, j_p_top=79 (sanity).
    expect(cases[0].ip).toBeCloseTo(20, 9);
    expect(cases[0].jp).toBeCloseTo(79, 9);

    for (const c of cases) {
      const r = pristineWorldToPixel(cumTx, cumTy, oxP, oyP, c.yaw, 100, HP, res);
      expect(r.i_p, c.label + ' i_p').toBeCloseTo(c.ip, 8);
      expect(r.j_p_top, c.label + ' j_p_top').toBeCloseTo(c.jp, 8);
    }
  });
});

describe('issue#30 — composeCumulative algebra (mirror of webctl D3)', () => {
  it('identity step: cumulative.translate = parent.translate when typed_delta=0 AND picked=parent', async () => {
    const { composeCumulative } = await import('../../src/lib/originMath');
    const result = composeCumulative(
      { translate_x_m: 1, translate_y_m: 2, rotate_deg: 45 },
      {
        delta_translate_x_m: 0,
        delta_translate_y_m: 0,
        delta_rotate_deg: 0,
        picked_world_x_m: 1,
        picked_world_y_m: 2,
      },
    );
    expect(result.translate_x_m).toBeCloseTo(1, 9);
    expect(result.translate_y_m).toBeCloseTo(2, 9);
    expect(result.rotate_deg).toBeCloseTo(45, 9);
  });

  it('typed delta absorbed: pick (5, 0) + typed (1, 0) → cumulative (4, 0)', async () => {
    const { composeCumulative } = await import('../../src/lib/originMath');
    const result = composeCumulative(
      { translate_x_m: 0, translate_y_m: 0, rotate_deg: 0 },
      {
        delta_translate_x_m: 1,
        delta_translate_y_m: 0,
        delta_rotate_deg: 0,
        picked_world_x_m: 5,
        picked_world_y_m: 0,
      },
    );
    expect(result.translate_x_m).toBeCloseTo(4, 9);
    expect(result.translate_y_m).toBeCloseTo(0, 9);
    expect(result.rotate_deg).toBeCloseTo(0, 9);
  });

  it('rotate accumulates with wrap into (-180, 180]', async () => {
    const { composeCumulative } = await import('../../src/lib/originMath');
    const result = composeCumulative(
      { translate_x_m: 0, translate_y_m: 0, rotate_deg: 170 },
      {
        delta_translate_x_m: 0,
        delta_translate_y_m: 0,
        delta_rotate_deg: 30,
        picked_world_x_m: 0,
        picked_world_y_m: 0,
      },
    );
    // 170 + 30 = 200 → wraps to -160.
    expect(result.rotate_deg).toBeCloseTo(-160, 9);
  });
});

describe('issue#30 — resolveDeltaFromPose @deprecated marker', () => {
  it('resolveDeltaFromPose is still exported (back-compat marker)', async () => {
    const mod = await import('../../src/lib/originMath');
    expect(typeof mod.resolveDeltaFromPose).toBe('function');
  });
});
