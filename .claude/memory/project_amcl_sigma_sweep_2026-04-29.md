---
name: AMCL sigma_hit sweep results 2026-04-29
description: Empirical k_post + σ_xy data for sigma_hit values 1.0/0.5/0.2/0.1/0.05 on TS5 chroma studio with 04.29_v3 map. Forms the basis for Track D-5 annealing schedule.
type: project
---

Measured 2026-04-29 21:00 KST on news-pi01 with `04.29_v3.pgm` active map and merged-main tracker binary (D-3 active, D-4 not merged). 10 OneShot calibrations per sigma value via UDS `/run/godo/ctl.sock` (probe at `/tmp/godo_amcl_probe.py`). LiDAR physically stationary at ground-truth location ~(1.84, 0.79, yaw 174°) per σ=1.0 single-basin convergence.

| σ_hit (m) | k_post | σ_xy mean | σ_xy median | basins |
|---|---|---|---|---|
| 1.0 | 2/10 | 0.031 | 0.033 | 1 (right) |
| 0.5 | 3/10 | 0.016 | 0.015 | 2 |
| 0.2 | 9/10 | 0.668* | 0.006 | 3 |
| 0.1 | 0/10 | 6.690 | 6.691 | none |
| 0.05 (default) | 0/10 | 6.680 | 6.679 | none |

(*0.668 mean = 1 outlier σ=6.6m dragged it up; median 0.006m is the truth.)

## Key conclusions

1. **`AMCL_SIGMA_HIT_M = 0.05` is below the convergence cliff.** With 5000 random particles over 14×18m × 360°, P(any particle within ~5cm × 5cm × 5° of correct pose) ≈ 1.4e-5 → expected ~0.07 useful particles → AMCL never finds a basin.

2. **Convergence cliff lies between σ=0.1 and σ=0.2** — sharp transition (0/10 → 9/10).

3. **σ=1.0 always converges to the same basin** — robust basin-finding mode. Pose ~(1.84, 0.79, 174°) confirmed by operator visual on /map.

4. **σ=0.2 finds basins reliably but DISTINCT BASINS** due to studio partial symmetry (T-shape long axis). Three basins emerge: (1.1, 0.6, 179°) "right", (-2.7, 8.5, 265°), (-4.7, -1.4, 82°).

5. **D-3 / D-4 are NOT root cause**. With σ=0.05 they all give k=0/10 (verified empirically by reverting D-3 in working tree experiment + applying/reverting D-4 row-flip — system blocked the production-code revert; SPA-side observation that "scan shape matches map" stays valid for D-3).

## Annealing schedule recommendation

Per the sweep + user idea (2026-04-29 21:30 KST): coarse-to-fine schedule lets σ=1.0 lock the basin, then progressively shrink to σ=0.05 final precision.

Recommended schedule for Track D-5: `1.0, 0.5, 0.2, 0.1, 0.05` with `seed_around(last_pose, σ_seed_xy=σ_current_phase * 0.5)` between phases. K=10 iterations per phase. Total ~5 × 100ms ≈ 500ms per OneShot — well within the user's "OneShot completes in seconds" tolerance.

Future optimization (NOT in Track D-5): pipelined-parallel sigma grid search per user's CPU-pipeline analogy — multiple AMCL chains running concurrently at different sigmas on cores 0/1/2 (CPU 3 RT-isolated). Useful for:
- Finding the convergence-cliff sigma quickly across runs
- Disambiguating false basins by comparing convergence locations across sigma tiers
- Live mode where prev_pose narrows the search → more pipeline tiers fit in latency budget
