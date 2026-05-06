#include "diag_publisher.hpp"

#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <exception>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "core/time.hpp"
#include "rt/jitter_stats.hpp"

namespace godo::rt {

namespace {

constexpr std::int64_t kPublishIntervalNs =
    static_cast<std::int64_t>(godo::constants::JITTER_PUBLISH_INTERVAL_MS) *
    1'000'000LL;

// Compute the AMCL iteration Hz over the publisher's tick window using
// two-tick differencing. `prev_count` / `prev_last_ns` are the publisher's
// stored state from the prior tick; on the first call they are 0.
//
// Mode-A M2 + plan §"Scan-rate publication": when fewer than 2 records
// have been observed (count < 2) OR last_ns hasn't advanced, we hold
// rate at 0.0 and valid=0. This keeps the SPA's "Idle" display honest:
// a parked LiDAR + paused cold writer ⇒ rate=0 + a Mode chip showing
// Idle, not "1 sample over a 1 s window".
void compute_amcl_rate(const AmclRateRecord& cur,
                       std::uint64_t         prev_count,
                       std::uint64_t         prev_last_ns,
                       std::int64_t          publish_mono_ns,
                       AmclIterationRate&    out) noexcept {
    out.last_iteration_mono_ns = cur.last_ns;
    out.total_iteration_count  = cur.count;
    out.published_mono_ns      = static_cast<std::uint64_t>(publish_mono_ns);
    out._pad0[0] = out._pad0[1] = out._pad0[2] = out._pad0[3] = 0;
    out._pad0[4] = out._pad0[5] = out._pad0[6] = 0;

    if (cur.count < 2 || cur.last_ns <= prev_last_ns) {
        out.hz    = 0.0;
        out.valid = 0;
        return;
    }
    const std::uint64_t window_count =
        (cur.count >= prev_count) ? (cur.count - prev_count) : 0;
    if (window_count == 0) {
        out.hz    = 0.0;
        out.valid = 0;
        return;
    }
    const double window_s =
        static_cast<double>(cur.last_ns - prev_last_ns) / 1e9;
    out.hz    = (window_s > 0.0)
                ? static_cast<double>(window_count) / window_s
                : 0.0;
    out.valid = (out.hz > 0.0) ? std::uint8_t{1} : std::uint8_t{0};
}

void publish_one_tick(
    JitterRing&                                              ring,
    AmclRateAccumulator&                                     accum,
    Seqlock<JitterSnapshot>&                                 jitter_seq,
    Seqlock<AmclIterationRate>&                              amcl_rate_seq,
    Seqlock<godo::parallel::ParallelEvalSnapshot>*           parallel_eval_seq,
    const ParallelEvalSnapshotGetter&                        pool_getter,
    std::uint64_t&                                           prev_count_inout,
    std::uint64_t&                                           prev_last_ns_inout,
    std::int64_t                                             now_ns) {
    // --- jitter --------------------------------------------------------
    // Stack-allocated scratch — no heap. Sized to JITTER_RING_DEPTH so
    // sort + percentile work on the full snapshot.
    static_assert(godo::constants::JITTER_RING_DEPTH > 0,
                  "JITTER_RING_DEPTH must be positive");
    std::array<std::int64_t,
               static_cast<std::size_t>(godo::constants::JITTER_RING_DEPTH)>
        scratch{};
    std::size_t copied = 0;
    ring.snapshot(scratch.data(), copied);

    JitterSnapshot js{};
    compute_summary(scratch.data(), copied, js);
    js.published_mono_ns = static_cast<std::uint64_t>(now_ns);
    jitter_seq.store(js);

    // --- AMCL iteration rate -------------------------------------------
    const AmclRateRecord cur = accum.snapshot();
    AmclIterationRate ar{};
    compute_amcl_rate(cur, prev_count_inout, prev_last_ns_inout, now_ns, ar);
    amcl_rate_seq.store(ar);
    prev_count_inout   = cur.count;
    prev_last_ns_inout = cur.last_ns;

    // --- Parallel eval pool diag (issue#11) ----------------------------
    // Pump samples once per publisher tick (1 Hz). The pool's
    // snapshot_diag() is lock-protected internally + cheap; we layer the
    // wallclock published_mono_ns on top here so consumers see the same
    // shape as JitterSnapshot.
    if (parallel_eval_seq != nullptr && pool_getter) {
        godo::parallel::ParallelEvalSnapshot ps = pool_getter();
        ps.published_mono_ns = static_cast<std::uint64_t>(now_ns);
        parallel_eval_seq->store(ps);
    }
}

}  // namespace

void run_diag_publisher_with_clock(
    JitterRing&                                              ring,
    AmclRateAccumulator&                                     accum,
    Seqlock<JitterSnapshot>&                                 jitter_seq,
    Seqlock<AmclIterationRate>&                              amcl_rate_seq,
    Seqlock<godo::parallel::ParallelEvalSnapshot>*           parallel_eval_seq,
    ParallelEvalSnapshotGetter                               pool_getter,
    NowProvider                                              now_ns,
    SleepFor                                                 sleep_for) noexcept {
    std::uint64_t prev_count   = 0;
    std::uint64_t prev_last_ns = 0;

    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        try {
            const std::int64_t t = now_ns();
            publish_one_tick(ring, accum, jitter_seq, amcl_rate_seq,
                             parallel_eval_seq, pool_getter,
                             prev_count, prev_last_ns, t);
        } catch (const std::exception& e) {
            // TM9: a percentile-math throw logs and exits the publisher;
            // the seqlocks keep their last valid snapshot. Other threads
            // are unaffected.
            std::fprintf(stderr,
                "diag_publisher: tick body threw: %s — exiting publisher.\n",
                e.what());
            return;
        }
        if (!sleep_for(kPublishIntervalNs)) {
            return;  // sleep cancelled (e.g., test-driven exit)
        }
    }
}

void run_diag_publisher(
    JitterRing&                                              ring,
    AmclRateAccumulator&                                     accum,
    Seqlock<JitterSnapshot>&                                 jitter_seq,
    Seqlock<AmclIterationRate>&                              amcl_rate_seq,
    Seqlock<godo::parallel::ParallelEvalSnapshot>&           parallel_eval_seq,
    godo::parallel::ParallelEvalPool&                        pool) noexcept {
    auto now_provider = []() -> std::int64_t {
        return godo::rt::monotonic_ns();
    };
    auto sleep_callable = [](std::int64_t ns) -> bool {
        timespec req{};
        req.tv_sec  = static_cast<std::time_t>(ns / 1'000'000'000LL);
        req.tv_nsec = static_cast<long>(ns % 1'000'000'000LL);
        // Loop on EINTR so SIGTERM-bound signals don't short-circuit
        // the publisher's interval; the outer loop polls g_running and
        // exits cleanly on the next iteration.
        for (;;) {
            const int rc = ::nanosleep(&req, &req);
            if (rc == 0) return true;
            if (errno == EINTR) {
                if (!godo::rt::g_running.load(std::memory_order_acquire)) {
                    return false;
                }
                continue;  // resume with the residual `req` timespec
            }
            std::fprintf(stderr,
                "diag_publisher: nanosleep failed: %s — exiting publisher.\n",
                std::strerror(errno));
            return false;
        }
    };
    auto pool_getter = [&pool]() {
        return pool.snapshot_diag();
    };
    run_diag_publisher_with_clock(ring, accum, jitter_seq, amcl_rate_seq,
                                  &parallel_eval_seq, pool_getter,
                                  now_provider, sleep_callable);
}

}  // namespace godo::rt
