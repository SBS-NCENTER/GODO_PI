---
name: Range-proportional deadline pattern for fork-join hot paths with workload that varies 10× across modes
description: When a fork-join primitive is dispatched with workload sizes that vary by an order of magnitude across modes (e.g., AMCL steady-state N=500 vs OneShot first-tick N=5000), a flat hard timeout is mathematically incompatible with both modes. The pattern `deadline ∝ max(1, workload / steady_anchor) × base` preserves the worker-stall guard for the steady mode AND accommodates the heavy mode within the same architectural surface. Locked 2026-05-06 KST via issue#11 PR #99 commit `bfbf671`.
type: project
---

## The pattern

```cpp
constexpr int64_t  kBaseTimeoutNs  = X * 1'000'000LL;   // X ms — anchor for the steady mode
constexpr size_t   kAnchorN        = N_steady;          // workload size of the steady mode

const size_t  workload  = end - begin;
const int64_t scale_n   = std::max<int64_t>(
    1, static_cast<int64_t>(workload / kAnchorN));
const int64_t deadline_ns = kBaseTimeoutNs * scale_n;
```

For workload < anchor → scale clamps to 1 → base deadline (preserves worker-stall guard for any "small" range, including test cases).

For workload = N×anchor → scale = N → deadline N×base.

## Why a flat deadline is the wrong default

A flat deadline forces a tradeoff between two failure modes:

| Flat deadline value | Steady mode | Heavy mode |
|---|---|---|
| **Tuned for steady mode** (e.g., 50 ms when steady runtime is 35 ms) | OK — fast worker-stall detection | Heavy mode runtime exceeds → permanent fallback on first heavy dispatch |
| **Tuned for heavy mode** (e.g., 500 ms when heavy runtime is 190 ms) | Worker-stall window is 10× too generous; dead worker takes ~500 ms to surface | OK |

There is no single value that is both fast-enough on steady AND slack-enough on heavy. The range-proportional rule resolves this without compromise: each mode gets its own appropriate deadline, derived from a single base + anchor pair.

## When the pattern applies

- **Workload size is a function of mode**, not a function of time or scheduling jitter. AMCL N (particles per dispatch) is a function of mode: N=500 in steady-state Live, N=5000 in OneShot first-tick / Live re-entry. EDT row/column passes are W × H — function of map size, not mode.
- **The cost is roughly linear in workload size.** If cost is super-linear (e.g., O(N log N) sort), the formula needs a non-linear scaling factor and may not fit cleanly into the "× scale_n" idiom.
- **The mode shift is observable at dispatch time.** The dispatch caller knows `(begin, end)` and can compute the scale before kicking off workers. If the workload size is unknown until inside fn(), the pattern degenerates to a flat deadline.

## Reusable sites in GODO

| Site | Workload anchor | Notes |
|---|---|---|
| issue#11 ParallelEvalPool (shipped PR #99) | N=500 (Live steady) | Anchor: `kJoinTimeoutAnchorN = 500`; first-tick N=5000 → 10× scale → 500 ms deadline. |
| issue#19 EDT 2D 3-way (shipped feat/issue-19-edt-parallel, 2026-05-07 KST — DONE) | `max(W, H)` per row/col pass dispatch | EDT-specific Tier-1 anchors `EDT_PARALLEL_DEADLINE_BASE_NS = 50 ms` (single-pass anchor at the 1000-dim reference scale), `EDT_PARALLEL_ANCHOR_DIM = 1000` (`max(W, H)` is the dispatch range, NOT cell count). Formula `scale = max(1, max(W,H) / 1000)`: 1000×1000 → scale=1 → 50 ms/pass; 2000×2000 (EDT_MAX_CELLS edge) → scale=2 → 100 ms/pass. m2 fallback rule (operator-locked 2026-05-06 21:00 KST): if HIL or `bench_lf_rebuild` measures 2000×2000 worker p99 > 80 ms, anchor drops to 750 via separate small PR. Shares the `parallel_for_with_scratch<S>` extension (caller-owned `std::vector<EdtScratch> per_worker`, type-erased shim). issue#19.2 reserved for production-runtime fold-rate telemetry per m2 HIL ask; issue#19.3 reserved for the aligned-vs-naive partition 1-shot wallclock A/B (D-bench-2 follow-up); issue#19.4 reserved for `RUN_SERIAL TRUE` bench harness + strict floor restoration (D-m5 + bench_amcl_converge flake). |
| Map activate phased reload (future) | Active map cell count | Re-prime time scales with map. |
| Phase 5 UE characterization runs (future) | Scenario length | Long scenarios get longer budgets. |
| FreeD smoother fast-recovery path (future, hypothetical) | Burst replay length | If we ever build a "replay-and-re-smooth" path, range-proportional fits. |

## When NOT to use this pattern

- Workload size is **unknown at dispatch**. The pattern requires `(begin, end)` to be known to the caller before fork-join dispatch. If the caller can't compute the size, fall back to a flat deadline tuned for the worst-case mode.
- Cost is **non-linear in workload**. For O(N log N) workloads, `× max(1, N/N_anchor)` is too aggressive on heavy-end and too tight on light-end. Use `× max(1, log(N/N_anchor))` or precompute a piecewise schedule.
- Workload size is **truly fixed across modes**. If the steady-state and heavy modes both share the same N, the optimization is moot — flat deadline is correct.

## Forensic anchor — why this pattern was locked

issue#11 ParallelEvalPool plan §3.7 projected ~190 ms parallel runtime for OneShot first-tick (N=5000); plan §4 set a flat 50 ms hard deadline. Three review passes (Mode-A round 1, round 2, Mode-B) verified each section individually but did not cross-multiply them. Operator HIL caught the mismatch within 1m 49s of deploy on news-pi01 (PR #99): `[pool-degraded] parallel_for join exceeded 50 ms hard deadline (workers=3, range=[0,5000))`.

Fix shipped same-day as commit `bfbf671`:

- `parallel_eval_pool.cpp:22-39` defines `kJoinTimeoutBaseNs = 50 ms`, `kJoinTimeoutAnchorN = 500`.
- `parallel_eval_pool.cpp:351-359` computes `deadline_ns = kJoinTimeoutBaseNs × max(1, range / kJoinTimeoutAnchorN)` per dispatch.
- `[pool-degraded]` stderr message extended to print `N=<range>, base=50 ms × <scale>` so future timeouts are diagnostically richer.

Empirical verification (2026-05-06 16:30 KST, 5-min Phase-0 capture, 2989 scans on post-fix binary): **0 `[pool-degraded]` events** — first-tick dispatches now finish within their proportional deadline, and steady-state dispatches still benefit from the original 50 ms worker-stall guard.

## Test surface implications

- Any unit test that exercises the **deadline timeout fallback** path (e.g., a synthetic fn with `sleep(100ms)` against a 50 ms deadline) MUST use a small range (< anchor) so scale clamps to 1 and the flat-deadline base is preserved. The `tests/test_parallel_eval_pool.cpp::case 6` deliberately uses `range = (0, 16)` for this reason; without that small range the test would either need to sleep proportionally longer (slow CI) or change the deadline measurement.
- Bench tests that stress both N=500 and N=5000 paths get the appropriate deadline naturally — no test code changes needed.

## Cross-link to feedback memory

This pattern emerged from a Mode-A/Mode-B miss documented at `feedback_cross_section_consistency_after_round_2_adds.md`. The pattern is the structural answer; the feedback memory is the process answer. Both should be applied together when a future plan re-encounters the "workload varies by ~10× across modes + dispatch has a hard deadline" shape.
