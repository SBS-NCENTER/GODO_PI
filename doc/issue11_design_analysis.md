# issue#11 — Live mode pipelined-parallel: design analysis reference

> Captured: 2026-05-03 KST (twentieth-session, afternoon)
> Status: planning paused for empirical measurement (per operator decision 2026-05-03 ~14:00 KST)
> Source documents:
> - Plan rounds 1+2: `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`
> - Operator-locked axes: `.claude/memory/project_pipelined_compute_pattern.md` "issue#11 planning axes"
> - CPU 3 invariant: `.claude/memory/project_cpu3_isolation.md`

This document is the cold-start reference for the design analysis around issue#11. It exists because the analysis surfaced multiple architectural alternatives + numerical traps that should not be re-discovered next session.

---

## 1. The problem in one paragraph

Live mode publishes a corrected camera-base pose at the LiDAR scan rate (~10 Hz) by running an iterative AMCL refinement against a pre-built map. The published pose then ramps to Thread D's 60 Hz UDP send loop via the offset smoother. Today's Live tick already runs ~16 AMCL steps via a 3-phase σ-anneal (`converge_anneal_with_hint` at `production/RPi5/src/localization/cold_writer.cpp:601-645`). Operator wants better Live-mode latency AND better steady-state pose σ **simultaneously** (not a trade), and wants the architectural pattern to be reusable across other compute sites in the project. The crane base may move at up to ~30 cm/s, with boom up/down dynamics, so Live must hold accuracy under motion.

**Operator-locked priority** (2026-05-03 14:00 KST update): OneShot calibrate latency (~500 ms today) is **NOT a goal** — OneShot is rare and operator can wait. **Only Live mode real-time behaviour matters.**

---

## 2. The 5 architecture options analysed

| Opt | Idea | Threads | Cascade-jitter | Cross-applicability |
|---|---|---|---|---|
| A | Single-core deeper sequential schedule (more phases or higher iters_per_phase on one CFS thread) | 1 | None | Anneal-shaped sites only |
| B | Multi-core staggered tier pipeline — operator's original idiom; 3 tiers on CPU 0/1/2, results flow tier 0 → 1 → 2 via SPSC ring | 3 (workers) | Bounded to 1 tick under skip-tick + per-stage deadline | OneShot direct; weak elsewhere |
| C | Multi-core within-tick fork-join over particle eval; cold writer dispatches `parallel_for(0, N, fn)` and joins per AMCL step | 3 (workers) | None by construction | OneShot direct; EDT via API extension |
| D | Hybrid (A for Live + C for OneShot) | 3 (workers, OneShot only) | None | Same as C |
| E | Null baseline — measure first, decide later | 0 | n/a | n/a |

### 2.1 Option A — single-core deeper schedule

- Smallest change. ~30 LOC of TOML schema bumps + tests. Mostly already accessible today via Tier-2 config (raise `amcl_anneal_iters_per_phase` from 10 to 15, or add a 4th σ phase).
- Helps σ tightness but does NOT speed per-step compute.
- **Implication for current operator goal**: Live wants tighter convergence under motion → Option A is not enough alone (deeper schedule = longer wallclock per tick, may miss the 100 ms LiDAR period under worst-case patience-2 fall-through).

### 2.2 Option B — multi-core staggered tier pipeline (operator's original vision)

