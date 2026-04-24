#pragma once

// Tier-1 protocol / algorithmic invariants. Changing any of these requires
// a coordinated downstream update (UE project file, legacy Arduino rollback).
// See SYSTEM_DESIGN.md §11.1.

#include <cstdint>

namespace godo::constants {

// FreeD D1 protocol — pinned by the wire format, not tunable.
// Byte layout cross-reference: XR_FreeD_to_UDP/src/main.cpp L17-31.
inline constexpr int      FREED_PACKET_LEN = 29;
inline constexpr double   FREED_PAN_Q      = 1.0 / 32768.0;  // deg per lsb
inline constexpr double   FREED_POS_Q      = 1.0 / 64.0;     // mm per lsb

// Derived multipliers for Offset → wire-lsb re-encoding in apply_offset_inplace.
// Named so sender.cpp has no magic literals. Changing Tier-1 quanta cascades.
inline constexpr double   MM_PER_M              = 1000.0;
inline constexpr double   FREED_POS_LSB_PER_M   = MM_PER_M / FREED_POS_Q;   // 64'000 lsb/m
inline constexpr double   FREED_PAN_LSB_PER_DEG = 1.0 / FREED_PAN_Q;        // 32'768 lsb/deg

// SLAMTEC C1 sample decoding — pinned by the SDK.
inline constexpr double   RPLIDAR_Q14_DEG  = 90.0 / 16384.0;
inline constexpr double   RPLIDAR_Q2_MM    = 1.0 / 4.0;

// Hot-path cadence — pinned by UE's 59.94 fps project standard.
inline constexpr double   FRAME_RATE_HZ    = 60000.0 / 1001.0;
inline constexpr int64_t  FRAME_PERIOD_NS  = 16'683'350;

// FreeD D1 field offsets within the 29-byte packet.
// Source of truth: XR_FreeD_to_UDP/src/main.cpp L67-85.
namespace FreeD {
    inline constexpr int OFF_TYPE     = 0;
    inline constexpr int OFF_CAM_ID   = 1;
    inline constexpr int OFF_PAN      = 2;
    inline constexpr int OFF_TILT     = 5;
    inline constexpr int OFF_ROLL     = 8;
    inline constexpr int OFF_X        = 11;
    inline constexpr int OFF_Y        = 14;
    inline constexpr int OFF_Z        = 17;
    inline constexpr int OFF_ZOOM     = 20;
    inline constexpr int OFF_FOCUS    = 23;
    inline constexpr int OFF_STATUS   = 26;
    inline constexpr int OFF_CHECKSUM = 28;

    inline constexpr std::uint8_t TYPE_D1 = 0xD1;
}  // namespace FreeD

}  // namespace godo::constants
