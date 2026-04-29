import { describe, expect, it } from 'vitest';
import { projectScanToWorld } from '../../src/lib/scanTransform';
import type { LastScan } from '../../src/lib/protocol';

function makeScan(overrides: Partial<LastScan>): LastScan {
  return {
    valid: 1,
    forced: 0,
    pose_valid: 1,
    iterations: 5,
    published_mono_ns: 1,
    pose_x_m: 0,
    pose_y_m: 0,
    pose_yaw_deg: 0,
    n: 1,
    angles_deg: [0],
    ranges_m: [1],
    ...overrides,
  };
}

describe('projectScanToWorld — Mode-A TB2 polar→Cartesian cases', () => {
  it('case 1: yaw=90° + beam at 0° + r=1 → (pose_x, pose_y + 1)', () => {
    const scan = makeScan({
      pose_x_m: 5,
      pose_y_m: 7,
      pose_yaw_deg: 90,
      angles_deg: [0],
      ranges_m: [1],
    });
    const points = projectScanToWorld(scan);
    expect(points).toHaveLength(1);
    expect(points[0]!.x).toBeCloseTo(5, 9);
    expect(points[0]!.y).toBeCloseTo(8, 9);
  });

  it('case 2: yaw=45° + beam at 0° + r=√2 → (pose_x + 1, pose_y + 1)', () => {
    // Catches x/y-swap bugs that case 1 hides because cos(90°) = 0.
    const scan = makeScan({
      pose_x_m: 0,
      pose_y_m: 0,
      pose_yaw_deg: 45,
      angles_deg: [0],
      ranges_m: [Math.SQRT2],
    });
    const points = projectScanToWorld(scan);
    expect(points).toHaveLength(1);
    expect(points[0]!.x).toBeCloseTo(1, 9);
    expect(points[0]!.y).toBeCloseTo(1, 9);
  });

  it('case 3: yaw=0° + beam at 90° (RPLIDAR CW = right side) + r=1 → (pose_x, pose_y - 1)', () => {
    // RPLIDAR C1 emits angles CW-positive from forward (per
    // doc/RPLIDAR/RPLIDAR_C1.md). Beam at 90° therefore points to the
    // LiDAR's RIGHT side (local -y), so with yaw=0 the world endpoint
    // is at (pose_x, pose_y - 1). Catches both yaw-vs-beam-angle
    // confusion AND the CW-vs-CCW sign convention bugs.
    const scan = makeScan({
      pose_x_m: 5,
      pose_y_m: 7,
      pose_yaw_deg: 0,
      angles_deg: [90],
      ranges_m: [1],
    });
    const points = projectScanToWorld(scan);
    expect(points).toHaveLength(1);
    expect(points[0]!.x).toBeCloseTo(5, 9);
    expect(points[0]!.y).toBeCloseTo(6, 9);
  });
});

describe('projectScanToWorld — gating', () => {
  it('returns empty when scan is null', () => {
    expect(projectScanToWorld(null)).toEqual([]);
  });

  it('returns empty when valid=0', () => {
    const scan = makeScan({ valid: 0 });
    expect(projectScanToWorld(scan)).toEqual([]);
  });

  it('renders even when pose_valid=0 — diagnostic mode (gate lifted 2026-04-29 during PR #29 HIL)', () => {
    // The earlier "Mode-A M3 — non-converged anchor; rendering would be
    // misleading" gate is gone. Operator needs to SEE the LiDAR scan
    // shape before AMCL converges to diagnose pose mismatch.
    const scan = makeScan({
      pose_valid: 0,
      pose_x_m: 0,
      pose_y_m: 0,
      pose_yaw_deg: 0,
      angles_deg: [0],
      ranges_m: [1],
    });
    const points = projectScanToWorld(scan);
    expect(points).toHaveLength(1);
    expect(points[0]!.x).toBeCloseTo(1, 9);
    expect(points[0]!.y).toBeCloseTo(0, 9);
  });

  it('drops samples with range_m <= 0 (server invalid sentinel)', () => {
    const scan = makeScan({
      n: 3,
      angles_deg: [0, 0, 0],
      ranges_m: [1, 0, -0.5],
    });
    const points = projectScanToWorld(scan);
    expect(points).toHaveLength(1);
  });

  it('clamps iteration count to min(n, angles.length, ranges.length)', () => {
    // n claims 5 but the arrays only carry 2 — must not OOB-read.
    const scan = makeScan({
      n: 5,
      angles_deg: [0, 0],
      ranges_m: [1, 1],
    });
    const points = projectScanToWorld(scan);
    expect(points).toHaveLength(2);
  });

  it('n=0 returns empty (no crash)', () => {
    const scan = makeScan({ n: 0, angles_deg: [], ranges_m: [] });
    expect(projectScanToWorld(scan)).toEqual([]);
  });
});

describe('projectScanToWorld — Mode-A TB1 positional integrity', () => {
  // Mode-A TB1: a torn read on the wire would manifest as an array-pair
  // where ranges_m[i] and angles_deg[i] do NOT satisfy the positional
  // invariant the writer baked in. The C++ side (seqlock.load) catches
  // this BEFORE the wire; on the SPA side the equivalent integrity
  // contract is "given a well-formed scan with the writer's positional
  // formula, the projection produces the expected per-index points".
  //
  // Writer fills (per the C++ stress test):
  //   ranges_m[i]   = i × 0.001
  //   angles_deg[i] = i × 0.5
  //
  // For pose_x = pose_y = 0 and pose_yaw = 0, the world-frame point at
  // index i is (r × cos(a), -r × sin(a)) — the CW→CCW sign flip per
  // doc/RPLIDAR/RPLIDAR_C1.md is applied inside projectScanToWorld so
  // the test's expected formula must mirror it. We verify three sample
  // indices to pin the contract.
  it('positional invariant: per-index point matches the writer formula', () => {
    const N = 720;
    const ranges_m: number[] = [];
    const angles_deg: number[] = [];
    for (let i = 0; i < N; i++) {
      ranges_m.push(i * 0.001);
      angles_deg.push(i * 0.5);
    }
    const scan = makeScan({
      pose_x_m: 0,
      pose_y_m: 0,
      pose_yaw_deg: 0,
      n: N,
      ranges_m,
      angles_deg,
    });
    const points = projectScanToWorld(scan);
    // Index 0 has range 0 → dropped by the invalid-sentinel filter.
    // The first kept point is index 1, with r=0.001 and a=0.5°.
    expect(points).toHaveLength(N - 1);
    // Spot-check three indices (1, 100, 500) against the formula.
    const checkIndex = (i: number) => {
      const r = i * 0.001;
      const a = i * 0.5 * (Math.PI / 180);
      const expectedX = r * Math.cos(a);
      const expectedY = -r * Math.sin(a);  // RPLIDAR CW → REP-103 CCW
      // points[0] corresponds to scan index 1 (after drop), so the
      // i-th surviving point maps to scan index (i + 1 ... or simpler:
      // points are emitted in order, and index 0 was dropped).
      const p = points[i - 1]!;
      expect(p.x).toBeCloseTo(expectedX, 9);
      expect(p.y).toBeCloseTo(expectedY, 9);
    };
    checkIndex(1);
    checkIndex(100);
    checkIndex(500);
  });
});
