#include "parallel_eval_pool.hpp"

#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <thread>

#include <pthread.h>
#include <sched.h>

#include "core/time.hpp"

namespace godo::parallel::test_hooks {

// issue#19 — test-only escape hatch for the D1 size-mismatch abort.
// `std::abort()` cannot be exercised directly under doctest (it tears
// down the test runner), so the test fixture sets `s_abort_throws_for_test`
// to swap the production `std::abort()` for a `std::logic_error` throw.
// Production code paths (cold writer, AMCL) NEVER touch this flag — it
// stays `false` and the dispatcher's guard calls `std::abort()` verbatim.
// The build-grep `[edt-scratch-asserted]` matches `std::abort` in source
// text and stays clean (the keyword is still present below, merely
// gated behind a runtime atomic).
std::atomic<bool> s_abort_throws_for_test{false};

}  // namespace godo::parallel::test_hooks

namespace godo::parallel {

namespace {

// Range-proportional hard timeout on the per-dispatch join wait (R5).
//
// `kJoinTimeoutBaseNs` is the deadline for the steady-state Live anchor
// (N=`kJoinTimeoutAnchorN`=500 particles per `Amcl::step`). For larger
// ranges — most importantly the OneShot first-tick / Live re-entry case
// where `seed_global` makes N=5000 — the deadline scales linearly:
//
//   deadline_ns = kJoinTimeoutBaseNs × max(1, range / kJoinTimeoutAnchorN)
//
// → N=500  (steady-state)         → 50 ms
// → N=5000 (first-tick / re-seed) → 500 ms (~2.5× safety over plan §3.7
//                                   first-tick parallel projection ~190 ms)
//
// A flat 50 ms is empirically sufficient for steady-state but causes
// permanent fallback on the very first N=5000 dispatch (plan §3.7 is
// internally inconsistent with a flat deadline). Range-proportional
// preserves the R5 worker-stall guard while honoring §3.7.
constexpr std::int64_t kJoinTimeoutBaseNs  = 50'000'000LL;  // 50 ms
constexpr std::size_t  kJoinTimeoutAnchorN = 500;

// issue#37 — Consecutive-misses gate on the join deadline (K=3).
//
// A single deadline-overrun no longer trips the pool to permanent
// inline-sequential mode (round-1 1-Strike-Out behavior). Operator's
// non-RTOS framing (Raspberry Pi OS / Linux): one isolated 50 ms
// scheduling jitter per ~6 hours is mathematical inevitability under
// CFS preemption + kernel softirqs, NOT signal of a real worker hang.
// Treating that single inevitability as a permanent halt is too
// brittle for the production cadence.
//
// K=3 raises the bar to "3 consecutive deadline-overruns within a
// streak" — pattern, not noise. The counter is shared between
// `parallel_for` (issue#11 evaluate_scan path) and
// `dispatch_with_scratch_erased` (issue#19 EDT 2D path); both
// dispatchers serialize through the same `in_dispatch_` CAS so the
// counter is single-writer by construction. A success-completion
// (parallel join finished within the appropriate deadline) resets the
// counter to 0 — range-aware-by-construction because the deadline
// itself is range-proportional.
//
// Worst-case time-to-trip for a real worker hang:
//   - Live steady-state (N=500, deadline=50 ms):   3 × 50 ms = 150 ms.
//   - OneShot first-tick (N=5000, deadline=500 ms): 3 × 500 ms = 1.5 s.
// Both bounded under the implicit OneShot UX budget (typical first-tick
// wallclock ~190 ms per PR #99 standalone bench; 1.5 s only if 3
// consecutive overruns occur, which has never been observed in HIL).
//
// Empirical anchor: 6h12min HIL on news-pi01 build `7a91806`
// (`.claude/tmp/phase0_results_long_run_2026-05-07_160813.md`) showed
// exactly 1 isolated `[pool-degraded]` event surrounded by clean
// dispatches both before and after — textbook isolated-jitter
// signature that K=3 would have absorbed outright.
constexpr std::uint32_t kConsecutiveMissesGate = 3;

// Pool ctor waits this long for every worker to publish ready=1 before
// transitioning to degraded inline-sequential mode (M4 / R12).
constexpr std::int64_t kCtorReadyTimeoutNs = 1'000'000'000LL;  // 1 s

// Cache-line alignment for the per-dispatch shared atomics (R2 / §3.3).
// Pi 5 Cortex-A76 cache line is 64 bytes.
constexpr std::size_t kCacheLineBytes = 64;

// 1 s decaying-max window: the diag pump samples on every dispatch and the
// max value decays once per 1 s walltime.
constexpr std::int64_t kMaxDecayWindowNs = 1'000'000'000LL;

// Reservoir / latency-sample window. We keep the last N dispatch latencies
// in a wraparound buffer to compute p99 in `snapshot_diag` without locks
// on the diag-publisher side. A 256-slot ring at the steady-state ~170
// dispatches/s gives ~1.5 s of history — matches the 1 Hz publisher.
constexpr std::size_t kLatencyRingDepth = 256;

}  // namespace

struct ParallelEvalPool::Impl {
    explicit Impl(std::vector<int> cpus_to_pin);
    ~Impl();

