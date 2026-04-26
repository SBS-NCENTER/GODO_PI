// Hardware-free tests for godo::uds::UdsServer + json_mini.
//
// Pattern: spawn the server on a temp UDS path, drive a client socket
// through the four canonical commands + the parse / unknown / oversized
// error paths, and verify responses. RAII `TempUdsPath` guard (S7) unlinks
// the socket on every exit (pass or fail), preventing EADDRINUSE on a
// failed re-run.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <utility>

#include <sys/socket.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "uds/json_mini.hpp"
#include "uds/uds_server.hpp"

using godo::rt::AmclMode;
using godo::uds::UdsServer;

namespace {

// RAII guard — destructor unlinks even when a test scope fails (S7).
struct TempUdsPath {
    std::string path;
    explicit TempUdsPath(std::string p) : path(std::move(p)) {}
    ~TempUdsPath() { ::unlink(path.c_str()); }
    TempUdsPath(const TempUdsPath&) = delete;
    TempUdsPath& operator=(const TempUdsPath&) = delete;
};

std::string tmp_socket_path(const char* tag) {
    char buf[256];
    std::snprintf(buf, sizeof(buf), "/tmp/godo_uds_%d_%s.sock",
                  static_cast<int>(::getpid()), tag);
    return std::string(buf);
}

// Spawn a server thread bound to `path`, with mode-getter / mode-setter
// driving `mode_target`. Returns the running thread + a g_running guard
// that the caller must trip to shut down.
struct ServerHarness {
    std::thread th;
    std::atomic<AmclMode> mode_target{AmclMode::Idle};

    ServerHarness() = default;
    ~ServerHarness() {
        // Caller is responsible for joining; assert here that the
        // teardown path has run.
    }
};

// Connect a SOCK_STREAM client to `path`; returns the connected fd or -1.
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

// Send a request line, then read the response line. Returns the response
// (empty string on read error / connection closed without data).
std::string send_recv(int fd, const std::string& req) {
    if (::send(fd, req.data(), req.size(), 0) < 0) return {};
    char buf[256];
    ssize_t n = ::recv(fd, buf, sizeof(buf), 0);
    if (n <= 0) return {};
    return std::string(buf, static_cast<std::size_t>(n));
}

}  // namespace

