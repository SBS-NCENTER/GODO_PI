---
name: CPU 3 isolation is the GODO design baseline
description: GODO production reserves CPU 3 for the RT hot path (godo_tracker_rt Thread D). The full isolation stack (SCHED_FIFO + IRQ pinning + isolcpus + nohz_full + rcu_nocbs) is the target — not optional polish.
type: project
---

## Decision (2026-04-25)

CPU 3 on the production RPi 5 is **fully reserved** for `godo_tracker_rt` Thread D (the 59.94 Hz UDP send loop). No CFS task, no IRQ, no kernel background work allowed there once production is hardened.

**Why**: once the full system (LiDAR + AMCL + UDS web control + UE traffic) is integrated, jitter regressions are hard to root-cause. Going into Phase 5 with the isolation stack already in place removes "did `isolcpus` matter?" as a debugging variable. The cost is low (CPU 3 = 25% of compute, used 0.3% of the time by the hot path; the LiDAR + AMCL cold path easily fits on CPU 0-2).

**How to apply**: phased so each layer's contribution is measurable. Each step gets its own `godo_jitter` measurement appended to `test_sessions/TS5/jitter_summary.md`.

```text
Step 0 — SCHED_FIFO 50 only (2026-04-25 baseline: p99=29.4 µs, max=56.8 µs)
Step 1 — + IRQ pinning (eth/xhci/uart/dma → 0-2, mmc → 0-1) + irqbalance off
Step 2 — + isolcpus=3 (kernel cmdline; reboot required)
Step 3 — + nohz_full=3 + rcu_nocbs=3 (reboot required; nohz and rcu_nocbs go together)
```

Steps 0–1 are runtime-only. Steps 2–3 require `/boot/firmware/cmdline.txt` edits and a reboot.

## How to apply this memory

- When the user (or another agent) asks "should we add `isolcpus`?", the answer is **yes, that's the plan, see step 2 above**.
- When measuring jitter, always record p50/p95/p99/max alongside the step number so the contribution of each layer stays auditable.
- If a future measurement shows a step REGRESSED jitter, treat it as a bug to investigate, not a reason to drop the step — the cause is likely an interaction with another setting (e.g. nohz_full without rcu_nocbs).
- The full isolation stack is the **production target**, not a "Phase 5 optional". Production deployment must pass with all four layers active.
