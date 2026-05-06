---
name: issue#11 Live pipelined-parallel — DONE in PR #99 (2026-05-06)
description: HISTORICAL. issue#11 (Live mode pipelined-parallel multi-thread) shipped as PR #99 on 2026-05-06 KST. Original 20th-session pause + 27th-session Phase-0 measurement + 28th-session full pipeline + post-deploy range-proportional fix all closed. Production cold-path Hz lift verified 7.34 → 11.52 Hz (+57%). Memory entry retained as historical anchor; no further "paused" semantics.
type: project
---

## Status — DONE

Shipped as **PR #99** (`64a2abb` on main, 2026-05-06 KST, 28th-session).

Production binary deployed on news-pi01; fresh 5-min Phase-0 re-capture verified the Option C fork-join lift:

| Metric | Sequential baseline | Post-fix Option C | Speedup |
|---|---|---|---|
| evaluate_scan p50 | 94.85 ms | 45.11 ms | 2.10× |
| TOTAL p50 | 136.15 ms | 86.80 ms | 1.57× |
| Cold-path Hz | 7.34 Hz | 11.52 Hz | +57% |
| `[pool-degraded]` events (5-min window) | n/a | 0 | range-proportional fix verified |

10 Hz LiDAR cleared with margin. Next headroom is issue#19 (EDT 2D Felzenszwalb 3-way), projected to bring 11.52 → ~21 Hz.

## Historical journey (preserved for context)

The original "paused" framing held from the 20th-session through the 27th. Sequence:

1. **20th-session (2026-05-03 KST)** — Planner round 1 + Mode-A round 1 REJECT. Numerical foundation collapse: K=1 was wrong (~16 actual), N=10000 was wrong (500 local / 5000 first-tick), "particle eval is dominant" unverified. Plan paused; Round 2 content returned inline by reviewer was never persisted because operator scope-shifted before persistence: dropped OneShot calibrate from issue#11 scope, requested empirical measurement first.
2. **27th-session (2026-05-05 → 2026-05-06 evening-overnight-morning arc)** — issue#11 P4-2-11-0 trim Phase-0 instrumentation shipped as PR #96. Operator HIL captured 3 windows totalling 2,716 scans. **Main 5-min capture (2166 scans, 1 PID) locked the foundation:** TOTAL p50 = 136.15 ms / 7.34 Hz; eval = 94.85 ms (69.7%); LF rebuild = 39.58 ms (29.1%); jitter+norm+resample combined < 1%; cross-capture variance < 0.5%.
3. **28th-session (2026-05-06 afternoon arc)** — full pipeline run end-to-end:
   - **Planner** rewrote plan with Phase-0 numbers (Round 2). All Mode-A round 1 critical findings (C1 K=1, C2 N=10000, C3 dominance unverified) closed by empirical numbers; mechanical findings (C4 schema 67→68, C5 invariant `(s)`, C6 EDT scratch deferred to issue#19, C7 M1 spirit articulation) absorbed.
   - **Mode-A round 2 reviewer** verdict: APPROVE WITH MINOR REVISIONS. 4 minor inline-folded patches (N1 ctor signature, N2 R18 MESI traffic, n1 cold_writer cite refresh, n2 amcl.cpp eval loop cite).
   - **Writer** shipped P4-2-11-1 ~ -7 across 6 commits (38 files, +2376/-57 LOC).
   - **Mode-B reviewer** verdict: APPROVE WITH MINOR REVISIONS. 2 docs-fix recommendations (M-1 bench band drift, M-2 weighted_mean line cite); both closed by Parent docs commit.
   - **PR #99 merged** as squash → main `64a2abb`.
4. **Post-deploy fix (same session)** — Operator HIL caught a critical defect within 1m 49s of deploy: §3.7/§4 self-inconsistency (~190 ms parallel projected vs 50 ms flat deadline). Fixed via range-proportional deadline (`kJoinTimeoutBaseNs × max(1, range / kJoinTimeoutAnchorN)`), shipped as commit `bfbf671` within PR #99 squash. See `project_range_proportional_deadline_pattern.md` for the reusable pattern + `feedback_cross_section_consistency_after_round_2_adds.md` for the review-pipeline lesson.

## Operator-locked scope decisions (preserved)

These constraints applied throughout and remain valid for issue#11 follow-ups:

- **OneShot calibrate is NOT in scope.** Issue#11 was Live-only. OneShot is unaffected by the pool (it benefits as a side-effect — N=5000 first-tick parallel ~190 ms vs sequential ~580 ms — but no part of the design optimized for it).
- **Pose hint = strong command** (`project_hint_strong_command_semantics.md`). AMCL converges INSIDE the hint cloud, never away from it. Issue#11's fork-join did not change this.
- **CPU 3 reserved for RT** (`project_cpu3_isolation.md`). Pool ctor hard-vetoes CPU 3 in `cpus_to_pin` with a runtime throw. Pinned by `tests/test_parallel_eval_pool.cpp`.

## Cross-references (live)

- `production/RPi5/CODEBASE.md` invariant `(s)` — ParallelEvalPool ownership + worker pinning + M1 spirit + range-proportional deadline rule.
- `production/RPi5/SYSTEM_DESIGN.md` §6.6 — pool architecture page (data flow / cache topology / bit-equality / diag surface / rollback / cross-applicability).
- `production/RPi5/CODEBASE/2026-W19.md` 2026-05-06 14:34 KST entry + Post-deploy HIL section — the per-PR change-log with empirical measurements.
- `PROGRESS/2026-W19.md` 2026-05-06 28th-session block — cross-session technical narrative.
- `doc/history/2026-W19.md` 스물 여덟 번째 세션 block — Korean human-readable narrative.
- `doc/issue11_design_analysis.md` — design SSOT (5 architecture options + Option B vs C FAQ + pre-implementation analysis).
- `doc/amcl_algorithm_analysis.md` — algorithm-level deep-dive written 2026-05-06 KST (untracked at issue#11 close; will be its own docs PR in next session).

## What's "open" past issue#11

- **issue#19** (next priority) — EDT 2D Felzenszwalb 3-way parallelization. Reuses ParallelEvalPool with a `parallel_for_with_scratch<S>` API extension for per-worker (v, z) scratch buffers. ~80 LOC. Projected 11.52 → ~21 Hz.
- **issue#13** — distance-weighted AMCL likelihood (orthogonal; modifies `evaluate_scan` body, not the pool integration).
- **issue#21** — NEON/SIMD `evaluate_scan` (compatible with pool; per-particle vectorization on top of fork-join).
- **issue#22** — KLD-sampling adaptive N (the "A" of AMCL; reduces N during steady-state Live).
- **issue#23** — LF prefetch / gather-batch (cache-miss mitigation in `evaluate_scan`).

These are tracked in `NEXT_SESSION.md` priority list; they replace the now-closed issue#11 on the active queue.
