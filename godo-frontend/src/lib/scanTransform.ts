/**
 * Track D — polar→Cartesian world-frame transform for the LiDAR scan
 * overlay. Extracted so unit tests can exercise the math without
 * mounting the full PoseCanvas component.
 *
 * Discipline (invariant (l)): the world-frame transform uses the
 * SCAN's anchor pose (`scan.pose_x_m / pose_y_m / pose_yaw_deg`),
 * NEVER a separately-fetched pose. The anchor was the AMCL pose at
 * the moment the scan was processed by the cold writer — zero skew
 * between scan and its anchor.
 */

import { DEG_TO_RAD } from './constants';
import type { LastScan } from './protocol';

/** A single beam's world-frame Cartesian endpoint. */
export interface ScanWorldPoint {
  x: number;
  y: number;
}

/**
 * Project all valid beams in `scan` into world-frame Cartesian points.
 * Drops samples with `range_m <= 0` (the server's invalid sentinel)
 * and clamps the iteration count to `min(scan.n, angles.length, ranges.length)`.
 *
 * Returns an empty array when:
 *   - scan is null,
 *   - scan.valid !== 1.
 *
 * The earlier `pose_valid !== 1` gate (Mode-A M3) was lifted 2026-04-29
 * during PR #29 HIL — the operator needs to see the LiDAR scan shape
 * BEFORE AMCL converges so they can diagnose pose mismatch visually.
 * When `pose_valid === 0`, the snapshot's `pose_x_m / pose_y_m /
 * pose_yaw_deg` are AMCL's current best estimate (may jump between
 * iterations); rays still trace a coherent shape relative to the
 * anchor and are useful as a "what does the LiDAR see right now"
 * diagnostic.
 */
export function projectScanToWorld(scan: LastScan | null): ScanWorldPoint[] {
  if (!scan) return [];
  if (scan.valid !== 1) return [];

  const yawRad = scan.pose_yaw_deg * DEG_TO_RAD;
  const cosYaw = Math.cos(yawRad);
  const sinYaw = Math.sin(yawRad);

  const n = Math.min(scan.n, scan.angles_deg.length, scan.ranges_m.length);
  const out: ScanWorldPoint[] = [];
  for (let i = 0; i < n; i++) {
    const r = scan.ranges_m[i] ?? 0;
    if (r <= 0) continue;
    // RPLIDAR C1 emits angles CW-positive from forward (doc/RPLIDAR/RPLIDAR_C1.md
    // §"θ (0–360°, clockwise)"). The 2D rotation below assumes CCW-positive
    // angles per REP-103, so negate here. Equivalent C++ AMCL math in
    // production/RPi5/src/localization/scan_ops.cpp has the same convention
    // mismatch and is tracked as a separate fix.
    const a = -(scan.angles_deg[i] ?? 0) * DEG_TO_RAD;
    const lx = r * Math.cos(a);
    const ly = r * Math.sin(a);
    out.push({
      x: scan.pose_x_m + lx * cosYaw - ly * sinYaw,
      y: scan.pose_y_m + lx * sinYaw + ly * cosYaw,
    });
  }
  return out;
}