    bool parallel_for(std::size_t begin,
                      std::size_t end,
                      std::function<void(std::size_t)> fn);

    // issue#19 — Type-erased per-worker-scratch dispatcher. The public
    // template `parallel_for_with_scratch<S>` (header) wraps the fn into
    // `void(size_t, void*)` and supplies a `void* const*` table of
    // per-worker pointers; this routine drives the same fork-join
    // machinery as `parallel_for` but each worker invokes
    // `fn_erased(i, per_worker_ptrs[wid])` per iteration. The deadline
    // is caller-supplied (D2) — pool does NOT auto-scale via the
    // issue#11 N=500 anchor for these dispatches.
    bool dispatch_with_scratch_erased(
        std::size_t                              begin,
        std::size_t                              end,
        void* const*                             per_worker_ptrs,
        std::size_t                              per_worker_count,
        std::function<void(std::size_t, void*)>  fn_erased,
        std::int64_t                             deadline_ns_override);

    ParallelEvalSnapshot snapshot_diag() const noexcept;
    bool degraded_load() const noexcept {
        return degraded_.load(std::memory_order_acquire);
    }
    std::size_t worker_count() const noexcept { return workers_.size(); }

private:
    void worker_body(std::size_t worker_id);

    void record_latency(std::uint32_t us, std::int64_t now_ns) noexcept;
    std::uint32_t compute_p99_us() const noexcept;
    std::uint32_t compute_max_us(std::int64_t now_ns) const noexcept;

    // Per-dispatch shared state — the workers each pick up the same range
    // and fn and partition it by worker_id.
    //
    // R5 lifetime hazard: when parallel_for's range-proportional join
    // deadline fires (kJoinTimeoutBaseNs × max(1, range/kJoinTimeoutAnchorN)),
    // the caller returns to its frame while one or more workers may still
    // be inside fn(). To avoid UB on a caller-stack-allocated lambda we
    // store fn BY VALUE inside the Impl state so its lifetime extends
    // past the caller's frame. Future dispatches overwrite the stored
    // copy under the mutex; pre-overwrite we wait for the prior
    // dispatch's workers to finish (re-checked via in_dispatch_ + the
    // dispatch_seq_ sequence pin in worker_body).
    struct alignas(kCacheLineBytes) DispatchState {
        std::size_t                       begin{0};
        std::size_t                       end{0};
        std::function<void(std::size_t)>  fn;        // owned copy (R5)
        // issue#19 — scratch-mode dispatch path. When `is_scratch_mode`
        // is true, workers invoke `scratch_fn(i, scratch_ptrs[wid])`
        // instead of `fn(i)`. `scratch_ptrs` stores caller-owned per-
        // worker void* pointers; their lifetime is bounded by
        // `dispatch_with_scratch_erased` returning (the timeout path
        // drains stragglers before returning, mirroring `fn`'s lifetime
        // story). The two fn slots are held simultaneously so an in-
        // flight straggler from a prior dispatch keeps its captured
        // signature alive across a mode flip.
        std::function<void(std::size_t, void*)> scratch_fn;
        std::vector<void*>                scratch_ptrs;
        bool                              is_scratch_mode{false};
        bool                              has_work{false};
    };
    DispatchState dispatch_;

    // Synchronization. mutex_ + cv_ wake workers; dispatch_seq_ increments
    // on each new dispatch (per-worker spurious-wakeup predicate, M7);
    // completed_ tracks worker completion for the join spin.
    mutable std::mutex            mutex_;
    std::condition_variable       cv_;
    alignas(kCacheLineBytes)
    std::atomic<std::uint64_t>    dispatch_seq_{0};
    alignas(kCacheLineBytes)
    std::atomic<std::uint32_t>    completed_{0};
    alignas(kCacheLineBytes)
    std::atomic<bool>             stop_{false};

    // Per-worker last-processed dispatch counter. A worker wakes when
    // `last_processed_dispatch[wid] < dispatch_seq_.load()`. Robust
    // against ABA + spurious wakeups (M7).
    std::vector<std::uint64_t> last_processed_dispatch_;

    // Per-worker ready-publish flag. Workers set ready_[wid] = 1 once
    // affinity is bound + their wait loop is active; ctor waits on these
    // with a 1 s timeout (M4).
    std::vector<std::atomic<std::uint8_t>> ready_;

