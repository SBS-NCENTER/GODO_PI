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

}  // namespace godo::rt
