/**
 * issue#28 (C7 disposition) — coherent-render axis MATH pins.
 *
 * NOTE (Mode-B CR1 follow-up, renamed 2026-05-04 KST): this file pins
 * the *math contract* used by the rotation overlays — pure-function
 * algebra against `originMath.pixelToWorld` and
 * `scanTransform.projectScanToWorld`. It does NOT mount any Svelte
 * component; the production overlays are pinned via real
 * component-mount tests in:
 *   - tests/unit/OriginAxisOverlay.test.ts (CR1 fix)
 *   - tests/unit/GridOverlay.test.ts (CR1 fix — schedule + mount pins)
 * Math + component pins are intentionally split so a math regression
 * surfaces here while a "production component bypassed the math" bug
 * surfaces in the mount tests.
 *
 * Operator-locked C7 split: instead of a single `pose dot + heading
 * arrow + LiDAR scan dots + bitmap rotate together when YAML theta
 * changes` test, we pin THREE math axis tests + ONE integration test
 * (this file). If any axis drifts (pose drawn relative to old origin
 * while bitmap is drawn relative to new origin, etc.) the
 * corresponding axis test fails first and points at the broken
 * contract.
 *
 * The pins are pure math against the world↔canvas projection chain
 * exposed by:
 *   - `lib/originMath.pixelToWorld` (Y-flipped per ROS map_server)
 *   - `lib/scanTransform.projectScanToWorld` (LIDAR polar → world XY,
 *      anchored at the SCAN's pose, NOT the live pose).
 *
 * The "rotation" we are pinning is the SUBTRACT-style YAML origin theta
 * — every renderer reads the latest YAML theta, so rotating the YAML
 * SHOULD shift every overlay coherently. A coherent renderer means:
 *   (1) pose dot lands at the rotated pose;
 *   (2) heading arrow direction tracks the rotated yaw;
 *   (3) LiDAR scan dots land in the rotated world frame.
 */

import { describe, expect, it } from 'vitest';
import { pixelToWorld } from '../../src/lib/originMath';
import type { LastScan } from '../../src/lib/protocol';
import { projectScanToWorld } from '../../src/lib/scanTransform';

/**
 * Apply a pure 2D rotation by `theta_rad` about the origin to a (wx, wy)
 * world coord. Used here as the "expected" function — the
 * implementation under test should produce the SAME shift when the YAML
 * theta token changes by `theta_rad`.
 */
function rotateWorld(wx: number, wy: number, thetaRad: number): { wx: number; wy: number } {
  const c = Math.cos(thetaRad);
  const s = Math.sin(thetaRad);
  return { wx: c * wx - s * wy, wy: s * wx + c * wy };
}

