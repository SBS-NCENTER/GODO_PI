// Config loader precedence chain: CLI > env > TOML > default.
// Unknown keys must be rejected with an actionable error.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
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
    std::filesystem::path    auto_toml;  // empty if test supplied its own

    explicit Env(std::initializer_list<std::string> items) {
        bool has_config_path = false;
        for (auto&& s : items) {
            if (s.rfind("GODO_CONFIG_PATH=", 0) == 0) has_config_path = true;
            storage.push_back(s);
        }
        if (!has_config_path) {
            // Self-isolation: when the test does not supply
            // GODO_CONFIG_PATH explicitly, synthesise an empty
            // per-test-case TOML and point at it. Without this the
            // Config::load fallback would hit the developer host's
            // /var/lib/godo/tracker.toml — which on a host that has
            // exercised features like issue#3's hint-σ keys carries
            // entries the in-tree Config struct may not yet recognise,
            // causing every test_config case to throw with
            // "unknown TOML key 'amcl.hint_sigma_xy_m_default'" or
            // similar. Production paths reach this fallback only when
            // the tracker is intentionally configured against a host
            // with matched binary + TOML; tests must NOT.
            char buf[64];
            std::snprintf(buf, sizeof(buf), "godo_test_env_%d_%p.toml",
                          static_cast<int>(::getpid()),
                          static_cast<void*>(this));
            auto_toml = std::filesystem::temp_directory_path() / buf;
            std::ofstream(auto_toml).close();  // create empty file
            storage.push_back("GODO_CONFIG_PATH=" + auto_toml.string());
        }
        for (auto& s : storage) env.push_back(const_cast<char*>(s.c_str()));
        env.push_back(nullptr);
    }

    ~Env() {
        if (!auto_toml.empty()) {
            std::error_code ec;
            std::filesystem::remove(auto_toml, ec);
        }
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

// ---------------------------------------------------------------------------
// Phase 4-2 D Wave A — Live σ pair + GPIO pin pair (4 new Tier-2 keys).
// 8-touchpoint coverage: defaults wired, TOML round-trip, env round-trip,
// CLI round-trip, validation rejects out-of-range. GPIO pin range [0, 27]
// uses the new `validate_gpio` path; σ pair reuses `require_positive_double`.
// ---------------------------------------------------------------------------

TEST_CASE("Config::make_default — wires Phase 4-2 D Live σ + GPIO pin defaults") {
    Config c = Config::make_default();
    CHECK(c.amcl_sigma_xy_jitter_live_m    == godo::config::defaults::AMCL_SIGMA_XY_JITTER_LIVE_M);
    CHECK(c.amcl_sigma_yaw_jitter_live_deg == godo::config::defaults::AMCL_SIGMA_YAW_JITTER_LIVE_DEG);
    CHECK(c.gpio_calibrate_pin             == godo::config::defaults::GPIO_CALIBRATE_PIN);
    CHECK(c.gpio_live_toggle_pin           == godo::config::defaults::GPIO_LIVE_TOGGLE_PIN);
}

TEST_CASE("Config::load — Phase 4-2 D keys TOML round-trip (positive)") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "sigma_xy_jitter_live_m = 0.020\n"
        "sigma_yaw_jitter_live_deg = 2.5\n"
        "[gpio]\n"
        "calibrate_pin = 17\n"
        "live_toggle_pin = 22\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.amcl_sigma_xy_jitter_live_m    == 0.020);
    CHECK(c.amcl_sigma_yaw_jitter_live_deg == 2.5);
    CHECK(c.gpio_calibrate_pin             == 17);
    CHECK(c.gpio_live_toggle_pin           == 22);
}

TEST_CASE("Config::load — Phase 4-2 D keys env round-trip (positive)") {
    Argv argv({});
    Env  env({
        "GODO_AMCL_SIGMA_XY_JITTER_LIVE_M=0.025",
        "GODO_AMCL_SIGMA_YAW_JITTER_LIVE_DEG=3.0",
        "GODO_GPIO_CALIBRATE_PIN=5",
        "GODO_GPIO_LIVE_TOGGLE_PIN=6",
    });
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.amcl_sigma_xy_jitter_live_m    == 0.025);
    CHECK(c.amcl_sigma_yaw_jitter_live_deg == 3.0);
    CHECK(c.gpio_calibrate_pin             == 5);
    CHECK(c.gpio_live_toggle_pin           == 6);
}

