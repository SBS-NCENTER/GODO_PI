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
// populated when `cmd == "set_mode"`. `key_arg` + `value_arg` are only
// populated when `cmd == "set_config"` (Track B-CONFIG / PR-CONFIG-α).
struct Request {
    std::string cmd;
    std::string mode_arg;
    std::string key_arg;
    std::string value_arg;
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

// Format the `get_last_scan` response (Track D). The wire field NAMES
// MUST match `godo::rt::LastScan` field declarations in core/rt_types.hpp
// (drift catch: tests/test_protocol.py::test_last_scan_header_fields_
// match_cpp_source — set-equality vs. struct names). The wire field
// ORDER is NOT the struct order: the wire opens with flags + iterations
// + pose anchor, then `n`, then the two array bodies at the tail. Order
// is pinned in two places: byte-exact at the C++ side by tests/test_uds_
// server.cpp::format_ok_scan — byte-exact shape on a default-zero
// LastScan, and tuple-equal on the Python side by tests/test_protocol.py
// ::test_last_scan_wire_order_matches_format_ok_scan.
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

// Track B-DIAG (PR-DIAG) — `get_jitter` response (uds_protocol.md §C.6).
// Field order MUST match `godo::rt::JitterSnapshot` declaration in
// core/rt_types.hpp. The Python mirror godo-webctl/protocol.py::
// JITTER_FIELDS is regex-pinned against this format string at test time.
//
// Precision split:
//   - p-tile values + max + mean → %lld   (signed int64 ns)
//   - sample_count                → %llu  (uint64)
//   - published_mono_ns           → %llu  (uint64)
//   - valid                       → %u    (uint8 → unsigned int)
//
// Worst-case payload pinned by static_assert against
// constants::JITTER_FORMAT_SCRATCH_BYTES (512 B).
std::string format_ok_jitter(const godo::rt::JitterSnapshot& j);

// Track B-DIAG (Mode-A M2 fold) — `get_amcl_rate` response (uds_protocol.md
// §C.7). Renamed from `format_ok_scan_rate` per Mode-A reviewer; the
// metric measures cold-writer publish cadence, not raw LiDAR scan rate.
//
// Precision split:
//   - hz                          → %.6f   (1 µHz precision)
//   - last_iteration_mono_ns      → %llu   (uint64)
//   - total_iteration_count       → %llu   (uint64)
//   - published_mono_ns           → %llu   (uint64)
//   - valid                       → %u
std::string format_ok_amcl_rate(const godo::rt::AmclIterationRate& r);

// Track B-CONFIG (PR-CONFIG-α) — `set_config` reply. The `body_json`
// argument is the pre-rendered JSON payload (see config/apply.cpp's
// apply_get_all / apply_get_schema for the get-side encoders). On
// `set_config` the wire reply carries the resolved reload class so the
// SPA can decide whether to show the restart-pending banner.
std::string format_ok_set_config(std::string_view reload_class);
std::string format_ok_get_config(std::string_view body_json);
std::string format_ok_get_config_schema(std::string_view body_json);

// Track B-CONFIG (PR-CONFIG-α) — `set_config` rejection with detail.
// The validator surfaces both an `err` code and a per-key `detail`
// string; the client renders detail inline next to the failed input.
std::string format_err_with_detail(std::string_view code,
                                   std::string_view detail);

// Convert AmclMode → string used in the wire protocol. Inverse of
// `parse_mode_arg` below. Returns "Idle" for unknown values for safety.
std::string_view mode_to_string(godo::rt::AmclMode mode) noexcept;

// Inverse of mode_to_string. Returns false on unknown input; sets `out`
// only on success.
bool parse_mode_arg(std::string_view arg, godo::rt::AmclMode& out) noexcept;

}  // namespace godo::uds
