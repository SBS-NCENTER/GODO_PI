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
| issue#11 ParallelEvalPool (shipped PR #99) | N=500 (Live steady) | Anchor: `kJoinTimeoutAnchorN = 500`; first-tick N=5000 → 10× scale → 500 ms deadline. **+ K=3 consecutive-misses gate (issue#37, 2026-05-07 KST)** — counter resets on success-completion; isolated jitter under non-RTOS Linux no longer trips the pool. See "consecutive-misses gate companion" section below. |
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

## When isolated jitter is mathematical inevitability — pair the deadline with a consecutive-misses gate (issue#37, 2026-05-07 KST)

A range-proportional hard deadline solves "deadline value matches workload size", but it does not solve "deadline overrun = trip-and-stick is too brittle under non-RTOS scheduling jitter". A 6h12min HIL on news-pi01 build `7a91806` (`.claude/tmp/phase0_results_long_run_2026-05-07_160813.md`) measured exactly 1 isolated `[pool-degraded]` event surrounded by clean dispatches both before and after — textbook isolated-jitter signature — that nevertheless extinguished both the issue#11 evaluate_scan (~2.25×) and issue#19 EDT 2D (~1.43×) lifts for the remaining 4h19min (62 % of the analyzable window).

Operator's framing (locked 2026-05-07 KST): under Raspberry Pi OS / Linux (non-RTOS), one isolated 50 ms scheduling jitter per ~6 hours is **mathematical inevitability** given CFS preemption + kernel softirqs + userspace processes on the unisolated cores 0/1/2. Treating that single inevitability as a 1-Strike-Out is environmentally too brittle.

### The companion pattern

```cpp
constexpr uint32_t kConsecutiveMissesGate = 3;
std::atomic<uint32_t> consecutive_misses_{0};
std::atomic<bool>     degraded_{false};

// Inside the timeout branch (after deadline overrun):
const uint32_t streak = consecutive_misses_.fetch_add(
    1, std::memory_order_relaxed) + 1;
if (streak >= kConsecutiveMissesGate) {
    degraded_.store(true, std::memory_order_release);
    fallback_count_.fetch_add(1, std::memory_order_relaxed);
    log("[pool-degraded] streak reached K=...");
} else {
    log("[pool-miss-streak] streak=N/K, gate not yet tripped...");
}
// R5 lifetime invariant — drain stragglers in BOTH branches.

// Inside the success branch:
consecutive_misses_.store(0, std::memory_order_relaxed);
```

### Worst-case responsiveness math (K=3)

The gate trades trip responsiveness for jitter tolerance. A real worker hang takes K × deadline before the trip fires:

- Live steady-state (N=500, deadline=50 ms): 3 × 50 ms = **150 ms** before degraded fires.
- OneShot first-tick (N=5000, deadline=500 ms): 3 × 500 ms = **1.5 s** before degraded fires.

The 1.5 s first-tick worst case is honest: typical OneShot first-tick wallclock is ~190 ms (PR #99 standalone bench measurement, NOT the deadline), so the user-visible OneShot stays at ~190 ms in the typical path; only a real K=3-streak hang spends up to 1.5 s before the gate fires.

### When the companion applies

Apply the consecutive-misses gate IN ADDITION to the range-proportional deadline when ALL three conditions hold:

1. **Long-run cadence**: the dispatcher runs millions of times across hours (issue#11 ~170 dispatches/sec × 6 h ≈ 3.7M dispatches). At that cadence the probability of one isolated jitter spike per 6 h converges to ~1 under non-RTOS Linux.
2. **Trip-and-stick state machine**: the existing trip handler is sticky for the lifetime of the process. Without the gate, one inevitability ⇒ permanent regression.
3. **Cost of false-positive trip is high**: the trip extinguishes a measurable steady-state lift. issue#11 / issue#19 / future fork-join primitives all have this property; FreeD smoother / yaw lerp / GPIO debounce do not (they are stateless or self-recovering).

### When NOT to use the companion

- **Real-time / safety-critical deadline**: if the deadline IS the contract (e.g., Thread D's 59.94 fps UDP send), do not absorb misses. Trip immediately.
- **Trip cost is low**: if the recovery is automatic (e.g., a re-try loop with a finite retry budget), a streak counter adds complexity without longevity benefit.
- **Workload is bursty rather than steady**: K=3 in-a-row is the natural-language criterion for "pattern, not noise". If dispatches are sparse (e.g., 1 per minute), the streak window is too long to mean anything — switch to a time-windowed variant.

### Counter race semantics (single-writer guarantee)

The counter is single-writer-by-construction in GODO because the pool's `in_dispatch_` CAS guard already serializes dispatches on the same instance to the cold writer thread. `memory_order_relaxed` is correct for both increment and reset because the CAS provides the required happens-before. If a future fork-join primitive lacks this serialization (e.g., per-dispatcher pool variant), the counter must escalate to `memory_order_acq_rel` or wrap in the dispatcher's own mutex.

### Forensic anchor — why this companion was locked

The 11:47:10 KST trip on news-pi01 was a single line in `journalctl`, surrounded by clean dispatches both before and after. K=3 gate would have absorbed it (counter reaches 1, next dispatch succeeds, counter resets to 0). The fix is anchored on the actual data shape we have, not on a hypothetical population. Round-1 plan tried (c1) deadline raise (50 → 80+ ms) which was mathematically un-anchored on n=1; round-2 reversed to (c2) K=3 gate which is also un-anchored on n=1 but has a stronger natural-language prior (3-in-a-row = pattern not noise = the criterion humans use to triage similar systems).

Operator post-deploy HIL acceptance bar: ≥ 6 h Live mode HIL with 0 `[pool-degraded]` events. `[pool-miss-streak]` lines acceptable (and expected — they confirm the gate absorbed isolated jitter without flipping `degraded`).

### Cross-link

- `production/RPi5/CODEBASE.md` invariant `(s)` — full body in production stack's invariants table.
- `SYSTEM_DESIGN.md` §6.6 closing paragraph — backend SSOT.
- `production/RPi5/CODEBASE/2026-W19.md` 2026-05-07 17:33 KST entry — dated change-log.
- `.claude/tmp/phase0_results_long_run_2026-05-07_160813.md` — empirical anchor.
