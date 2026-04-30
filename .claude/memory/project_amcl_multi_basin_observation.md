---
name: AMCL multi-basin yaw observation 2026-04-30 (test4 vs test5)
description: HIL screenshots showed 5–10° yaw bias (one-shot) and ~90° yaw error (live) for the same physical LiDAR pose, scan shape identical between modes. Confirms multi-basin localization in T-shape studio, not a noise issue. Drives issue#3 (pose hint) priority.
type: project
---

## What we observed (2026-04-30 KST)

Operator captured two LiDAR-overlay screenshots on news-pi01 with the same physical crane position:

- **test4.png** (one-shot calibrate): cyan scan dots form a clean T-shape but rotated ~5–10° clockwise relative to the PGM walls.
- **test5.png** (live mode): cyan scan dots form the SAME T-shape (operator-confirmed: "오버레이의 형태는 one shot과 live가 동일") but rotated ~90° from the PGM. What appears as a horizontal cyan line through the center is in fact the studio's right vertical wall projected through a wrong AMCL yaw.

Pose readout for both: `σ_xy ≈ 0.01 m, converged`. The convergence flag is **lying** — particle filter is dense at one basin but that basin is far from ground truth.

## What this rules out

- **Hardware mount tilt** (operator: "약 1cm 정도 차이") — verified visually: scan dot bands on walls are thin (~1 px), not thickened. A misaligned rotation axis would smear dots across multiple pixels as the LiDAR yaws.
- **Random noise** — same physical position yielding 5° vs 90° errors is bimodal, not Gaussian.
- **Operator/dynamic obstacle** — operator confirmed studio empty at that hour; the small cluster of cyan dots near the pose dot is a hardware artifact (boom arm or cable, ruled out as person).
- **Per-mode scan publishing diff** — verified in code (`fill_last_scan` is byte-identical between one-shot and live; `cfg.amcl_range_min_m = 0.15` filter applied to both).

## What this implies

**Multi-basin yaw localization** in the T-shape studio. AMCL's likelihood landscape over yaw has multiple local maxima with similar match scores; particle filter converges to whichever basin the initial spread happens to favor. With uniform-ish initial yaw, basins ~90° apart are sometimes selected (the studio's "narrow top + wide bottom" geometry doesn't have full 90° symmetry but features are sparse enough that a 90°-rotated scan can match low-information regions of the map).

## Priority implications

- **issue#3 (pose hint) is now P0** — operator clicks rough position on map → AMCL particle initial spread becomes narrow Gaussian around hint → only one basin's particles survive → 90° false-converge eliminated. Most direct fix.
- **issue#4 (silent-converge diagnostic)** — needed to MEASURE whether issue#3 actually escapes the basin. Candidate metrics: mean L2 distance from each scan dot to nearest obstacle pixel; repeatability variance over N runs; multi-basin detector by running converge() from multiple seeds.
- **issue#5 (pipelined K-step Live)** — does NOT fix multi-basin; iterating more on the same scan with the same particle distribution just narrows into one basin faster (possibly the wrong one). Useful for general per-scan accuracy but orthogonal to multi-basin.
- **issue#6 (B-MAPEDIT-3 rotation)** — frame redefinition, orthogonal entirely. Apply only after AMCL is reliable (else next calibrate flips back to wrong basin and undoes the rotation alignment).

## Hardware artifact (test5 center cluster)

Operator observed a small cluster of cyan dots near the red pose dot in test5 (and in test4 once they looked closer). Studio confirmed empty → not a person. Most likely:
- Crane boom arm intercepting LiDAR rays at certain pan angles (boom is fixed in place, but LiDAR yaw rotates with pan, so boom appears at different relative angles)
- Cable or mounting fixture
- LiDAR housing reflection at certain orientations

→ issue#7 (boom-arm angle masking) — optional, contingent on δ diagnostic confirming pan-correlated cluster pattern. May not be necessary if cluster doesn't materially affect AMCL match score.

## Don't re-litigate

Operator briefly hypothesized motor spin-up could cause one-shot vs live quality difference (one-shot using slow-spin data, live using fast-spin). Verified WRONG by code inspection: `lidar_source_rplidar.cpp:66-75` — `setMotorSpeed()` + `startScan()` called ONCE at `godo_tracker_rt/main.cpp:438` boot, motor runs continuously until process shutdown. Both modes operate on stable-RPM data. Operator agreed: "motor 가설이 원인이 아닐 확률이 높아". Park this hypothesis.

## Visual diagnostic for future "is this AMCL or frame?" questions

If the LiDAR scan has the SAME shape as the map but is ROTATED relative to it: AMCL yaw issue (Problem 1 in `feedback_two_problem_taxonomy.md`).
If the LiDAR scan has the SAME shape as the map and is correctly aligned, but the (x, y) labels don't match the operator's mental coordinate system: frame redefinition (Problem 2).
If the LiDAR scan has a DIFFERENT shape from the map (e.g., regional warping): map quality / SLAM distortion. Re-mapping needed.
