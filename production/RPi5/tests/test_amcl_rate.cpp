// PR-DIAG — AmclRateAccumulator round-trip + 1W/1R seqlock stress.
//
// Mode-A M1 fold: the accumulator wraps (count, last_ns) in a
// Seqlock<AmclRateRecord>. The reader (publisher thread) sees a
// consistent pair on every snapshot() — never a torn (count, last_ns)
// where one field has updated and the other has not.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <atomic>
#include <thread>

#include "rt/amcl_rate.hpp"

using godo::rt::AmclRateAccumulator;

TEST_CASE("AmclRateAccumulator — initial snapshot is zero-zero") {
    AmclRateAccumulator a;
    const auto rec = a.snapshot();
    CHECK(rec.count == 0u);
    CHECK(rec.last_ns == 0u);
}

TEST_CASE("AmclRateAccumulator — record advances both fields atomically") {
    AmclRateAccumulator a;
    a.record(1'000'000'000ULL);
    a.record(2'000'000'000ULL);
    a.record(3'000'000'000ULL);
    const auto rec = a.snapshot();
    CHECK(rec.count == 3u);
    CHECK(rec.last_ns == 3'000'000'000u);
}

TEST_CASE("AmclRateAccumulator — count is monotonic under writer pressure") {
    AmclRateAccumulator a;
    std::atomic<bool> stop{false};
    constexpr int kIters = 50000;

    std::thread writer([&]() {
        for (int i = 0; i < kIters && !stop.load(std::memory_order_relaxed); ++i) {
            a.record(static_cast<std::uint64_t>(i + 1) * 1000ULL);
        }
    });

    std::uint64_t prev_count = 0;
    std::uint64_t prev_last  = 0;
    for (int rd = 0; rd < 1000; ++rd) {
        const auto rec = a.snapshot();
        CHECK(rec.count >= prev_count);
        // last_ns is monotonic in the writer's view because we feed
        // monotonically increasing timestamps.
        CHECK(rec.last_ns >= prev_last);
        prev_count = rec.count;
        prev_last  = rec.last_ns;
    }
    stop.store(true, std::memory_order_relaxed);
    writer.join();
}

TEST_CASE("AmclRateAccumulator — last_ns advances on every record") {
    AmclRateAccumulator a;
    a.record(100ULL);
    const std::uint64_t a1 = a.snapshot().last_ns;
    a.record(200ULL);
    const std::uint64_t a2 = a.snapshot().last_ns;
    CHECK(a2 > a1);
    CHECK(a2 == 200u);
}
