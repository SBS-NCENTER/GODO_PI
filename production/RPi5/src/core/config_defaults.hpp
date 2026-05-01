#pragma once

// Tier-2 runtime-tunable defaults. Operators override these through
// /var/lib/godo/tracker.toml, GODO_* environment variables, or CLI flags.
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

// Single-instance pidfile lock target. main() acquires
// fcntl(F_SETLK, F_WRLCK) here BEFORE any thread spawn. Path MUST live
// on a local FS — tmpfs /run/godo is the project default; NFS is
// unsupported (POSIX advisory lock semantics differ). Override via
// CLI --pidfile, env GODO_TRACKER_PIDFILE, or TOML key
// ipc.tracker_pidfile. See production/RPi5/CODEBASE.md invariant (l).
inline constexpr std::string_view TRACKER_PIDFILE_DEFAULT =
    "/run/godo/godo-tracker.pid";

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

// Track D-5 — Coarse-to-fine sigma_hit annealing for OneShot AMCL.
// Schedule starts wide (σ=1.0 locks the basin per the 21:00 KST sweep:
// 2/10 single-basin) and narrows to the production default σ=0.05 for
// final cm-scale precision. Empirical motivation:
// .claude/memory/project_amcl_sigma_sweep_2026-04-29.md.
//
// AMCL_SIGMA_SEED_XY_SCHEDULE_M is paired LENGTH-MATCHED with
// AMCL_SIGMA_HIT_SCHEDULE_M; the first entry is the sentinel "-" because
// phase 0 uses seed_global (no seed σ). Entries 1..N-1 must be positive
// doubles. Live mode is unaffected — it uses the static AMCL_SIGMA_HIT_M
// field, which the cold writer rebuilds at every OneShot completion.
inline constexpr std::string_view AMCL_SIGMA_HIT_SCHEDULE_M      =
    "1.0,0.5,0.2,0.1,0.05";
inline constexpr std::string_view AMCL_SIGMA_SEED_XY_SCHEDULE_M  =
    "-,0.10,0.05,0.03,0.02";
inline constexpr int              AMCL_ANNEAL_ITERS_PER_PHASE    = 10;

// Phase 4-2 D — GPIO BCM pin assignments. BCM 16 (calibrate button) and
// BCM 20 (live-toggle button); active-low against PULL_UP. See
// production/RPi5/doc/gpio_wiring.md (Wave B).
inline constexpr int              GPIO_CALIBRATE_PIN       = 16;
inline constexpr int              GPIO_LIVE_TOGGLE_PIN     = 20;

// issue#3 — calibrate pose-hint default σ (recalibrate class). When the
// operator places a hint via webctl WITHOUT supplying explicit σ
// overrides, the cold writer falls back to these.
//
// Defaults rationale (plan §R1, §R2): test4/test5 HIL showed one-shot
// (x, y) error of ~0.5 m and yaw error of ~5–10°; live mode showed
// (x, y) error of ~4 m and yaw ~90°. σ_xy = 0.50 m (~10 grid cells at
// 0.05 m/cell) gives ±2σ = 1.0 m radius — comfortably covers the
// observed 0.5 m one-shot bias and the operator's coarse click
// precision. σ_yaw = 20° covers ±40°, well below the 90° false-basin
// separation. Both Tier-2 keys; HIL-tunable down later if these prove
// over-permissive in practice.
inline constexpr double           AMCL_HINT_SIGMA_XY_M_DEFAULT     = 0.50;
inline constexpr double           AMCL_HINT_SIGMA_YAW_DEG_DEFAULT  = 20.0;

}  // namespace godo::config::defaults
