#pragma once

// JitterStats — pure functions for percentile / summary computation.
//
// Used ONLY by rt/diag_publisher.cpp (NOT by Thread D). Free functions
// keep the surface stateless and thread-safe by construction. The caller
// owns the working buffer (sort-in-place); the snapshot fills a
// JitterSnapshot mirroring rt_types.hpp.
//
// `compute_percentile` uses the lower-quantile convention (matches
// `godo_jitter` Phase 4-1 measurement harness): for input length N at
// quantile p, return v[floor(p × (N-1))]. p50 of [1,2,3,4] → 2 (lower).
//
// Mode-A TB2 pin: feeding `[1, 100, 1000]` → p50=100 (the median); the
// publisher tick test asserts this end-to-end.

#include <cstddef>
#include <cstdint>

#include "core/rt_types.hpp"

namespace godo::rt {

// Quantile from a SORTED span. `p` ∈ [0.0, 1.0]; out-of-range is clamped.
// Returns 0 on empty input. Lower-quantile convention.
std::int64_t compute_percentile(const std::int64_t* sorted_data,
                                std::size_t n,
                                double p) noexcept;

// In-place sort + summary. Mutates `data[0..n)` (sorts ascending) then
// fills `out` with p50/p95/p99/max/mean + sample_count + valid=1 (or
// valid=0 + zeros for empty input). `published_mono_ns` is left to the
// caller (the publisher stamps it just before storing to the seqlock).
void compute_summary(std::int64_t* data,
                     std::size_t n,
                     JitterSnapshot& out) noexcept;

}  // namespace godo::rt
