#pragma once

// Tier-2 runtime-tunable defaults. Operators override these through
// /etc/godo/tracker.toml, GODO_* environment variables, or CLI flags.
// See SYSTEM_DESIGN.md §11.2.

#include <cstdint>
#include <string_view>

namespace godo::config::defaults {

// Network.
inline constexpr std::string_view UE_HOST      = "192.168.0.0";  // TBD
inline constexpr int              UE_PORT      = 6666;

// Serial devices.
inline constexpr std::string_view LIDAR_PORT   = "/dev/ttyUSB0";
inline constexpr int              LIDAR_BAUD   = 460'800;
inline constexpr std::string_view FREED_PORT   = "/dev/ttyAMA0";  // PL011 UART0 via YL-128
inline constexpr int              FREED_BAUD   = 38'400;

// Smoother & deadband.
inline constexpr int64_t          T_RAMP_NS      = 500'000'000;   // 500 ms
inline constexpr double           DEADBAND_MM    = 10.0;           // 1 cm
inline constexpr double           DEADBAND_DEG   = 0.1;
inline constexpr double           DIVERGENCE_MM  = 2000.0;
inline constexpr double           DIVERGENCE_DEG = 10.0;

// RT scheduling.
inline constexpr int              RT_CPU         = 3;
inline constexpr int              RT_PRIORITY    = 50;

// IPC.
inline constexpr std::string_view UDS_SOCKET     = "/run/godo/ctl.sock";

}  // namespace godo::config::defaults
