#pragma once

// AmclRateAccumulator — single-writer (cold writer) / single-reader
// (rt/diag_publisher.cpp) accumulator that records each AMCL iteration
// timestamp + total count.
//
// Mode-A M1 fold: implementation wraps the (count, last_ns) pair in a
// Seqlock<AmclRateRecord> primitive (the existing core/seqlock.hpp).
// The original two-atomic design exposed measurable Hz-skew under
// concurrent record() / publisher reads; the seqlock atomically swaps
// both fields so the publisher always sees a consistent snapshot.
//
// Cold writer is single-threaded so the writer side is single-producer
// (Seqlock contract); the reader is the publisher thread on
// SCHED_OTHER.
//
// No allocation, no syscalls. record() is one Seqlock load + one store
// (~50 ns measured); the publisher's snapshot() is an atomic load that
// retries on writer-in-flight.

#include <cstdint>

#include "core/seqlock.hpp"

namespace godo::rt {

// Wrapped pair stored under Seqlock. Trivially copyable, 16 B.
struct AmclRateRecord {
    std::uint64_t count;        // monotonic; never wraps in practice
    std::uint64_t last_ns;      // CLOCK_MONOTONIC ns at the most recent record()
};

static_assert(sizeof(AmclRateRecord) == 16, "AmclRateRecord layout pinned");
static_assert(std::is_trivially_copyable_v<AmclRateRecord>,
              "AmclRateRecord must be trivially copyable for Seqlock");

class AmclRateAccumulator {
public:
    AmclRateAccumulator() noexcept = default;

    AmclRateAccumulator(const AmclRateAccumulator&)            = delete;
    AmclRateAccumulator& operator=(const AmclRateAccumulator&) = delete;

    // SINGLE-WRITER ONLY. The load-then-store sequence is race-free
    // against publisher READS under the seqlock, but TWO concurrent
    // record() callers would lose updates (both load the same `cur`,
    // both store cur.count+1, the second clobbers the first). The
    // [amcl-rate-publisher-grep] build gate enforces "only cold_writer.cpp
    // calls record()" textually; the single-thread invariant on top of
    // that is asserted in production/RPi5/CODEBASE.md (Mode-B S3 fold).
    // Caller MUST guarantee no concurrent record().
    void record(std::uint64_t now_ns) noexcept {
        const auto cur = rec_.load();
        rec_.store({cur.count + 1, now_ns});
    }

    // Single-reader snapshot. Atomic across the (count, last_ns) pair.
    AmclRateRecord snapshot() const noexcept {
        return rec_.load();
    }

private:
    Seqlock<AmclRateRecord> rec_;
};

}  // namespace godo::rt
