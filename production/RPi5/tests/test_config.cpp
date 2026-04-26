// Config loader precedence chain: CLI > env > TOML > default.
// Unknown keys must be rejected with an actionable error.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "core/config.hpp"
#include "core/config_defaults.hpp"

using godo::core::Config;

namespace {

struct TempFile {
    std::filesystem::path path;
    ~TempFile() { std::error_code ec; std::filesystem::remove(path, ec); }
};

TempFile write_temp_toml(const std::string& body) {
    auto tmp = std::filesystem::temp_directory_path() /
               ("godo_cfg_" + std::to_string(::getpid()) + ".toml");
    std::ofstream f(tmp);
    f << body;
    f.close();
    return TempFile{tmp};
}

// Construct an argv array that outlives the parser call.
struct Argv {
    std::vector<std::string> storage;
    std::vector<char*>       argv;
    int argc = 0;

    Argv(std::initializer_list<std::string> items) {
        storage.push_back("godo_tracker_rt");      // argv[0]
        for (auto&& s : items) storage.push_back(s);
        for (auto& s : storage) argv.push_back(const_cast<char*>(s.c_str()));
        argv.push_back(nullptr);
        argc = static_cast<int>(storage.size());
    }
};

struct Env {
    std::vector<std::string> storage;
    std::vector<char*>       env;

    explicit Env(std::initializer_list<std::string> items) {
        for (auto&& s : items) storage.push_back(s);
        for (auto& s : storage) env.push_back(const_cast<char*>(s.c_str()));
        env.push_back(nullptr);
    }

    char** ptr() { return env.data(); }
};

}  // namespace

TEST_CASE("Config::make_default — wires the compile-time defaults") {
    Config c = Config::make_default();
    CHECK(c.ue_host      == std::string(godo::config::defaults::UE_HOST));
    CHECK(c.ue_port      == godo::config::defaults::UE_PORT);
    CHECK(c.lidar_port   == std::string(godo::config::defaults::LIDAR_PORT));
    CHECK(c.lidar_baud   == godo::config::defaults::LIDAR_BAUD);
    CHECK(c.freed_port   == std::string(godo::config::defaults::FREED_PORT));
    CHECK(c.freed_baud   == godo::config::defaults::FREED_BAUD);
    CHECK(c.t_ramp_ns    == godo::config::defaults::T_RAMP_NS);
    CHECK(c.deadband_mm  == godo::config::defaults::DEADBAND_MM);
    CHECK(c.deadband_deg == godo::config::defaults::DEADBAND_DEG);
    CHECK(c.rt_cpu       == godo::config::defaults::RT_CPU);
    CHECK(c.rt_priority  == godo::config::defaults::RT_PRIORITY);
    CHECK(c.uds_socket   == std::string(godo::config::defaults::UDS_SOCKET));
}

TEST_CASE("Config::load — TOML overrides defaults") {
    auto tmp = write_temp_toml(
        "[network]\n"
        "ue_host = \"10.1.2.3\"\n"
        "ue_port = 12345\n"
        "[smoother]\n"
        "t_ramp_ms = 250\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.ue_host   == "10.1.2.3");
    CHECK(c.ue_port   == 12345);
    CHECK(c.t_ramp_ns == 250'000'000LL);
}

TEST_CASE("Config::load — env overrides TOML") {
    auto tmp = write_temp_toml(
        "[network]\n"
        "ue_host = \"10.1.2.3\"\n"
    );
    Argv argv({});
    Env  env({
        "GODO_CONFIG_PATH=" + tmp.path.string(),
        "GODO_UE_HOST=192.168.99.99",
    });
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.ue_host == "192.168.99.99");
}

TEST_CASE("Config::load — CLI overrides env") {
    Argv argv({"--ue-host=172.16.0.7", "--ue-port", "9999"});
    Env  env({"GODO_UE_HOST=192.168.99.99"});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.ue_host == "172.16.0.7");
    CHECK(c.ue_port == 9999);
}

TEST_CASE("Config::load — unknown TOML key is rejected") {
    auto tmp = write_temp_toml(
        "[network]\n"
        "ue_host = \"10.1.2.3\"\n"
        "typo_key = 42\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — unknown CLI flag is rejected") {
    Argv argv({"--bogus=1"});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — missing GODO_CONFIG_PATH file is rejected") {
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=/does/not/exist/tracker.toml"});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — t_ramp_ms is converted to nanoseconds") {
    Argv argv({"--t-ramp-ms=125"});
    Env  env({});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.t_ramp_ns == 125'000'000LL);
}

