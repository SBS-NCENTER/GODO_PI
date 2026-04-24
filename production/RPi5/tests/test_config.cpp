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
