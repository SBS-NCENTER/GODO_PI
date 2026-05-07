#pragma once

// issue#11 — Fork-join particle eval pool.
//
// Public API for the cold-side worker pool that accelerates AMCL
// `evaluate_scan` over N=500 particles by partitioning the index range
// across worker threads pinned to CPU {0, 1, 2}. Joined per dispatch so
// cascade-jitter is structurally impossible (no inter-tick worker state).
//
// Design (plan §3.2):
//   - Single-caller contract — only the cold writer thread calls
//     `parallel_for`. Concurrent dispatches from the same instance are
//     rejected.
//   - Pimpl — std::mutex + std::condition_variable live in the .cpp;
//     this header only drags <cstddef> + <functional> + <vector>.
//     cold_writer.cpp can include this header and remain M1-clean
//     (build.sh [m1-no-mutex] grep is line-based on cold_writer.cpp
//     source text only; header includes are not expanded).
//   - Pool worker affinity is explicit through the ctor's
//     `cpus_to_pin` vector; CPU 3 is a hard-veto invariant
//     (project_cpu3_isolation.md). Empty vector ⇒ no workers spawned;
//     `parallel_for` runs fn on the caller thread (workers=1
//     rollback path; `degraded()` reports false because empty-vector
//     is a configured choice, not a degradation).
//   - Ctor blocks ≤ 1 s on per-worker `ready` atomics; on timeout the
//     pool boots in degraded inline-sequential mode (M4 / R12).
//
// CODEBASE.md invariant (s) summarises the ownership + M1-spirit
// articulation; the body of that invariant lives in the master
// CODEBASE.md.

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <type_traits>
#include <vector>

namespace godo::parallel {

namespace test_hooks {
// issue#19 — test-only flag. When set true by a test fixture, the
// dispatcher's D1 size-mismatch guard throws `std::logic_error` instead
// of calling `std::abort()` (which would tear down the doctest runner).
// Production code MUST NOT touch this. Pinned by build-grep
// [edt-scratch-asserted] which still requires the verbatim `std::abort`
// keyword in parallel_eval_pool.cpp.
extern std::atomic<bool> s_abort_throws_for_test;
}  // namespace test_hooks

// Snapshot of the pool's runtime state, sampled by the diag publisher.
// Layout pinned to 32 B for Seqlock<T> safety (8-aligned + trivially
// copyable). Mirrors the `format_ok_parallel_eval` field order in
// uds/json_mini.cpp.
//
// The published_mono_ns is appended at publish time by the diag pump
// (mirroring JitterSnapshot's pattern); kept out of the pool's internal
// snapshot because the pool itself doesn't observe wall-clock publish
// cadence.
struct ParallelEvalSnapshot {
    std::uint64_t dispatch_count;       // total `parallel_for` calls since boot
    std::uint64_t fallback_count;       // total inline-sequential fallbacks
    std::uint64_t published_mono_ns;    // monotonic_ns at diag-publisher store time (set by pump)
    std::uint32_t p99_us;               // pool-side dispatch+join wallclock p99 (µs)
    std::uint32_t max_us;               // decaying max over a 1 s window (µs)
    std::uint8_t  valid;                // 0 = no publish yet, 1 = populated
    std::uint8_t  degraded;             // 1 = ctor timed out / sequential inline; 0 = active
    std::uint8_t  _pad[6];              // align trailing to 8 B
};

static_assert(sizeof(ParallelEvalSnapshot) == 40,
              "ParallelEvalSnapshot layout pinned at 40 B");
static_assert(alignof(ParallelEvalSnapshot) == 8,
              "ParallelEvalSnapshot must be 8-aligned");
static_assert(std::is_trivially_copyable_v<ParallelEvalSnapshot>,
              "ParallelEvalSnapshot must be trivially copyable for Seqlock payload");

class ParallelEvalPool {
public:
    // Construct the pool and spawn N workers, where N == cpus_to_pin.size().
    //
    // Mapping from the TOML key `amcl.parallel_eval_workers` (main.cpp
    // owns the translation; pool API stays domain-agnostic):
    //   1 → cpus_to_pin = {}        (no workers; `parallel_for` runs fn on
    //                                caller thread; `degraded()` = false)
    //   2 → cpus_to_pin = {0, 1}
    //   3 → cpus_to_pin = {0, 1, 2}
    //
    // Hard-veto: CPU 3 must NEVER appear in the vector
    // (project_cpu3_isolation.md). The ctor asserts this at runtime.
    //
    // Workers are created with a 256 KB stack via pthread_attr_setstacksize
    // (M5 / R13) so mlockall(MCL_FUTURE) costs 768 KB total (vs 24 MB at
    // the default 8 MB stacks). Affinity is set via pthread_setaffinity_np
    // BEFORE the worker enters its loop; the test asserts via
    // pthread_getaffinity_np that exactly one CPU bit is set per worker.
    //
    // Ctor blocks ≤ 1 s on per-worker `ready` atomics. On timeout the pool
    // transitions to degraded inline-sequential mode (logs once to stderr,
    // sets `degraded() = true`); subsequent `parallel_for` calls run fn on
    // the caller thread and increment `fallback_count`. Permanent until
    // tracker restart.
    explicit ParallelEvalPool(std::vector<int> cpus_to_pin);

