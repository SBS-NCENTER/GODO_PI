---
name: Phase-0 trim instrumentation pattern (env-var + thread-local + stderr emit)
description: Re-usable design pattern for capturing per-component wallclock timing inside the cold path WITHOUT building a full ship-vs-wire surface. env-var-gated `static const bool` latch (read once at static init), thread-local accumulators per scan, fprintf-to-stderr at scan-end captured by journald. Single-PR-revert clean. Pattern shipped in PR #96 (issue#11 P4-2-11-0); empirically validated under load (49/49 ctest + zero-overhead path verified).
type: project
---

## Pattern shape

When you need to measure per-component timing inside production code (cold path or otherwise) and the goal is **temporary, removable, no operator UI**, use this trim instrumentation pattern. ~70 LOC + 1 test, ~1 hour Writer.

### Required pieces

1. **POD out-param struct** in a shared header (e.g., `core/rt_types.hpp`). Pure data fields, `static_assert(sizeof == N)`, `is_trivially_copyable_v` pin. NOT a Seqlock payload — out-param shape only.

2. **Function overload(s) accepting `const StructName*` (default `nullptr`)** at the leaf measurement seam. When non-null, capture `monotonic_ns()` deltas around each stage. Existing call sites delegate with `nullptr` (zero-overhead path preserved).

3. **Anonymous-namespace env latch** in the orchestrator TU (e.g., `cold_writer.cpp`):
   ```cpp
   namespace {
   const bool kFeatureOn = []() {
       const char* env = std::getenv("FEATURE_NAME");
       return env != nullptr && env[0] == '1' && env[1] == '\0';
   }();
   }
   ```
   Read once at static init, immutable thereafter. Strict equality to `"1"` (no false positives from `"10"` / `"true"`).

4. **Thread-local accumulators** for per-scan sums (across multiple inner-loop calls):
   ```cpp
   thread_local std::int64_t g_metric_sum = 0;
   thread_local InnerStruct  g_inner_sum{};
   thread_local std::int64_t g_scan_seq = 0;
   ```
   Single-thread cold writer is the SOLE writer; thread-local is safe.

5. **Two helpers** — `reset_and_stamp_start(int64_t& scan_start_ns)` (zero accums + capture mono ns) + `emit(label, scan_start_ns, iters)` (fprintf to stderr with all slices + total + path label).

6. **Wire-in to all wrappers**: `if (kFeatureOn) reset_and_stamp_start(scan_start_ns);` at top, `if (kFeatureOn) emit("path_label", scan_start_ns, result.iterations);` at bottom.

7. **One test** (sentinel pre-fill, deterministic — NOT timing-based): pre-fill the out-param with a sentinel value (e.g., `0x0DEADBEE0DEADBEELL`), call the new overload, assert all fields strictly < sentinel (i.e., were overwritten). Plus nullptr-no-write contract test.

### Output format

Single fprintf line per scan, kernel-buffered to journald:
```
FEATURE path=<label> scan=<seq> iters=<K> stage1_ns=<N> stage2_ns=<N> ... total_ns=<N>
```

Operator captures via:
```bash
sudo systemctl edit <service>
# add Environment="FEATURE_NAME=1"
sudo systemctl restart <service>
# run scenario
sudo journalctl -u <service> -S '<window>' | grep FEATURE > results.log
```

## When to use this pattern

- **Goal**: measurement input for a downstream architectural decision (e.g., issue#11 Mode-A round 2 needs per-component breakdown).
- **Operator UX**: stderr/journalctl is acceptable (operator already SSHs to the host for ops; structured JSON via curl is overkill for a one-off capture).
- **Lifetime**: TEMPORARY (revert after data absorbed). If the diagnostic proves valuable for repeat use, promote to permanent ship-vs-wire (Seqlock + UDS getter + webctl endpoint + invariant) — purely additive, no rewrite needed.

## When NOT to use this pattern

- Operator wants the data on the SPA in real time → go straight to ship-vs-wire (Seqlock + UDS + webctl).
- Permanent diagnostic that multiple future investigations will need → ship-vs-wire from day 1.
- Need rolling p50/p95/p99 windows (not just latest) → Seqlock + dedicated worker thread for percentile computation.
- Hot path / RT-critical timing → fprintf has unbounded latency; use lock-free ring buffer + dedicated diag publisher seam.

## Promotion path (trim → permanent)

If the trim instrumentation proves useful enough to retain after data absorption:

1. Add `BreakdownSnapshot` Seqlock payload (96 B padded, `static_assert(sizeof == 96)`).
2. Allocate `Seqlock<BreakdownSnapshot> seq` in `main.cpp` next to other diag seqlocks.
3. Replace fprintf at scan-end with `seq.store(snapshot)`.
4. Add UDS handler `get_breakdown` + `format_ok_breakdown` JSON formatter.
5. Add webctl `/api/system/breakdown` endpoint + protocol mirror + tests.
6. Add new build-grep `[breakdown-publisher-grep]` enforcing single-writer at the seqlock store seam.
7. Promote the build-grep to invariant `(s)` in master `production/RPi5/CODEBASE.md`.

The trim foundation (POD struct + new overload + thread-local accumulators) stays. Promotion is purely additive.

## Why this matters (twenty-seventh-session origin story)

issue#11 (Live pipelined-parallel multi-thread) plan was REJECTed at Mode-A round 1 for unverified per-component compute times. Round 2 needed concrete numbers — eval vs LF rebuild vs jitter vs normalize vs resample.

Original Phase-0 plan inflated the upstream "~30 LOC, removable" budget into a ~500 LOC + 11 test full-stack ship-vs-wire surface (lane (ii)). Reviewer's Mode-A round 1 flagged the contradiction (TEMPORARY label + permanent surface). Operator decision-locked **lane (i) trim** — this pattern was the result.

PR #96 (`53453f5`) shipped 6 files / +390/-6 LOC including the 177 LOC test file. Production code delta was ~213 LOC. Single Writer pass. Mode-B APPROVE zero-blocker. HIL captured 2,716 scans, locked in p50 = 136.15 ms with 0.5% cross-capture variance. Round 2 input secured.

## Cross-references

- Production code: `production/RPi5/src/core/rt_types.hpp` (Phase0InnerBreakdown), `production/RPi5/src/localization/amcl.{hpp,cpp}` (overloads), `production/RPi5/src/localization/cold_writer.cpp` (env latch + helpers + wire-in).
- Test: `production/RPi5/tests/test_phase0_env.cpp` (sentinel pre-fill).
- Capture results: `.claude/tmp/phase0_results_*.md` (3 files, 2716 scans).
- Plan trail: `.claude/tmp/plan_issue_11_phase0_instrumentation.md` (Round 1 + Mode-A r1 fold + Trim path resolution).
- Related: `project_pipelined_compute_pattern.md` (issue#11 reference design), `project_live_mode_cpu_thrashing_2026-05-05.md` (empirical macroscopic baseline).