TEST_CASE("set_mode then get_mode round-trips") {
    TempUdsPath guard(tmp_socket_path("set_get"));
    ServerHarness h;

    // Reset g_running for this test scope (the global default is true; we
    // must re-arm in case a prior test cleared it).
    godo::rt::g_running.store(true, std::memory_order_release);

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(std::memory_order_acquire); },
        [&](AmclMode m) { h.mode_target.store(m, std::memory_order_release); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\"}\n");
    ::close(fd);
    CHECK(resp == "{\"ok\":true}\n");
    CHECK(h.mode_target.load() == AmclMode::OneShot);

    fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    resp = send_recv(fd, "{\"cmd\":\"get_mode\"}\n");
    ::close(fd);
    CHECK(resp == "{\"ok\":true,\"mode\":\"OneShot\"}\n");

    // Set to Live, then back to Idle.
    fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    resp = send_recv(fd, "{\"cmd\":\"set_mode\",\"mode\":\"Live\"}\n");
    ::close(fd);
    CHECK(resp == "{\"ok\":true}\n");
    CHECK(h.mode_target.load() == AmclMode::Live);

    fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    resp = send_recv(fd, "{\"cmd\":\"set_mode\",\"mode\":\"Idle\"}\n");
    ::close(fd);
    CHECK(resp == "{\"ok\":true}\n");
    CHECK(h.mode_target.load() == AmclMode::Idle);

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("ping returns ok") {
    TempUdsPath guard(tmp_socket_path("ping"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"ping\"}\n");
    ::close(fd);
    CHECK(resp == "{\"ok\":true}\n");

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("Unknown command returns unknown_cmd error") {
    TempUdsPath guard(tmp_socket_path("unknown"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"reboot\"}\n");
    ::close(fd);
    CHECK(resp == "{\"ok\":false,\"err\":\"unknown_cmd\"}\n");

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("Bad mode argument returns bad_mode error") {
    TempUdsPath guard(tmp_socket_path("badmode"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"set_mode\",\"mode\":\"Hyperdrive\"}\n");
    ::close(fd);
    CHECK(resp == "{\"ok\":false,\"err\":\"bad_mode\"}\n");

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("Malformed JSON returns parse_error") {
    TempUdsPath guard(tmp_socket_path("parse"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    // Each test case opens a fresh connection (server closes after one
    // request).
    auto check_parse = [&](const char* req) {
        int fd = connect_client(guard.path);
        REQUIRE(fd >= 0);
        auto resp = send_recv(fd, req);
        ::close(fd);
        CHECK(resp == "{\"ok\":false,\"err\":\"parse_error\"}\n");
    };
    check_parse("{not json}\n");
    check_parse("{\"cmd\":\"ping\"\n");          // missing close brace
    check_parse("{\"cmd\":}\n");                  // missing value
    check_parse("\n");                            // empty line

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("Oversized request without newline closes without response") {
    TempUdsPath guard(tmp_socket_path("oversized"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    // Send UDS_REQUEST_MAX_BYTES + 1 of garbage with no newline. Note:
    // ::send may not write the full buffer in one call on a small socket
    // buffer; loop until done OR the peer resets the connection (the
    // server may close while we're still feeding bytes).
    const std::size_t total = static_cast<std::size_t>(
        godo::constants::UDS_REQUEST_MAX_BYTES) + 1;
    std::string blob(total, 'x');
    std::size_t sent = 0;
    while (sent < total) {
        ssize_t n = ::send(fd, blob.data() + sent, total - sent, MSG_NOSIGNAL);
        if (n < 0) break;       // server reset connection
        sent += static_cast<std::size_t>(n);
    }
    char buf[16];
    ssize_t n = ::recv(fd, buf, sizeof(buf), 0);
    // Server closes without sending anything. Depending on whether the
    // peer close races our send, recv may return 0 (orderly shutdown) or
    // -1 with errno = ECONNRESET. Both prove the server did not respond
    // to the oversized payload.
    CHECK((n == 0 || (n < 0 && errno == ECONNRESET)));
    ::close(fd);

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("Server unblocks within 200 ms of g_running cleared (M1)") {
    TempUdsPath guard(tmp_socket_path("unblock"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    // No connections at all — the server is waiting in poll(). Clear
    // g_running and time the join.
    const auto t0 = std::chrono::steady_clock::now();
    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
    const auto t1 = std::chrono::steady_clock::now();
    const auto ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
    // Worst case is one full SHUTDOWN_POLL_TIMEOUT_MS (100 ms); allow
    // double for scheduling slack.
    CHECK(ms <= 2 * godo::constants::SHUTDOWN_POLL_TIMEOUT_MS);
}

// --------------------------------------------------------------
// Direct json_mini parser tests (no socket).
// --------------------------------------------------------------

TEST_CASE("json_mini::parse_request — well-formed shapes") {
    using godo::uds::parse_request;

    auto r1 = parse_request("{\"cmd\":\"ping\"}");
    CHECK(r1.cmd == "ping");
    CHECK(r1.mode_arg.empty());

    auto r2 = parse_request("{\"cmd\":\"set_mode\",\"mode\":\"Live\"}");
    CHECK(r2.cmd == "set_mode");
    CHECK(r2.mode_arg == "Live");

    // Tolerated whitespace.
    auto r3 = parse_request("  { \"cmd\" : \"get_mode\" }  ");
    CHECK(r3.cmd == "get_mode");
}

TEST_CASE("json_mini::parse_request — error cases produce empty cmd") {
    using godo::uds::parse_request;

    CHECK(parse_request("").cmd.empty());
    CHECK(parse_request("not json").cmd.empty());
    CHECK(parse_request("{}").cmd.empty());                // missing cmd key
    CHECK(parse_request("{\"unknown\":\"x\"}").cmd.empty());
    CHECK(parse_request("{\"cmd\":\"x\",}").cmd.empty()); // trailing comma
    CHECK(parse_request("{\"cmd\":\"x\"} junk").cmd.empty());
    CHECK(parse_request("{\"cmd\":\"esc\\n\"}").cmd.empty());  // backslash rejected
    CHECK(parse_request("{\"cmd\":\"a\",\"cmd\":\"b\"}").cmd.empty());  // dup
}

TEST_CASE("json_mini::format_* shapes") {
    using namespace godo::uds;
    CHECK(format_ok() == "{\"ok\":true}\n");
    CHECK(format_ok_mode(AmclMode::Idle)    == "{\"ok\":true,\"mode\":\"Idle\"}\n");
    CHECK(format_ok_mode(AmclMode::OneShot) == "{\"ok\":true,\"mode\":\"OneShot\"}\n");
    CHECK(format_ok_mode(AmclMode::Live)    == "{\"ok\":true,\"mode\":\"Live\"}\n");
    CHECK(format_err("parse_error") == "{\"ok\":false,\"err\":\"parse_error\"}\n");
}

TEST_CASE("json_mini::parse_mode_arg round-trips") {
    using namespace godo::uds;
    AmclMode m;
    REQUIRE(parse_mode_arg("Idle", m));    CHECK(m == AmclMode::Idle);
    REQUIRE(parse_mode_arg("OneShot", m)); CHECK(m == AmclMode::OneShot);
    REQUIRE(parse_mode_arg("Live", m));    CHECK(m == AmclMode::Live);
    CHECK_FALSE(parse_mode_arg("idle", m));      // case-sensitive
    CHECK_FALSE(parse_mode_arg("", m));
    CHECK_FALSE(parse_mode_arg("Hyperdrive", m));
}
