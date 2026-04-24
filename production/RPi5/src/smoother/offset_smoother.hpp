#pragma once

// Linear-ramp offset smoother for the RT hot path.
// See SYSTEM_DESIGN.md §6.4.2.
//
// State is Thread-D-local; no atomics. Edge detection uses the seqlock
// generation counter (integer, exact) supplied by the caller, never float
// equality on the payload.

#include <cstdint>

#include "core/rt_types.hpp"

namespace godo::smoother {

class OffsetSmoother {
public:
    explicit OffsetSmoother(std::int64_t t_ramp_ns) noexcept;

    // Update internal state from `target` observed at `now_ns` with the
    // seqlock generation `gen`. Idempotent in `gen`: repeated calls with
    // the same `gen` do not restart the ramp. Pure non-throwing arithmetic.
    void tick(const godo::rt::Offset& target,
              std::uint64_t            gen,
              std::int64_t             now_ns) noexcept;

    // Current interpolated value.
    godo::rt::Offset live() const noexcept { return live_; }

private:
    // INT64_MIN/2 — sentinel meaning "ramp has never started". The first
    // real gen bump moves `t_start_` forward.
    static constexpr std::int64_t kSentinelNotStarted = INT64_MIN / 2;

    std::int64_t     t_ramp_ns_;
    godo::rt::Offset live_{};
    godo::rt::Offset prev_{};
    godo::rt::Offset target_{};
    std::uint64_t    target_g_{0};
    std::int64_t     t_start_{kSentinelNotStarted};
};

}  // namespace godo::smoother
