#pragma once

// Runtime configuration — see SYSTEM_DESIGN.md §11.2.
//
// Precedence (highest first):
//   1. CLI flags               (--ue-host, --ue-port, --freed-port, ...)
//   2. Environment variables   (GODO_UE_HOST, GODO_UE_PORT, ...)
//   3. TOML file               (path from $GODO_CONFIG_PATH, default
//                               /var/lib/godo/tracker.toml; optional)
//   4. Compile-time defaults   (config_defaults.hpp)
//
// Unknown TOML keys are rejected with an actionable error message.

#include <cstdint>
#include <string>
#include <vector>

namespace godo::core {

struct Config {
    // Network.
    std::string ue_host;
    int         ue_port{};

    // Serial.
    std::string lidar_port;
    int         lidar_baud{};
    std::string freed_port;
    int         freed_baud{};

    // Smoother & deadband.
    std::int64_t t_ramp_ns{};
    double       deadband_mm{};
    double       deadband_deg{};
    double       divergence_mm{};
    double       divergence_deg{};

    // RT.
    int rt_cpu{};
    int rt_priority{};

    // IPC.
    std::string uds_socket;
    std::string tracker_pidfile;

    // AMCL — Phase 4-2 B Tier-2 tunables (see config_defaults.hpp).
    std::string   amcl_map_path;
    double        amcl_origin_x_m{};
    double        amcl_origin_y_m{};
    double        amcl_origin_yaw_deg{};
    int           amcl_particles_global_n{};
    int           amcl_particles_local_n{};
    int           amcl_max_iters{};
    double        amcl_sigma_hit_m{};
    double        amcl_sigma_xy_jitter_m{};
    double        amcl_sigma_yaw_jitter_deg{};
    double        amcl_sigma_seed_xy_m{};
    double        amcl_sigma_seed_yaw_deg{};
    int           amcl_downsample_stride{};
    double        amcl_range_min_m{};
    double        amcl_range_max_m{};
    double        amcl_converge_xy_std_m{};
    double        amcl_converge_yaw_std_deg{};
    double        amcl_yaw_tripwire_deg{};
    int           amcl_trigger_poll_ms{};
    std::uint64_t amcl_seed{};

    // Phase 4-2 D — Live mode motion-model σ pair. OneShot uses the
    // amcl_sigma_xy_jitter_m / _yaw_jitter_deg pair above (5 mm / 0.5°);
    // Live mode uses these wider values (15 mm / 1.5°) to track a base
    // that may move at ~30 cm/s while still letting the particle cloud
    // refine on each scan.
    double        amcl_sigma_xy_jitter_live_m{};
    double        amcl_sigma_yaw_jitter_live_deg{};

    // Phase 4-2 D — GPIO BCM pin assignments (Wave A lands these so Wave B
    // can read them; consumers in src/gpio/ arrive in Wave B).
    int           gpio_calibrate_pin{};
    int           gpio_live_toggle_pin{};

    // Track D-5 — Coarse-to-fine sigma_hit annealing for OneShot AMCL.
    // `amcl_sigma_hit_schedule_m` lists the per-phase σ values; phase 0 is
    // wide (basin lock), the last phase is the production σ = amcl_sigma_hit_m.
    // `amcl_sigma_seed_xy_schedule_m` is length-matched: the first entry is
    // a sentinel NaN ("-") because phase 0 uses seed_global; entries 1..N-1
    // are the seed_around σ_xy values for phases 1..N-1.
    // `amcl_anneal_iters_per_phase` is the per-phase upper-bound iteration
    // count; default 10. Schedule length 1 falls through to the same path —
    // operators wanting pre-Track-D-5 behaviour set BOTH
    // `amcl.sigma_hit_schedule_m = "0.05"` AND
    // `amcl.anneal_iters_per_phase = 25`.
    std::vector<double> amcl_sigma_hit_schedule_m;
    std::vector<double> amcl_sigma_seed_xy_schedule_m;
    int                 amcl_anneal_iters_per_phase{};

    // issue#3 — calibrate pose-hint default σ (recalibrate class).
    // Cold writer falls back to these when the UDS hint payload omits
    // sigma_xy_m / sigma_yaw_deg overrides (i.e. the operator placed a
    // hint position+yaw without touching the σ inputs). Defaults match
    // config_defaults.hpp::AMCL_HINT_SIGMA_*_DEFAULT (0.50 m / 20°).
    double              amcl_hint_sigma_xy_m_default{};
    double              amcl_hint_sigma_yaw_deg_default{};

    // issue#5 — Live mode pipelined-hint kernel selector + per-tick σ +
    // schedule (recalibrate class). When `live_carry_pose_as_hint` is true
    // the cold writer routes Live ticks through `run_live_iteration_pipelined`
    // (sequential `converge_anneal_with_hint` driven by the previous-tick
    // pose) instead of the bare `Amcl::step` rollback path. σ defaults are
    // tight (matched to inter-tick crane-base drift, not padded for AMCL
    // search comfort, per `project_hint_strong_command_semantics.md`); the
    // schedule is short (avoids the wide-σ phases the OneShot anneal needs
    // for basin lock — a tight carry-hint already locks the basin). Default
    // OFF in this PR; HIL operator flips on via tracker.toml + restart, then
    // a follow-up PR flips the compile-time default. See
    // production/RPi5/CODEBASE.md invariant (q).
    bool                live_carry_pose_as_hint{};
    double              amcl_live_carry_sigma_xy_m{};
    double              amcl_live_carry_sigma_yaw_deg{};
    std::vector<double> amcl_live_carry_schedule_m;

    // issue#12 — webctl SSE stream cadence (Hz). Tracker stores these
    // verbatim through the apply / render_toml round-trip so the SPA's
    // Config tab can edit them via /api/config. No tracker logic path
    // reads the stored value — godo-webctl is the sole consumer, reading
    // /var/lib/godo/tracker.toml directly via webctl_toml.py. See
    // production/RPi5/CODEBASE.md invariant (r). Reload class is Restart
    // because webctl restarts to pick up the new value (the tracker has
    // no live-reload responsibility for these fields).
    int                 webctl_pose_stream_hz{};
    int                 webctl_scan_stream_hz{};

    // Build a Config with defaults applied from core/config_defaults.hpp.
    static Config make_default();

    // Load effective config. Throws std::runtime_error on any parse or
    // validation failure — caller decides whether to print-and-exit.
    //
    // argv/envp may be null; passing them in lets CLI and env overrides
    // apply. envp is searched linearly (small key set, set-and-forget).
    static Config load(int argc, char** argv, char** envp);
};

}  // namespace godo::core
