---
name: RPLIDAR CW vs ROS CCW angle convention bug
description: RPLIDAR C1 emits CW angles (per doc/RPLIDAR/RPLIDAR_C1.md), but production C++ AMCL (`scan_ops.cpp:73-74`) does standard CCW math `r*cos(a), r*sin(a)`. Likely root cause of the 1-in-15 AMCL convergence rate.
type: project
---

Discovered 2026-04-29 18:55 KST during PR #29 (Track D) HIL testing on news-pi01.

## Symptoms

- Operator's PR #29 HIL on `/map`: PGM map matches the actual studio orientation, but the LiDAR scan overlay is vertically mirrored relative to the walls.
- NEXT_SESSION.md TL;DR #3 already noted: "AMCL `calibrate` converges roughly 1 in 15 attempts… When it doesn't converge, pose lands completely outside the studio."
- The operator interpreted the convergence rate as "Phase 2 hardware-gated levers (LiDAR pivot offset + un-tuned AMCL Tier-2 params)". Those may STILL be issues, but the angle convention bug below is a much earlier-in-the-pipeline cause.

## Root cause

RPLIDAR C1's native angle convention: `θ (0–360°, clockwise)` from a fixed reference (forward) — see `doc/RPLIDAR/RPLIDAR_C1.md:128`. CW means angle increases CW when viewed from above the LiDAR.

ROS REP-103 / standard 2D math convention: angle increases CCW from +x, with sin's range mapping to +y on the left side.

**Production C++ AMCL** at `production/RPi5/src/localization/scan_ops.cpp:73-74` uses standard CCW math on raw RPLIDAR CW angles:
```cpp
const double xs = r * std::cos(a);   // a is RAW RPLIDAR CW angle in radians
const double ys = r * std::sin(a);   // ← negated y vs. physical reality
```
Beam at RPLIDAR-90° physically points to the LiDAR's RIGHT side (local -y), but this code computes it as +y. Every beam's y-component is sign-flipped.

**Frontend** had the identical bug at `godo-frontend/src/lib/scanTransform.ts:46-48` until 2026-04-29 18:58 KST when the SPA-only fix landed (negate the angle so the same `cos/sin` produces REP-103-frame `ly`).

**godo-mapping (Docker)** does NOT have this bug. The pipeline uses the official `rplidar_ros2` driver which converts CW→CCW at the driver level before publishing `sensor_msgs/LaserScan`. Therefore slam_toolbox builds a correctly-oriented map (PGM matches real studio), and operators consuming the PGM directly see no mirror.

## Why AMCL still sometimes converges

When AMCL's particle pose hypothesis happens to be `(px = px_actual, py = -py_actual, yaw = -yaw_actual)`, the buggy beam endpoint math
```
xw_buggy(p) = px + xs cos(yaw) - ys_buggy sin(yaw)
            = px + xs cos(yaw) + ys_physical sin(yaw)
```
collapses to a value that matches a wall in the (correct) map — but only when the studio's geometry happens to be approximately symmetric around `y=0`. The TS5 chroma studio is partially symmetric (long axis). Hence "1 in 15" convergences, none of which are physically meaningful poses.

## Why **fixing** AMCL is required (not just the SPA)

The SPA-only fix in scanTransform.ts gives the operator a visually correct overlay-on-map for HIL purposes, BUT the underlying AMCL pose remains in a mirrored frame. Pose dot may render at a "convincing" location due to symmetry but does not correspond to where the LiDAR physically sits.

For real HIL pose accuracy and reliable convergence, the C++ AMCL MUST be fixed in the same way:
- `scan_ops.cpp:48` — when filling the beam, negate the angle: `b.angle_rad = -static_cast<float>(s.angle_deg * kDegToRad);`
- OR negate `ys` in the projection at `scan_ops.cpp:74`.

Either fix is mathematically equivalent. The first is safer because it isolates the convention shift to a single point and downstream code (likelihood field evaluation, etc.) needs no further changes.

## How to apply

NOT urgent for Track D ship — PR #29 is "scale + Y-flip in worldToCanvas" scope; the scanTransform.ts fix bolts on cleanly because it's same-module same-feature. The C++ AMCL fix is a separate Track ("Track D-2: scan angle convention") with its own plan + Mode-A + writer + Mode-B + HIL convergence-rate retest.

Track D-2 sequencing: do BEFORE further Phase 2 AMCL parameter tuning. Tier-2 params tuned against a buggy pipeline would mis-calibrate in the FAR larger convergence basin available after the fix.

Confidence: HIGH. The math derivation is unambiguous; the symptom matches; fix is one-character per side.

## Related artifacts (point-in-time, may rot)

- `production/RPi5/src/localization/scan_ops.cpp:48,73-74`
- `godo-frontend/src/lib/scanTransform.ts:46` (post-fix)
- `production/RPi5/src/lidar/lidar_source_rplidar.cpp:152-164` (where angle_deg is set from angle_z_q14 — confirmed raw CW)
- `doc/RPLIDAR/RPLIDAR_C1.md:128` (the CW convention quote)
