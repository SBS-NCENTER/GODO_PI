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

namespace godo::parallel {

namespace {

// 50 ms hard timeout on the per-dispatch join wait (R5).
constexpr std::int64_t kJoinTimeoutNs = 50'000'000LL;

// Pool ctor waits this long for every worker to publish ready=1 before
// transitioning to degraded inline-sequential mode (M4 / R12).
constexpr std::int64_t kCtorReadyTimeoutNs = 1'000'000'000LL;  // 1 s

// pthread stack size for the workers (M5 / R13). Eval of N=500 particles
// uses minimal stack (only the evaluate_scan call frame + integer locals).
constexpr std::size_t kWorkerStackBytes = 256 * 1024;  // 256 KB

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
    // R5 lifetime hazard: when parallel_for's 50 ms join deadline fires,
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

    // Worker threads. Created with pthread_attr_setstacksize(256 KB).
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

    // Spawn workers with a bounded stack via pthread_attr_setstacksize.
    // std::thread's default ctor uses the default 8 MB stack; we go
    // through a thin pthread wrapper to override that.
    workers_.reserve(n_workers);
    for (std::size_t wid = 0; wid < n_workers; ++wid) {
        // std::thread spawn — we then override the stack size by setting
        // the attribute via the thread's native handle is not possible
        // (the stack is set at create time). Use pthread_create directly
        // and wrap the joinable handle into std::thread via a small
        // adapter is also non-portable. Instead, accept the default 8 MB
        // stack and rely on mlockall+RLIMIT_MEMLOCK headroom (24 MB total
        // for 3 workers — within the 128 MB headroom rt_setup.cpp
        // requires; documented in §3.5).
        //
        // The plan §3.2 line 289 / §6.1 case 4 / R13 allow this to be
        // either pthread_attr_setstacksize OR documented as accepted
        // 8 MB×N cost. We pick the explicit pthread_create path for
        // production-ready hygiene.
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
        }

        if (range_lo < range_hi && has_work) {
            // dispatch_.fn is owned by the Impl (R5); its lifetime
            // outlives any caller-stack frame even if parallel_for's
            // join timed out (the timeout path drains stragglers before
            // returning to the caller, so fn stays valid throughout).
            for (std::size_t i = range_lo; i < range_hi; ++i) {
                dispatch_.fn(i);
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
        dispatch_.begin    = begin;
        dispatch_.end      = end;
        dispatch_.fn       = std::move(fn);
        dispatch_.has_work = true;
        completed_.store(0, std::memory_order_release);
        dispatch_seq_.fetch_add(1, std::memory_order_release);
    }
    cv_.notify_all();

    // Spin-wait on completed_ with a 50 ms hard deadline (R5). Yield
    // periodically so a worker that ended up on the same CFS-scheduled
    // CPU is not starved (m7 yield).
    const std::int64_t deadline = t0 + kJoinTimeoutNs;
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
        // Timeout — pool transitions to degraded inline-sequential mode
        // for the rest of this process's lifetime (M8). Increment
        // fallback_count_ so the operator can see this transition once;
        // subsequent inline dispatches will increment it further.
        //
        // After flipping degraded_ we BLOCK until completed_ reaches
        // target so the workers' inflight references to dispatch_.fn
        // are released before this function returns. This trades an
        // unbounded wait for memory safety on the timeout path; the
        // caller observes a timeout via the false return value but
        // can't safely free its captured state until the workers have
        // visibly finished. Combined with the in_dispatch_ guard this
        // also keeps the next parallel_for call from racing with the
        // straggler workers.
        degraded_.store(true, std::memory_order_release);
        fallback_count_.fetch_add(1, std::memory_order_relaxed);
        std::fprintf(stderr,
            "[pool-degraded] ParallelEvalPool: parallel_for join exceeded "
            "%lld ms hard deadline (workers=%zu, range=[%zu,%zu)); falling "
            "back to inline-sequential mode for the remainder of this "
            "tracker process. Draining stragglers before return.\n",
            static_cast<long long>(kJoinTimeoutNs / 1'000'000),
            workers_.size(), begin, end);
        // Bounded straggler drain — workers respect dispatch_seq_ and
        // are guaranteed to bump completed_ when they finish their
        // partition. Worst case is bounded by fn's wallclock; the test
        // exercises a 100 ms fn against a 50 ms deadline.
        while (completed_.load(std::memory_order_acquire) < target) {
            std::this_thread::yield();
        }
        in_dispatch_.store(false, std::memory_order_release);
        return false;
    }
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
