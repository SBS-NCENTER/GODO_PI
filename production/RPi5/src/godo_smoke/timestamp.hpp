#pragma once

// Monotonic nanosecond timestamps (CLOCK_MONOTONIC).
//
// Matches Python `time.monotonic_ns()` semantics on Linux: the same clock
// source, so the values are directly comparable across the two prototypes.

#include <cstdint>
#include <string>

namespace godo::smoke {

// Nanoseconds since an unspecified monotonic epoch. Never decreases.
std::int64_t monotonic_ns();

// UTC timestamp formatted as "YYYYMMDDThhmmssZ" (no punctuation).
// Used to build output filenames: `<ts>_<tag>.csv` / `<ts>_<tag>.txt`.
std::string utc_timestamp_compact();

// UTC timestamp formatted per ISO-8601, second precision, e.g.
// "2026-04-23T15:04:05+00:00". Used inside the session log header.
std::string utc_timestamp_iso();

}  // namespace godo::smoke
