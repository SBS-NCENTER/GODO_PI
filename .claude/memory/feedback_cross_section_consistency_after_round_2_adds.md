---
name: Cross-section quantitative consistency must be re-verified after late-stage section adds
description: When a Mode-A round 2 closes a finding by adding a new subsection (e.g., §3.7 first-tick anatomy), the next reviewer pass MUST re-cross-check the new subsection's quantitative claims against constraints in OTHER sections (e.g., §4 deadline), not just verify the new subsection's internal consistency. Surfaced 2026-05-06 28th-session via issue#11 §3.7/§4 self-inconsistency caught only at HIL.
type: feedback
---

The rule (operator-locked 2026-05-06 KST, 28th-session).

When a review round closes a finding by **adding** a new subsection to the plan (typical pattern: Mode-A round 1 Major M2 says "missing first-tick anatomy" → Mode-A round 2 reviewer or Planner adds §3.7 with the missing analysis), the **next reviewer pass MUST re-cross-check the new subsection's quantitative claims against constraints elsewhere in the plan** — not just verify the new subsection exists and reads internally consistent.

**Why:** A defect can live entirely in the **interaction** between two adjacent sections, not in either section alone. Each section may be correct against its own logic, while their relationship is broken. A multi-pass review that verifies sections individually but never multiplies them together can pass all rounds and still ship a deterministic production failure.

**How to apply:**

- After ANY plan section is added in response to a review finding, the next pass must enumerate the new section's quantitative claims (timing, sizing, throughput, deadlines, capacities) and grep / re-read every OTHER section that constrains or is constrained by those claims. Specifically:
  - new latency projection in subsection X → audit every deadline, timeout, budget, and rate constraint in §4 / §7 / §10 against it
  - new throughput claim in subsection X → audit capacity tables, RT budgets, and Hz acceptance bars
  - new sizing claim (e.g., particle count, buffer size) → audit static_assert counts, capacity invariants, allocation budgets
- Mechanical audit, not interpretive. Even if the cross-check seems redundant ("the original section already had this number locked"), do it anyway. The cost is one re-read; the cost of missing it is a permanent-degraded production binary.
- This applies to both Mode-A and Mode-B passes. Mode-A round-2 reviewers who added a section themselves are NOT exempt; they should mark in their fold which OTHER sections they cross-checked, with line cites.

**Concrete example (the incident that drove the rule):**

issue#11 plan, Mode-A round 1 (2026-05-03):

- Reviewer flagged M2: "missing first-tick anatomy". Closure: "add §3.7".

issue#11 plan, Mode-A round 2 (2026-05-06):

- Planner added §3.7: "tick 0 (seed_global N=5000, all 3 phases run, ~580 ms sequential → ~190 ms parallel)".
- Mode-A round 2 reviewer closed M2 by reading §3.7 and confirming "§3.7 lines 343-352 distinguishes ... first-tick (~580 ms seq → ~190 ms parallel)".
- §4 already said "Per-step deadline: **50 ms** (fork-join hard timeout)" (long predating §3.7).
- **Neither reviewer cross-multiplied** §3.7's "190 ms parallel" against §4's "50 ms deadline" to notice they are mathematically incompatible.

issue#11 Mode-B (same day):

- Reviewer verified the 50 ms code at `parallel_eval_pool.cpp:362-364` against §4's spec.
- Reviewer did NOT re-verify §4's spec against §3.7's projection.

issue#11 deploy on news-pi01 (same afternoon):

- Within 1m 49s of `ParallelEvalPool ready (workers=3)` boot signal, journalctl emitted `[pool-degraded] parallel_for join exceeded 50 ms hard deadline (workers=3, range=[0,5000))` — the OneShot first-tick `seed_global` N=5000 dispatch hit the 50 ms deadline and the pool transitioned to permanent inline-sequential mode for the rest of the tracker's lifetime.
- Operator HIL caught it. Fix shipped same-day as `bfbf671` (range-proportional deadline; see `project_range_proportional_deadline_pattern.md`).

**Forensic signature:** the defect was caught only when the production binary actually ran. Tests passed. Build greps clean. Mode-A and Mode-B verdicts both APPROVE. The interaction was the bug.

**Cross-link to per-stack invariant cite:** `production/RPi5/CODEBASE.md` `(s)` invariant body now anchors the empirical 2026-05-06 HIL incident, which the next reviewer should treat as an in-repo case study when teaching this rule.
