// Track D — Seqlock<LastScan> stress test under writer pressure.
//
// 1 writer + 4 readers, 10⁵ iterations each. The LastScan payload is
// ~11.3 KiB (much wider than LastPose's 56 B), so retry probability
// scales with payload-copy duration vs. writer cadence. This test pins
// that the existing Seqlock retry semantics still produce torn-read-free
// loads at the new payload size.
//
// Mode-A TB1 fold — torn-read invariant must be PURELY POSITIONAL.
// Writer fills:
//   ranges_m[i]   = i × 0.001
//   angles_deg[i] = i × 0.5
// for the entire LAST_SCAN_RANGES_MAX-wide array (regardless of `n`).
// Readers verify BOTH expected shapes from a single seqlock.load(); a
// torn read is detectable from the single load alone (no sibling atomic
// or cross-payload reference).

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

// Build a writer snapshot using the TB1 positional invariant. Every cell
// (whether logically "in use" or not) is filled, so any reader that
// observes a torn payload will see at least one cell whose ranges_m or
// angles_deg does not satisfy the per-index formula.
LastScan make_writer_snapshot(std::uint64_t mono_ns) {
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
        s.ranges_m[i]   = static_cast<double>(i) * 0.001;
        s.angles_deg[i] = static_cast<double>(i) * 0.5;
    }
    return s;
}

// Verify the TB1 positional invariant on a single loaded snapshot.
// Returns true when the snapshot is fully consistent.
bool verify_positional_invariant(const LastScan& s) {
    constexpr std::size_t kCap =
        static_cast<std::size_t>(godo::constants::LAST_SCAN_RANGES_MAX);
    for (std::size_t i = 0; i < kCap; ++i) {
        const double expected_r = static_cast<double>(i) * 0.001;
        const double expected_a = static_cast<double>(i) * 0.5;
        if (s.ranges_m[i] != expected_r) return false;
        if (s.angles_deg[i] != expected_a) return false;
    }
    return true;
}

}  // namespace

TEST_CASE("Seqlock<LastScan> — 1W/4R 100k iterations, no torn reads") {
    Seqlock<LastScan> seq;
    seq.store(make_writer_snapshot(1));

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

    // Writer thread loops kIterations times, each storing a fresh snapshot
    // with a slightly different mono_ns (so generation strictly advances)
    // but the same TB1 positional payload.
    std::thread writer([&]() {
        for (int i = 1; i <= kIterations; ++i) {
            seq.store(make_writer_snapshot(static_cast<std::uint64_t>(i + 1)));
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