    ~ParallelEvalPool();

    ParallelEvalPool(const ParallelEvalPool&)            = delete;
    ParallelEvalPool& operator=(const ParallelEvalPool&) = delete;
    ParallelEvalPool(ParallelEvalPool&&)                 = delete;
    ParallelEvalPool& operator=(ParallelEvalPool&&)      = delete;

    // Run `fn(i)` for each i in [begin, end). Workers partition the range
    // contiguously, aligned to 8 elements (one cache line of 8 doubles)
    // when end-begin >= 8 (R2 / §3.3 false-sharing).
    //
    // Caller must be a single thread (the cold writer). A second concurrent
    // `parallel_for` from the same instance returns false immediately.
    //
    // Range-proportional hard deadline (50 ms × max(1, range/500)) on
    // the join wait (R5). On a deadline overrun the function returns
    // false and drains stragglers before returning so caller-stack
    // captures stay live. The pool transitions to degraded only after
    // `kConsecutiveMissesGate=3` consecutive deadline-overruns (issue#37
    // K-gate); intermediate K-1 overruns log a `[pool-miss-streak]` line
    // and absorb the jitter without flipping `degraded`. The counter
    // resets on the first success-completion. `fallback_count` increments
    // only on the K-th miss (the trip itself) and on each subsequent
    // inline-sequential dispatch. The caller is expected to fall back to
    // sequential evaluation on any false return regardless of K state.
    //
    // When the pool was constructed with an empty `cpus_to_pin` vector the
    // call runs fn sequentially on the caller thread and returns true with
    // `fallback_count` unchanged (workers=1 rollback path; not a
    // degradation).
    bool parallel_for(std::size_t                       begin,
                      std::size_t                       end,
                      std::function<void(std::size_t)>  fn);

