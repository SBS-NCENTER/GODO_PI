// Track B-CONFIG (PR-CONFIG-α) — end-to-end UDS test for the three
// new config commands. Spins up an in-process UdsServer with the
// production wiring (apply_set / apply_get_all / apply_get_schema),
// drives the wire from a client socket, and asserts:
//   - TOML file written + readable bytes match.
//   - live_cfg mutation visible via subsequent get_config.
//   - HotConfig seqlock published (generation increments) for hot keys.
//   - restart_pending flag touched for restart / recalibrate keys.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <atomic>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <system_error>
#include <thread>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "config/apply.hpp"
#include "config/restart_pending.hpp"
#include "core/config.hpp"
#include "core/hot_config.hpp"
#include "core/rt_flags.hpp"
#include "core/seqlock.hpp"
#include "uds/uds_server.hpp"

using godo::config::apply_get_all;
using godo::config::apply_get_schema;
using godo::config::apply_set;
using godo::config::is_pending;
using godo::core::Config;
using godo::core::HotConfig;
using godo::rt::AmclMode;
using godo::rt::Seqlock;
using godo::uds::ConfigSetReply;
using godo::uds::UdsServer;
namespace fs = std::filesystem;

namespace {

struct TempDir {
    fs::path path;
    explicit TempDir(const char* tag) {
        char buf[256];
        std::snprintf(buf, sizeof(buf), "/tmp/godo_e2e_%d_%s",
                      static_cast<int>(::getpid()), tag);
        path = buf;
        std::error_code ec;
        fs::remove_all(path, ec);
        fs::create_directories(path);
    }
    ~TempDir() {
        std::error_code ec;
        fs::remove_all(path, ec);
    }
};

std::string sock_path(const char* tag) {
    char buf[256];
    std::snprintf(buf, sizeof(buf), "/tmp/godo_e2e_uds_%d_%s.sock",
                  static_cast<int>(::getpid()), tag);
    return buf;
}

int connect_client(const std::string& path) {
    int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::memcpy(addr.sun_path, path.data(), path.size());
    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        ::close(fd);
        return -1;
    }
    return fd;
}

std::string send_recv(int fd, const std::string& req) {
    if (::send(fd, req.data(), req.size(), 0) < 0) return {};
    std::string out;
    out.reserve(8192);
    char buf[4096];
    while (out.size() < 65536) {
        ssize_t n = ::recv(fd, buf, sizeof(buf), 0);
        if (n <= 0) break;
        out.append(buf, static_cast<std::size_t>(n));
        if (!out.empty() && out.back() == '\n') break;
    }
    return out;
}

std::string read_file(const fs::path& p) {
    std::ifstream f(p);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

struct Harness {
    TempDir            td;
    std::string        socket_path;
    std::atomic<AmclMode> mode_target{AmclMode::Idle};
    std::mutex         live_mtx;
    Config             live_cfg;
    Seqlock<HotConfig> hot_seq;
    fs::path           toml_path;
    fs::path           flag_path;
    std::thread        th;

    explicit Harness(const char* tag)
        : td(tag),
          socket_path(sock_path(tag)),
          live_cfg(Config::make_default()),
          toml_path(td.path / "tracker.toml"),
          flag_path(td.path / "restart_pending") {
        ::unlink(socket_path.c_str());
        hot_seq.store(godo::core::snapshot_hot(live_cfg));
    }
    ~Harness() {
        godo::rt::g_running.store(false, std::memory_order_release);
        if (th.joinable()) th.join();
        ::unlink(socket_path.c_str());
    }
};

}  // namespace

TEST_CASE("e2e: get_config_schema returns 37-row JSON array") {
    Harness h("schema");
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        h.socket_path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr, nullptr, nullptr,
        [&]() { return apply_get_all(h.live_cfg, h.live_mtx); },
        []()  { return apply_get_schema(); },
        [&](std::string_view k, std::string_view v) {
            const auto ar = apply_set(k, v, h.live_cfg, h.live_mtx,
                                      h.hot_seq, h.toml_path, h.flag_path);
            ConfigSetReply rep;
            rep.ok           = ar.ok;
            rep.err          = ar.err;
            rep.err_detail   = ar.err_detail;
            rep.reload_class.assign(
                godo::core::config_schema::reload_class_to_string(
                    ar.reload_class));
            return rep;
        });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(h.socket_path);
    REQUIRE(fd >= 0);
    const auto resp = send_recv(fd, "{\"cmd\":\"get_config_schema\"}\n");
    ::close(fd);

    CHECK(resp.find("\"ok\":true") != std::string::npos);
    CHECK(resp.find("\"schema\":") != std::string::npos);
    CHECK(resp.find("\"name\":\"smoother.deadband_mm\"") != std::string::npos);
    CHECK(resp.find("\"name\":\"network.ue_host\"")      != std::string::npos);
}

