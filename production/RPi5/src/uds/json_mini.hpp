#pragma once

// Hand-rolled minimal JSON parser/serializer for the UDS control protocol.
//
// Justification (plan §"Why hand-rolled"): the schema is exactly four
// message shapes, each with at most two string fields and one boolean. A
// `nlohmann/json` dependency would add ~20 KLOC of header to every TU
// that includes `uds_server.hpp`. Hand-rolled keeps the build small and
// dependency-free.
//
// This parser is NOT a general JSON implementation. It accepts only:
//   {"cmd":"<name>"}
//   {"cmd":"<name>","mode":"<value>"}
// Whitespace is tolerated between structural tokens. String contents must
// not contain backslash escapes (the schema only uses bare ASCII). Any
// deviation is reported as a parse error.

#include <string>
#include <string_view>

#include "core/rt_flags.hpp"
#include "core/rt_types.hpp"

namespace godo::uds {

// Parsed request. `cmd.empty()` indicates a parse failure; the caller
// returns format_err("parse_error") to the client. `mode_arg` is only
// populated when `cmd == "set_mode"`.
struct Request {
    std::string cmd;
    std::string mode_arg;
};

// Parse one request line. Tolerates trailing whitespace / newline.
Request parse_request(std::string_view line);

// Format the four canonical responses. format_ok() and format_ok_mode()
// always succeed; format_err() copies its input verbatim into the err
// field (caller is responsible for keeping it short and ASCII).
std::string format_ok();
std::string format_ok_mode(godo::rt::AmclMode mode);
std::string format_err(std::string_view code);

// Format the `get_last_pose` response (Track B). Field order MUST match
// `godo::rt::LastPose` declaration in core/rt_types.hpp; the Python mirror
// godo-webctl/protocol.py::LAST_POSE_FIELDS is pinned against the format
// string at test time. Precision split (F8): %.6f for pose fields (x, y,
// yaw — 1 µm / 1 µdeg precision is well below noise floor), %.9g for the
// std fields (xy_std_m, yaw_std_deg — keep full mantissa visible for
// diagnostics), %llu for `published_mono_ns` (uint64_t).
std::string format_ok_pose(const godo::rt::LastPose& p);

// Format the `get_last_scan` response (Track D). Field order MUST match
// the `godo::rt::LastScan` struct field declarations in core/rt_types.hpp;
// the Python mirror godo-webctl/protocol.py::LAST_SCAN_HEADER_FIELDS is
// regex-extracted from rt_types.hpp at test time
// (tests/test_protocol.py::test_last_scan_header_fields_match_cpp_source).
//
// Precision split (Track D, mirrors Track B):
//   - pose anchor (pose_x_m, pose_y_m, pose_yaw_deg) → %.6f (µm / µdeg)
//   - ranges_m[i]   → %.4f  (0.1 mm precision; well below C1's ~25 mm noise)
//   - angles_deg[i] → %.4f  (0.0001° precision; well below C1's ~0.36° step)
//   - published_mono_ns → %llu
//   - iterations    → %d
//   - flags (valid, forced, pose_valid) → %u
//
// Snapshot.n is clamped at LAST_SCAN_RANGES_MAX before iteration; the
// scratch buffer (constants::JSON_SCRATCH_BYTES) sizes to the worst case
// at that cap. See cpp body for the static_assert pinning the math.
std::string format_ok_scan(const godo::rt::LastScan& s);

// Convert AmclMode → string used in the wire protocol. Inverse of
// `parse_mode_arg` below. Returns "Idle" for unknown values for safety.
std::string_view mode_to_string(godo::rt::AmclMode mode) noexcept;

// Inverse of mode_to_string. Returns false on unknown input; sets `out`
// only on success.
bool parse_mode_arg(std::string_view arg, godo::rt::AmclMode& out) noexcept;

}  // namespace godo::uds