// ---------------------------------------------------------------------------
// Phase 4-2 B Wave 1 — AMCL Tier-2 keys.
// Per the plan's M7 8-touchpoint table, every key gets at least a positive
// case (accept) and a negative case (reject). Negative pattern is shared
// across families with identical validation (sigma_*, particle counts).
// ---------------------------------------------------------------------------

TEST_CASE("Config::make_default — wires AMCL Tier-2 defaults") {
    Config c = Config::make_default();
    CHECK(c.amcl_map_path             == std::string(godo::config::defaults::AMCL_MAP_PATH));
    CHECK(c.amcl_origin_x_m           == godo::config::defaults::AMCL_ORIGIN_X_M);
    CHECK(c.amcl_origin_y_m           == godo::config::defaults::AMCL_ORIGIN_Y_M);
    CHECK(c.amcl_origin_yaw_deg       == godo::config::defaults::AMCL_ORIGIN_YAW_DEG);
    CHECK(c.amcl_particles_global_n   == godo::config::defaults::AMCL_PARTICLES_GLOBAL_N);
    CHECK(c.amcl_particles_local_n    == godo::config::defaults::AMCL_PARTICLES_LOCAL_N);
    CHECK(c.amcl_max_iters            == godo::config::defaults::AMCL_MAX_ITERS);
    CHECK(c.amcl_sigma_hit_m          == godo::config::defaults::AMCL_SIGMA_HIT_M);
    CHECK(c.amcl_sigma_xy_jitter_m    == godo::config::defaults::AMCL_SIGMA_XY_JITTER_M);
    CHECK(c.amcl_sigma_yaw_jitter_deg == godo::config::defaults::AMCL_SIGMA_YAW_JITTER_DEG);
    CHECK(c.amcl_sigma_seed_xy_m      == godo::config::defaults::AMCL_SIGMA_SEED_XY_M);
    CHECK(c.amcl_sigma_seed_yaw_deg   == godo::config::defaults::AMCL_SIGMA_SEED_YAW_DEG);
    CHECK(c.amcl_downsample_stride    == godo::config::defaults::AMCL_DOWNSAMPLE_STRIDE);
    CHECK(c.amcl_range_min_m          == godo::config::defaults::AMCL_RANGE_MIN_M);
    CHECK(c.amcl_range_max_m          == godo::config::defaults::AMCL_RANGE_MAX_M);
    CHECK(c.amcl_converge_xy_std_m    == godo::config::defaults::AMCL_CONVERGE_XY_STD_M);
    CHECK(c.amcl_converge_yaw_std_deg == godo::config::defaults::AMCL_CONVERGE_YAW_STD_DEG);
    CHECK(c.amcl_yaw_tripwire_deg     == godo::config::defaults::AMCL_YAW_TRIPWIRE_DEG);
    CHECK(c.amcl_trigger_poll_ms      == godo::config::defaults::AMCL_TRIGGER_POLL_MS);
    CHECK(c.amcl_seed                 == godo::config::defaults::AMCL_SEED);
}

TEST_CASE("Config::load — AMCL TOML round-trip (positive)") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "map_path = \"/tmp/godo/maps/test.pgm\"\n"
        "origin_x_m = 1.25\n"
        "origin_y_m = -2.5\n"
        "origin_yaw_deg = 30.0\n"
        "particles_global_n = 2000\n"
        "particles_local_n = 200\n"
        "max_iters = 10\n"
        "sigma_hit_m = 0.04\n"
        "sigma_xy_jitter_m = 0.003\n"
        "sigma_yaw_jitter_deg = 0.25\n"
        "sigma_seed_xy_m = 0.05\n"
        "sigma_seed_yaw_deg = 2.0\n"
        "downsample_stride = 4\n"
        "range_min_m = 0.20\n"
        "range_max_m = 8.0\n"
        "converge_xy_std_m = 0.01\n"
        "converge_yaw_std_deg = 0.5\n"
        "yaw_tripwire_deg = 3.0\n"
        "trigger_poll_ms = 100\n"
        "seed = 42\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.amcl_map_path             == "/tmp/godo/maps/test.pgm");
    CHECK(c.amcl_origin_x_m           == 1.25);
    CHECK(c.amcl_origin_y_m           == -2.5);
    CHECK(c.amcl_origin_yaw_deg       == 30.0);
    CHECK(c.amcl_particles_global_n   == 2000);
    CHECK(c.amcl_particles_local_n    == 200);
    CHECK(c.amcl_max_iters            == 10);
    CHECK(c.amcl_sigma_hit_m          == 0.04);
    CHECK(c.amcl_sigma_xy_jitter_m    == 0.003);
    CHECK(c.amcl_sigma_yaw_jitter_deg == 0.25);
    CHECK(c.amcl_sigma_seed_xy_m      == 0.05);
    CHECK(c.amcl_sigma_seed_yaw_deg   == 2.0);
    CHECK(c.amcl_downsample_stride    == 4);
    CHECK(c.amcl_range_min_m          == 0.20);
    CHECK(c.amcl_range_max_m          == 8.0);
    CHECK(c.amcl_converge_xy_std_m    == 0.01);
    CHECK(c.amcl_converge_yaw_std_deg == 0.5);
    CHECK(c.amcl_yaw_tripwire_deg     == 3.0);
    CHECK(c.amcl_trigger_poll_ms      == 100);
    CHECK(c.amcl_seed                 == 42u);
}

