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

}  // namespace godo::rt
