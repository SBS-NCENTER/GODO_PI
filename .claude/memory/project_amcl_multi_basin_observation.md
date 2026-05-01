---
name: AMCL multi-basin yaw observation 2026-04-30 (test4 vs test5)
description: HIL screenshots showed 5–10° yaw bias (one-shot) and ~90° yaw error (live) for the same physical LiDAR pose, scan shape identical between modes. Confirms multi-basin localization in T-shape studio, not a noise issue. Drives issue#3 (pose hint) priority.
type: project
---

## What we observed (2026-04-30 KST)

Operator captured two LiDAR-overlay screenshots on news-pi01 with the same physical crane position:

- **test4.png** (one-shot calibrate): cyan scan dots form a clean T-shape but **shifted in (x, y) AND rotated ~5–10° clockwise** relative to the walls. Visual estimate of shift was misleading; later the operator measured by reading PGM-frame coords (see "Quantitative re-measurement" below) — one-shot (x, y) error is actually small (~0.5 m), the visual impression of large shift came from the yaw rotation propagating linearly with range to the far walls.
- **test5.png** (live mode): scan dots dramatically displaced and rotated ~90° from the PGM. Both (x, y) and yaw are large.

Pose readout for both: `σ_xy ≈ 0.01 m, converged`. The convergence flag is **lying** — particle filter is dense at one basin but that basin is far from ground truth.

## Quantitative re-measurement (2026-04-30 23:10 KST)

Operator re-ran with the LiDAR at the same physical pose AND read off PGM-frame coordinates from the SPA pose readout:

| Mode | Ground-truth (operator-measured) | AMCL output | Δ(x, y) | Δ yaw |
|---|---|---|---|---|
| One-shot | (26, 34) | (26, 34.5) | **~0.5 m** | ~5–10° |
| Live | (26, 34) | (22.34, 35.58) | **~4.0 m** | ~90° |

Operator note: "구체적인 수치는 매번 달라지니 대략 이렇구나 알면 될 것 같아요" — these are typical magnitudes, not deterministic values.

## What this implies (revised 2026-04-30 23:10 KST)

**One-shot vs Live convergence quality is dramatically different.** One-shot's `converge_anneal` (multi-phase, sigma annealing) achieves much tighter convergence than Live's per-scan `step()`:

- **One-shot**: (x, y) is recovered to within ~0.5 m of true pose; yaw retains a ~5–10° bias (multi-basin signature in yaw, but the (x, y) basin is correct).
- **Live**: both (x, y) and yaw are wrong. (x, y) drifts ~4 m and yaw flips by ~90°. step() does NOT escape the wrong basin.

The earlier framing "multi-basin localization in yaw" was incomplete. Refined picture:
- One-shot's annealing schedule pulls (x, y) into the correct basin reliably; multi-basin issue surfaces mainly in yaw fine-tuning.
- Live's per-scan single-iteration step() lacks the convergence depth to escape the wrong (x, y, yaw) basin once entered. This is exactly what issue#5 (Pipelined K-step Live AMCL) is meant to address.

**Implications for the issue priority order**:
- **issue#3 (pose hint)** is still the right next move. σ_xy=0.50 m default is well-matched to one-shot's typical ~0.5 m (x, y) bias (1σ catches it). It will improve one-shot yaw multi-basin escape AND give Live a strong-enough seed that step() can hold the basin until issue#5 lands.
- **issue#4 (silent-converge diagnostic)** — even more important than thought. The (x, y) gap between one-shot (good) and Live (bad) is exactly the kind of "converged flag lying differently between modes" that needs a unified metric.
- **issue#5 (Pipelined K-step Live)** — operator's quantitative data confirms this is a real, not theoretical, fix. Live's 4 m drift makes the operator effectively unable to use Live mode without a hint preceding it. issue#5 elevates from "future" to "needed soon".

## What this rules out

- **Hardware mount tilt** (operator: "약 1cm 정도 차이") — verified visually: scan dot bands on walls are thin (~1 px), not thickened. A misaligned rotation axis would smear dots across multiple pixels as the LiDAR yaws.
- **Random noise** — same physical position yielding 5° vs 90° errors is bimodal, not Gaussian.
- **Operator/dynamic obstacle** — operator confirmed studio empty at that hour; the small cluster of cyan dots near the pose dot is a hardware artifact (boom arm or cable, ruled out as person).
- **Per-mode scan publishing diff** — verified in code (`fill_last_scan` is byte-identical between one-shot and live; `cfg.amcl_range_min_m = 0.15` filter applied to both).

## What this implies

**Multi-basin full 3-DoF pose localization** (NOT yaw-only) in the T-shape studio. AMCL's likelihood landscape has multiple local maxima with similar match scores spanning the (x, y, yaw) joint space. Particle filter converges to whichever basin the initial spread happens to favor. With uniform-ish initial pose, basins ~1 m apart in (x, y) AND ~90° apart in yaw can be selected. The studio's low-feature density (long bare walls without distinctive geometry) lets a translated + rotated scan match low-information regions of the map nearly as well as the true pose.

The fix scope is therefore broader than originally framed: pose hint must narrow particle initial spread in **all three DoF** (x, y, yaw) — not just yaw.

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