- Direct realisation of the operator's `project_pipelined_compute_pattern.md` "variable-scope microscope" idiom.
- Highest accuracy ceiling (effective K ≈ 30 with 3-tier pipeline, latency 33 ms / pose output after warmup).
- Highest implementation cost (~700 LOC: thread pool + lock-free SPSC ring + per-stage deadline + skip-tick policy + telemetry).
- Highest memory cost: 3× LF replication = 48 MB DRAM working set; only ~3 MB fits L2/L3 → continuous DRAM streaming → memory-bus saturation that shares the controller with Thread D's UDP writes.
- Cascade-jitter is **bounded to 1 tick** under skip-tick + per-stage deadline + bounded queue (operator's own canonical Axis-2 mitigation), NOT unbounded as round-1 plan implied.
- **Real disqualifier for issue#11**: implementation cost + cache topology, not cascade-jitter.
- **Pattern preserved for future sites** (smoother / map-activate / confidence-monitor / Phase 5 UE characterization).

### 2.3 Option C — multi-core within-tick fork-join (round 1 recommendation)

- New `ParallelEvalPool` static lib (~280 LOC). 3 worker threads pinned to CPU 0/1/2, sleep on cv until cold writer dispatches.
- Per-tick savings (corrected for real N=500): per-step eval ~0.6 ms sequential → ~0.2-0.25 ms parallel. 16 steps × ~0.4 ms saved = ~6 ms / tick. **Modest, NOT 80 ms as round-1 phantom claimed.**
- Cascade-jitter structurally impossible — every AMCL step is a self-contained fork-join.
- TOML kill-switch (`amcl.parallel_eval_workers = 1`) for instant rollback.
- **Caveat**: if EDT rebuild (3× per tick) is the actual dominant compute, the Live-tick win is small and the architectural value lives mostly in cross-applicability (issue#19 EDT parallelization).

### 2.4 Option D — hybrid (round 2 partial)

- Round 2 considered Live = A + OneShot = C. **Operator just removed OneShot from scope (2026-05-03 14:00 KST), so Hybrid collapses to "A only" — no longer a distinct option.**

### 2.5 Option E — null baseline (now PROMOTED)

- Round 1 dismissed E as "Reviewer-only artifact". Round 2 folded a Phase-0 micro-benchmark into the Writer task list as the FIRST step.
- **Operator decision 2026-05-03 14:00 KST: E is the actual next move.** Build a cross-device measurement tool, gather empirical data, then decide between A/B/C with real numbers.

### 2.6 Option B vs Option C — what gets split (FAQ)

This is the most common point of confusion when reading the options side-by-side. The two architectures parallelize along **different axes of the same workload**.

**Option B = time-axis split** (stage / tier parallelism). Three threads run in lockstep, each on a *different σ value* in the schedule:

- Thread 0: σ=0.2 (wide, basin discovery) — runs every tick on the newest scan
- Thread 1: σ=0.1 (mid) — runs every tick on Thread 0's previous-tick output
- Thread 2: σ=0.05 (tight, publishes) — runs every tick on Thread 1's previous-tick output

After warmup (3 ticks), every wallclock tick produces one tier-2 pose. Each thread sees the **full scan + full LF** for its own σ. The split is on *which σ tier each thread is responsible for*, not on which beams or which particles each thread sees. Cascade-jitter risk lives here: Thread 0 stalling on tick t → Thread 1 stale input on tick t+1 → Thread 2 stale input on tick t+2 (bounded to 1 tick under skip-tick + per-stage deadline policy, but the dependency chain is fundamental to the architecture).

**Option C = data-axis split** (per-particle / fork-join parallelism). Inside ONE AMCL step at ONE σ, the inner particle loop is split across 3 workers:

- Worker 0: particles 0..166 (167 candidate poses)
- Worker 1: particles 167..333 (166 candidate poses)
- Worker 2: particles 334..499 (166 candidate poses)

Every worker uses the **full scan (all ~290 beams) + full LF (all 16 MB)**. The split is purely on *which candidate poses are evaluated*. After fork-join completion, the cold writer continues sequential post-processing (normalize → resample → publish). No inter-tick state propagation between workers → cascade-jitter structurally impossible.

**Common misunderstanding (operator-flagged 2026-05-05)**: "splitting particles 1/3 each → each worker sees only 1/3 of the LiDAR scan → less information → AMCL accuracy degrades". This is wrong. The scan is read-only and shared across all workers. Each particle still scores against every beam, identical to the sequential path. The split is on *how many candidate poses we score in parallel*, not on *what information each pose has access to*.

**Analogy**: 500 candidate answer sheets to grade. 3 graders divide the answer sheets among themselves (167 sheets each), but every grader uses the same complete grading rubric. We do not split the rubric; we only split the sheets.

```text
Option B (tier-pipeline) ─ time axis
                  tick1   tick2   tick3   tick4   tick5
   Thread0(σ=0.2): scan1 → scan2 → scan3 → scan4 → scan5    (wide σ, basin discovery)
   Thread1(σ=0.1):    ·  → scan1 → scan2 → scan3 → scan4    (1 tick lag, narrows)
   Thread2(σ=0.05):   ·  →    ·  → scan1 → scan2 → scan3    (2 tick lag, publishes)
                                       ▲
                              tier0 stall → tier1 stale → tier2 stale → ripple

Option C (fork-join) ─ data axis (within one tick)
                  tick1                          tick2
                  ┌──────────────────────┐       ┌──────────────────────┐
                  │ jitter (single)      │       │ jitter (single)      │
                  │ eval ↓ FORK          │       │ eval ↓ FORK          │
   Worker 0:      │   particles 0..166   │       │   particles 0..166   │
   Worker 1:      │   particles 167..333 │       │   particles 167..333 │
   Worker 2:      │   particles 334..499 │       │   particles 334..499 │
                  │ JOIN                 │       │ JOIN                 │
                  │ normalize + resample │       │ normalize + resample │
                  │ publish pose1        │       │ publish pose2        │
                  └──────────────────────┘       └──────────────────────┘
                          tick 안에 fork-join 완결 → 다음 tick은 독립
```

**Compatibility with issue#13 (distance-weighted likelihood)**: issue#13 modifies the *body* of `evaluate_scan` to add per-beam weighting based on range (down-weight near-LiDAR beams). Option C parallelizes the *caller* of `evaluate_scan` over particles. The two operate at different abstraction layers and compose without conflict — the parallel path calls the same `evaluate_scan` body, distance-weighted or not. issue#13 may be merged before, after, or alongside issue#11 without re-design.

---

## 3. Mode-A round 1 findings — the numerical foundation collapse

The round-1 plan was REJECTED because three baseline assumptions were factually wrong against current source code.

### 3.1 Critical findings (foundation-shifting)

| # | Round-1 plan said | Actual (verified in source) |
|---|---|---|
| **C1** | Live runs `K=1` AMCL step per tick today | Live runs ~16 steps (3-phase σ-anneal × ≤10 iters/phase, mean=15.7 per HIL note at `config_defaults.hpp:138`) |
| **C2** | N = 10000 particles | N = 500 steady-state, N = 5000 only OneShot phase 0 (10000 is buffer ceiling, not population) |
| **C3** | "Particle eval is the dominant compute" | Unverified. EDT rebuild (3× per tick × ~50 ms each) may dominate. |
| **C4** | Schema size 52 → 53 | Already 53 today; new row makes it 54 |
| **C5** | New invariant `(v)` | Next free letter is `(s)` (gaps at `(o)`, `(p)`) |
| **C6** | "EDT row/col is embarrassingly parallel — 0-LOC bonus" | `edt_1d`'s `v, z` scratch buffers are reused across rows; per-worker scratch required → API extension needed (NOT 0-LOC) |
| **C7** | "M1 invariant safe because separate TU" | Build-grep mechanics are safe, but M1's *spirit* (no blocking in cold publish path) needs articulation: cold writer is NOT a wait-free publisher (only Thread D is); pool's mutex held only during dispatch/join, never around `target_offset.store()`. |

**Why these matter**: latency / accuracy projections in round-1 §2-§4 were all derived from C1-C3. With real numbers, the per-tick savings drop from claimed 80 ms to actual ~6 ms, and the architectural conclusion may shift toward "EDT parallelization is the real win" (issue#19 follow-up) rather than "Live eval parallelization".

### 3.2 Major findings (reasoning quality)

- **M1**: Option B's rejection should lead with **implementation cost + cache topology**, not cascade-jitter. Ripple is bounded to 1 tick under skip-tick policy. Round-1 had right answer for wrong reason.
- **M2**: Round-1 distinguished "first tick (N=5000 seed_global)" from steady-state — but **Live never goes through `seed_global`**; that path only exists in OneShot. Live is uniform N=500 hint-seeded.
- **M3**: bit-equality of parallel-vs-sequential output requires `weighted_mean()` to be sequential summation (it is, verified `amcl.cpp:257-274`). Future-fragility flag if anyone parallel-reduces the mean.
- **M4**: Pool ctor needs bounded ready-wait timeout (1 s); on timeout boot in degraded inline mode.
- **M5**: Pool worker stacks default 8 MB × 3 = 24 MB locked under `mlockall(MCL_FUTURE)`. Bound to 256 KB each (768 KB total).
- **M6**: TOML branch-compat (R8) is simpler than round-1 thought — toml++ silently ignores unknown keys (`config.cpp:171-180`). install.sh strip not required.
- **M7**: cv predicate must use per-worker monotonic dispatch counter (`last_processed_dispatch[wid] < current_dispatch_seq`) to avoid lost wakes.
- **M8**: Permanent-degraded fallback semantics on worker crash — not silent retry.
- **M9**: Diag publisher choice: NEW dedicated `format_ok_parallel_eval` UDS endpoint + new seqlock; NOT extending `JitterSnapshot` (would conflate two metrics). Planner picks, doesn't punt to reviewer.
- **M10**: Build-grep `[m1-no-mutex]` "extension" is comment-only; no new project-wide grep added.

### 3.3 Minor findings (cross-analysis depth)

| # | Finding |
|---|---|
| m1 | Time-stamp convention for new CODEBASE.md `(s)` entry per CLAUDE.md §6 |
| m2 | Korean summary inherits the C1 K=1 error — must correct after fix |
| m3 | **NEON SIMD on `evaluate_scan`** — Pi 5's Cortex-A76 NEON, vectorize per-beam coordinate transform (4 doubles/instruction). 2-3× single-core speedup. **Zero RT-safety risk, zero threading.** Best cost-benefit alternative. → issue#21 candidate |
| m4 | **Adaptive N (KLD-sampling)** — after basin lock, N=500 may be excess. KLD-sampling drops to ~100. Beats parallelization on cost. → issue#22 |
| m5 | **LF prefetch / gather batching** — `__builtin_prefetch` 4-8 beams ahead hides DRAM cache miss without threading. 1.5-2× speedup. → issue#23 |
| m6 | Phase reduction 3→1 in Live carry — wide-σ phase may be unproductive when hint-seeded. TOML-only. → issue#24 |
| m7 | `amcl_anneal_iters_per_phase` 10→5 — early-exit fires fast, ceiling rarely applies. → issue#25 |
| m8 | RNG state determinism in test §6.2 case 1 (capture + deep-copy) |

---

## 4. Cross-analysis verdicts

### 4.1 Option B rejection re-examined

**Verdict: defensible, but for different reasons than round-1 stated.**

- Cascade-jitter is bounded to 1 tick under skip-tick + per-stage deadline + bounded queue (operator's own canonical Axis-2 mitigation). Round-1's "unbounded ripple" framing was incorrect.
- Real disqualifiers: (1) implementation cost ~700 LOC vs ~280 LOC for C, (2) 3× LF replication (48 MB) saturates DRAM bandwidth on Pi 5.
- **Operator's broader staggered-tier idiom is preserved as a future tool** for sites 2-5 in `project_pipelined_compute_pattern.md` (FreeD smoother, Map activate, confidence monitor, Phase 5 UE characterization). issue#11 selecting C does NOT foreclose B for those sites.

### 4.2 Hidden assumptions surfaced

| # | Assumption | Resolution |
|---|---|---|
| 1 | Operator wants tighter convergence per tick | May actually want HOLDABLE pose without jitter — these are different optimization targets. Resolution: HIL must measure deadband pass rate alongside σ. |
| 2 | 10 Hz publisher cadence is the rate axis | `project_pipelined_compute_pattern.md` Phase 5 mentions "concurrent σ tiers giving real-time confidence signal" — implies operator may want >10 Hz output. Smoother already runs at 60 Hz. **Open question for operator confirmation.** |
| 3 | Deadband stays 10 mm + 0.1° | Tighter σ → more poses pass deadband → more smoother churn → potentially more visible UE jitter. Must measure. |
| 4 | K saturation point | With σ_live_xy=50mm hint-seeded, AMCL may converge in 2-3 steps; beyond that K is wasted. Phase-0 measurement required. |
| 5 | Pool stays alive when workers=1 | Fixed in round-2 §3.5: workers NOT spawned when configured to 1; pool runs degenerate inline. |

### 4.3 Path forward (per Mode-A round 1)

1. Phase-0 micro-benchmark — instrument `converge_anneal_with_hint` with `monotonic_ns()` checkpoints.
2. Operator runs 30 s Live on news-pi01, captures breakdown CSV.
3. Plan re-derives architecture with real numbers.
4. Mode-A round 2.

---

## 5. Operator direction shift (2026-05-03 14:00 KST)

Operator made two scope-changing decisions:

### 5.1 OneShot calibrate spinner is NOT a goal

Round-1 + round-2 plans both leveraged Option C as a "OneShot calibrate ~500 ms → ~150 ms side benefit". Operator: **OneShot is a one-shot operation, real-time pressure does not apply.** Drop OneShot from the value equation.

**Implication**: Option C's cross-applicability story narrows. The pool's transfer to OneShot σ-anneal becomes "free if Amcl uses pool unconditionally" but is no longer a deciding factor. The remaining cross-applicability targets:
- EDT 2D parallelization (issue#19) — still attractive for Live-side LF rebuild speedup if EDT dominates per tick.
- Future sites 2-5 in pattern memory — long-term.

### 5.2 Empirical measurement before architecture decision (Option E promoted)

Operator decision: **build a cross-device measurement tool, gather data, then re-decide.** Reasoning: round-1 plan's numerical foundation collapse showed that decisions made on assumed baselines burn iterations. Real measurements first.

**Test surface specified by operator**:
- **GPS-synced KST clock comparison** between RPi5 + MacBook + (broadcasting room PC) at ms granularity.
- **RPi5-side measurements**:
  - Per-pipeline-stage latency (only stages observable without perturbing the production path).
  - UDP packet send timestamp (both Tailscale IP + local IP).
  - SSE send timestamp (webctl → frontend).
- **Receiving-PC-side measurements** (broadcasting room — wired Ethernet):
  - Web-page API receive timestamp.
  - UDP receive timestamp (both Tailscale + local).
- **Cross-machine log sync** via the same git repo so timestamps align for analysis.
- **Packet identity for cross-device matching** (operator detail, 2026-05-03 ~14:30 KST): each log line records `(timestamp, last_N_bytes_of_payload, checksum)` rather than the full payload. Lightweight to write, sufficient to confidently pair the SAME packet across sender + receiver logs without bloating the repo. For FreeD UDP (29-byte structured packet), `last 4-8 bytes + the FreeD D1 checksum byte` is a natural match key. For SSE JSON lines, the trailing `,"seq":N}` plus a short payload hash works. Logs synced via git → analyst grep-joins by checksum to align same-packet-across-devices.

**Rationale for cross-device**: same repo across MacBook + RPi5 means logs land in a known place; GPS-grade KST sync lets the analyst align cold-path → UDP → wire → broadcasting-PC → UE rendering on a single timeline. Packet identity matching ensures every (send, receive) pair is the SAME packet, not a coincidence on adjacent timestamps. Without this two-part rigour (synced clock + packet identity), every stage's contribution to user-visible jitter is opaque.

---

## 6. Outstanding architectural questions (deferred until measurement)

The following questions are **explicitly deferred** until empirical data is in hand:

1. Is per-tick eval (today ~9.6 ms) actually the dominant Live-tick compute, or does EDT rebuild (3× ~50 ms hypothetical) dominate? — answers whether issue#11 (eval parallelization) or issue#19 (EDT parallelization) is the bigger win.
2. Does motion at 30 cm/s genuinely degrade σ to ±10 cm today, or is the eighteenth-session HIL number conservative? — answers whether AMCL convergence is even the bottleneck at all (could be motion-model uncertainty floor).
3. What is the K-saturation point? After how many steps does σ_xy stop tightening? — answers whether Option A (deeper schedule) or Option C (faster steps) makes more sense.
4. What is the deadband-pass rate today, and how does σ improvement change it? — answers whether tighter convergence helps or hurts user-visible UE jitter.
5. What are end-to-end stage timestamps from "scan arrival" to "UE renders pose"? — only the cross-device GPS-synced measurement tool can answer.

---

## 7. Reference reading order

For a future cold-start picking up issue#11:

1. This document — design analysis context.
2. `.claude/memory/project_pipelined_compute_pattern.md` — operator-locked 3 axes + 5 future application sites + `project pipelined-pattern` idiom.
3. `.claude/memory/project_cpu3_isolation.md` — RT invariant.
4. `.claude/tmp/plan_issue_11_live_pipelined_parallel.md` — full round-1 plan + Mode-A round-1 fold (round-2 content not persisted to file due to operator scope shift).
5. Source files (verified in pre-survey + Mode-A): `cold_writer.cpp:601-645`, `amcl.cpp:194-274`, `likelihood_field.cpp:33-78,109-144`, `config_defaults.hpp:72-162`, `config_schema.hpp:105,162`.

---

## 8. Issue label reservations

Per CLAUDE.md §6 issue scheme. Next free integer is `issue#19` as of 2026-05-03 14:00 KST.

| Issue | Scope | Status |
|---|---|---|
| issue#11 | Live mode pipelined-parallel — analysis paused for measurement | analysis paused |
| issue#12 (existing) | Smoother latency tuning | shipped |
| issue#13 (existing) | distance-weighted AMCL likelihood | open, deferred |
| issue#19 | EDT 2D Felzenszwalb parallelization (requires `parallel_for_with_scratch<S>` API ext) | reserved |
| issue#20 | Track D-5-P (deeper σ schedule for OneShot, staggered-tier) | reserved (was D-5-P, now low priority since OneShot scope dropped) |
| issue#21 | NEON/SIMD vectorization of `evaluate_scan` | reserved |
| issue#22 | Adaptive N (KLD-sampling) | reserved |
| issue#23 | LF prefetch / gather-batch | reserved |
| issue#24 | Phase reduction 3→1 in Live carry (TOML-only) | reserved |
| issue#25 | `amcl_anneal_iters_per_phase` 10→5 (TOML-only) | reserved |
| issue#26 | Cross-device GPS-synced measurement tool | **NEW — to be planned, current next-session priority** |

Next free integer after this batch: `issue#27`.
