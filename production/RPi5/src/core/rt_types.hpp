#pragma once

// Types exchanged across the hot/cold path boundary.
// See SYSTEM_DESIGN.md §6.1.1.

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "constants.hpp"

namespace godo::rt {

struct Offset {
    double dx;    // metres, world-frame
    double dy;    // metres, world-frame
    double dyaw;  // degrees, [0, 360) canonical (see yaw/lerp_angle)
};

static_assert(sizeof(Offset) == 24, "Offset layout is ABI-visible");
static_assert(std::is_trivially_copyable_v<Offset>,
              "Offset must be trivially copyable for Seqlock payload");

struct FreedPacket {
    std::array<std::byte, godo::constants::FREED_PACKET_LEN> bytes;
};

static_assert(sizeof(FreedPacket) == godo::constants::FREED_PACKET_LEN,
              "FreedPacket layout is ABI-visible");
static_assert(std::is_trivially_copyable_v<FreedPacket>,
              "FreedPacket must be trivially copyable for Seqlock payload");

// Last AMCL pose snapshot, published by the cold writer at the OneShot
// success path and consumed via UDS `get_last_pose` (see
// production/RPi5/doc/uds_protocol.md §C.4 + Track B repeatability harness).
//
// Layout pinned (Track B plan F1+F7): 5×8 + 8 + 4 + 4×1 = 56 bytes,
// 8-byte aligned. Field order is ABI-visible — the JSON formatter in
// uds/json_mini.cpp::format_ok_pose mirrors this order; the Python mirror
// godo-webctl/protocol.py::LAST_POSE_FIELDS pins it at test time.
//
// `xy_std_m` is the combined-variance scalar produced by
// localization/amcl.cpp::xy_std_m (L272-300): sqrt(weighted_var_x +
// weighted_var_y). See uds_protocol.md §C.4 (F18) for the formula citation.
//
// `published_mono_ns` is set to godo::rt::monotonic_ns() at publish; readers
// can detect a stale snapshot by comparing this against their own
// monotonic clock + a freshness budget.
struct LastPose {
    double        x_m;                  // metres, world frame
    double        y_m;                  // metres, world frame
    double        yaw_deg;              // [0, 360) canonical
    double        xy_std_m;             // sqrt(var_x + var_y); amcl.cpp:272-300
    double        yaw_std_deg;          // circular std, degrees
    std::uint64_t published_mono_ns;    // monotonic_ns() at publish (F7)
    std::int32_t  iterations;           // AMCL iters; -1 = no run yet
    std::uint8_t  valid;                // 0 = no pose ever published, 1 = published
    std::uint8_t  converged;            // 0 = diverged, 1 = converged
    std::uint8_t  forced;               // OneShot=1; Live=0
    std::uint8_t  _pad0;                // reserved; keep zero
};

static_assert(sizeof(LastPose) == 56, "LastPose layout is ABI-visible");
static_assert(alignof(LastPose) == 8, "LastPose must be 8-aligned");
static_assert(std::is_trivially_copyable_v<LastPose>,
              "LastPose must be trivially copyable for Seqlock payload");

// Track D — last scan snapshot, published by the cold writer at the same
// seam as LastPose (run_one_iteration / run_live_iteration). Consumed via
// UDS `get_last_scan` (production/RPi5/doc/uds_protocol.md §C.5). The SPA
// renders the polar samples as a third canvas layer on top of the static
// map underlay so an operator can verify AMCL convergence visually.
//
// Mode-A folds (M1, M3, N6) shape the layout:
//   - M1: parallel `angles_deg[]` instead of (angle_min, increment) — the
//     downsample() step in scan_ops.cpp filters non-uniformly, so
//     parametrizing as `angle_min + i × increment` is wrong.
//   - M3: `pose_valid` flag distinguishes legitimate (0,0,0) anchor poses
//     from "no AMCL run yet" zeroes — the SPA gates the overlay on this.
//   - N6: `angles_deg[0]` lands at offset 56 already 8-aligned without a
//     trailing pad; no _pad3 needed.
//
// Field order is ABI-visible — the JSON formatter in
// uds/json_mini.cpp::format_ok_scan mirrors this order; the Python mirror
// godo-webctl/protocol.py::LAST_SCAN_HEADER_FIELDS is regex-extracted
// from this struct's source by tests/test_protocol.py and pinned at test
// time.
//
// Trivially copyable + fixed size = safe inside Seqlock<T>::payload_;
// no heap traffic on the cold-writer publish path.
struct LastScan {
    // Anchor pose used by the same-iteration AMCL converge/step. The SPA
    // uses these to do polar→Cartesian without needing a second SSE
    // correlation against /api/last_pose (Mode-A TM5).
    double  pose_x_m;
    double  pose_y_m;
    double  pose_yaw_deg;       // [0, 360) canonical

    // Publish timestamp (CLOCK_MONOTONIC ns); SPA gates "fresh vs stale"
    // ordering only — wall-clock freshness uses arrival-time per Mode-A M2.
    std::uint64_t published_mono_ns;

    // Header.
    std::int32_t  iterations;   // AMCL iters; -1 = no run yet
    std::uint8_t  valid;        // 0 = no scan ever published, 1 = published
    std::uint8_t  forced;       // 1 = OneShot, 0 = Live (mirrors LastPose.forced)
    std::uint8_t  pose_valid;   // 0 = AMCL pose not yet converged, 1 = valid
    std::uint8_t  _pad0;        // reserved; keep zero

    std::uint16_t n;            // [0, LAST_SCAN_RANGES_MAX]; valid sample count
    std::uint16_t _pad1;
    std::uint8_t  _pad2[4];     // align ranges/angles arrays to 8 B

    // Parallel arrays — angles_deg[i] is the bearing of ranges_m[i] in
    // the LiDAR frame. Both fixed-size to keep the type trivially
    // copyable (no std::vector, no heap).
    double angles_deg[godo::constants::LAST_SCAN_RANGES_MAX];
    double ranges_m[godo::constants::LAST_SCAN_RANGES_MAX];
};

// Layout pin: 24 (pose) + 8 (mono_ns) + 4 (iter) + 4 (flags+_pad0) +
// 2 (n) + 2 (_pad1) + 4 (_pad2) + 5760 (angles) + 5760 (ranges) = 11568 B.
// 11568 is 8-aligned (1446 × 8); no trailing pad needed (Mode-A N6).
static_assert(sizeof(LastScan) == 11568, "LastScan layout is ABI-visible");
static_assert(alignof(LastScan) == 8, "LastScan must be 8-aligned");
static_assert(std::is_trivially_copyable_v<LastScan>,
              "LastScan must be trivially copyable for Seqlock payload");

}  // namespace godo::rt
