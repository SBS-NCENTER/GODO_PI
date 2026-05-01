---
name: pose hint is operator's strong command, not weak prior
description: Operator-locked semantics for issue#3 hint (2026-05-01 KST after PR #56 deploy + σ sweep on real frame). σ default = 0.5 m / 20° is the production setting. Hint is a directive, not a soft prior. AMCL converges INSIDE the hint cloud; precision must not degrade when the hint is correct.
type: project
---

## What operator decided

After PR #56 (frame fix) deployed and the σ sweep was redone on a correct frame, operator probed:

| σ_xy / σ_yaw | hint near true pose | hint at wrong pose |
|---|---|---|
| 0.3 / 15° | locks to true pose ✓ | follows hint ✗ |
| 0.4 / 18° | locks to true pose ✓ | follows hint ✗ |
| 0.5 / 20° | locks to true pose ✓ | follows hint ✗ |

Operator's framing: **"가까운 곳 두면 실제위치 우세. 이상한 곳 두면 먼 곳 우세. 일단 난 지금의 힌트도 좋은 것 같아. hint 안에 있을 때에는 정밀도가 저하되면 안 된다는 것이 내 생각"** (2026-05-01 KST).

→ Operator-locked: **σ default stays at 0.5 m / 20°. Hint is a directive.** Do not propose code paths that reduce hint strength (e.g., shrinking `anneal_iters_per_phase`, adding likelihood-distance priors that pull AMCL out of the hint basin) without explicit operator approval — they trade hint-safety for hint-error-tolerance, and operator's mental model rejects that asymmetric cost.

## Implications for future Live mode (Live previous-pose-as-hint)

`project_calibration_alternatives.md` proposes "Live previous-pose-as-hint" for continuous tracking (each tick's pose feeds the next tick's hint). The operator's strong-command framing applies even more strongly there: σ for the carry-over hint should match the maximum plausible inter-tick crane-base drift, not be padded for AMCL's "search comfort." A wide σ in Live mode would re-introduce the multi-basin escape route that one-shot mode has been tuned to close.

Concrete: when implementing issue#5 (Pipelined K-step Live + carry-over), default Live carry-over σ_xy ≈ 0.05 m (one tick × ~1 m/s safety × 50 ms ≈ 0.05 m), σ_yaw small. Tune via Tier-2 keys; do NOT auto-widen.

## Implications for issue#7+ (boom-arm masking, distance-weighted likelihood, etc.)

Future AMCL-accuracy work that broadens the search basin (distance-weighted likelihood, masking, etc.) must be opt-in or gated, not change the default behaviour of hint-driven calibrate. The hint-driven path is now stable and operator-validated; do not regress its predictability.

## σ tighten experiment for Live carry-hint — empirically rejected (2026-05-01 PM KST)

After PR #62 (issue#5 Live pipelined-hint kernel) HIL passed, operator probed whether tightening `amcl.live_carry_sigma_xy_m` below the default 0.05 m would reduce the observed ±2-3 cm bounded-jitter at standstill. Result: **No. Tightening σ_xy makes the situation worse, not better.**

| Metric | σ_xy = 0.05 (default) | σ_xy = 0.02 (experiment) | Verdict |
|---|---|---|---|
| x range over 60 s | 27.0 mm | 26.8 mm | unchanged |
| y range over 60 s | 36.5 mm | 34.4 mm | barely changed (6 % improvement) |
| **yaw range over 60 s** | **0.338°** | **0.844°** | **2.5× WORSE** |
| max yaw_std (particle cloud) | 0.224° | 1.925° | **8.6× WORSE** (yaw cloud occasionally explodes) |
| converged 600/600 | 600 ✓ | 598 (2 frames did not converge) | regression |
| iters reaching 30 (full schedule) | 0 | 2 | budget edge cases |

**Why σ tighten backfires:**

The xy floor at standstill is **map cell quantization** (5 cm/cell on `04.29_v3.pgm`), NOT σ. Tightening σ_xy below the cell width does not reduce sub-cell jitter — it just constrains the particle cloud's xy spread. The fixed 5000-particle budget then redistributes density into the yaw axis, expanding yaw spread and occasionally letting particles wander into a poor-yaw basin (visible as the 1.9° yaw_std spike). Worst-case the kernel runs the entire schedule without satisfying patience-2 convergence.

**Operator framing (2026-05-01 PM KST):**

> "정밀도는 내가 말한 부분은 이거야. 바로 앞과 뒤의 프레임만 비교하면 당연히 훨씬 정밀할거예요. 그런데 내가 말하고싶은건 지금 가만히 있는 상태인데도 총 변동 폭이 조금 크다는 것?"

After seeing the σ tighten data, operator restored σ_xy to 0.05 and locked it. The bounded ±2-3 cm jitter is acknowledged as **map-cell-quantization-bounded floor**, not a kernel tuning failure.

**True paths to reduce standstill jitter** (out of scope for issue#5/#12; future work):
- Map resolution 0.05 → 0.025 m (rebuild SLAM with finer grid; PGM 4×, likelihood field memory 4×).
- Distance-weighted likelihood (`r_cutoff` near-LiDAR down-weight) — see `project_calibration_alternatives.md` "Distance-weighted AMCL likelihood".
- Particle count 5000 → 10000 (statistical mean stabilisation; doubles per-tick wall-clock).

**Operator-locked rule (extends the issue#3 hint semantics to Live carry-hint):**

> σ_xy / σ_yaw for Live carry-over MUST stay at the operator-locked default (0.05 m / 5°). Do NOT propose tightening as a jitter remedy — the standstill floor is map-cell quantization, not σ. Tightening σ_xy redistributes particle density into yaw and degrades yaw stability + introduces convergence failures.

This reinforces the existing "do NOT widen for AMCL search comfort" rule from above, in the OPPOSITE direction: do NOT tighten beyond physical drift bounds either. σ is calibrated to a physical reality (inter-tick crane drift bound), not a knob to dial precision in or out.

## Status

- **OneShot hint** σ_xy default: 0.5 m, range [0.05, 5.0] (operator command — wide, directive)
- **OneShot hint** σ_yaw default: 20°, range [1.0, 90.0]
- **Live carry-hint** σ_xy default: 0.05 m, range [0.001, 0.5] (physical drift bound — tight, NOT padded, NOT tightened)
- **Live carry-hint** σ_yaw default: 5°, range [0.05, 30.0]
- All four are Tier-2 recalibrate-class keys; operators MAY PATCH per HIL session, but tightening Live carry σ is now empirically known to backfire and should be avoided without strong evidence.
- HIL acceptance for issue#3 (PR #54): met under PR #56 frame fix.
- HIL acceptance for issue#5 (PR #62) Live carry-hint: met 2026-05-01 PM KST. Operator-locked default-flip to ON queued in combined PR (this session's combined latency PR).
- σ tighten experiment 2026-05-01 PM KST: rejected. Live carry σ stays at default.
- Production-ready as of 2026-05-01 PM KST.