TEST_CASE("e2e: get_config returns 37-key dict") {
    Harness h("getall");
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        h.socket_path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr, nullptr, nullptr,
        [&]() { return apply_get_all(h.live_cfg, h.live_mtx); },
        []()  { return apply_get_schema(); },
        [&](std::string_view k, std::string_view v) {
            const auto ar = apply_set(k, v, h.live_cfg, h.live_mtx,
                                      h.hot_seq, h.toml_path, h.flag_path);
            ConfigSetReply rep;
            rep.ok = ar.ok;
            rep.err = ar.err;
            rep.err_detail = ar.err_detail;
            rep.reload_class.assign(
                godo::core::config_schema::reload_class_to_string(
                    ar.reload_class));
            return rep;
        });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(h.socket_path);
    REQUIRE(fd >= 0);
    const auto resp = send_recv(fd, "{\"cmd\":\"get_config\"}\n");
    ::close(fd);

    CHECK(resp.find("\"ok\":true") != std::string::npos);
    CHECK(resp.find("\"keys\":")   != std::string::npos);
    CHECK(resp.find("\"smoother.deadband_mm\":") != std::string::npos);
    CHECK(resp.find("\"network.ue_port\":")      != std::string::npos);
}

TEST_CASE("e2e: set_config hot-class round-trips TOML + RAM + HotConfig + reply") {
    Harness h("set_hot");
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        h.socket_path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr, nullptr, nullptr,
        [&]() { return apply_get_all(h.live_cfg, h.live_mtx); },
        []()  { return apply_get_schema(); },
        [&](std::string_view k, std::string_view v) {
            const auto ar = apply_set(k, v, h.live_cfg, h.live_mtx,
                                      h.hot_seq, h.toml_path, h.flag_path);
            ConfigSetReply rep;
            rep.ok = ar.ok;
            rep.err = ar.err;
            rep.err_detail = ar.err_detail;
            rep.reload_class.assign(
                godo::core::config_schema::reload_class_to_string(
                    ar.reload_class));
            return rep;
        });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    const auto pre_gen = h.hot_seq.generation();

    int fd = connect_client(h.socket_path);
    REQUIRE(fd >= 0);
    const auto resp = send_recv(fd,
        "{\"cmd\":\"set_config\",\"key\":\"smoother.deadband_mm\","
        "\"value\":\"15.5\"}\n");
    ::close(fd);

    CHECK(resp == "{\"ok\":true,\"reload_class\":\"hot\"}\n");
    CHECK(h.live_cfg.deadband_mm == 15.5);
    CHECK(fs::exists(h.toml_path));
    CHECK(read_file(h.toml_path).find("deadband_mm = 15.5") != std::string::npos);
    const auto post = h.hot_seq.load();
    CHECK(post.deadband_mm == 15.5);
    CHECK(h.hot_seq.generation() != pre_gen);
    CHECK_FALSE(is_pending(h.flag_path));
}

TEST_CASE("e2e: set_config restart-class touches flag + reply carries class") {
    Harness h("set_restart");
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        h.socket_path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr, nullptr, nullptr,
        [&]() { return apply_get_all(h.live_cfg, h.live_mtx); },
        []()  { return apply_get_schema(); },
        [&](std::string_view k, std::string_view v) {
            const auto ar = apply_set(k, v, h.live_cfg, h.live_mtx,
                                      h.hot_seq, h.toml_path, h.flag_path);
            ConfigSetReply rep;
            rep.ok = ar.ok;
            rep.err = ar.err;
            rep.err_detail = ar.err_detail;
            rep.reload_class.assign(
                godo::core::config_schema::reload_class_to_string(
                    ar.reload_class));
            return rep;
        });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    const auto pre_gen = h.hot_seq.generation();

    int fd = connect_client(h.socket_path);
    REQUIRE(fd >= 0);
    const auto resp = send_recv(fd,
        "{\"cmd\":\"set_config\",\"key\":\"network.ue_port\","
        "\"value\":\"7766\"}\n");
    ::close(fd);

    CHECK(resp == "{\"ok\":true,\"reload_class\":\"restart\"}\n");
    CHECK(h.live_cfg.ue_port == 7766);
    CHECK(is_pending(h.flag_path));
    CHECK(h.hot_seq.generation() == pre_gen);
}

