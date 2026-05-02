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
// issue#12: T_RAMP_NS lowered 500 ms → 100 ms after operator HIL approval.
// Live-primary architecture (SYSTEM_DESIGN.md §6.4): at 10 Hz LiDAR cadence,
// a 1-tick ramp (~100 ms) hides per-tick step changes without visible lag.
// The 500 ms value was tuned for the OneShot UX which inherits the
// smoother as a side-benefit; OneShot is operator-triggered and rare, so
// its comfort no longer dominates the trade-off. Operators may restore
// the legacy 500 ms via `smoother.t_ramp_ms = 500` in tracker.toml.
inline constexpr int64_t          T_RAMP_NS      = 100'000'000;   // 100 ms
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

// issue#5 — Live mode pipelined-hint kernel (default ON post-PR-#62 HIL
// approval, 2026-05-01 KST). HIL evidence: Live drift ~4 m → ±5 cm
// stationary / ±10 cm in motion; yaw ~90° → ±1°. R1 wall-clock budget
// validated (iters mode=16, max=21, mean=15.7 of 30-iter ceiling).
// Operators can roll back to the legacy `Amcl::step` per-scan kernel by
// setting `amcl.live_carry_pose_as_hint = 0` in tracker.toml + restart.
//
// σ derivation: operator memory cites "50 ms × 1 m/s = 50 mm"; actual
// LiDAR tick is ~100 ms (10 Hz). At realistic 30 cm/s crane peak,
// 100 ms tick × 30 cm/s = 30 mm displacement, well within 50 mm σ.
// Default is conservative-but-comfortable; operators can widen to
// 0.10 m via tracker.toml if HIL shows wider drift. σ_yaw 5° is
// conservative for a non-rotating SHOTOKU dolly base (see CLAUDE.md §1).
//
// Schedule rationale: with a tight carry-hint the OneShot anneal's wide-σ
// phases (1.0, 0.5) waste depth — basin lock is automatic at σ=0.05 m.
// Three phases × ~10 ms ≈ 30 ms confines per-tick wall-clock to ~1/3 of
// the 100 ms LiDAR period, leaving headroom for queue depth. Operators
// can lengthen via tracker.toml if HIL shows undersettling.
//
// Bool-as-Int convention: `live_carry_pose_as_hint` is encoded as
// CONFIG_SCHEMA `Int` with `min=0, max=1, default_repr="0|1"` until a
// future PR adds `ValueType::Bool`. Precedent-setting key.
inline constexpr bool             LIVE_CARRY_POSE_AS_HINT          = true;
inline constexpr double           AMCL_LIVE_CARRY_SIGMA_XY_M       = 0.050;
inline constexpr double           AMCL_LIVE_CARRY_SIGMA_YAW_DEG    = 5.0;
inline constexpr std::string_view AMCL_LIVE_CARRY_SCHEDULE_M       =
    "0.2,0.1,0.05";

// issue#12 — webctl SSE stream cadence (Hz). Tracker stores these in
// Config and emits them through the apply.cpp / render_toml round-trip
// so the SPA's schema-driven Config tab can edit them, but no tracker
// logic path reads the stored value. The actual consumer is godo-webctl
// which reads `/var/lib/godo/tracker.toml` directly via
// `godo_webctl/webctl_toml.py`. See production/RPi5/CODEBASE.md
// invariant (r). Range [1, 60] Hz mirrors the schema row bounds.
inline constexpr int              WEBCTL_POSE_STREAM_HZ_DEFAULT    = 30;
inline constexpr int              WEBCTL_SCAN_STREAM_HZ_DEFAULT    = 30;

// issue#14 Maj-1 — webctl-owned mapping-stop timing ladder defaults.
// Defaults pin the SIGTERM→SIGKILL grace ladder. The ordering invariant
//   docker_stop_grace (20) < systemd_stop_timeout (30) < webctl_stop_timeout (35)
// is what gives nav2 `map_saver_cli` enough time to atomic-rename the
// PGM/YAML pair before any layer escalates to SIGKILL — the difference
// between a complete lifetime asset and a torn write. install.sh
// sed-substitutes the docker grace + systemd timeout into the unit file;
// webctl's `mapping.stop()` reads `webctl_stop_timeout` from
// `cfg.mapping_webctl_stop_timeout_s` (Settings, mirrored from the
// `[webctl]` section of `tracker.toml` via `webctl_toml.py`). See
// production/RPi5/CODEBASE.md invariant (r) and godo-webctl/CODEBASE.md
// `mapping-timing-ladder` invariant.
inline constexpr int              WEBCTL_MAPPING_DOCKER_STOP_GRACE_S_DEFAULT   = 20;
inline constexpr int              WEBCTL_MAPPING_SYSTEMD_STOP_TIMEOUT_S_DEFAULT = 30;
inline constexpr int              WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S_DEFAULT = 35;

}  // namespace godo::config::defaults
