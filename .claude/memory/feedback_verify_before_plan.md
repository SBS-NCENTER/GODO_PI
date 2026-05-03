---
name: Verify-before-Plan — read current code before delegating to Planner
description: When delegating a memory-spec or NEXT_SESSION task to Planner, ALWAYS inspect the current code state first and include "I already inspected X — here are the starting facts" in the Planner brief. Saves a wasted plan iteration.
type: feedback
---

When delegating to a Planner from a memory-file spec or a NEXT_SESSION
TL;DR item, do NOT just forward the spec. **Inspect the current code
state first** and include a "Context discovered (don't re-discover)"
section in the Planner brief listing the facts you verified.

**Why:** Confirmed during issue#18 nineteenth-session 2026-05-03 KST.
The spec at `.claude/memory/project_uds_bootstrap_audit.md` listed MF1
"atexit/destructor unlink on graceful shutdown" as a fix to ship.
Pre-Planner inspection of `production/RPi5/src/uds/uds_server.cpp:103-105`
(`~UdsServer()` calls `close()`), `:502-515` (`close()` unlinks
`socket_path_` when `path_bound_=true`), and `production/RPi5/src/godo_tracker_rt/main.cpp:233`
(stack-allocated `UdsServer server(...)` in `thread_uds`) showed MF1
was ALREADY wired via stack unwinding. The Planner brief included this
finding up-front; the Planner correctly downgraded MF1 from "ship a
fix" to "doc-only closure with one test pin + new CODEBASE invariant".
Adding `atexit` would have duplicated the destructor path and created
a redundant unlink race. **One plan iteration saved.**

**How to apply:**

- Memory files describe the moment they were written. Current code is
  the SSOT. Always re-read before delegating.
- Specifically check: file paths cited in the spec (do they still
  exist? at the cited line numbers?), function names (still in scope?
  renamed?), invariants (still enforced? superseded?), and "fix needed"
  claims (already implemented? partially? differently?).
- The Planner brief should have a section like:
  ```
  ## Context discovered (don't re-discover)
  
  I already inspected the code. Note these starting facts:
  
  1. **MF1 (...) is ALREADY IMPLEMENTED** — the spec is slightly out
     of date. Verify yourself: <path>:<line> ...
  2. **PR #N's <feature>** is at <path>:<line> ...
  3. ...
  ```
- This pattern is generalizable: ANY task whose spec is older than ~1
  PR cycle should get a pre-flight verify pass before Planner delegation.
- Cost: ~5 minutes of Read calls. Benefit: avoids 30-60 minute wasted
  plan iteration when the Planner discovers the spec is stale and has
  to rework.

**Don't:** trust the spec verbatim, even when it's freshly written by
the same operator. Memory entries can become stale within hours when a
PR ships between spec authoring and the next session.

**Don't:** outsource the verify step to the Planner agent. Planner
without context can't tell "my brief is wrong" from "the codebase has
the right answer already" — it'll plan against the brief either way.

**See also:** Mode-A reviewer's role becomes thinner when the brief
has pre-verified facts, because the Planner output is already grounded
in current code. Some Mode-A round-2 reworks come from brief staleness
that Mode-A had to discover; Verify-before-Plan moves that work earlier
where it's cheaper.
