// Seqlock alignment + stress test.
// One writer thread, four reader threads, 10^6 iterations each — readers
// must never observe a torn payload.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <atomic>
#include <cstdint>
#include <thread>
#include <vector>

#include "core/rt_types.hpp"
#include "core/seqlock.hpp"

using godo::rt::Offset;
using godo::rt::Seqlock;

TEST_CASE("Seqlock<Offset>: alignment is >= 64 bytes (false-sharing guard)") {
    CHECK(alignof(Seqlock<Offset>) >= 64);
}

TEST_CASE("Seqlock<Offset>: 1W + 4R stress — readers never see torn payload") {
    // Each payload is a "witness" where dx/dy/dyaw encode the iteration
    // number consistently. A reader that sees inconsistent components has
    // observed a torn write.
    Seqlock<Offset> sl;
    std::atomic<bool> done{false};
    std::atomic<std::uint64_t> torn_count{0};

    constexpr std::uint64_t kIters = 1'000'000;

    std::thread writer([&]() {
        for (std::uint64_t i = 1; i <= kIters; ++i) {
            const double d = static_cast<double>(i);
            sl.store(Offset{d, d * 2.0, d * 3.0});
        }
        done.store(true, std::memory_order_release);
    });

    std::vector<std::thread> readers;
    for (int r = 0; r < 4; ++r) {
        readers.emplace_back([&]() {
            while (!done.load(std::memory_order_acquire)) {
                const Offset v = sl.load();
                if (v.dx == 0.0 && v.dy == 0.0 && v.dyaw == 0.0) continue;
                if (v.dy != v.dx * 2.0 || v.dyaw != v.dx * 3.0) {
                    torn_count.fetch_add(1, std::memory_order_relaxed);
                }
            }
        });
    }

    writer.join();
    for (auto& t : readers) t.join();

    CHECK(torn_count.load() == 0);
}

TEST_CASE("Seqlock: generation() is monotonic and even on consistent payload") {
    Seqlock<Offset> sl;
    CHECK(sl.generation() == 0);
    sl.store(Offset{1.0, 2.0, 3.0});
    const std::uint64_t g1 = sl.generation();
    CHECK((g1 & 1U) == 0);          // even
    CHECK(g1 > 0);
    sl.store(Offset{4.0, 5.0, 6.0});
    const std::uint64_t g2 = sl.generation();
    CHECK(g2 > g1);
    CHECK((g2 & 1U) == 0);
}

TEST_CASE("Seqlock: load observes the last stored payload") {
    Seqlock<Offset> sl;
    sl.store(Offset{1.5, -2.5, 123.0});
    const Offset v = sl.load();
    CHECK(v.dx   == 1.5);
    CHECK(v.dy   == -2.5);
    CHECK(v.dyaw == 123.0);
}
