---
name: Pipelined compute pattern (variable-scope / CPU-pipeline analogy)
description: Architectural pattern proposed by operator 2026-04-29 21:30 KST — for any iterative localization/tracking compute where multiple precision tiers can run concurrently with staggered start. Coarse tiers for basin discovery, fine tiers for precision. CPU-pipeline analogy: at tick t, tier_k runs its (t-k+1)th iteration.
type: project
---

## Idiom

When the project has an iterative refinement compute (AMCL converge, scan-match smoothing, EDT recompute, UE smoother ramp, etc.) where:
- Larger "scope" / "sigma" / "window" gives broad basin discovery but coarse precision
- Smaller scope gives fine precision but small capture range

…then a **pipelined chain of N independent instances** can run staggered on parallel cores. At wallclock tick t, instance_k is doing its (t-k+1)th internal step. Result throughput becomes 1/tick after warmup; total wallclock for N tiers × K steps = K + N - 1 ticks instead of N×K.

Operator's analogy (2026-04-29 21:30 KST): "variable-scope microscope — fast objects zoom out, slow objects zoom in." CPU instruction pipeline: instruction-1 stage 5 + instruction-2 stage 4 + ... + instruction-5 stage 1 in one cycle.

## Track D-5 application (CURRENT, sequential first)

OneShot AMCL annealing: σ schedule [1.0, 0.5, 0.2, 0.1, 0.05]. Sequential implementation first (Track D-5), pipelined-parallel as future optimization (Track D-5-P).

Per-σ AMCL chain: rebuild likelihood field, seed_global (phase 0) or seed_around (k>0), K iterations. Output basin pose, feed to next phase.

## Future applications this pattern unlocks

1. **Live mode tracker** — per-scan refinement at multiple σ tiers; finest tier gives 60 Hz UE output, coarser tiers run at lower rate to detect "we drifted out of basin" signal earlier.
2. **FreeD smoother** — currently ramp-interpolates 60 Hz; pipeline could pre-compute + publish + fetch in overlapping stages.
3. **Map activate → AMCL restart** — currently full restart. Pipeline: phase 1 = hot-swap raw cells, phase 2 = EDT recompute, phase 3 = likelihood rebuild, phase 4 = AMCL re-seed. Stages overlap for shorter operator-visible downtime.
4. **Operator convergence-confidence monitor** — continuously run 5-tier σ pipeline; UI shows "at σ=X you still converge, at σ=Y you don't" — gives operator real-time confidence signal during crane moves.
5. **Phase 5 UE integration test** — measure AMCL stability at multiple σ tiers concurrently to characterize precision-vs-robustness trade-off without re-runs.

## Constraints

- RPi 5: 4 cores. CPU 3 RT-isolated for hot path. Cores 0/1/2 available for cold pipeline → at most 3 tiers concurrent per pipeline. More tiers → sequential fallback.
- Memory: each tier holds its own particle buffer (~5000 × ~32 bytes ≈ 160 KB) and its own likelihood field (~105k cells × 4 bytes ≈ 420 KB). N=5 tiers ≈ 3 MB total. Acceptable on Pi 5's 8 GB.
- Build cache: each tier's likelihood field is a fixed σ; if σ schedule changes, all tiers must rebuild. Trade-off: fewer tiers = less memory + faster setup but coarser σ space coverage.

## Why sequential ships first (Track D-5)

Sequential annealing is a single thread, one σ at a time → no synchronization → simple → testable end-to-end. Pipelined-parallel adds thread coordination, memory layout, contention with the RT hot path. Ship after sequential proves the annealing math works on production hardware.

## NEXT-SESSION audit ★ (operator request, 2026-04-29 22:00 KST)

Operator asked to systematically check where this pattern fits — **beyond AMCL annealing** — including SSE / frontend. Investigate next session:

1. **`/api/scan/stream` + `/api/last_pose/stream` SSE producer-consumer** — currently single-stream per resource. Could a multi-tier scan stream (high-rate raw + low-rate smoothed + lowest-rate analysis) help operator dashboards? Check current SSE plumbing in `godo-webctl/src/godo_webctl/app.py` around the streams.
2. **Frontend `mapMetadata` + scan + pose merge** — PoseCanvas already gates redraw on three async sources. Could a tiered priority queue (high freq pose, mid freq scan, low freq metadata) reduce jank? Check `godo-frontend/src/components/PoseCanvas.svelte` redraw loop.
3. **FreeD smoother 60 Hz** — `production/RPi5/src/smoother/` (if exists). Currently ramp-interp; could pre-compute / publish / fetch overlap?
4. **Map activate phased reload** — currently full restart. Phase 1 hot-cells / phase 2 EDT / phase 3 likelihood / phase 4 reseed. Lower operator-visible downtime.
5. **AMCL Live mode tiered confidence** — concurrent σ tiers giving real-time "are we still locked" signal in operator UI.

Output: ranked table by (a) measured operator benefit (b) impl cost (c) RT-safety on hot path. Tracked as TaskCreate #8 (active "[Next session] Verify pipelined-pattern applicability across GODO").