    // CPU pinning vector captured for assert-only purposes (tests inspect
    // via worker_count + degraded()).
    std::vector<int> cpus_to_pin_;

    // Worker threads. DEVIATION from plan §3.2 line 289 / R13: workers use
    // std::thread default 8 MB stack (24 MB total under mlockall(MCL_FUTURE)).
    // The 256 KB cap requires pthread_create + pthread_attr_setstacksize +
    // a join wrapper — deferred. Within rt_setup.cpp's 128 MiB headroom.
    std::vector<std::thread> workers_;

    // Reentry guard: the API contract is single-caller. A second concurrent
    // dispatch from the same instance is a programming error. Detected via
    // a CAS on `in_dispatch_`.
    std::atomic<bool> in_dispatch_{false};

    // Diag counters. dispatch_count and fallback_count are monotonic
    // uint64; degraded_ flips once if the pool transitions to inline mode.
    std::atomic<std::uint64_t> dispatch_count_{0};
    std::atomic<std::uint64_t> fallback_count_{0};
    std::atomic<bool>          degraded_{false};

    // issue#37 — Consecutive deadline-overruns counter for the K-gate.
    // Shared between `parallel_for` (issue#11) and
    // `dispatch_with_scratch_erased` (issue#19) — both dispatchers
    // serialize through the in_dispatch_ CAS, so the counter is
    // single-writer by construction (cold-writer thread). Increments
    // on every overrun; resets to 0 on success-completion. The pool
    // flips `degraded_` only when this reaches kConsecutiveMissesGate.
    // Memory order is relaxed — the in_dispatch_ critical section
    // already serializes dispatchers; no inter-thread happens-before
    // is needed beyond that.
    std::atomic<std::uint32_t> consecutive_misses_{0};

    // Latency history ring + decaying max. Single-writer (cold writer
    // calling `parallel_for`); single-reader (diag publisher calling
    // `snapshot_diag`). The ring is protected by `latency_mtx_` because
    // the diag reader sorts a copy in compute_p99_us; a relaxed atomic
    // ring would be visible-but-torn during sort.
    mutable std::mutex         latency_mtx_;
    std::vector<std::uint32_t> latency_us_;     // wraparound; size kLatencyRingDepth
    std::size_t                latency_count_{0};
    std::size_t                latency_head_{0};
    std::uint32_t              max_us_{0};
    std::int64_t               max_window_start_ns_{0};
};

namespace {

void set_thread_affinity(std::thread::native_handle_type handle, int cpu_id) {
    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cpu_id, &mask);
    const int rc = pthread_setaffinity_np(handle, sizeof(mask), &mask);
    if (rc != 0) {
        std::fprintf(stderr,
            "parallel_eval_pool: pthread_setaffinity_np(cpu=%d) failed: %s\n",
            cpu_id, std::strerror(rc));
    }
}

}  // namespace

ParallelEvalPool::Impl::Impl(std::vector<int> cpus_to_pin)
    : cpus_to_pin_(std::move(cpus_to_pin)) {
    // Hard-veto: CPU 3 is reserved for Thread D.
    for (int cpu : cpus_to_pin_) {
        if (cpu == 3) {
            throw std::invalid_argument(
                "ParallelEvalPool: CPU 3 is reserved for Thread D "
                "(project_cpu3_isolation.md); refusing to pin a worker "
                "to CPU 3.");
        }
        if (cpu < 0) {
            throw std::invalid_argument(
                "ParallelEvalPool: cpus_to_pin entry < 0");
        }
    }

    // Latency ring sized at construction — single allocation. Always
    // initialised (workers=1 inline path also records latencies for
    // observability symmetry with the worker-spawn path).
    latency_us_.assign(kLatencyRingDepth, 0);

    if (cpus_to_pin_.empty()) {
        // workers=1 rollback path — no workers spawned. parallel_for runs
        // fn inline on the caller thread. NOT a degradation.
        return;
    }

    const std::size_t n_workers = cpus_to_pin_.size();
    last_processed_dispatch_.assign(n_workers, 0);
    ready_ = std::vector<std::atomic<std::uint8_t>>(n_workers);
    for (auto& r : ready_) r.store(0, std::memory_order_relaxed);

    // Spawn workers via std::thread (default 8 MB stack — see header field
    // comment for the 256 KB cap deviation). Affinity is set immediately
    // after spawn via the native handle.
    workers_.reserve(n_workers);
    for (std::size_t wid = 0; wid < n_workers; ++wid) {
        workers_.emplace_back([this, wid]() { worker_body(wid); });
        set_thread_affinity(workers_.back().native_handle(),
                            cpus_to_pin_[wid]);
    }

    // Wait up to 1 s for every worker to publish ready=1 (M4).
    const std::int64_t deadline =
        godo::rt::monotonic_ns() + kCtorReadyTimeoutNs;
    bool all_ready = false;
    while (godo::rt::monotonic_ns() < deadline) {
        all_ready = true;
        for (auto& r : ready_) {
            if (r.load(std::memory_order_acquire) == 0) {
                all_ready = false;
                break;
            }
        }
        if (all_ready) break;
        std::this_thread::sleep_for(std::chrono::microseconds(500));
    }
    if (!all_ready) {
        std::fprintf(stderr,
            "[pool-degraded] ParallelEvalPool: ctor timed out waiting for "
            "workers to become ready; falling back to inline-sequential "
            "mode for the lifetime of this tracker process.\n");
        degraded_.store(true, std::memory_order_release);
        // Workers may still be spawning but are unable to do useful work
        // synchronously by the deadline; we still hold their handles for
        // clean teardown in the dtor.
    }
}

