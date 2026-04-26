#pragma once

// Runtime configuration — see SYSTEM_DESIGN.md §11.2.
//
// Precedence (highest first):
//   1. CLI flags               (--ue-host, --ue-port, --freed-port, ...)
//   2. Environment variables   (GODO_UE_HOST, GODO_UE_PORT, ...)
//   3. TOML file               (path from $GODO_CONFIG_PATH, default
//                               /etc/godo/tracker.toml; optional)
//   4. Compile-time defaults   (config_defaults.hpp)
//
// Unknown TOML keys are rejected with an actionable error message.

#include <cstdint>
#include <string>

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
