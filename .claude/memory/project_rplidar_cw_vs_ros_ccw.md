---
name: RPLIDAR CW vs ROS CCW angle convention — full pipeline status
description: SSOT for LIDAR angle convention across all 5 GODO paths (live driver, live AMCL, live overlay, mapping driver, mapping rf2o). Live paths fixed 2026-04-29; mapping driver fixed 2026-05-05 via Dockerfile sed patch (PR #84 Finding 2). All five paths now CCW-correct.
type: project
---

## Problem statement

RPLIDAR C1 native frame (per SLAMTEC datasheet `sources/SLAMTEC_rplidar_datasheet_C1_v1.2_en.pdf` page 11 + `RPLIDAR_C1.md` §3 Figure 2-4):
- LEFT-handed coords
- ▲ marker = +x = scanner forward
- +y = device's right side
- θ measured from +x toward +y → **CW positive** when viewed from above

ROS REP-103 frame:
- right-handed
- +x forward, +y LEFT
- θ CCW positive

**Correct conversion**: `ψ_REP103 = -θ_RAW` (single negation handles both handedness flip + CW→CCW direction in one op, because the y-axis mirror exactly equals an angle negation in polar form).

A driver/library that uses `M_PI - θ` instead of `-θ` adds an extra 180° rotation, mapping every beam endpoint to the origin-symmetric (point-reflected) position.

## Path-by-path status (5 paths)

| Path | Code location | Status |
| --- | --- | --- |
| Live driver (raw output) | `production/RPi5/src/lidar/lidar_source_rplidar.cpp:152-154` | Raw CW pass-through (downstream handles). ✅ |
| Live AMCL | `production/RPi5/src/localization/scan_ops.cpp:53` | `b.angle_rad = -s.angle_deg * kDegToRad`. ✅ Fixed 2026-04-29. |
| Live frontend overlay | `godo-frontend/src/lib/scanTransform.ts:58` | `const a = -(scan.angles_deg[i]) * DEG_TO_RAD`. ✅ Fixed 2026-04-29. |
| Mapping driver | `Slamtec/rplidar_ros` upstream `src/rplidar_node.cpp:247-251` | Upstream had `M_PI - angle` (extra 180°). ✅ Fixed 2026-05-05 via `godo-mapping/Dockerfile` sed patch + commit pin to `24cc9b6`. |
| Mapping rf2o | `MAPIRlab/rf2o_laser_odometry` (commit pin `b38c68e`) | No own sign manipulation; consumes `/scan` via standard `cos(θ)/sin(θ)` projection. Self-consistent with whatever angles the driver publishes — driver fix is sufficient. ✅ |

**Live and mapping pipelines are now both CCW-correct end-to-end.**

## Mapping driver bug discovery (PR #84 Finding 2)

Operator's HIL on PR #84 (issue#30 pick-anchored YAML normalization) created 3 fresh pristine maps `05.05_v1/v2/v3` by physically rotating the LIDAR 90° CCW between each. SPA showed map content rotating in the SAME direction as the LIDAR (CCW), where slam_toolbox's "world frame = initial scan pose" convention predicts the OPPOSITE direction (CW relative to the new world frame).

Verification matrix dump via single-fan mapping `test_180check_left_obstacle.pgm` (2026-05-05 KST):
- Physical setup: 1 m wall in front of LIDAR ▲ marker, additional obstacles to the LIDAR's left.
- World span observed: `x ∈ [-1.15, +10.25], y ∈ [-7.64, +8.91]`. The +x axis (claimed forward) ran 10 m of free space — implying no wall in that direction. The −x axis was cut at 1.15 m (the actual physical wall).
- Operator confirmed: 1 m wall (physically forward) appeared at PGM −x_world; left-side obstacles appeared at PGM −y_world.

Fingerprint: every beam endpoint at `(x, y) → (−x, −y)` = origin point-reflection = exactly what `ψ = π − θ` produces (= `−θ + π` = correct conversion + extra 180° rotation around origin).

`M_PI - θ` vs `-θ`:
- `−θ` (correct): handedness flip + CW→CCW. Single sign change.
- `π − θ` (driver): the same handedness/CW→CCW flip PLUS a 180° offset. The 180° is the bug.

The 180° rotation on its own is direction-preserving (it's a rotation, not a reflection), so a static scene looks "rotated 180°". When LIDAR rotates physically by Δθ, the rotated published scan also rotates by Δθ in the same direction → slam_toolbox's per-session world-frame anchor inherits this → map appears to rotate the same direction as LIDAR (against the standard convention).

## Driver fix (Dockerfile sed patch)

`godo-mapping/Dockerfile` patches the cloned `rplidar_node.cpp` before `colcon build`:

```dockerfile
RUN ... \
    && git clone https://github.com/Slamtec/rplidar_ros.git \
    && cd rplidar_ros \
    && git checkout 24cc9b6dea97e045bda1408eaa867ce730fd3fc3 \
    && sed -i 's|M_PI - angle_max|-angle_max|g; s|M_PI - angle_min|-angle_min|g' \
       src/rplidar_node.cpp \
    && ...
```

The 4 site replacements all live in `publish_scan()` lines 247-251. Same `git clone` + commit-pin + sed pattern as `rf2o_laser_odometry` (existing precedent in the same Dockerfile).

## Why mapping vs live used different driver paths

- **Live** path: production/RPi5 binary embeds the vendored `rplidar_sdk` directly → raw CW angles → `scan_ops.cpp:53` negates → REP-103 angles → AMCL.
- **Mapping** path: docker container runs the ROS `rplidar_node` binary → publishes `/scan` topic → slam_toolbox / rf2o consume.

The duplication exists because mapping requires the standard ROS topic interface (slam_toolbox + rf2o) but live requires hard real-time C++ (sub-millisecond cold-path budget). The same upstream driver bug never affected live because live never used the ROS driver.

## Confidence

HIGH. Three independent confirmations:
1. **Datasheet derivation**: SLAMTEC's official frame definition + REP-103's standard → `-θ` is correct, anything else is wrong.
2. **Visual HIL**: 1 m wall physically forward → PGM −x_world (point reflection signature).
3. **World-span fingerprint**: 10 m free-space on claimed +x where physical wall blocks at 1 m.

## Related artifacts (point-in-time, may rot)

- `production/RPi5/src/localization/scan_ops.cpp:53` — live AMCL fix
- `godo-frontend/src/lib/scanTransform.ts:58` — live overlay fix
- `godo-mapping/Dockerfile:46-90` — mapping driver patch (sed + commit pin)
- `production/RPi5/src/lidar/lidar_source_rplidar.cpp:152-154` — vendored SDK raw output
- `doc/RPLIDAR/RPLIDAR_C1.md:128` (CW convention quote) + `sources/SLAMTEC_rplidar_datasheet_C1_v1.2_en.pdf` page 11 (Figure 2-4)
- `/home/ncenter/maps_png_for_review/test_180check_left_obstacle.png` — HIL verification artifact (host-local; backup in `/var/lib/godo/maps/test_180check_left_obstacle.{pgm,yaml}`)
