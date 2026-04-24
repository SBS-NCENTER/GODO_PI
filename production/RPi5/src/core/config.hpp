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
