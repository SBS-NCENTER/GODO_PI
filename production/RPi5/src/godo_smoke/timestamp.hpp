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

// KST timestamp formatted as "YYYYMMDDThhmmss" (no punctuation, no
// offset suffix — host-KST convention). Used to build output filenames:
// `<ts>_<tag>.csv` / `<ts>_<tag>.txt`. Function name retained for ABI
// stability; payload is KST per project convention (see
// `.claude/memory/feedback_timestamp_kst_convention.md`).
std::string utc_timestamp_compact();

// KST timestamp formatted per ISO-8601, second precision with explicit
// offset, e.g. "2026-04-23T15:04:05+09:00". Used inside the session log
// header. Function name retained for ABI stability.
std::string utc_timestamp_iso();

}  // namespace godo::smoke