TEST_CASE("Config::load — AMCL CLI round-trip (positive)") {
    Argv argv({
        "--amcl-map-path=/srv/godo/maps/cli.pgm",
        "--amcl-origin-x-m=0.7",
        "--amcl-particles-global-n=1500",
        "--amcl-particles-local-n", "150",
        "--amcl-sigma-hit-m=0.025",
        "--amcl-seed=7",
    });
    Env  env({});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.amcl_map_path           == "/srv/godo/maps/cli.pgm");
    CHECK(c.amcl_origin_x_m         == 0.7);
    CHECK(c.amcl_particles_global_n == 1500);
    CHECK(c.amcl_particles_local_n  == 150);
    CHECK(c.amcl_sigma_hit_m        == 0.025);
    CHECK(c.amcl_seed               == 7u);
}

TEST_CASE("Config::load — AMCL env round-trip (positive)") {
    Argv argv({});
    Env  env({
        "GODO_AMCL_PARTICLES_GLOBAL_N=750",
        "GODO_AMCL_MAX_ITERS=12",
        "GODO_AMCL_RANGE_MAX_M=15.0",
    });
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.amcl_particles_global_n == 750);
    CHECK(c.amcl_max_iters          == 12);
    CHECK(c.amcl_range_max_m        == 15.0);
}

TEST_CASE("Config::load — AMCL CLI overrides env overrides TOML for AMCL keys") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "particles_global_n = 1000\n"
        "max_iters = 20\n"
    );
    Argv argv({"--amcl-particles-global-n=4000"});
    Env  env({
        "GODO_CONFIG_PATH=" + tmp.path.string(),
        "GODO_AMCL_PARTICLES_GLOBAL_N=2000",  // overridden by CLI
        "GODO_AMCL_MAX_ITERS=15",             // overrides TOML
    });
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.amcl_particles_global_n == 4000);
    CHECK(c.amcl_max_iters          == 15);
}

TEST_CASE("Config::load — empty amcl_map_path is rejected") {
    Argv argv({"--amcl-map-path="});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — non-positive particle count is rejected (covers global/local)") {
    {
        Argv argv({"--amcl-particles-global-n=0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-particles-local-n=-3"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-max-iters=0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-downsample-stride=0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-trigger-poll-ms=0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — particle count over PARTICLE_BUFFER_MAX is rejected") {
    Argv argv({"--amcl-particles-global-n=20000"});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — non-positive sigma values are rejected (shared family pattern)") {
    // One representative per sigma_* family: every sigma key uses the
    // identical require_positive_double validation, so rejecting one is
    // a contract proxy for rejecting the rest.
    {
        Argv argv({"--amcl-sigma-hit-m=0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-sigma-xy-jitter-m=-0.001"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-sigma-yaw-jitter-deg=-1"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-sigma-seed-xy-m=0.0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-sigma-seed-yaw-deg=-2"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — convergence thresholds must be positive") {
    {
        Argv argv({"--amcl-converge-xy-std-m=0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-converge-yaw-std-deg=-0.1"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — range_max must exceed range_min") {
    Argv argv({"--amcl-range-min-m=5.0", "--amcl-range-max-m=3.0"});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — yaw_tripwire_deg may be zero but not negative") {
    {
        Argv argv({"--amcl-yaw-tripwire-deg=0"});
        Env  env({});
        Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
        CHECK(c.amcl_yaw_tripwire_deg == 0.0);
    }
    {
        Argv argv({"--amcl-yaw-tripwire-deg=-1"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — amcl_seed must be non-negative") {
    {
        Argv argv({"--amcl-seed=0"});  // 0 is the "time-derived" sentinel
        Env  env({});
        Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
        CHECK(c.amcl_seed == 0u);
    }
    {
        Argv argv({"--amcl-seed=-5"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — unknown amcl.* TOML key is rejected") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "totally_not_a_key = 1\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}
