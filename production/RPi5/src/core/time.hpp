#pragma once

// CLOCK_MONOTONIC nanoseconds. See SYSTEM_DESIGN.md §6.1.2.
// Header-only: callers include this into the hot path; inlining avoids
// a function-call boundary on every tick.

#include <cstdint>
#include <ctime>

namespace godo::rt {

inline std::int64_t monotonic_ns() noexcept {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<std::int64_t>(ts.tv_sec) * 1'000'000'000LL
         + static_cast<std::int64_t>(ts.tv_nsec);
}

}  // namespace godo::rt