    // issue#19 — Per-worker scratch variant.
    //
    // Run `fn(i, per_worker[wid])` for each i in [begin, end). Each worker
    // receives the SAME `Scratch&` for every iteration it executes within
    // one dispatch (so scratch can be re-used between iterations on the
    // same worker), but workers see DISJOINT references — no synchronization
    // is required inside fn().
    //
    // Caller MUST pass `per_worker.size() == worker_count()`. A mismatch
    // is a programming error and trips a runtime guard in BOTH debug AND
    // release builds (`fprintf(stderr) + std::abort()` rather than the
    // NDEBUG-conditional `assert(...)` macro). D1 is explicit: production
    // builds must trip too. Pinned by build-grep `[edt-scratch-asserted]`.
    //
    // `deadline_ns_override` REPLACES the issue#11 N=500-anchored auto-scale
    // for this dispatch — it is a hard caller-specified deadline, NOT
    // optional, NOT auto-scaled. EDT callers compute their own scale (see
    // `localization/likelihood_field.cpp` against `EDT_PARALLEL_*`
    // constants in `core/constants.hpp`); the pool does not interpret the
    // value. D2.
    //
    // Returns true on full completion of all iterations. Returns false on
    // (a) size mismatch (after the abort lands), (b) pool degraded
    // mid-call (per-pass false-return, drains stragglers before returning),
    // (c) deadline overrun (drains stragglers before returning + flips
    // `degraded` sticky for the rest of the process).
    //
    // workers=0 path: when the pool was constructed with an empty
    // cpus_to_pin, runs fn inline on the caller thread with
    // `per_worker[0]` (asserts per_worker.size() == 1).
    //
    // ---- Type-erasure rationale (Mode-A m3) ----
    // The header surface is a non-virtual function template; the body
    // forwards into a non-template private dispatcher in the .cpp. The
    // dispatcher accepts `void**` per-worker pointers + a
    // `std::function<void(size_t, void*)>` so that the pimpl Impl (and
    // its `<mutex>` / `<condition_variable>` private members) stay sealed
    // inside the .cpp. Future Scratch types do NOT cascade a header
    // re-include into every TU that uses the pool. Per-call overhead is
    // one small `std::vector<void*>` (≤ 24 B at N=3) plus one
    // `std::function` construction per dispatch — NOT per iteration. The
    // worker hot loop dereferences the per-worker pointer directly inside
    // the wrapped fn lambda; reviewers must verify the Impl never
    // re-wraps `fn_erased` per-iteration.
    template <typename Scratch>
    bool parallel_for_with_scratch(
        std::size_t                                  begin,
        std::size_t                                  end,
        std::vector<Scratch>&                        per_worker,
        std::function<void(std::size_t, Scratch&)>   fn,
        std::int64_t                                 deadline_ns_override) {
        // Build the per-worker void* table on the caller stack
        // (size N ≤ 3 in production; small_vector-like via the std::vector
        // single allocation). Stable address: per_worker.data() must not
        // be invalidated for the duration of dispatch_with_scratch_erased.
        std::vector<void*> ptr_table(per_worker.size());
        for (std::size_t i = 0; i < per_worker.size(); ++i) {
            ptr_table[i] = static_cast<void*>(&per_worker[i]);
        }
        // Wrap fn into the type-erased dispatcher signature once per call.
        std::function<void(std::size_t, void*)> erased =
            [fn](std::size_t i, void* p) {
                fn(i, *static_cast<Scratch*>(p));
            };
        return dispatch_with_scratch_erased(
            begin, end, ptr_table.data(), per_worker.size(),
            std::move(erased), deadline_ns_override);
    }

    // Snapshot the diag counters. Safe to call from any thread; uses
    // atomic loads only.
    [[nodiscard]] ParallelEvalSnapshot snapshot_diag() const noexcept;

    // True if the pool is operating in degraded inline-sequential mode
    // (ctor timeout OR `kConsecutiveMissesGate=3` consecutive
    // deadline-overruns on the range-proportional 50 ms × max(1, range/500)
    // join wait — issue#37 K-gate). Sticky for the lifetime of the process
    // once it flips.
    [[nodiscard]] bool degraded() const noexcept;

    // Number of workers spawned (== cpus_to_pin.size() at construction;
    // 0 in the workers=1 rollback path).
    [[nodiscard]] std::size_t worker_count() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;

    // issue#19 — Type-erased dispatcher for `parallel_for_with_scratch<S>`.
    // Public-API surface is the template above; this private function is
    // the actual implementation seam. Defined in parallel_eval_pool.cpp.
    bool dispatch_with_scratch_erased(
        std::size_t                              begin,
        std::size_t                              end,
        void* const*                             per_worker_ptrs,
        std::size_t                              per_worker_count,
        std::function<void(std::size_t, void*)>  fn_erased,
        std::int64_t                             deadline_ns_override);

    // Befriend the public template wrapper so it can reach the private
    // dispatcher above. (The template lives in this class scope so
    // implicit access is sufficient — no friend declaration needed.)
};

}  // namespace godo::parallel
