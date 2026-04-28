// Track D — Seqlock<LastScan> stress test under writer pressure.
//
// 1 writer + 4 readers, 10⁵ iterations each. The LastScan payload is
// ~11.3 KiB (much wider than LastPose's 56 B), so retry probability
// scales with payload-copy duration vs. writer cadence. This test pins
// that the existing Seqlock retry semantics still produce torn-read-free
// loads at the new payload size.
//
// Mode-A TB1 + Mode-B N2/TB-A fold — torn-read invariant must be
// PURELY POSITIONAL and per-iteration DISTINCT, so a torn read mixing
// payloads from two adjacent writes is detectable from one load alone.
// Writer fills:
//   ranges_m[i]   = i × 0.001 + iter_marker
//   angles_deg[i] = i × 0.5   + iter_marker
// where iter_marker varies per writer iteration. Readers derive the
// marker from ranges_m[0] (= 0×0.001 + iter_marker = iter_marker) and
// verify the formula against EVERY cell. A torn read whose array body
// spans two iterations breaks the formula on the cells from the
// "wrong" iteration. No sibling atomic, no cross-payload reference —
// detection is purely positional + arithmetic.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <atomic>
#include <cstdint>
#include <thread>
#include <vector>

#include "core/constants.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"

using godo::rt::LastScan;
using godo::rt::Seqlock;

namespace {

constexpr int kIterations = 100'000;
constexpr int kReaders    = 4;

// Build a writer snapshot using the TB1+N2 positional+per-iteration
// invariant. Every cell is filled; the iter_marker offset shifts every
// write so a torn read mixing two adjacent payloads is detectable.
LastScan make_writer_snapshot(std::uint64_t mono_ns, double iter_marker) {
    LastScan s{};
    s.pose_x_m          = 1.0;
    s.pose_y_m          = 2.0;
    s.pose_yaw_deg      = 45.0;
    s.published_mono_ns = mono_ns;
    s.iterations        = 7;
    s.valid             = 1;
    s.forced            = 1;
    s.pose_valid        = 1;
    s._pad0             = 0;
    s.n = static_cast<std::uint16_t>(godo::constants::LAST_SCAN_RANGES_MAX);
    s._pad1 = 0;
    for (std::size_t i = 0;
         i < static_cast<std::size_t>(godo::constants::LAST_SCAN_RANGES_MAX);
         ++i) {
        s.ranges_m[i]   = static_cast<double>(i) * 0.001 + iter_marker;
        s.angles_deg[i] = static_cast<double>(i) * 0.5   + iter_marker;
    }
    return s;
}

// Verify the TB1+N2 positional invariant on a single loaded snapshot.
// Derives the iter_marker from ranges_m[0] (= 0*0.001 + marker = marker)
// then checks every other cell against the per-index formula. A torn
// read whose array body spans two iterations breaks the formula on at
// least one cell from the "wrong" iteration. Returns true on a fully
// consistent snapshot.
bool verify_positional_invariant(const LastScan& s) {
    constexpr std::size_t kCap =
        static_cast<std::size_t>(godo::constants::LAST_SCAN_RANGES_MAX);
    const double marker = s.ranges_m[0];
    if (s.angles_deg[0] != marker) return false;
    for (std::size_t i = 1; i < kCap; ++i) {
        const double expected_r = static_cast<double>(i) * 0.001 + marker;
        const double expected_a = static_cast<double>(i) * 0.5   + marker;
        if (s.ranges_m[i] != expected_r) return false;
        if (s.angles_deg[i] != expected_a) return false;
    }
    return true;
}

}  // namespace

TEST_CASE("Seqlock<LastScan> — 1W/4R 100k iterations, no torn reads") {
    Seqlock<LastScan> seq;
    seq.store(make_writer_snapshot(1, 0.0));

    std::atomic<bool>          stop{false};
    std::atomic<std::uint64_t> torn_reads{0};
    std::atomic<std::uint64_t> good_reads{0};

    auto reader = [&]() {
        while (!stop.load(std::memory_order_acquire)) {
            const LastScan got = seq.load();
            if (verify_positional_invariant(got)) {
                good_reads.fetch_add(1, std::memory_order_relaxed);
            } else {
                torn_reads.fetch_add(1, std::memory_order_relaxed);
            }
        }
    };

    std::vector<std::thread> readers;
    readers.reserve(kReaders);
    for (int i = 0; i < kReaders; ++i) {
        readers.emplace_back(reader);
    }

    // Writer thread loops kIterations times, each storing a fresh
    // snapshot with strictly advancing mono_ns AND a per-iteration
    // distinct iter_marker offset. The marker shift makes a torn read
    // mixing iter X and iter Y observable: ranges_m[0] yields marker X,
    // but the cells from iter Y satisfy `i*0.001 + Y` not `i*0.001 + X`.
    std::thread writer([&]() {
        for (int i = 1; i <= kIterations; ++i) {
            const double marker = static_cast<double>(i);
            seq.store(make_writer_snapshot(static_cast<std::uint64_t>(i + 1),
                                           marker));
        }
    });

    writer.join();
    stop.store(true, std::memory_order_release);
    for (auto& t : readers) t.join();

    // Zero torn reads — Seqlock retry must catch every concurrent
    // payload write.
    CHECK(torn_reads.load() == 0u);
    // Every reader thread should have completed at least one good
    // load — a stuck reader would imply pathological retry storms.
    CHECK(good_reads.load() > 0u);
}
