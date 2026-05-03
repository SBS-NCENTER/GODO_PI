---
name: Post-Mode-B inline polish — when OK to add changes after Mode-B approval
description: Small operator-driven additions (UI text fixes, defensive guards, log additions) can be absorbed inline AFTER Mode-B verdict APPROVE without re-review, provided the addition does not change Mode-B's verdict. Verified twice (PR #72 backup-help follow-up commit, PR #73 ~37 fix + UDS guard).
type: feedback
---

Locked 2026-05-03 KST after PR #72 + PR #73 both successfully absorbed post-Mode-B changes.

**Pattern**: After the reviewer agent returns Mode-B `APPROVE` (or `APPROVE WITH MINOR FIXES`) and the writer's work is committed, the operator may surface small additional needs — UI polish, a defensive log line, a follow-up card in a help section. The question: do we re-run Mode-B, or absorb inline?

**Operator-locked answer**: **absorb inline** if all of the following hold:

1. The addition does NOT touch the contract (no API shape change, no schema row addition/removal, no validator rule change, no test fixture rewrite that affects assertions).
2. The addition is bounded (≤30-50 LOC, single file or tightly-coupled small set).
3. Tests still pass after the addition (run them; do not assume).
4. Mode-B's existing verdict would NOT flip from APPROVE to REWORK based on the addition. (If unsure, run Mode-B again — but in practice, polish changes don't flip verdicts.)

**When to RE-RUN Mode-B** (despite operator pressure to ship):

- Addition introduces a new behavior path (not just polish).
- Addition touches a file that Mode-B specifically commented on.
- Addition would invalidate a test case that Mode-B verified.
- Addition is large enough (>50 LOC, multi-file) that a fresh look is justified.
- Addition introduces a NEW invariant (CODEBASE.md `(letter)` body change).

**Verified twice this session**:

1. **PR #72 follow-up commit `e5c90ab`** — System tab 도움말 sub-tab. Added AFTER Mode-B verdict on the issue#16.1 + issue#10 bundle. Pure UI addition (new sub-tab + new help card + Korean text + CSS). Tests not affected. Operator merged the bundle without re-review.
2. **PR #73 post-Mode-B commits** — three things absorbed inline:
   - **"~37" → `{schema.length}` fix** (`Config.svelte:360` 1-line). Pure cosmetic.
   - **UDS stale-socket guard** in `uds_server.cpp` (~30 LOC including comment). Defensive code path — runs only on stale-state, no behavior change otherwise. Mode-B's existing verdict on the lidar-serial schema row was untouched.
   - **NEXT_SESSION.md issue#18 registration** (~5 lines patch).
   All three landed in the same final commit before push; PR opened directly.

**Why this works**: the bias-mitigation discipline of Mode-B (cite file:line + check for test-of-implementation) is most valuable for the contract-touching changes. Polish changes don't have a contract to verify. The cost-benefit is wrong for re-running.

**Why this DOESN'T mean "skip Mode-B for small PRs"**: the polish absorbs INTO an already-Mode-B-reviewed PR. The substrate (the planned contract changes) was reviewed. Polish rides on top. A whole new PR — even small — still goes through full pipeline per `feedback_pipeline_short_circuit.md`.

**How to apply when polish appears post-Mode-B**:

1. Operator surfaces a small need — assess against the four criteria above.
2. If absorbable: edit + run tests + commit on the same feature branch + push (PR auto-updates).
3. If not absorbable: ask operator if they want re-review or hold the polish for a follow-up PR. Don't assume.
4. Document the absorption in the PR body or commit message ("Mode-A round 2 minor #1-#5 absorbed inline post-review" pattern from PR #72).
5. The Mode-B fold in the plan file does NOT need re-edit (the original verdict still stands; polish was post-fold).

**Anti-pattern**: "scope creep" disguised as polish. If the operator's "small ask" turns into a 100-LOC refactor with new validator rules, that's a NEW PR — say so. The four criteria are the gate.

**Cross-reference**: `feedback_pipeline_short_circuit.md` covers the abbreviated pipeline pattern (skip planner+Mode-B for small standalone PRs). This rule is a different axis: full pipeline ran, AND polish landed after.
