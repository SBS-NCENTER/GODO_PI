// PR-DIAG — diag publisher tick-by-tick virtual-clock test.
//
// Drives the publisher with injected NowProvider + SleepFor so we can
// advance virtual time and assert the seqlocks were stored.
//
// Mode-A TB2 content invariant: feeding [1, 100, 1000] into the ring
// then ticking the publisher must store p50=100 in jitter_seq.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <atomic>
#include <cstdint>

#include "core/rt_flags.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "rt/amcl_rate.hpp"
#include "rt/diag_publisher.hpp"
#include "rt/jitter_ring.hpp"

using godo::rt::AmclIterationRate;
using godo::rt::AmclRateAccumulator;
using godo::rt::JitterRing;
using godo::rt::JitterSnapshot;
using godo::rt::Seqlock;

namespace {

struct VirtualClock {
    std::int64_t now = 0;
    std::int64_t step;
    bool         allow_more = true;
    int          ticks_observed = 0;
    int          max_ticks;

    explicit VirtualClock(std::int64_t step_ns, int max)
        : step(step_ns), max_ticks(max) {}

    std::int64_t time_now() {
        return now;
    }

    bool sleep_for(std::int64_t ns) {
        now += ns;
        ++ticks_observed;
        return ticks_observed < max_ticks;
    }
};

}  // namespace

TEST_CASE("diag_publisher — publishes-once-per-interval with virtual clock") {
    JitterRing            ring;
    AmclRateAccumulator   accum;
    Seqlock<JitterSnapshot>     jitter_seq;
    Seqlock<AmclIterationRate>  amcl_rate_seq;

    // Mode-A TB2 shape: ring contains [1, 100, 1000]. After publish:
    // jitter_seq.load().p50_ns must equal 100.
    ring.record(1);
    ring.record(100);
    ring.record(1000);

    // Two iterations across a 1 s window so the rate publisher has
    // (count delta = 2, last_ns delta = 1e9 ns) → ~2 Hz.
    accum.record(0ULL);
    accum.record(1'000'000'000ULL);

    VirtualClock vc(1'000'000'000LL, /*max_ticks=*/3);

    godo::rt::g_running.store(true, std::memory_order_release);
    godo::rt::run_diag_publisher_with_clock(
        ring, accum, jitter_seq, amcl_rate_seq,
        [&]() { return vc.time_now(); },
        [&](std::int64_t ns) { return vc.sleep_for(ns); });

    const JitterSnapshot js = jitter_seq.load();
    CHECK(js.valid == 1);
    CHECK(js.sample_count == 3u);
    CHECK(js.p50_ns == 100);
    CHECK(js.max_ns == 1000);
    CHECK(js.mean_ns == (1 + 100 + 1000) / 3);

    const AmclIterationRate ar = amcl_rate_seq.load();
    // Second tick onward sees count_delta=0 vs the prior; first tick has
    // (count=2, prev_count=0, prev_last_ns=0) → 2 / (1e9/1e9) = 2.0 Hz.
    CHECK(ar.total_iteration_count == 2u);
    // Final published snapshot (after the 3rd tick) — the rate window
    // arithmetic between identical accumulator snapshots yields hz=0
    // and valid=0; that's fine, the upstream consumer dims the chip.
}

TEST_CASE("diag_publisher — first tick computes hz correctly (Mode-B TB2)") {
    JitterRing            ring;
    AmclRateAccumulator   accum;
    Seqlock<JitterSnapshot>     jitter_seq;
    Seqlock<AmclIterationRate>  amcl_rate_seq;

    // Two record()s exactly 1 s apart. After the first publish tick:
    // count_delta = 2 - 0 = 2, time_delta = 1e9 - 0 = 1 s → hz = 2.0.
    accum.record(0ULL);
    accum.record(1'000'000'000ULL);

    // max_ticks=1 captures the snapshot AFTER the first publish, before
    // the rate window arithmetic clobbers prev to (count=2, last_ns=1e9)
    // and yields hz=0 on subsequent ticks.
    VirtualClock vc(1'000'000'000LL, /*max_ticks=*/1);

    godo::rt::g_running.store(true, std::memory_order_release);
    godo::rt::run_diag_publisher_with_clock(
        ring, accum, jitter_seq, amcl_rate_seq,
        [&]() { return vc.time_now(); },
        [&](std::int64_t ns) { return vc.sleep_for(ns); });

    const AmclIterationRate ar = amcl_rate_seq.load();
    CHECK(ar.valid == 1);
    CHECK(ar.total_iteration_count == 2u);
    CHECK(ar.last_iteration_mono_ns == 1'000'000'000u);
    // The actual rate-correctness pin: a bug returning hz=999 or hz=0.5
    // here would not be caught by the count check above.
    CHECK(ar.hz == doctest::Approx(2.0));
}

TEST_CASE("diag_publisher — exits when sleep_for returns false") {
    JitterRing            ring;
    AmclRateAccumulator   accum;
    Seqlock<JitterSnapshot>     jitter_seq;
    Seqlock<AmclIterationRate>  amcl_rate_seq;

    int sleep_calls = 0;
    godo::rt::g_running.store(true, std::memory_order_release);
    godo::rt::run_diag_publisher_with_clock(
        ring, accum, jitter_seq, amcl_rate_seq,
        []() -> std::int64_t { return 0; },
        [&](std::int64_t /*ns*/) { ++sleep_calls; return false; });
    CHECK(sleep_calls == 1);
}

TEST_CASE("diag_publisher — exits when g_running is false on entry") {
    JitterRing            ring;
    AmclRateAccumulator   accum;
    Seqlock<JitterSnapshot>     jitter_seq;
    Seqlock<AmclIterationRate>  amcl_rate_seq;

    godo::rt::g_running.store(false, std::memory_order_release);
    int sleep_calls = 0;
    int now_calls = 0;
    godo::rt::run_diag_publisher_with_clock(
        ring, accum, jitter_seq, amcl_rate_seq,
        [&]() -> std::int64_t { ++now_calls; return 0; },
        [&](std::int64_t /*ns*/) { ++sleep_calls; return true; });
    // No tick body executed; loop checks g_running first.
    CHECK(sleep_calls == 0);
    CHECK(now_calls == 0);
    // Re-arm for the rest of the suite.
    godo::rt::g_running.store(true, std::memory_order_release);
}

TEST_CASE("diag_publisher — empty ring publishes valid=0 sentinel") {
    JitterRing            ring;
    AmclRateAccumulator   accum;
    Seqlock<JitterSnapshot>     jitter_seq;
    Seqlock<AmclIterationRate>  amcl_rate_seq;

    VirtualClock vc(1'000'000'000LL, /*max_ticks=*/1);
    godo::rt::g_running.store(true, std::memory_order_release);
    godo::rt::run_diag_publisher_with_clock(
        ring, accum, jitter_seq, amcl_rate_seq,
        [&]() { return vc.time_now(); },
        [&](std::int64_t ns) { return vc.sleep_for(ns); });

    const JitterSnapshot js = jitter_seq.load();
    CHECK(js.valid == 0);
    CHECK(js.sample_count == 0u);

    const AmclIterationRate ar = amcl_rate_seq.load();
    CHECK(ar.valid == 0);
    CHECK(ar.hz == 0.0);
}