TEST_CASE("Config::load — Phase 4-2 D keys CLI round-trip (positive)") {
    Argv argv({
        "--amcl-sigma-xy-jitter-live-m=0.030",
        "--amcl-sigma-yaw-jitter-live-deg", "1.75",
        "--gpio-calibrate-pin=12",
        "--gpio-live-toggle-pin=13",
    });
    Env  env({});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.amcl_sigma_xy_jitter_live_m    == 0.030);
    CHECK(c.amcl_sigma_yaw_jitter_live_deg == 1.75);
    CHECK(c.gpio_calibrate_pin             == 12);
    CHECK(c.gpio_live_toggle_pin           == 13);
}

TEST_CASE("Config::load — non-positive Live σ values are rejected") {
    {
        Argv argv({"--amcl-sigma-xy-jitter-live-m=0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-sigma-xy-jitter-live-m=-0.001"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-sigma-yaw-jitter-live-deg=0"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--amcl-sigma-yaw-jitter-live-deg=-1"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — out-of-range GPIO pins are rejected") {
    // Pi 5 BCM range is [0, 27] (GPIO_MAX_BCM_PIN). Cover both bounds.
    {
        Argv argv({"--gpio-calibrate-pin=-1"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--gpio-calibrate-pin=28"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--gpio-live-toggle-pin=-1"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({"--gpio-live-toggle-pin=28"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — GPIO pin boundary values 0 and 27 are accepted") {
    Argv argv({"--gpio-calibrate-pin=0", "--gpio-live-toggle-pin=27"});
    Env  env({});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.gpio_calibrate_pin   == 0);
    CHECK(c.gpio_live_toggle_pin == 27);
}

TEST_CASE("Config::load — unknown gpio.* TOML key is rejected") {
    auto tmp = write_temp_toml(
        "[gpio]\n"
        "phantom_pin = 9\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

// ---------------------------------------------------------------------------
// Track D-5 — sigma_hit annealing schedule + seed_xy schedule + iters
// per phase. Per Mode-A T4: bound bump test (sigma_hit_m=1.5 accepted).
// ---------------------------------------------------------------------------

TEST_CASE("Config::make_default — wires Track D-5 annealing defaults") {
    Config c = Config::make_default();
    REQUIRE(c.amcl_sigma_hit_schedule_m.size() == 5u);
    CHECK(c.amcl_sigma_hit_schedule_m[0] == 1.0);
    CHECK(c.amcl_sigma_hit_schedule_m[1] == 0.5);
    CHECK(c.amcl_sigma_hit_schedule_m[2] == 0.2);
    CHECK(c.amcl_sigma_hit_schedule_m[3] == 0.1);
    CHECK(c.amcl_sigma_hit_schedule_m[4] == 0.05);
    REQUIRE(c.amcl_sigma_seed_xy_schedule_m.size() == 5u);
    // First entry is the NaN sentinel (phase 0 = seed_global).
    CHECK(std::isnan(c.amcl_sigma_seed_xy_schedule_m[0]));
    CHECK(c.amcl_sigma_seed_xy_schedule_m[1] == 0.10);
    CHECK(c.amcl_sigma_seed_xy_schedule_m[2] == 0.05);
    CHECK(c.amcl_sigma_seed_xy_schedule_m[3] == 0.03);
    CHECK(c.amcl_sigma_seed_xy_schedule_m[4] == 0.02);
    CHECK(c.amcl_anneal_iters_per_phase == 10);
}

TEST_CASE("Config::load — Track D-5 schedule TOML round-trip (positive)") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "sigma_hit_schedule_m = \"2.0,1.0,0.5,0.05\"\n"
        "sigma_seed_xy_schedule_m = \"-,0.20,0.10,0.05\"\n"
        "anneal_iters_per_phase = 15\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    REQUIRE(c.amcl_sigma_hit_schedule_m.size() == 4u);
    CHECK(c.amcl_sigma_hit_schedule_m[0] == 2.0);
    CHECK(c.amcl_sigma_hit_schedule_m[3] == 0.05);
    REQUIRE(c.amcl_sigma_seed_xy_schedule_m.size() == 4u);
    CHECK(std::isnan(c.amcl_sigma_seed_xy_schedule_m[0]));
    CHECK(c.amcl_sigma_seed_xy_schedule_m[1] == 0.20);
    CHECK(c.amcl_anneal_iters_per_phase == 15);
}

TEST_CASE("Config::load — Track D-5 length-1 schedule (single-phase annealing)") {
    Argv argv({"--amcl-sigma-hit-schedule-m=0.05",
               "--amcl-sigma-seed-xy-schedule-m=-",
               "--amcl-anneal-iters-per-phase=25"});
    Env  env({});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    REQUIRE(c.amcl_sigma_hit_schedule_m.size() == 1u);
    CHECK(c.amcl_sigma_hit_schedule_m[0] == 0.05);
    REQUIRE(c.amcl_sigma_seed_xy_schedule_m.size() == 1u);
    CHECK(std::isnan(c.amcl_sigma_seed_xy_schedule_m[0]));
    CHECK(c.amcl_anneal_iters_per_phase == 25);
}

TEST_CASE("Config::load — Track D-5 non-monotonic schedule rejected") {
    // Second entry is NOT < first.
    Argv argv({"--amcl-sigma-hit-schedule-m=0.5,1.0,0.05",
               "--amcl-sigma-seed-xy-schedule-m=-,0.10,0.05"});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — Track D-5 schedule out-of-range entry rejected") {
    // 6.0 exceeds the [0.005, 5.0] bound.
    Argv argv({"--amcl-sigma-hit-schedule-m=6.0,0.05",
               "--amcl-sigma-seed-xy-schedule-m=-,0.10"});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — Track D-5 empty schedule rejected") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "sigma_hit_schedule_m = \"\"\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — Track D-5 length mismatch between paired schedules rejected") {
    Argv argv({"--amcl-sigma-hit-schedule-m=1.0,0.5,0.05",
               "--amcl-sigma-seed-xy-schedule-m=-,0.10"});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — Track D-5 sigma_seed_xy_schedule first entry must be sentinel") {
    Argv argv({"--amcl-sigma-hit-schedule-m=1.0,0.05",
               "--amcl-sigma-seed-xy-schedule-m=0.10,0.05"});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — Track D-5 anneal_iters_per_phase = 0 rejected") {
    Argv argv({"--amcl-anneal-iters-per-phase=0"});
    Env  env({});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

TEST_CASE("Config::load — Track D-5 sigma_hit_m bound bump (1.5 accepted, 5.01 rejected)") {
    // Mode-A T4: pin that the bound was actually loosened, not just
    // left at 1.0 with a typo.
    {
        // 1.5 was REJECTED under the old [0.005, 1.0] bound; must now be
        // accepted under the bumped [0.005, 5.0] bound.
        Argv argv({"--amcl-sigma-hit-m=1.5"});
        Env  env({});
        Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
        CHECK(c.amcl_sigma_hit_m == 1.5);
    }
    // The schema-side bound is enforced by validate.cpp on apply_set;
    // Config::load itself only require_positive_double, so 5.01 here is
    // accepted. The schema-bound check belongs to test_config_validate.
    // The bound-check pin therefore lives in the schema test itself.
}

// ---------------------------------------------------------------------------
// issue#5 — Live pipelined-hint kernel keys (4 new Tier-2 entries).
// Every key gets at least one positive (round-trip) and one negative
// (range / type) case. Bool-as-Int wire shape: TOML accepts true/false
// AND 0/1; env + CLI accept 0/1/true/false (case-insensitive).
// ---------------------------------------------------------------------------

TEST_CASE("Config::make_default — wires issue#5 Live carry-hint defaults") {
    Config c = Config::make_default();
    CHECK(c.live_carry_pose_as_hint        ==
          godo::config::defaults::LIVE_CARRY_POSE_AS_HINT);
    CHECK(c.amcl_live_carry_sigma_xy_m     ==
          godo::config::defaults::AMCL_LIVE_CARRY_SIGMA_XY_M);
    CHECK(c.amcl_live_carry_sigma_yaw_deg  ==
          godo::config::defaults::AMCL_LIVE_CARRY_SIGMA_YAW_DEG);
    REQUIRE(c.amcl_live_carry_schedule_m.size() == 3u);
    CHECK(c.amcl_live_carry_schedule_m[0] == 0.2);
    CHECK(c.amcl_live_carry_schedule_m[1] == 0.1);
    CHECK(c.amcl_live_carry_schedule_m[2] == 0.05);
    // issue#5 follow-up: default flipped 0 → 1 post-PR-#62 HIL approval.
    CHECK(c.live_carry_pose_as_hint == true);
}

TEST_CASE("Config::load — issue#5 Live carry-hint TOML round-trip (positive)") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "live_carry_pose_as_hint = true\n"
        "live_carry_sigma_xy_m = 0.07\n"
        "live_carry_sigma_yaw_deg = 4.0\n"
        "live_carry_schedule_m = \"0.3,0.1,0.05\"\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.live_carry_pose_as_hint        == true);
    CHECK(c.amcl_live_carry_sigma_xy_m     == 0.07);
    CHECK(c.amcl_live_carry_sigma_yaw_deg  == 4.0);
    REQUIRE(c.amcl_live_carry_schedule_m.size() == 3u);
    CHECK(c.amcl_live_carry_schedule_m[0] == 0.3);
}

TEST_CASE("Config::load — issue#5 Live carry-hint TOML accepts 0/1 for bool key") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "live_carry_pose_as_hint = 1\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.live_carry_pose_as_hint == true);
}

TEST_CASE("Config::load — issue#5 Live carry-hint env round-trip (positive)") {
    Argv argv({});
    Env  env({
        "GODO_LIVE_CARRY_POSE_AS_HINT=true",
        "GODO_AMCL_LIVE_CARRY_SIGMA_XY_M=0.08",
        "GODO_AMCL_LIVE_CARRY_SIGMA_YAW_DEG=3.5",
        "GODO_AMCL_LIVE_CARRY_SCHEDULE_M=0.4,0.2,0.1,0.05",
    });
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.live_carry_pose_as_hint        == true);
    CHECK(c.amcl_live_carry_sigma_xy_m     == 0.08);
    CHECK(c.amcl_live_carry_sigma_yaw_deg  == 3.5);
    REQUIRE(c.amcl_live_carry_schedule_m.size() == 4u);
}

TEST_CASE("Config::load — issue#5 Live carry-hint CLI round-trip (positive)") {
    Argv argv({
        "--live-carry-pose-as-hint=true",
        "--amcl-live-carry-sigma-xy-m=0.06",
        "--amcl-live-carry-sigma-yaw-deg", "3.0",
        "--amcl-live-carry-schedule-m=0.5,0.2,0.05",
    });
    Env  env({});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.live_carry_pose_as_hint        == true);
    CHECK(c.amcl_live_carry_sigma_xy_m     == 0.06);
    CHECK(c.amcl_live_carry_sigma_yaw_deg  == 3.0);
    REQUIRE(c.amcl_live_carry_schedule_m.size() == 3u);
    CHECK(c.amcl_live_carry_schedule_m[0] == 0.5);
}

TEST_CASE("Config::load — issue#5 CLI > env > TOML precedence holds for Live carry-hint keys") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "live_carry_sigma_xy_m = 0.10\n"
    );
    Argv argv({"--amcl-live-carry-sigma-xy-m=0.08"});
    Env  env({
        "GODO_CONFIG_PATH=" + tmp.path.string(),
        "GODO_AMCL_LIVE_CARRY_SIGMA_XY_M=0.09",
    });
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.amcl_live_carry_sigma_xy_m == 0.08);  // CLI wins
}

TEST_CASE("Config::load — issue#5 σ_xy out-of-range rejected") {
    {
        // Below schema lower bound 0.001.
        Argv argv({"--amcl-live-carry-sigma-xy-m=0.0005"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        // Above schema upper bound 0.5.
        Argv argv({"--amcl-live-carry-sigma-xy-m=0.6"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        // Negative.
        Argv argv({"--amcl-live-carry-sigma-xy-m=-0.05"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — issue#5 σ_yaw out-of-range rejected") {
    {
        // Below schema lower bound 0.05.
        Argv argv({"--amcl-live-carry-sigma-yaw-deg=0.01"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        // Above schema upper bound 30.0.
        Argv argv({"--amcl-live-carry-sigma-yaw-deg=45"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — issue#5 schedule monotonicity + bounds enforced") {
    {
        // Non-monotonic.
        Argv argv({"--amcl-live-carry-schedule-m=0.2,0.5,0.05"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        // Out-of-range entry (5.01 > 5.0).
        Argv argv({"--amcl-live-carry-schedule-m=5.01,1.0,0.1"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        // Empty.
        auto tmp = write_temp_toml(
            "[amcl]\n"
            "live_carry_schedule_m = \"\"\n"
        );
        Argv argv({});
        Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — issue#5 bool flag rejects non-bool/non-{0,1} values") {
    {
        Argv argv({"--live-carry-pose-as-hint=maybe"});
        Env  env({});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
    {
        Argv argv({});
        Env  env({"GODO_LIVE_CARRY_POSE_AS_HINT=2"});
        CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                        std::runtime_error);
    }
}

TEST_CASE("Config::load — issue#5 unknown amcl.live_carry.* TOML key rejected") {
    auto tmp = write_temp_toml(
        "[amcl]\n"
        "live_carry_phantom = 1.0\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}

// ---------------------------------------------------------------------------
// issue#5 follow-up — default-flip pin. PR-#62 HIL approval flipped the
// compile-time default `LIVE_CARRY_POSE_AS_HINT` from false to true.
// ---------------------------------------------------------------------------

TEST_CASE("Config::make_default — issue#5 follow-up: live_carry_pose_as_hint defaults to true") {
    Config c = Config::make_default();
    CHECK(c.live_carry_pose_as_hint == true);
    CHECK(godo::config::defaults::LIVE_CARRY_POSE_AS_HINT == true);
}

// ---------------------------------------------------------------------------
// issue#12 — smoother default ramp 500 → 100 ms; webctl-owned schema
// rows. webctl.* keys are first-class Config fields per Parent decision
// A1 — tracker stores them through apply_one + read_effective + render_toml
// but no tracker logic path reads the value (CODEBASE.md (r)). webctl
// reads /var/lib/godo/tracker.toml directly via webctl_toml.py.
// ---------------------------------------------------------------------------

TEST_CASE("Config::make_default — issue#12: T_RAMP_NS default lowered 500 → 100 ms") {
    Config c = Config::make_default();
    CHECK(c.t_ramp_ns == 100'000'000LL);
    CHECK(godo::config::defaults::T_RAMP_NS == 100'000'000LL);
}

TEST_CASE("Config::make_default — issue#12: webctl pose/scan stream Hz defaults to 30") {
    Config c = Config::make_default();
    CHECK(c.webctl_pose_stream_hz == 30);
    CHECK(c.webctl_scan_stream_hz == 30);
    CHECK(godo::config::defaults::WEBCTL_POSE_STREAM_HZ_DEFAULT == 30);
    CHECK(godo::config::defaults::WEBCTL_SCAN_STREAM_HZ_DEFAULT == 30);
}

TEST_CASE("Config::load — issue#12: webctl.* TOML keys parse without unknown-key throw") {
    auto tmp = write_temp_toml(
        "[webctl]\n"
        "pose_stream_hz = 45\n"
        "scan_stream_hz = 50\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.webctl_pose_stream_hz == 45);
    CHECK(c.webctl_scan_stream_hz == 50);
}

TEST_CASE("Config::load — issue#12: webctl env override beats TOML") {
    auto tmp = write_temp_toml(
        "[webctl]\n"
        "pose_stream_hz = 20\n"
    );
    Argv argv({});
    Env  env({
        "GODO_CONFIG_PATH=" + tmp.path.string(),
        "GODO_WEBCTL_POSE_STREAM_HZ=40",
    });
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.webctl_pose_stream_hz == 40);  // env wins
}

TEST_CASE("Config::load — issue#12: webctl CLI overrides env + TOML") {
    auto tmp = write_temp_toml(
        "[webctl]\n"
        "scan_stream_hz = 10\n"
    );
    Argv argv({"--webctl-scan-stream-hz=55"});
    Env  env({
        "GODO_CONFIG_PATH=" + tmp.path.string(),
        "GODO_WEBCTL_SCAN_STREAM_HZ=20",
    });
    Config c = Config::load(argv.argc, argv.argv.data(), env.ptr());
    CHECK(c.webctl_scan_stream_hz == 55);  // CLI wins
}

TEST_CASE("Config::load — issue#12: webctl.* unknown key rejected (positive control)") {
    // Only pose_stream_hz / scan_stream_hz are accepted; any other
    // [webctl] leaf must trip allowed_keys() rejection.
    auto tmp = write_temp_toml(
        "[webctl]\n"
        "phantom_key = 1\n"
    );
    Argv argv({});
    Env  env({"GODO_CONFIG_PATH=" + tmp.path.string()});
    CHECK_THROWS_AS(Config::load(argv.argc, argv.argv.data(), env.ptr()),
                    std::runtime_error);
}
