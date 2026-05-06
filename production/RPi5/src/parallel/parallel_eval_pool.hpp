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

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <type_traits>
#include <vector>

namespace godo::parallel {

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
    // 50 ms hard timeout on the join wait (R5). On timeout the function
    // returns false, the pool is marked degraded (permanent until restart),
    // and `fallback_count` increments. The caller is expected to fall back
    // to sequential evaluation for that step.
    //
    // When the pool was constructed with an empty `cpus_to_pin` vector the
    // call runs fn sequentially on the caller thread and returns true with
    // `fallback_count` unchanged (workers=1 rollback path; not a
    // degradation).
    bool parallel_for(std::size_t                       begin,
                      std::size_t                       end,
                      std::function<void(std::size_t)>  fn);

    // Snapshot the diag counters. Safe to call from any thread; uses
    // atomic loads only.
    [[nodiscard]] ParallelEvalSnapshot snapshot_diag() const noexcept;

    // True if the pool is operating in degraded inline-sequential mode
    // (ctor timeout OR a `parallel_for` join exceeded the 50 ms deadline).
    [[nodiscard]] bool degraded() const noexcept;

    // Number of workers spawned (== cpus_to_pin.size() at construction;
    // 0 in the workers=1 rollback path).
    [[nodiscard]] std::size_t worker_count() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace godo::parallel