ParallelEvalPool::Impl::~Impl() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        stop_.store(true, std::memory_order_release);
        // Bump dispatch_seq_ so any worker waiting on cv_ wakes and
        // observes stop_.
        dispatch_seq_.fetch_add(1, std::memory_order_release);
    }
    cv_.notify_all();
    for (auto& t : workers_) {
        if (t.joinable()) t.join();
    }
}

void ParallelEvalPool::Impl::worker_body(std::size_t wid) {
    // Worker is now affinity-pinned + about to enter the wait loop.
    ready_[wid].store(1, std::memory_order_release);

    while (true) {
        std::uint64_t my_seq    = 0;
        std::size_t   range_lo  = 0;
        std::size_t   range_hi  = 0;
        bool          has_work  = false;
        bool          scratch_mode = false;
        void*         my_scratch = nullptr;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            cv_.wait(lock, [this, wid] {
                return stop_.load(std::memory_order_acquire) ||
                       last_processed_dispatch_[wid] <
                           dispatch_seq_.load(std::memory_order_acquire);
            });
            if (stop_.load(std::memory_order_acquire)) return;
            my_seq = dispatch_seq_.load(std::memory_order_acquire);

            // Snapshot the partition under the mutex — caller may overwrite
            // dispatch_ on the next dispatch only after `in_dispatch_` is
            // released (which itself awaits all `completed_` increments).
            const std::size_t total     = dispatch_.end - dispatch_.begin;
            const std::size_t n_workers = workers_.size();
            std::size_t chunk = (total + n_workers - 1) / n_workers;
            if (chunk < 8 && total >= 8) chunk = 8;
            if (total >= 8) {
                chunk = (chunk + 7) & ~static_cast<std::size_t>(7);
            }
            range_lo = dispatch_.begin + wid * chunk;
            range_hi = (range_lo + chunk < dispatch_.end)
                       ? (range_lo + chunk) : dispatch_.end;
            has_work = dispatch_.has_work;
            scratch_mode = dispatch_.is_scratch_mode;
            if (scratch_mode && wid < dispatch_.scratch_ptrs.size()) {
                my_scratch = dispatch_.scratch_ptrs[wid];
            }
        }

        if (range_lo < range_hi && has_work) {
            // dispatch_.fn / scratch_fn is owned by the Impl (R5); its
            // lifetime outlives any caller-stack frame even if the join
            // timed out (the timeout path drains stragglers before
            // returning to the caller, so fn stays valid throughout).
            if (scratch_mode) {
                for (std::size_t i = range_lo; i < range_hi; ++i) {
                    dispatch_.scratch_fn(i, my_scratch);
                }
            } else {
                for (std::size_t i = range_lo; i < range_hi; ++i) {
                    dispatch_.fn(i);
                }
            }
        }

        last_processed_dispatch_[wid] = my_seq;
        completed_.fetch_add(1, std::memory_order_release);
    }
}

