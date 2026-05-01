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

## Status

- σ_xy default: 0.5 m, range [0.05, 5.0]
- σ_yaw default: 20°, range [1.0, 90.0]
- Both Tier-2 recalibrate-class keys; operators may PATCH per HIL session.
- HIL acceptance for issue#3 (PR #54): met under PR #56 frame fix. Multi-basin failure rate (test11-like, ~5% pre-hint) is reduced to operator-controlled (driven entirely by hint placement quality).
- Production-ready as of 2026-05-01 KST.
