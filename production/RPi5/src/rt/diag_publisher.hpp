#pragma once

// Diagnostics publisher — non-RT thread that periodically reads the
// jitter ring + amcl-rate accumulator, computes summaries, and stores
// them into the two seqlocks consumed by UDS `get_jitter` /
// `get_amcl_rate`.
//
// Lifecycle:
//   - Spawned from godo_tracker_rt/main.cpp AFTER the cold writer + UDS
//     threads (so the seqlocks are already constructed).
//   - Runs on SCHED_OTHER (NO pin_current_thread_to_cpu, NO
//     set_current_thread_fifo) — deliberately yields freely to Thread D.
//   - Polls godo::rt::g_running every JITTER_PUBLISH_INTERVAL_MS via
//     clock_nanosleep; exits cleanly within one tick of g_running=false.
//   - Body wrapped in try/catch — a percentile-math throw (TM9) logs to
//     stderr and exits the publisher; the seqlocks retain their last
//     valid snapshot so the SPA shows stale-data instead of vanishing.
//
// Test injection seam: `run_diag_publisher_with_clock` accepts a
// `nowProvider` + `sleepFor` pair so tests can drive virtual time
// without wall-clock waits. The production overload calls the variant
// with CLOCK_MONOTONIC + clock_nanosleep.

#include <chrono>
#include <functional>

#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "rt/amcl_rate.hpp"
#include "rt/jitter_ring.hpp"

namespace godo::rt {

// Test-injection clock + sleep callable. NowProvider returns ns since
// some monotonic epoch (production: CLOCK_MONOTONIC); SleepFor blocks
// for the given ns (or returns false to indicate cancellation).
using NowProvider = std::function<std::int64_t()>;
using SleepFor    = std::function<bool(std::int64_t)>;

// Test variant — drives the loop with an injected clock + sleep. Returns
// when g_running becomes false OR `sleep_for` returns false (the test's
// signal to stop). Exceptions inside the body are caught and logged; the
// loop exits.
void run_diag_publisher_with_clock(JitterRing&                ring,
                                   AmclRateAccumulator&       accum,
                                   Seqlock<JitterSnapshot>&   jitter_seq,
                                   Seqlock<AmclIterationRate>& amcl_rate_seq,
                                   NowProvider                now_ns,
                                   SleepFor                   sleep_for) noexcept;

// Production variant — uses monotonic_ns() + clock_nanosleep. Spawned
// from godo_tracker_rt/main.cpp.
void run_diag_publisher(JitterRing&                ring,
                        AmclRateAccumulator&       accum,
                        Seqlock<JitterSnapshot>&   jitter_seq,
                        Seqlock<AmclIterationRate>& amcl_rate_seq) noexcept;

}  // namespace godo::rt