TEST_CASE("e2e: set_config bad_value returns 'detail' field on the wire") {
    Harness h("bad_value");
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        h.socket_path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr, nullptr, nullptr,
        [&]() { return apply_get_all(h.live_cfg, h.live_mtx); },
        []()  { return apply_get_schema(); },
        [&](std::string_view k, std::string_view v) {
            const auto ar = apply_set(k, v, h.live_cfg, h.live_mtx,
                                      h.hot_seq, h.toml_path, h.flag_path);
            ConfigSetReply rep;
            rep.ok = ar.ok;
            rep.err = ar.err;
            rep.err_detail = ar.err_detail;
            rep.reload_class.assign(
                godo::core::config_schema::reload_class_to_string(
                    ar.reload_class));
            return rep;
        });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(h.socket_path);
    REQUIRE(fd >= 0);
    const auto resp = send_recv(fd,
        "{\"cmd\":\"set_config\",\"key\":\"smoother.deadband_mm\","
        "\"value\":\"9999\"}\n");
    ::close(fd);

    CHECK(resp.find("\"ok\":false")        != std::string::npos);
    CHECK(resp.find("\"err\":\"bad_value\"") != std::string::npos);
    CHECK(resp.find("\"detail\":")         != std::string::npos);
    CHECK(resp.find("out of range")        != std::string::npos);
    // Failure → no TOML write.
    CHECK_FALSE(fs::exists(h.toml_path));
}

TEST_CASE("e2e: set_config bad_key surfaces detail with the unknown key name") {
    Harness h("bad_key");
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        h.socket_path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr, nullptr, nullptr,
        [&]() { return apply_get_all(h.live_cfg, h.live_mtx); },
        []()  { return apply_get_schema(); },
        [&](std::string_view k, std::string_view v) {
            const auto ar = apply_set(k, v, h.live_cfg, h.live_mtx,
                                      h.hot_seq, h.toml_path, h.flag_path);
            ConfigSetReply rep;
            rep.ok = ar.ok;
            rep.err = ar.err;
            rep.err_detail = ar.err_detail;
            rep.reload_class.assign(
                godo::core::config_schema::reload_class_to_string(
                    ar.reload_class));
            return rep;
        });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(h.socket_path);
    REQUIRE(fd >= 0);
    const auto resp = send_recv(fd,
        "{\"cmd\":\"set_config\",\"key\":\"nope.foo\","
        "\"value\":\"x\"}\n");
    ::close(fd);

    CHECK(resp.find("\"err\":\"bad_key\"") != std::string::npos);
    CHECK(resp.find("nope.foo")            != std::string::npos);
}

TEST_CASE("e2e: null callbacks return config_unsupported") {
    Harness h("unsupported");
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        h.socket_path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    auto roundtrip = [&](const char* req) {
        int fd = connect_client(h.socket_path);
        REQUIRE(fd >= 0);
        const auto r = send_recv(fd, req);
        ::close(fd);
        return r;
    };

    CHECK(roundtrip("{\"cmd\":\"get_config\"}\n").find("config_unsupported")
          != std::string::npos);
    CHECK(roundtrip("{\"cmd\":\"get_config_schema\"}\n").find("config_unsupported")
          != std::string::npos);
    CHECK(roundtrip(
        "{\"cmd\":\"set_config\",\"key\":\"smoother.deadband_mm\","
        "\"value\":\"1\"}\n").find("config_unsupported")
          != std::string::npos);
}

TEST_CASE("e2e: set_config without 'key' returns bad_payload") {
    Harness h("missing_key");
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        h.socket_path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr, nullptr, nullptr,
        [&]() { return apply_get_all(h.live_cfg, h.live_mtx); },
        []()  { return apply_get_schema(); },
        [&](std::string_view k, std::string_view v) {
            const auto ar = apply_set(k, v, h.live_cfg, h.live_mtx,
                                      h.hot_seq, h.toml_path, h.flag_path);
            ConfigSetReply rep;
            rep.ok = ar.ok;
            rep.err = ar.err;
            rep.err_detail = ar.err_detail;
            rep.reload_class.assign(
                godo::core::config_schema::reload_class_to_string(
                    ar.reload_class));
            return rep;
        });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(h.socket_path);
    REQUIRE(fd >= 0);
    const auto resp = send_recv(fd, "{\"cmd\":\"set_config\"}\n");
    ::close(fd);

    CHECK(resp.find("\"err\":\"bad_payload\"") != std::string::npos);
    CHECK(resp.find("missing 'key'")            != std::string::npos);
}
