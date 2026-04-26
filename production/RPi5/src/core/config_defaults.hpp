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

// AMCL Tier-2 tunables. Operators override these via TOML / env / CLI;
// see SYSTEM_DESIGN.md §11.2 and the per-key 8-touchpoint table in
// .claude/tmp/plan_phase4_2_b.md.
inline constexpr std::string_view AMCL_MAP_PATH            = "/etc/godo/maps/studio_v1.pgm";  // map files installed by ops
inline constexpr double           AMCL_ORIGIN_X_M          = 0.0;     // calibration origin, X
inline constexpr double           AMCL_ORIGIN_Y_M          = 0.0;     // calibration origin, Y
inline constexpr double           AMCL_ORIGIN_YAW_DEG      = 0.0;     // calibration origin yaw; tripwire anchor
inline constexpr int              AMCL_PARTICLES_GLOBAL_N  = 5000;    // first-run global localization
inline constexpr int              AMCL_PARTICLES_LOCAL_N   = 500;     // subsequent runs around last_pose
inline constexpr int              AMCL_MAX_ITERS           = 25;      // converge() upper bound for OneShot
inline constexpr double           AMCL_SIGMA_HIT_M         = 0.050;   // C1 ±30 mm spec inflated for long range
inline constexpr double           AMCL_SIGMA_XY_JITTER_M   = 0.005;   // motion-model σ for static crane (5 mm)
inline constexpr double           AMCL_SIGMA_YAW_JITTER_DEG = 0.5;    // motion-model yaw σ
inline constexpr double           AMCL_SIGMA_SEED_XY_M     = 0.10;    // seed cloud spread for seed_around
inline constexpr double           AMCL_SIGMA_SEED_YAW_DEG  = 5.0;     // seed cloud yaw spread for seed_around
inline constexpr int              AMCL_DOWNSAMPLE_STRIDE   = 2;       // even-sample LiDAR decimation (≥360 beams kept)
inline constexpr double           AMCL_RANGE_MIN_M         = 0.15;    // discard sub-15 cm returns (LiDAR housing)
inline constexpr double           AMCL_RANGE_MAX_M         = 12.0;    // C1 quality-degraded beyond ~12 m
inline constexpr double           AMCL_CONVERGE_XY_STD_M   = 0.015;   // 1.5 cm; tighter than 1-2 cm UE budget
inline constexpr double           AMCL_CONVERGE_YAW_STD_DEG = 0.3;    // circular std
inline constexpr double           AMCL_YAW_TRIPWIRE_DEG    = 5.0;     // vs origin_yaw_deg; flags suspected base rotation
inline constexpr int              AMCL_TRIGGER_POLL_MS     = 50;      // idle wake cadence for cold writer
inline constexpr std::uint64_t    AMCL_SEED                = 0;       // 0 = time-derived; non-zero = deterministic

// Phase 4-2 D — Live-mode motion-model σ pair. The OneShot σ pair
// (AMCL_SIGMA_XY_JITTER_M / _YAW_JITTER_DEG above) was tuned for a static
// crane; Live mode tracks a base that may move at up to ~30 cm/s, so the
// per-scan jitter must be wider. 0.015 m / 1.5° gives ~2σ coverage of the
// expected 100 ms inter-scan motion. See plan §"Deviations" rationale.
inline constexpr double           AMCL_SIGMA_XY_JITTER_LIVE_M    = 0.015;  // 15 mm
inline constexpr double           AMCL_SIGMA_YAW_JITTER_LIVE_DEG = 1.5;    // 3× OneShot

// Phase 4-2 D — GPIO BCM pin assignments. BCM 16 (calibrate button) and
// BCM 20 (live-toggle button); active-low against PULL_UP. See
// production/RPi5/doc/gpio_wiring.md (Wave B).
inline constexpr int              GPIO_CALIBRATE_PIN       = 16;
inline constexpr int              GPIO_LIVE_TOGGLE_PIN     = 20;

}  // namespace godo::config::defaults