bool ParallelEvalPool::Impl::parallel_for(
    std::size_t                       begin,
    std::size_t                       end,
    std::function<void(std::size_t)>  fn) {
    if (begin >= end) {
        // No-op range. Count as a successful dispatch for symmetry.
        dispatch_count_.fetch_add(1, std::memory_order_relaxed);
        return true;
    }

    // workers=1 rollback path OR degraded inline-sequential mode → run on
    // caller thread. Both paths bump dispatch_count_; only the degraded
    // path bumps fallback_count_.
    if (workers_.empty()) {
        const std::int64_t t0 = godo::rt::monotonic_ns();
        for (std::size_t i = begin; i < end; ++i) fn(i);
        const std::int64_t dt = godo::rt::monotonic_ns() - t0;
        dispatch_count_.fetch_add(1, std::memory_order_relaxed);
        const std::uint32_t us = (dt < 0) ? 0
            : static_cast<std::uint32_t>(dt / 1000);
        record_latency(us, t0);
        return true;
    }
    if (degraded_.load(std::memory_order_acquire)) {
        const std::int64_t t0 = godo::rt::monotonic_ns();
        for (std::size_t i = begin; i < end; ++i) fn(i);
        const std::int64_t dt = godo::rt::monotonic_ns() - t0;
        dispatch_count_.fetch_add(1, std::memory_order_relaxed);
        fallback_count_.fetch_add(1, std::memory_order_relaxed);
        const std::uint32_t us = (dt < 0) ? 0
            : static_cast<std::uint32_t>(dt / 1000);
        record_latency(us, t0);
        return true;
    }

    // Reentry guard. If a second caller is mid-dispatch we reject —
    // the API contract is single-caller (cold writer thread).
    bool expected = false;
    if (!in_dispatch_.compare_exchange_strong(
            expected, true,
            std::memory_order_acq_rel,
            std::memory_order_acquire)) {
        return false;
    }

    const std::int64_t t0 = godo::rt::monotonic_ns();

    // Publish the work range + fn (by value, R5) under the mutex, then
    // bump the sequence counter and notify all workers. fn is moved
    // into dispatch_.fn so its lifetime is owned by the pool, not the
    // caller stack.
    {
        std::lock_guard<std::mutex> lock(mutex_);
        dispatch_.begin           = begin;
        dispatch_.end             = end;
        dispatch_.fn              = std::move(fn);
        dispatch_.is_scratch_mode = false;
        dispatch_.has_work        = true;
        completed_.store(0, std::memory_order_release);
        dispatch_seq_.fetch_add(1, std::memory_order_release);
    }
    cv_.notify_all();

    // Spin-wait on completed_ with a range-proportional hard deadline
    // (R5). Yield periodically so a worker that ended up on the same
    // CFS-scheduled CPU is not starved (m7 yield).
    const std::size_t  range    = end - begin;  // begin < end checked above
    const std::int64_t scale_n  = std::max<std::int64_t>(
        1, static_cast<std::int64_t>(range / kJoinTimeoutAnchorN));
    const std::int64_t deadline_ns = kJoinTimeoutBaseNs * scale_n;
    const std::int64_t deadline    = t0 + deadline_ns;
    const std::uint32_t target  = static_cast<std::uint32_t>(workers_.size());
    bool ok = false;
    while (true) {
        if (completed_.load(std::memory_order_acquire) >= target) {
            ok = true;
            break;
        }
        if (godo::rt::monotonic_ns() >= deadline) {
            break;
        }
        std::this_thread::yield();
    }

    // dispatch_.fn is left in place — workers that didn't finish before
    // the deadline are still inside fn() and need its body to remain
    // valid. The std::function destructor only runs when a future
    // dispatch overwrites it (and that future dispatch waits for
    // in_dispatch_ to be released; see below).

    const std::int64_t dt = godo::rt::monotonic_ns() - t0;
    const std::uint32_t us = (dt < 0) ? 0
        : static_cast<std::uint32_t>(dt / 1000);
    record_latency(us, t0);

    dispatch_count_.fetch_add(1, std::memory_order_relaxed);

    if (!ok) {
        // Deadline overrun — issue#37 K=3 consecutive-misses gate.
        //
        // R5 lifetime invariant (preserved in BOTH the K-1 and K-th
        // paths): we MUST drain stragglers before returning false so
        // the workers' inflight references to dispatch_.fn are
        // released before this function returns. fn lifetime extends
        // past the timeout regardless of the gate decision.
        const std::uint32_t streak = consecutive_misses_.fetch_add(
            1, std::memory_order_relaxed) + 1;
        if (streak >= kConsecutiveMissesGate) {
            // K-th miss — flip degraded for the rest of the process's
            // lifetime, increment fallback_count for the trip itself,
            // and log the [pool-degraded] line. Subsequent dispatches
            // short-circuit at the top of parallel_for and run inline.
            degraded_.store(true, std::memory_order_release);
            fallback_count_.fetch_add(1, std::memory_order_relaxed);
            std::fprintf(stderr,
                "[pool-degraded] ParallelEvalPool: parallel_for join "
                "exceeded %lld ms hard deadline (workers=%zu, "
                "range=[%zu,%zu), N=%zu, base=%lld ms × %lld); "
                "streak reached K=%u, falling back to inline-sequential "
                "mode for the remainder of this tracker process. "
                "Draining stragglers before return.\n",
                static_cast<long long>(deadline_ns / 1'000'000),
                workers_.size(), begin, end, range,
                static_cast<long long>(kJoinTimeoutBaseNs / 1'000'000),
                static_cast<long long>(scale_n),
                kConsecutiveMissesGate);
        } else {
            // K-1 absorbed streak — log [pool-miss-streak] but do NOT
            // flip degraded and do NOT increment fallback_count. The
            // dispatch returns false so the caller can take its
            // sequential fallback branch for THIS tick; future ticks
            // continue to use the parallel path until the streak
            // either reaches K or is broken by a success.
            std::fprintf(stderr,
                "[pool-miss-streak] ParallelEvalPool: parallel_for "
                "join exceeded %lld ms hard deadline (workers=%zu, "
                "range=[%zu,%zu), N=%zu, base=%lld ms × %lld); "
                "streak=%u/%u, gate not yet tripped — draining "
                "stragglers and continuing.\n",
                static_cast<long long>(deadline_ns / 1'000'000),
                workers_.size(), begin, end, range,
                static_cast<long long>(kJoinTimeoutBaseNs / 1'000'000),
                static_cast<long long>(scale_n),
                streak, kConsecutiveMissesGate);
        }
        // Bounded straggler drain — workers respect dispatch_seq_ and
        // are guaranteed to bump completed_ when they finish their
        // partition. Worst case is bounded by fn's wallclock; the
        // tests exercise a 150 ms fn against a 50 ms deadline (1.875×).
        while (completed_.load(std::memory_order_acquire) < target) {
            std::this_thread::yield();
        }
        in_dispatch_.store(false, std::memory_order_release);
        return false;
    }
    // Success — reset the K-gate streak counter so isolated jitter
    // does not accumulate across long quiet windows. Memory ordering
    // matches the increment side (relaxed under the in_dispatch_
    // critical section).
    consecutive_misses_.store(0, std::memory_order_relaxed);
    in_dispatch_.store(false, std::memory_order_release);
    return true;
}

