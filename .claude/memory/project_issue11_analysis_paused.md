---
name: issue#11 Live pipelined-parallel — analysis paused awaiting empirical data
description: Operator decision 2026-05-03 14:00 KST. Live mode pipelined-parallel design analysis (5 architectures A-E + Mode-A REJECT + cross-analysis) is captured at /doc/issue11_design_analysis.md. Paused pending issue#26 cross-device measurement tool. OneShot calibrate scope dropped — Live only.
type: project
---

## What

issue#11 (Live mode pipelined-parallel multi-thread) ran a full Planner round 1 + Mode-A round 1 in twentieth-session (2026-05-03 KST, afternoon). Plan Round 1 was REJECTED by Mode-A on numerical foundation collapse (K=1 vs actual K≈16, N=10000 vs actual N=500, "particle eval is dominant" unverified). Round 2 Planner content was returned inline (Edit/Write tools missing in that thread) but **never persisted** because operator scope-shifted before persistence: (1) OneShot calibrate scope dropped, (2) empirical measurement first via cross-device GPS-synced test tool.

**Status: PAUSED**. Resumes after issue#26 measurement tool ships AND operator runs at least one capture in broadcasting-room studio.

## Why (operator-locked decisions, twentieth-session)

### Decision 1 — OneShot calibrate is NOT a goal

OneShot is a one-shot operation. Operator can wait the ~500 ms. Real-time pressure does not apply. Round 1 + Round 2 plans both leveraged "OneShot calibrate ~500 ms → ~150 ms side benefit"; this is no longer in the value equation.

**Implication for Option C recommendation**: cross-applicability story narrows. Pool's transfer to OneShot σ-anneal becomes "free if Amcl uses pool unconditionally" but is no longer a deciding factor. Remaining cross-applicability targets: EDT 2D parallelization (issue#19) + future Live re-evaluation post-data.

### Decision 2 — Empirical measurement first (Option E promoted)

Round 1 plan's numerical foundation collapse showed that decisions made on assumed baselines burn iterations. Real measurements first.

Cross-device test tool: RPi5 ↔ MacBook on broadcasting-room wired Ethernet (same subnet). Broadcasting PC explicitly out of scope (server gating prod traffic). Operator goes to office tomorrow (2026-05-04+) for physical wiring + first capture. Tool spec: `project_issue26_measurement_tool.md`.

## Where everything lives

- **`/doc/issue11_design_analysis.md`** — full analysis SSOT. 5 architecture options (A-E) compared on 9 criteria; Mode-A round 1 findings categorized (7 Critical + 10 Major + 8 Minor); cross-analysis verdicts (Option B rejection re-examined; missed alternatives like NEON SIMD / adaptive N / LF prefetch; hidden assumptions). §5 records operator's 2026-05-03 14:00 KST direction shift verbatim.
- **`.claude/tmp/plan_issue_11_live_pipelined_parallel.md`** — Round 1 plan body + Mode-A round 1 fold (lines 533-728). Round 2 content NOT in this file (returned by Planner inline, deemed obsolete by operator scope shift).
- **`.claude/memory/project_pipelined_compute_pattern.md`** — operator-locked 3 axes + 5 future application sites. Still authoritative for the broader pipelined-pattern roadmap.
- **`.claude/memory/project_cpu3_isolation.md`** — RT invariant, applies to any future Live-side work.

## Reading order on cold-start (when issue#11 resumes)

1. This memory file — context of why analysis paused.
2. `/doc/issue11_design_analysis.md` — full analysis. Recently-current as of 2026-05-03; outstanding architectural questions at §6 are deferred to empirical data.
3. `.claude/memory/project_issue26_measurement_tool.md` — companion memory. Status of the measurement tool that produces issue#11 input data.
4. `.claude/memory/project_pipelined_compute_pattern.md` — pattern memory. Sites 2-5 stay open for staggered-tier (Option B idiom); only site 1 (Live) was assessed in twentieth-session.
5. `.claude/tmp/plan_issue_11_live_pipelined_parallel.md` Mode-A round 1 fold (lines 533-728) — 7 Critical findings + cross-analysis. Numbers there are SOURCED against actual code at twentieth-session time.

## Resumption trigger

issue#11 design analysis resumes when **at least one of**:

- issue#26 measurement tool ships AND operator delivers at least one capture (`test_sessions/<TS_ID>/`) of Live mode under realistic studio conditions, including LF-rebuild ms, eval ms, normalize ms, total per-tick ms breakdown.
- Operator manually instruments cold_writer.cpp temporarily (Phase-0 P4-2-11-0 micro-benchmark) and delivers per-stage breakdown CSV.

The architectural conclusion (Option A / B / C / D) is **provisional pending the data**. Round 1 plan recommended Option C (fork-join particle eval) — that recommendation may shift toward issue#19 (EDT parallelization) if data shows EDT rebuild is the actual dominant compute, OR toward Option A (deeper schedule) if K-saturation point is much lower than today's K≈16.

## What NOT to do on cold-start

- Do NOT re-spawn Planner with assumed baseline (K=1 / N=10000) — that error is locked in `feedback_verify_before_plan.md`. Always verify against `production/RPi5/src/localization/cold_writer.cpp:601-645` and `config_defaults.hpp:72-138` first.
- Do NOT proceed without Phase-0 data — operator-locked.
- Do NOT delete `.claude/tmp/plan_issue_11_live_pipelined_parallel.md` Mode-A fold — Round 1 findings remain reference for Round 2.

## Cross-references

- Issue label scheme (CLAUDE.md §6): `issue#11` is the Live pipelined-parallel work. Related reserved labels: `issue#19` (EDT parallelization, candidate follow-up), `issue#21-25` (NEON SIMD / adaptive N / LF prefetch / phase reduction / iters reduction — missed alternatives flagged in Mode-A).
- Prior memory: `project_pipelined_compute_pattern.md` "issue#11 planning axes" section — operator-locked 3 axes verbatim. Round 1 Plan §1 + Round 2 mental model both honor these.
