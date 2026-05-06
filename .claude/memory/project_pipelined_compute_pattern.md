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

## issue#11 planning axes (operator-locked, 2026-05-03 12:07 KST nineteenth-session close)

Operator outlined three axes for the next-session deep dive on issue#11
(Live mode pipelined-parallel multi-thread). These are the planning
constraints the Planner must address up front:

### Axis 1 — real-time-vs-accuracy trade-off minimization

The pipelined pattern should improve BOTH simultaneously, not trade one for the other.
Sequential Live currently runs K refinement steps per tick → fixed
latency budget caps K, which caps achievable accuracy at high tick
rates. Pipelined: more steps amortized across cores → tighter
convergence per pose output without lengthening the wallclock per tick.
The Planner must show the projected improvement in BOTH dimensions
(latency p99 + steady-state pose error std-dev) — failing to improve
both is a scope misfit.

### Axis 2 — single-core sequential vs multi-core distributed (and the cascade-jitter risk)

The Planner must decide between:

- **Single-core deeper pipeline** (CPU 3 RT-isolated, deeper per-tick
  schedule): no inter-core comm latency, no cascade-jitter risk, but
  caps total throughput at one core's compute budget. Simpler model.
- **Multi-core distributed pipeline** (cores 0/1/2 host different
  pipeline stages, CPU 3 reserved for hot path): higher aggregate
  compute, BUT inter-core handoff adds ~µs-scale latency and — operator's
  key concern — **a stage stall ripples jitter through every downstream
  stage in the pipeline**. One stage missing its deadline means every
  later stage is also late on the next tick.

The Planner must propose a **stall-isolation strategy** for the
multi-core option (e.g., per-stage deadline + skip-tick on overrun + bounded
queue size) OR justify falling back to single-core. "It just works" is
not acceptable — show the worst-case stage-stall ripple analysis.

### Axis 3 — non-Live computation paths audit

Live mode is the obvious candidate, but the Planner must also audit:

- **Calibration (OneShot AMCL)**: σ-anneal already runs sequentially
  (Track D-5 ships sequential). Pipelined-parallel candidate (Track
  D-5-P).
- **AMCL one-shot iteration loops**: per-σ K-step refinement is
  inherently iterative. Could K-step distribute across cores within a
  single σ tier?
- Any other repetitive-pattern compute path the Planner discovers via
  grep of "while" + "for k in range" patterns in production/RPi5/src/.

Goal: a single architectural pattern usable across multiple compute
sites, NOT a Live-mode-specific bolt-on.

### Cross-references

- This memory file's earlier sections describe the conceptual idiom
  + Track D-5 sequential implementation status.
- Spec context for issue#11 is consolidated here; the eighteenth-
  session HIL data baseline (Live ±5 cm stationary / ±10 cm motion /
  yaw ±1°) is the "before" measurement to beat.
- CPU 3 isolation invariant: `.claude/memory/project_cpu3_isolation.md`
  pins CPU 3 RT-only; pipeline must respect this.

## issue#11 status — DONE (2026-05-06 KST, twenty-seventh-session)

**Option C (fork-join particle eval) selected** after Round 2
empirical re-anchor on Phase-0 5-min main capture (eval 69.7 % / LF
29.1 %, TOTAL p50 = 136.15 ms / 7.34 Hz). Plan §2 / §3 / §6 fully
re-derived from measured numbers; Round 1's "phantom baseline"
critique closed. See `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`
for the full Round 2 body + Mode-A round 2 APPROVE-WITH-MINOR-REVISIONS
fold.

Implementation shipped in branch `feat/issue-11-parallel-eval-pool`:

- P4-2-11-1: `src/parallel/parallel_eval_pool.{hpp,cpp}` static lib
  + 9 unit tests (lifecycle / 5000-particle bit-equality / 10⁵
  random-partition stress / worker affinity / workers=1 fallback /
  50 ms deadline timeout / concurrent-dispatch reject / healthy diag /
  CPU 3 ctor reject).
- P4-2-11-2: Amcl ctor + step() accept optional pool pointer; eval
  loop wraps in `pool->parallel_for` with sequential fallback on
  pool==nullptr or join timeout. weighted_mean unchanged. 5
  integration cases pin bit-equal step output / converge_anneal_with_hint
  / converge_anneal / null-safety / empty-cpus-bit-equal-to-nullptr.
- P4-2-11-3: cold writer + main.cpp wiring (pool spawn BEFORE cold
  writer thread per R11; RAII reverse construction guarantees pool
  dtor runs after cold writer join).
- P4-2-11-4: schema row 67 → 68 `amcl.parallel_eval_workers` Int [1, 3]
  default 3 Recalibrate. Plumbing through allowed_keys / TOML / env /
  CLI / make_default / validate_amcl / apply_one / read_effective.
  7 new test cases pin TOML / env / CLI round-trips and
  forward-compat (toml++ silently ignores missing key).
- P4-2-11-5: Seqlock<ParallelEvalSnapshot> + `format_ok_parallel_eval`
  JSON writer + `get_parallel_eval` UDS endpoint
  + diag publisher pump (1 Hz cadence, mirrors JitterSnapshot seam).
- P4-2-11-6: `bench_amcl_converge` regression band — parallel ≥ 2×
  faster than sequential at N=500 (Phase-0 projects ~3×); ≥ 1.5× at
  N=5000. Initial dev-host run: 2.01× / 2.37× — passes the floor.
- P4-2-11-7: CODEBASE.md invariant `(s)` + weekly archive entry
  (`production/RPi5/CODEBASE/2026-W19.md`) + SYSTEM_DESIGN.md §6.6
  parallel particle evaluation subsection + this status close note.

Final: 52/52 hardware-free tests pass; full build.sh gate clean
(`[m1-no-mutex]`, `[rt-alloc-grep]`, etc.). HIL on news-pi01 driven
by operator per plan §6.6 acceptance bar.

**Operator's broader staggered-tier pattern preserved** for sites 2-5
(FreeD smoother, Map activate, confidence monitor, Phase 5 UE
characterization). Selecting C for issue#11 does NOT foreclose B for
those sites — see plan §2.B' for the rejection-reasoning split.

**issue#19** (EDT 2D parallelization) inherits the pool primitive as
~80 LOC follow-up: ~30 LOC `parallel_for_with_scratch<S>` API
extension + ~50 LOC EDT integration. Combined with #11, projects
~21 Hz at p50 / 48 ms scan total on the same Phase-0 fixture.