// issue#19 — Type-erased per-worker-scratch dispatcher. Mirrors
// `parallel_for` semantics (R5 fn-by-value, in_dispatch_ guard, latency
// ring) but: (1) workers receive `(i, per_worker_ptrs[wid])`, (2) the
// caller's `deadline_ns_override` REPLACES the issue#11 N=500 anchor —
// pool does not auto-scale (D2). Size-mismatch trips a runtime guard in
// BOTH debug AND release (D1) via `fprintf(stderr) + std::abort()` —
// NOT the NDEBUG-conditional `assert(...)` macro. Build-grep
// `[edt-scratch-asserted]` pins this contract.
bool ParallelEvalPool::Impl::dispatch_with_scratch_erased(
    std::size_t                              begin,
    std::size_t                              end,
    void* const*                             per_worker_ptrs,
    std::size_t                              per_worker_count,
    std::function<void(std::size_t, void*)>  fn_erased,
    std::int64_t                             deadline_ns_override) {
    // D1 — runtime size guard: per_worker.size() must match
    // worker_count() (or be exactly 1 for the workers=0 inline path).
    // Tripping this is a programming error; we abort BOTH in debug and
    // release so the bug surfaces in production too. Pinned by
    // [edt-scratch-asserted] build-grep targeting this function's body.
    const std::size_t expected_workers =
        workers_.empty() ? std::size_t{1} : workers_.size();
    if (per_worker_count != expected_workers) {
        std::fprintf(stderr,
            "[edt-scratch-asserted] dispatch_with_scratch_erased: "
            "per_worker size mismatch — got %zu, expected %zu "
            "(worker_count()=%zu). This is a programming error: caller "
            "MUST size per_worker to worker_count() (or 1 for the "
            "workers=0 rollback path). Aborting.\n",
            per_worker_count, expected_workers, workers_.size());
        // Production: hard abort. Tests: optionally throw so doctest can
        // observe the abort-shaped guard without tearing down the runner.
        if (test_hooks::s_abort_throws_for_test.load(
                std::memory_order_acquire)) {
            throw std::logic_error(
                "[edt-scratch-asserted] size mismatch (test hook)");
        }
        std::abort();
    }

    if (begin >= end) {
        dispatch_count_.fetch_add(1, std::memory_order_relaxed);
        return true;
    }

    // workers=0 rollback path OR pool degraded → run inline on caller
    // thread with per_worker_ptrs[0]. fn_erased is invoked directly
    // without going through the worker queue.
    if (workers_.empty()) {
        const std::int64_t t0 = godo::rt::monotonic_ns();
        for (std::size_t i = begin; i < end; ++i) {
            fn_erased(i, per_worker_ptrs[0]);
        }
        const std::int64_t dt = godo::rt::monotonic_ns() - t0;
        dispatch_count_.fetch_add(1, std::memory_order_relaxed);
        const std::uint32_t us = (dt < 0) ? 0
            : static_cast<std::uint32_t>(dt / 1000);
        record_latency(us, t0);
        return true;
    }
    if (degraded_.load(std::memory_order_acquire)) {
        const std::int64_t t0 = godo::rt::monotonic_ns();
        for (std::size_t i = begin; i < end; ++i) {
            fn_erased(i, per_worker_ptrs[0]);
        }
        const std::int64_t dt = godo::rt::monotonic_ns() - t0;
        dispatch_count_.fetch_add(1, std::memory_order_relaxed);
        fallback_count_.fetch_add(1, std::memory_order_relaxed);
        const std::uint32_t us = (dt < 0) ? 0
            : static_cast<std::uint32_t>(dt / 1000);
        record_latency(us, t0);
        // Caller asked for parallel; degraded path returns false so the
        // caller can take its sequential fallback branch (the iterations
        // already ran inline above, but the caller's contract is "false
        // ⇒ the parallel path didn't fire, run it sequentially yourself
        // if you want bit-equality with sequential"). Mirrors the
        // parallel_for degraded behaviour.
        return false;
    }

    // Reentry guard — same single-caller contract as parallel_for.
    bool expected = false;
    if (!in_dispatch_.compare_exchange_strong(
            expected, true,
            std::memory_order_acq_rel,
            std::memory_order_acquire)) {
        return false;
    }

    const std::int64_t t0 = godo::rt::monotonic_ns();

    // Publish range + scratch fn + per-worker pointers under the mutex.
    {
        std::lock_guard<std::mutex> lock(mutex_);
        dispatch_.begin           = begin;
        dispatch_.end             = end;
        dispatch_.scratch_fn      = std::move(fn_erased);
        dispatch_.scratch_ptrs.assign(per_worker_ptrs,
                                      per_worker_ptrs + per_worker_count);
        dispatch_.is_scratch_mode = true;
        dispatch_.has_work        = true;
        completed_.store(0, std::memory_order_release);
        dispatch_seq_.fetch_add(1, std::memory_order_release);
    }
    cv_.notify_all();

    // Spin-wait on completion against caller-supplied deadline (D2).
    // The fallback default is a literal 50 ms (NOT kJoinTimeoutBaseNs)
    // so EDT semantics stay decoupled from issue#11 evaluate_scan even
    // if the latter's anchor is later tuned. Today's EDT call sites
    // (likelihood_field.cpp:234 and :266) always pass an explicit
    // positive deadline derived from EDT_PARALLEL_DEADLINE_BASE_NS, so
    // this fallback branch is dead code in production — kept for
    // defensive completeness (round-1 m1 fold).
    const std::int64_t deadline_ns =
        (deadline_ns_override > 0) ? deadline_ns_override
                                   : 50'000'000LL;
    const std::int64_t deadline = t0 + deadline_ns;
    const std::uint32_t target  = static_cast<std::uint32_t>(workers_.size());
    bool ok = false;
    while (true) {
        if (completed_.load(std::memory_order_acquire) >= target) {
            ok = true;
            break;
        }
        if (godo::rt::monotonic_ns() >= deadline) {
            break;
        }
        std::this_thread::yield();
    }

    const std::int64_t dt = godo::rt::monotonic_ns() - t0;
    const std::uint32_t us = (dt < 0) ? 0
        : static_cast<std::uint32_t>(dt / 1000);
    record_latency(us, t0);
    dispatch_count_.fetch_add(1, std::memory_order_relaxed);

    if (!ok) {
        // Deadline overrun — issue#37 K=3 consecutive-misses gate.
        // Counter is shared with parallel_for so an EDT miss + 2
        // evaluate_scan misses (or any other interleaving) still
        // trips at K=3 in a row. R5 lifetime invariant preserved in
        // both branches via the straggler-drain below.
        const std::uint32_t streak = consecutive_misses_.fetch_add(
            1, std::memory_order_relaxed) + 1;
        if (streak >= kConsecutiveMissesGate) {
            degraded_.store(true, std::memory_order_release);
            fallback_count_.fetch_add(1, std::memory_order_relaxed);
            std::fprintf(stderr,
                "[pool-degraded] dispatch_with_scratch_erased: scratch "
                "join exceeded %lld ms caller-specified deadline "
                "(workers=%zu, range=[%zu,%zu)); streak reached K=%u, "
                "falling back to inline-sequential mode for the "
                "remainder of this tracker process. Draining stragglers "
                "before return.\n",
                static_cast<long long>(deadline_ns / 1'000'000),
                workers_.size(), begin, end,
                kConsecutiveMissesGate);
        } else {
            std::fprintf(stderr,
                "[pool-miss-streak] dispatch_with_scratch_erased: "
                "scratch join exceeded %lld ms caller-specified "
                "deadline (workers=%zu, range=[%zu,%zu)); streak=%u/%u, "
                "gate not yet tripped — draining stragglers and "
                "continuing.\n",
                static_cast<long long>(deadline_ns / 1'000'000),
                workers_.size(), begin, end,
                streak, kConsecutiveMissesGate);
        }
        // Bounded straggler drain — mirrors parallel_for timeout path so
        // caller-side per_worker / fn_erased lifetimes are safe to free
        // after this returns false.
        while (completed_.load(std::memory_order_acquire) < target) {
            std::this_thread::yield();
        }
        in_dispatch_.store(false, std::memory_order_release);
        return false;
    }
    // Success — reset the K-gate streak counter (mirrors parallel_for).
    consecutive_misses_.store(0, std::memory_order_relaxed);
    in_dispatch_.store(false, std::memory_order_release);
    return true;
}

