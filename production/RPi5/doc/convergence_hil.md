# AMCL convergence-rate HIL protocol

> Operator-driven hardware-in-the-loop test for AMCL OneShot convergence.
> Targets news-pi01 in the TS5 chroma studio.
>
> First authored 2026-04-29 KST as the post-merge gate for Track D-3
> (`fix/track-d-3-cpp-amcl-cw-ccw`). Repeatable for any future change that
> touches `scan_ops`, `amcl`, or the likelihood field.

---

## Why

The C++ AMCL pipeline at `production/RPi5/` is exercised by hardware-free
unit tests (`ctest -L hardware-free`) but those tests do not measure the
end-to-end convergence rate against the real studio environment. Track
D-3's pre-fix HIL session (2026-04-29 19:20 KST) observed roughly
**1 success in 30 calibrate attempts** with the LiDAR parked at a marked
floor location. After the CW→CCW boundary fix at `scan_ops.cpp:48` the
expected post-fix rate is **≥ 7 / 10 attempts** with the converged pose
landing within 1 m of the truth. This document is the script the operator
follows to measure that.

## Pre-flight

- `news-pi01` reachable, RPLIDAR C1 powered + USB connected.
- `production/RPi5/build/godo_tracker_rt` built from the branch under test.
- The studio map fixture used by the tracker (default `04.29_v3.{pgm,yaml}`)
  matches the studio's current state — no major furniture moves since the
  map was built. If furniture moved, redo mapping first.
- Fresh gaffer-tape cross marking the LiDAR pan-axis center on the floor.
  The X arms point along the studio's +X / +Y axes (roughly aligned with
  the long wall).

## Truth-pose extraction (one-time, per map)

```text
1. Open production/RPi5/maps/04.29_v3.yaml (or the active map). Note:
     origin: [origin_x, origin_y, 0]
     resolution: <res_m>          (typically 0.050 m / cell)
2. Open the matching .pgm in an image viewer (GIMP / ImageJ / pillow). For
   04.29_v3.pgm the dimensions are 384 × 365 px (run `file 04.29_v3.pgm`
   to confirm).
3. Identify the pixel (col, row) of the gaffer-tape cross. Row counts
   from the TOP of the image (PIL / image-viewer convention).
4. Compute:
     x_truth = origin_x + col · resolution
     y_truth = origin_y + (height − 1 − row) · resolution
   For 04.29_v3.yaml (origin [-10.855, -7.336, 0], resolution 0.050,
   height 365):
     x_truth ∈ [−10.855, +3.545]
     y_truth ∈ [−7.336, +10.914]
   Outside that range → marked location is off-map; reposition LiDAR.
5. Record (x_truth, y_truth) in the run log. The yaw truth is the angle
   between the cross's +X arm and the map's +X axis; usually 0° if the
   tape was laid axis-aligned.
```

## Run procedure

1. Start the tracker:

   ```sh
   bash /home/ncenter/projects/GODO/production/RPi5/scripts/run-pi5-tracker-rt.sh
   ```

   Confirm `/api/health` returns green. Confirm `/api/last_pose` returns
   `valid: 0` (no calibration run yet).

2. **Calibration loop — 10 attempts**:

   ```sh
   for i in $(seq 1 10); do
     curl -s -X POST http://news-pi01.local:8080/api/calibrate
     sleep 5
     curl -s http://news-pi01.local:8080/api/last_pose
     echo
   done
   ```

   The 5 s gap lets the AMCL converge() complete and the pose to settle.

3. **Per-attempt success criteria**:

   - `converged == 1`
   - `sqrt((pose_x − x_truth)² + (pose_y − y_truth)²) < 1.0 m`
   - `|pose_yaw − yaw_truth| < 30°` (loose; the operator may not have
     aligned the LiDAR pan-axis exactly to the truth yaw)

4. **Record** the count `k_post` of attempts that pass all three criteria.

5. **Visual sanity check**: take a screenshot of `/map` (the SPA map
   page) showing the converged pose dot landing on the floor cross and
   the live LIDAR scan dots tracing the actual studio walls. Attach to
   the PR / next-session entry.

## Acceptance gate

| `k_post / 10` | Decision |
|---------------|----------|
| ≥ 7           | PASS — convergence basin opened up as expected |
| 5–6           | MARGINAL — file Tier-2 retuning ticket but do not revert |
| < 5           | FAIL — escalate to Parent for revert decision per Track D-3 plan §Risks R1 |

Pre-fix baseline was ~1 / 30 ≈ 3 %; post-fix ≥ 7 / 10 = 70 % is the
expected step change. Anything in between is informative for Tier-2
retuning but does not block Track D-3 specifically.

## Tier-2 retuning trigger

Per Track D-3 plan §Risks R2: declare AMCL oscillation if post-OneShot
pose drift exceeds **5 cm/s for > 2 s**. Sample `/api/last_pose` SSE at
10 Hz; oscillation is ≥ 4 consecutive 10 Hz samples with
`√(Δx² + Δy²) > 5 mm`. If triggered, file a separate Tier-2 retuning
ticket. Track D-3 itself is NOT rolled back unless the FAIL row above
also fires (rate worsens vs. baseline).

## Run log template

Append to `production/RPi5/doc/convergence_hil_runs.md` (create if
absent):

```text
### 2026-MM-DD HH:MM KST — <branch / sha>

- LiDAR floor location: (x_truth = ___, y_truth = ___) m
- Yaw truth: ___ °
- Map: 04.29_v3 (height 365 px, resolution 0.050 m/cell)
- Tracker SHA: <git rev-parse HEAD>
- Attempts: 10
- Successes: ___ / 10
- Median pose error: ___ m
- Median yaw error: ___ °
- Screenshot: ___
- Decision: PASS / MARGINAL / FAIL
- Notes: ___
```