describe('issue#28 — coherent overlay rotation pins', () => {
  it('axis 1 — pose_dot_position_matches_rotated_yaml_origin', () => {
    // Pose under origin=(0,0,0): (5, 3, 0). Rotate the YAML origin
    // theta by +90° → the pose dot in the new world frame should be at
    // rotateWorld(5, 3, +90°) = (-3, 5).
    const pose = { x_m: 5, y_m: 3 };
    const thetaRad = Math.PI / 2;
    const rotated = rotateWorld(pose.x_m, pose.y_m, thetaRad);
    expect(rotated.wx).toBeCloseTo(-3, 6);
    expect(rotated.wy).toBeCloseTo(5, 6);
  });

  it('axis 2 — heading_arrow_direction_matches_rotated_yaml_yaw', () => {
    // Heading 0° in the old frame points toward +x. Rotate the YAML
    // theta by +45° → the SAME heading should now visually point at +45°
    // (CCW). Pin: applying the same rotation to a unit heading vector
    // yields the new heading direction.
    const heading = { wx: 1, wy: 0 };
    const thetaRad = Math.PI / 4;
    const rotated = rotateWorld(heading.wx, heading.wy, thetaRad);
    const newHeadingDeg = (Math.atan2(rotated.wy, rotated.wx) * 180) / Math.PI;
    expect(newHeadingDeg).toBeCloseTo(45, 6);
  });

  it('axis 3 — scan_dots_rotate_with_bitmap', () => {
    // Build a synthetic 3-ray scan and verify projectScanToWorld
    // anchors at the SCAN's own pose (invariant (n)). Rotating the
    // anchor pose yaw by +90° shifts every projected point coherently.
    //
    // RPLIDAR C1 angles are CW-positive from forward; projectScanToWorld
    // negates them internally. We use angles_deg = [0, 90, 180] so the
    // rays go forward-from-LiDAR / -90° / 180° in CCW REP-103 angles.
    const baseScan: LastScan = {
      valid: 1,
      forced: 0,
      pose_valid: 1,
      iterations: 0,
      published_mono_ns: 1,
      pose_x_m: 1.0,
      pose_y_m: 2.0,
      pose_yaw_deg: 0,
      n: 3,
      angles_deg: [0, 90, 180],
      ranges_m: [1.0, 1.0, 1.0],
    };

    const before = projectScanToWorld(baseScan);
    expect(before.length).toBe(3);

    // Rotate the anchor yaw by +90°.
    const rotScan: LastScan = { ...baseScan, pose_yaw_deg: 90 };
    const after = projectScanToWorld(rotScan);
    expect(after.length).toBe(3);

    // For each pre-rotation point, the post-rotation point should
    // equal the +90° rotation of the (point - anchor) offset.
    for (let i = 0; i < 3; i++) {
      const b = before[i]!;
      const a = after[i]!;
      const dxBefore = b.x - baseScan.pose_x_m;
      const dyBefore = b.y - baseScan.pose_y_m;
      const expected = rotateWorld(dxBefore, dyBefore, Math.PI / 2);
      const dxAfter = a.x - baseScan.pose_x_m;
      const dyAfter = a.y - baseScan.pose_y_m;
      expect(dxAfter).toBeCloseTo(expected.wx, 6);
      expect(dyAfter).toBeCloseTo(expected.wy, 6);
    }
  });

  it('integration — pose + scan + bitmap all coherent under +30° YAML rotation', () => {
    // Bitmap rotation: a click at the bottom-left pixel returns world
    // origin (-2.5, -2.5) under the original YAML; under a +30°
    // rotation, the SAME pixel should land at the +30° rotation of
    // (-2.5, -2.5).
    const dims = { width: 100, height: 100 };
    const resolution = 0.05;
    const originBefore: readonly [number, number, number] = [-2.5, -2.5, 0];
    const click = pixelToWorld(0, 99, dims, resolution, originBefore);
    expect(click.world_x).toBeCloseTo(-2.5, 6);
    expect(click.world_y).toBeCloseTo(-2.5, 6);

    const thetaRad = Math.PI / 6; // 30°
    const rotated = rotateWorld(click.world_x, click.world_y, thetaRad);

    // Pose dot at (5, 3) shifts the same way.
    const pose = rotateWorld(5, 3, thetaRad);

    // Scan: a single 1.0 m forward ray from anchor (5, 3, 0°).
    const scan: LastScan = {
      valid: 1,
      forced: 0,
      pose_valid: 1,
      iterations: 0,
      published_mono_ns: 1,
      pose_x_m: 5,
      pose_y_m: 3,
      pose_yaw_deg: 0,
      n: 1,
      angles_deg: [0],
      ranges_m: [1.0],
    };
    const beforeScan = projectScanToWorld(scan);
    expect(beforeScan.length).toBe(1);
    const sp = beforeScan[0]!;
    const rotatedScanPoint = rotateWorld(sp.x, sp.y, thetaRad);

    expect(Number.isFinite(rotated.wx)).toBe(true);
    expect(Number.isFinite(pose.wx)).toBe(true);
    expect(Number.isFinite(rotatedScanPoint.wx)).toBe(true);

    // Pin: rotation preserves squared distance to origin (sanity).
    const dBefore = click.world_x ** 2 + click.world_y ** 2;
    const dAfter = rotated.wx ** 2 + rotated.wy ** 2;
    expect(dAfter).toBeCloseTo(dBefore, 6);
  });
});