void ParallelEvalPool::Impl::record_latency(std::uint32_t us,
                                            std::int64_t now_ns) noexcept {
    std::lock_guard<std::mutex> lock(latency_mtx_);
    latency_us_[latency_head_] = us;
    latency_head_ = (latency_head_ + 1) % latency_us_.size();
    if (latency_count_ < latency_us_.size()) ++latency_count_;
    // Decaying max — reset the running max once the window expires.
    if (max_window_start_ns_ == 0 ||
        (now_ns - max_window_start_ns_) > kMaxDecayWindowNs) {
        max_window_start_ns_ = now_ns;
        max_us_ = us;
    } else if (us > max_us_) {
        max_us_ = us;
    }
}

std::uint32_t ParallelEvalPool::Impl::compute_p99_us() const noexcept {
    // Snapshot the ring under the lock, then sort + percentile. Worst-case
    // 256 entries × 4 B = 1 KB on the diag-publisher's stack — within
    // budget; no heap. Sort is std::nth_element to avoid full sort.
    std::uint32_t buf[kLatencyRingDepth];
    std::size_t   n = 0;
    {
        std::lock_guard<std::mutex> lock(latency_mtx_);
        n = latency_count_;
        for (std::size_t i = 0; i < n; ++i) {
            buf[i] = latency_us_[i];  // unordered fine; we sort below
        }
    }
    if (n == 0) return 0;
    // Simple insertion sort for small n (kLatencyRingDepth is small).
    for (std::size_t i = 1; i < n; ++i) {
        std::uint32_t v = buf[i];
        std::size_t j = i;
        while (j > 0 && buf[j - 1] > v) { buf[j] = buf[j - 1]; --j; }
        buf[j] = v;
    }
    // p99 index = ceil(0.99 * n) - 1
    std::size_t idx = (n * 99 + 99) / 100;
    if (idx == 0) idx = 0;
    else --idx;
    if (idx >= n) idx = n - 1;
    return buf[idx];
}

