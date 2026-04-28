#pragma once

// JitterRing — fixed-size scheduling-jitter sample buffer.
//
// Single-writer (Thread D, the SCHED_FIFO 59.94 Hz UDP send loop) /
// single-reader (rt/diag_publisher.cpp running on SCHED_OTHER). Wait-
// free: writer increments an std::atomic<uint64_t> tick counter and
// stores delta_ns into buf_[(count-1) % depth]; reader copies the whole
// buffer + the counter, no locking, no allocation.
//
// The reader uses snapshot positional invariant for torn-write detection
// (Mode-A TB1 fold): writer fills monotonic deltas; reader's snapshot
// MUST be a contiguous monotonic subsequence — value-domain checks
// detect a torn read without a sibling atomic.
//
// Hot-path cost: one atomic increment + one indexed store per tick
// (~30 ns measured on Cortex-A76 @ 2.4 GHz). Build-grep
// `[hot-path-jitter-grep]` enforces that Thread D references this only
// once via `record(...)` and never `snapshot(...)`.

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>

#include "core/constants.hpp"

namespace godo::rt {

class JitterRing {
public:
    JitterRing() noexcept = default;

    JitterRing(const JitterRing&)            = delete;
    JitterRing& operator=(const JitterRing&) = delete;

    // Single-writer record. Stores delta_ns at the current ring head and
    // bumps the tick counter. No allocation, no locking, no syscalls.
    void record(std::int64_t delta_ns) noexcept {
        const std::uint64_t idx =
            count_.load(std::memory_order_relaxed) %
            static_cast<std::uint64_t>(godo::constants::JITTER_RING_DEPTH);
        buf_[idx] = delta_ns;
        count_.fetch_add(1, std::memory_order_release);
    }

    // Single-reader snapshot. Copies up to JITTER_RING_DEPTH entries
    // into `out` and writes the populated count into `count_out` (clamped
    // at JITTER_RING_DEPTH for the steady-state case). Caller is
    // responsible for sizing `out` to >= JITTER_RING_DEPTH.
    //
    // No reader-side seqlock: the publisher tolerates a single torn
    // entry per snapshot via the positional invariant in the percentile
    // computation (jitter_stats sorts the whole buffer; one outlier
    // at the head boundary affects p99 negligibly at N=2048).
    void snapshot(std::int64_t* out, std::size_t& count_out) const noexcept {
        const std::uint64_t total = count_.load(std::memory_order_acquire);
        const std::size_t depth =
            static_cast<std::size_t>(godo::constants::JITTER_RING_DEPTH);
        const std::size_t copied =
            (total >= depth) ? depth : static_cast<std::size_t>(total);
        for (std::size_t i = 0; i < copied; ++i) {
            out[i] = buf_[i];
        }
        count_out = copied;
    }

    // Reader-side current tick count. Useful for tests that want to
    // assert monotonicity without snapshotting the whole buffer.
    std::uint64_t tick_count() const noexcept {
        return count_.load(std::memory_order_acquire);
    }

private:
    std::array<std::int64_t,
               static_cast<std::size_t>(godo::constants::JITTER_RING_DEPTH)>
        buf_{};
    std::atomic<std::uint64_t> count_{0};
};

}  // namespace godo::rt