std::uint32_t ParallelEvalPool::Impl::compute_max_us(
    std::int64_t now_ns) const noexcept {
    std::lock_guard<std::mutex> lock(latency_mtx_);
    if (max_window_start_ns_ == 0 ||
        (now_ns - max_window_start_ns_) > kMaxDecayWindowNs) {
        return 0;
    }
    return max_us_;
}

ParallelEvalSnapshot ParallelEvalPool::Impl::snapshot_diag() const noexcept {
    ParallelEvalSnapshot s{};
    s.dispatch_count    = dispatch_count_.load(std::memory_order_relaxed);
    s.fallback_count    = fallback_count_.load(std::memory_order_relaxed);
    s.published_mono_ns = 0;  // pump fills this at store time
    s.p99_us            = compute_p99_us();
    s.max_us            = compute_max_us(godo::rt::monotonic_ns());
    s.valid             = (s.dispatch_count > 0) ? 1 : 0;
    s.degraded          = degraded_.load(std::memory_order_acquire) ? 1 : 0;
    return s;
}

// ----- Public surface (forwards to Impl) ------------------------------

ParallelEvalPool::ParallelEvalPool(std::vector<int> cpus_to_pin)
    : impl_(std::make_unique<Impl>(std::move(cpus_to_pin))) {}

ParallelEvalPool::~ParallelEvalPool() = default;

bool ParallelEvalPool::parallel_for(
    std::size_t                       begin,
    std::size_t                       end,
    std::function<void(std::size_t)>  fn) {
    return impl_->parallel_for(begin, end, std::move(fn));
}

bool ParallelEvalPool::dispatch_with_scratch_erased(
    std::size_t                              begin,
    std::size_t                              end,
    void* const*                             per_worker_ptrs,
    std::size_t                              per_worker_count,
    std::function<void(std::size_t, void*)>  fn_erased,
    std::int64_t                             deadline_ns_override) {
    return impl_->dispatch_with_scratch_erased(
        begin, end, per_worker_ptrs, per_worker_count,
        std::move(fn_erased), deadline_ns_override);
}

ParallelEvalSnapshot ParallelEvalPool::snapshot_diag() const noexcept {
    return impl_->snapshot_diag();
}

bool ParallelEvalPool::degraded() const noexcept {
    return impl_->degraded_load();
}

std::size_t ParallelEvalPool::worker_count() const noexcept {
    return impl_->worker_count();
}

}  // namespace godo::parallel
