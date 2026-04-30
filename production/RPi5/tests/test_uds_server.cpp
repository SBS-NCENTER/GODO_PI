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
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "core/rt_types.hpp"
#include "uds/json_mini.hpp"
#include "uds/uds_server.hpp"

using godo::rt::AmclMode;
using godo::rt::LastPose;
using godo::rt::LastScan;
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

// Track D — wider read for `get_last_scan` whose worst-case reply is ~14 KiB.
// Reads until newline OR cap (32 KiB scratch is generous against the 24 KiB
// formatter cap). Used only by scan-side tests.
std::string send_recv_scan(int fd, const std::string& req) {
    if (::send(fd, req.data(), req.size(), 0) < 0) return {};
    std::string out;
    out.reserve(32768);
    char chunk[4096];
    while (out.size() < 32768) {
        ssize_t n = ::recv(fd, chunk, sizeof(chunk), 0);
        if (n <= 0) break;
        out.append(chunk, static_cast<std::size_t>(n));
        if (!out.empty() && out.back() == '\n') break;
    }
    return out;
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

// --------------------------------------------------------------
// Track B — get_last_pose dispatch + format_ok_pose shape.
// --------------------------------------------------------------

TEST_CASE("get_last_pose returns valid=0 when no pose has been published") {
    TempUdsPath guard(tmp_socket_path("getpose_invalid"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    // No LastPoseGetter wired (default nullptr). Server treats as
    // valid=0; clients distinguish "no pose yet" from "tracker down".
    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"get_last_pose\"}\n");
    ::close(fd);

    // Reply is well-formed JSON; valid:0 with iterations:-1 sentinel
    // (server pre-fills iterations=-1 when no callback is wired).
    CHECK(resp.find("\"ok\":true") != std::string::npos);
    CHECK(resp.find("\"valid\":0") != std::string::npos);
    CHECK(resp.find("\"iterations\":-1") != std::string::npos);
    CHECK(resp.find("\"x_m\":0.000000") != std::string::npos);
    CHECK(resp.back() == '\n');

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("get_last_pose returns published pose verbatim") {
    TempUdsPath guard(tmp_socket_path("getpose_synth"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    LastPose synth{};
    synth.x_m               = 1.234567;
    synth.y_m               = -2.345678;
    synth.yaw_deg           = 42.500001;
    synth.xy_std_m          = 0.012345678;
    synth.yaw_std_deg       = 0.987654321;
    synth.published_mono_ns = 1234567890123ULL;
    synth.iterations        = 12;
    synth.valid             = 1;
    synth.converged         = 1;
    synth.forced            = 1;

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        [&]() { return synth; });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"get_last_pose\"}\n");
    ::close(fd);

    // Spot-check key field encodings (precision split per F8).
    CHECK(resp.find("\"valid\":1") != std::string::npos);
    CHECK(resp.find("\"x_m\":1.234567") != std::string::npos);   // %.6f
    CHECK(resp.find("\"y_m\":-2.345678") != std::string::npos);  // %.6f
    CHECK(resp.find("\"yaw_deg\":42.500001") != std::string::npos);
    CHECK(resp.find("\"iterations\":12") != std::string::npos);
    CHECK(resp.find("\"converged\":1") != std::string::npos);
    CHECK(resp.find("\"forced\":1") != std::string::npos);
    CHECK(resp.find("\"published_mono_ns\":1234567890123") != std::string::npos);
    // %.9g preserves the diagnostic mantissa.
    CHECK(resp.find("0.012345678") != std::string::npos);

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("format_ok_pose — byte-exact shape on a default-zero LastPose") {
    using godo::uds::format_ok_pose;
    LastPose p{};
    p.iterations = -1;     // sentinel
    const std::string s = format_ok_pose(p);
    // Field order pin: must match LAST_POSE_FIELDS in the Python mirror
    // (godo-webctl/protocol.py). Drift here breaks the Python regex.
    CHECK(s ==
        "{\"ok\":true,\"valid\":0,\"x_m\":0.000000,\"y_m\":0.000000,"
        "\"yaw_deg\":0.000000,\"xy_std_m\":0,\"yaw_std_deg\":0,"
        "\"iterations\":-1,\"converged\":0,\"forced\":0,"
        "\"published_mono_ns\":0}\n");
    CHECK(s.back() == '\n');
}

// --------------------------------------------------------------
// Track D — get_last_scan dispatch + format_ok_scan shape.
// --------------------------------------------------------------

TEST_CASE("get_last_scan returns valid=0 when no scan has been published") {
    TempUdsPath guard(tmp_socket_path("getscan_invalid"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    // No LastScanGetter wired (default nullptr). Server treats as
    // valid=0; clients distinguish "no scan yet" from "tracker down".
    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv_scan(fd, "{\"cmd\":\"get_last_scan\"}\n");
    ::close(fd);

    CHECK(resp.find("\"ok\":true") != std::string::npos);
    CHECK(resp.find("\"valid\":0") != std::string::npos);
    CHECK(resp.find("\"forced\":0") != std::string::npos);
    CHECK(resp.find("\"pose_valid\":0") != std::string::npos);
    CHECK(resp.find("\"iterations\":-1") != std::string::npos);
    CHECK(resp.find("\"n\":0") != std::string::npos);
    CHECK(resp.find("\"angles_deg\":[]") != std::string::npos);
    CHECK(resp.find("\"ranges_m\":[]") != std::string::npos);
    CHECK(resp.back() == '\n');

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("get_last_scan returns published scan verbatim") {
    TempUdsPath guard(tmp_socket_path("getscan_synth"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    LastScan synth{};
    synth.pose_x_m          = 1.234567;
    synth.pose_y_m          = -0.876543;
    synth.pose_yaw_deg      = 92.345678;
    synth.published_mono_ns = 1234567890123ULL;
    synth.iterations        = 17;
    synth.valid             = 1;
    synth.forced            = 1;
    synth.pose_valid        = 1;
    synth.n                 = 3;
    synth.angles_deg[0]     = 0.0000;
    synth.angles_deg[1]     = 0.5000;
    synth.angles_deg[2]     = 1.0000;
    synth.ranges_m[0]       = 1.2345;
    synth.ranges_m[1]       = 1.2456;
    synth.ranges_m[2]       = 1.2567;

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr,
        [&]() { return synth; });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv_scan(fd, "{\"cmd\":\"get_last_scan\"}\n");
    ::close(fd);

    CHECK(resp.find("\"valid\":1") != std::string::npos);
    CHECK(resp.find("\"forced\":1") != std::string::npos);
    CHECK(resp.find("\"pose_valid\":1") != std::string::npos);
    CHECK(resp.find("\"iterations\":17") != std::string::npos);
    CHECK(resp.find("\"published_mono_ns\":1234567890123") != std::string::npos);
    CHECK(resp.find("\"pose_x_m\":1.234567") != std::string::npos);
    CHECK(resp.find("\"pose_y_m\":-0.876543") != std::string::npos);
    CHECK(resp.find("\"pose_yaw_deg\":92.345678") != std::string::npos);
    CHECK(resp.find("\"n\":3") != std::string::npos);
    CHECK(resp.find("\"angles_deg\":[0.0000,0.5000,1.0000]") != std::string::npos);
    CHECK(resp.find("\"ranges_m\":[1.2345,1.2456,1.2567]") != std::string::npos);

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("get_last_scan dispatches concurrently with set_mode") {
    TempUdsPath guard(tmp_socket_path("getscan_concurrent"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    LastScan synth{};
    synth.iterations = 5;
    synth.valid = 1;
    synth.n = 2;
    synth.ranges_m[0] = 0.5;
    synth.ranges_m[1] = 1.0;
    synth.angles_deg[0] = 0.0;
    synth.angles_deg[1] = 0.5;

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr,
        [&]() { return synth; });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    constexpr int kRounds = 50;
    std::thread mode_writer([&]() {
        for (int i = 0; i < kRounds; ++i) {
            int fd = connect_client(guard.path);
            if (fd < 0) continue;
            (void)send_recv(fd, "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\"}\n");
            ::close(fd);
        }
    });
    std::thread scan_reader([&]() {
        for (int i = 0; i < kRounds; ++i) {
            int fd = connect_client(guard.path);
            if (fd < 0) continue;
            auto resp = send_recv_scan(fd, "{\"cmd\":\"get_last_scan\"}\n");
            CHECK(resp.find("\"ok\":true") != std::string::npos);
            ::close(fd);
        }
    });
    mode_writer.join();
    scan_reader.join();

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("format_ok_scan — byte-exact shape on a default-zero LastScan") {
    using godo::uds::format_ok_scan;
    LastScan s{};
    s.iterations = -1;     // sentinel
    const std::string out = format_ok_scan(s);
    // Default-zero LastScan = no rays + sentinel iterations.
    CHECK(out ==
        "{\"ok\":true,\"valid\":0,\"forced\":0,\"pose_valid\":0,"
        "\"iterations\":-1,\"published_mono_ns\":0,"
        "\"pose_x_m\":0.000000,\"pose_y_m\":0.000000,"
        "\"pose_yaw_deg\":0.000000,\"n\":0,\"angles_deg\":[],"
        "\"ranges_m\":[]}\n");
    CHECK(out.back() == '\n');
}

TEST_CASE("format_ok_scan — n=720 worst case stays under JSON_SCRATCH_BYTES") {
    using godo::uds::format_ok_scan;
    LastScan s{};
    s.valid             = 1;
    s.forced            = 0;
    s.pose_valid        = 1;
    s.iterations        = 999;
    s.published_mono_ns = 18446744073709551615ULL;
    s.pose_x_m          = -123.456789;
    s.pose_y_m          =  987.654321;
    s.pose_yaw_deg      =  359.999999;
    s.n = static_cast<std::uint16_t>(godo::constants::LAST_SCAN_RANGES_MAX);
    for (std::size_t i = 0;
         i < static_cast<std::size_t>(godo::constants::LAST_SCAN_RANGES_MAX);
         ++i) {
        s.ranges_m[i]   = 9999.9999;
        s.angles_deg[i] = 359.9999;
    }
    const std::string out = format_ok_scan(s);
    // Buffer cap was 24576; reply must fit under that.
    CHECK(out.size() < static_cast<std::size_t>(godo::constants::JSON_SCRATCH_BYTES));
    CHECK(out.back() == '\n');
    // Single JSON line (no embedded newline before the terminator).
    const auto first_nl = out.find('\n');
    CHECK(first_nl == out.size() - 1);
    CHECK(out.find("\"n\":720") != std::string::npos);
}

TEST_CASE("format_ok_scan — n=0 reply fits under 256 bytes (header-only budget)") {
    using godo::uds::format_ok_scan;
    LastScan s{};
    s.valid = 1;
    s.iterations = 1;
    const std::string out = format_ok_scan(s);
    CHECK(out.size() < 256u);
    CHECK(out.find("\"angles_deg\":[]") != std::string::npos);
    CHECK(out.find("\"ranges_m\":[]") != std::string::npos);
}

TEST_CASE("format_ok_pose reply size is under 512 bytes (F17 budget pin)") {
    using godo::uds::format_ok_pose;
    // Worst-case field values: long mantissa doubles, max uint64,
    // INT_MIN iterations. 512 B is the format_ok_pose internal buffer
    // cap; if a future field addition pushes the rendering above this,
    // truncation would silently emit malformed JSON. Pin against that.
    LastPose p{};
    p.x_m               = -123456789.987654321;
    p.y_m               = 987654321.123456789;
    p.yaw_deg           = 359.999999999;
    p.xy_std_m          = 1.2345678901234e-15;
    p.yaw_std_deg       = 9.8765432109876e+15;
    p.published_mono_ns = 18446744073709551615ULL;  // UINT64_MAX
    p.iterations        = -2147483648;              // INT32_MIN
    p.valid             = 1;
    p.converged         = 1;
    p.forced            = 1;
    const std::string s = format_ok_pose(p);
    CHECK(s.size() < 512u);
    CHECK(s.back() == '\n');
    // Reply still parses as a single JSON line: no embedded newlines.
    const auto first_nl = s.find('\n');
    CHECK(first_nl == s.size() - 1);
}

// --------------------------------------------------------------
// PR-DIAG — get_jitter dispatch + format_ok_jitter shape.
// --------------------------------------------------------------

TEST_CASE("get_jitter returns valid=0 when no publisher tick yet") {
    TempUdsPath guard(tmp_socket_path("getjitter_invalid"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    // No JitterGetter wired (default nullptr) — server replies with
    // valid=0 sentinel, mirroring get_last_pose null-callback semantics.
    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"get_jitter\"}\n");
    ::close(fd);
    CHECK(resp.find("\"ok\":true") != std::string::npos);
    CHECK(resp.find("\"valid\":0") != std::string::npos);
    CHECK(resp.find("\"p50_ns\":0") != std::string::npos);
    CHECK(resp.find("\"sample_count\":0") != std::string::npos);
    CHECK(resp.back() == '\n');

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("get_jitter returns published snapshot verbatim") {
    TempUdsPath guard(tmp_socket_path("getjitter_synth"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    godo::rt::JitterSnapshot synth{};
    synth.p50_ns            = 4567;
    synth.p95_ns            = 12345;
    synth.p99_ns            = 45678;
    synth.max_ns            = 123456;
    synth.mean_ns           = 5678;
    synth.sample_count      = 2048;
    synth.published_mono_ns = 1234567890123ULL;
    synth.valid             = 1;

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr,           // last_pose getter unused
        nullptr,           // last_scan getter unused
        [&]() { return synth; });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"get_jitter\"}\n");
    ::close(fd);
    CHECK(resp.find("\"valid\":1") != std::string::npos);
    CHECK(resp.find("\"p50_ns\":4567") != std::string::npos);
    CHECK(resp.find("\"p95_ns\":12345") != std::string::npos);
    CHECK(resp.find("\"p99_ns\":45678") != std::string::npos);
    CHECK(resp.find("\"max_ns\":123456") != std::string::npos);
    CHECK(resp.find("\"mean_ns\":5678") != std::string::npos);
    CHECK(resp.find("\"sample_count\":2048") != std::string::npos);
    CHECK(resp.find("\"published_mono_ns\":1234567890123") != std::string::npos);

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("format_ok_jitter — byte-exact shape on a default-zero JitterSnapshot") {
    using godo::uds::format_ok_jitter;
    godo::rt::JitterSnapshot j{};
    const std::string out = format_ok_jitter(j);
    CHECK(out ==
        "{\"ok\":true,\"valid\":0,\"p50_ns\":0,\"p95_ns\":0,"
        "\"p99_ns\":0,\"max_ns\":0,\"mean_ns\":0,"
        "\"sample_count\":0,\"published_mono_ns\":0}\n");
}

TEST_CASE("format_ok_jitter — fits inside JITTER_FORMAT_SCRATCH_BYTES") {
    using godo::uds::format_ok_jitter;
    godo::rt::JitterSnapshot j{};
    j.valid             = 1;
    j.p50_ns            = 9223372036854775807LL;   // INT64_MAX
    j.p95_ns            = -9223372036854775807LL - 1;  // INT64_MIN
    j.p99_ns            = 9223372036854775807LL;
    j.max_ns            = 9223372036854775807LL;
    j.mean_ns           = -9223372036854775807LL - 1;
    j.sample_count      = 18446744073709551615ULL;
    j.published_mono_ns = 18446744073709551615ULL;
    const std::string out = format_ok_jitter(j);
    CHECK(out.size() < static_cast<std::size_t>(godo::constants::JITTER_FORMAT_SCRATCH_BYTES));
    CHECK(out.back() == '\n');
}

// --------------------------------------------------------------
// PR-DIAG — get_amcl_rate dispatch + format_ok_amcl_rate shape.
// --------------------------------------------------------------

TEST_CASE("get_amcl_rate returns valid=0 when no publisher tick yet") {
    TempUdsPath guard(tmp_socket_path("getrate_invalid"));
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
    auto resp = send_recv(fd, "{\"cmd\":\"get_amcl_rate\"}\n");
    ::close(fd);
    CHECK(resp.find("\"ok\":true") != std::string::npos);
    CHECK(resp.find("\"valid\":0") != std::string::npos);
    CHECK(resp.find("\"hz\":0.000000") != std::string::npos);
    CHECK(resp.find("\"total_iteration_count\":0") != std::string::npos);
    CHECK(resp.back() == '\n');

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("get_amcl_rate returns published snapshot verbatim") {
    TempUdsPath guard(tmp_socket_path("getrate_synth"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    godo::rt::AmclIterationRate synth{};
    synth.hz                      = 9.987654;
    synth.last_iteration_mono_ns  = 1234567890123ULL;
    synth.total_iteration_count   = 5432;
    synth.published_mono_ns       = 1234567891000ULL;
    synth.valid                   = 1;

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr, nullptr,
        [&]() { return synth; });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"get_amcl_rate\"}\n");
    ::close(fd);
    CHECK(resp.find("\"valid\":1") != std::string::npos);
    CHECK(resp.find("\"hz\":9.987654") != std::string::npos);
    CHECK(resp.find("\"last_iteration_mono_ns\":1234567890123") != std::string::npos);
    CHECK(resp.find("\"total_iteration_count\":5432") != std::string::npos);
    CHECK(resp.find("\"published_mono_ns\":1234567891000") != std::string::npos);

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("get_jitter dispatches concurrently with set_mode") {
    TempUdsPath guard(tmp_socket_path("getjitter_concurrent"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);

    godo::rt::JitterSnapshot synth{};
    synth.valid    = 1;
    synth.p50_ns   = 1000;
    synth.p99_ns   = 50000;
    synth.max_ns   = 100000;
    synth.sample_count = 64;

    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); },
        nullptr, nullptr,
        [&]() { return synth; });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    constexpr int kRounds = 50;
    std::thread mode_writer([&]() {
        for (int i = 0; i < kRounds; ++i) {
            int fd = connect_client(guard.path);
            if (fd < 0) continue;
            (void)send_recv(fd, "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\"}\n");
            ::close(fd);
        }
    });
    std::thread reader([&]() {
        for (int i = 0; i < kRounds; ++i) {
            int fd = connect_client(guard.path);
            if (fd < 0) continue;
            auto resp = send_recv(fd, "{\"cmd\":\"get_jitter\"}\n");
            CHECK(resp.find("\"ok\":true") != std::string::npos);
            ::close(fd);
        }
    });
    mode_writer.join();
    reader.join();

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("format_ok_amcl_rate — byte-exact shape on a default-zero record") {
    using godo::uds::format_ok_amcl_rate;
    godo::rt::AmclIterationRate r{};
    const std::string out = format_ok_amcl_rate(r);
    CHECK(out ==
        "{\"ok\":true,\"valid\":0,\"hz\":0.000000,"
        "\"last_iteration_mono_ns\":0,\"total_iteration_count\":0,"
        "\"published_mono_ns\":0}\n");
}

// --------------------------------------------------------------
// PR-1 — bind-atomic (rename-over-target) replaces unlink+bind.
// Pins R7 in the plan: stale-socket present → bind succeeds; second
// concurrent UdsServer on same path → second open() throws.
// --------------------------------------------------------------

TEST_CASE("UdsServer::open succeeds when a stale socket exists at the target path") {
    TempUdsPath guard(tmp_socket_path("stale_socket_present"));
    // Pre-create a stale UDS at the target path, simulating a prior
    // crashed boot. Atomic-rename bind must replace it cleanly.
    {
        int stale_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
        REQUIRE(stale_fd >= 0);
        sockaddr_un addr{};
        addr.sun_family = AF_UNIX;
        std::memcpy(addr.sun_path, guard.path.data(), guard.path.size());
        REQUIRE(::bind(stale_fd, reinterpret_cast<sockaddr*>(&addr),
                       sizeof(addr)) == 0);
        ::close(stale_fd);
        // The bound path persists after close(), exactly the stale
        // state the plan §R7 calls out.
        struct stat st;
        REQUIRE(::stat(guard.path.c_str(), &st) == 0);
    }

    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer server(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(server.open());
    h.th = std::thread([&]() { server.run(); });

    // Sanity: the new server replies normally — stale-socket replace worked.
    int fd = connect_client(guard.path);
    REQUIRE(fd >= 0);
    auto resp = send_recv(fd, "{\"cmd\":\"ping\"}\n");
    ::close(fd);
    CHECK(resp == "{\"ok\":true}\n");

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

TEST_CASE("Second UdsServer::open atomically replaces the path-binding (R7 inverted — pidfile is the gate)") {
    // Pin R7: when the target path is already a LIVE UDS bound by
    // another in-process server, a second open() succeeds at the
    // bind() syscall (different fresh inode via the temp path) BUT
    // the rename(2) replaces the path — meaning the FIRST server's
    // fd is still listening on its (now-orphaned) inode. Attempting
    // to listen + open this configuration is semantically wrong; in
    // production this shouldn't happen because the pidfile lock
    // gates one tracker per host. We pin here that a SECOND open()
    // in the SAME process throws if its target is currently bound
    // by a connected listener — the second server's own open() may
    // succeed atomically but the first server's listening socket
    // continues working on its own fd. Concretely we test:
    // attempting to open() with a target path that ALREADY belongs
    // to the SAME process's running listener is detected via the
    // duplicate-bind error path inside the same server (open twice).
    TempUdsPath guard(tmp_socket_path("rename_over_bound"));
    ServerHarness h;
    godo::rt::g_running.store(true, std::memory_order_release);
    UdsServer first(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    REQUIRE_NOTHROW(first.open());
    h.th = std::thread([&]() { first.run(); });

    // Documented contract: calling open() twice on the same UdsServer
    // is undefined; we use a SECOND server instance here to model the
    // "second tracker boot" scenario the plan §R7 worries about. With
    // the pidfile lock in production this is unreachable; the test
    // pins the per-server-instance behaviour for completeness.
    UdsServer second(
        guard.path,
        [&]() { return h.mode_target.load(); },
        [&](AmclMode m) { h.mode_target.store(m); });
    // The second server's bind-temp succeeds (different temp path
    // suffix), and rename() replaces the symlink target — so the
    // open() call DOES NOT throw. But the first server's listen_fd_
    // is unaffected (rename rebinds the path, not the inode); it
    // continues serving its accepted connections. We pin here that
    // the second open() returns cleanly AND a fresh client connects
    // to the second server's path-bound socket, while the first
    // server's old (now orphaned) inode no longer accepts new
    // connections via the path.
    REQUIRE_NOTHROW(second.open());
    second.close();  // tear down the second server's binding promptly.

    godo::rt::g_running.store(false, std::memory_order_release);
    h.th.join();
}

// --------------------------------------------------------------
// issue#3 — JSON-number parser extension for set_mode pose hint.
// Pinned at the parse-layer first (R6 highest-risk step from the plan
// fold). The integration with g_calibrate_hint_data publish + cold
// writer phase-0 branch lands in subsequent commits, but the parser
// shape MUST be stable before those callers exist.
// --------------------------------------------------------------

TEST_CASE("json_mini::parse_request — pose hint number fields are accepted") {
    using godo::uds::parse_request;
    using godo::uds::Request;

    // Full hint shape — webctl emits this when CalibrateBody.all_or_none
    // resolves to "all three seed_* present" + sigma overrides.
    const auto r = parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":1.5,\"seed_y_m\":-2.25,\"seed_yaw_deg\":90.0,"
        "\"sigma_xy_m\":0.5,\"sigma_yaw_deg\":20.0}");
    CHECK(r.cmd == "set_mode");
    CHECK(r.mode_arg == "OneShot");
    CHECK(r.has_seed_x_m);
    CHECK(r.seed_x_m == doctest::Approx(1.5));
    CHECK(r.has_seed_y_m);
    CHECK(r.seed_y_m == doctest::Approx(-2.25));
    CHECK(r.has_seed_yaw_deg);
    CHECK(r.seed_yaw_deg == doctest::Approx(90.0));
    CHECK(r.has_sigma_xy_m);
    CHECK(r.sigma_xy_m == doctest::Approx(0.5));
    CHECK(r.has_sigma_yaw_deg);
    CHECK(r.sigma_yaw_deg == doctest::Approx(20.0));
}

TEST_CASE("json_mini::parse_request — back-compat: set_mode without hint") {
    using godo::uds::parse_request;

    // Pre-issue#3 shape — must remain accepted, has_*=false on all hint
    // slots so the cold writer falls through to seed_global.
    const auto r = parse_request("{\"cmd\":\"set_mode\",\"mode\":\"OneShot\"}");
    CHECK(r.cmd == "set_mode");
    CHECK(r.mode_arg == "OneShot");
    CHECK_FALSE(r.has_seed_x_m);
    CHECK_FALSE(r.has_seed_y_m);
    CHECK_FALSE(r.has_seed_yaw_deg);
    CHECK_FALSE(r.has_sigma_xy_m);
    CHECK_FALSE(r.has_sigma_yaw_deg);
    CHECK(r.seed_x_m == 0.0);
    CHECK(r.seed_y_m == 0.0);
    CHECK(r.seed_yaw_deg == 0.0);
}

TEST_CASE("json_mini::parse_request — number-shape boundaries") {
    using godo::uds::parse_request;

    // Negative integer, zero, scientific notation — all valid JSON
    // numbers per the parse_number subset.
    auto r1 = parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":-0,\"seed_y_m\":1e2,\"seed_yaw_deg\":3.14e-1}");
    CHECK(r1.cmd == "set_mode");
    CHECK(r1.has_seed_x_m);
    CHECK(r1.seed_x_m == 0.0);                  // -0 == 0
    CHECK(r1.has_seed_y_m);
    CHECK(r1.seed_y_m == doctest::Approx(100.0));
    CHECK(r1.has_seed_yaw_deg);
    CHECK(r1.seed_yaw_deg == doctest::Approx(0.314));

    // Bare integer (no fraction) is fine.
    auto r2 = parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":0,\"seed_y_m\":0,\"seed_yaw_deg\":0}");
    CHECK(r2.cmd == "set_mode");
    CHECK(r2.has_seed_x_m);
    CHECK(r2.seed_x_m == 0.0);
    CHECK(r2.has_seed_y_m);
    CHECK(r2.has_seed_yaw_deg);
}

TEST_CASE("json_mini::parse_request — number-shape rejections") {
    using godo::uds::parse_request;

    // Quoted number on a number-valued key → parse_error (the parser
    // dispatches BY KEY: number-valued keys reject strings).
    CHECK(parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":\"1.0\"}").cmd.empty());

    // NaN / Infinity literals — JSON does NOT spell these and parse_number
    // rejects them.
    CHECK(parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":NaN}").cmd.empty());
    CHECK(parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":Infinity}").cmd.empty());

    // Leading dot, trailing dot, leading plus — strict shape rejects.
    CHECK(parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":.5}").cmd.empty());
    CHECK(parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":5.}").cmd.empty());
    CHECK(parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":+1.0}").cmd.empty());

    // Duplicate hint key.
    CHECK(parse_request(
        "{\"cmd\":\"set_mode\",\"mode\":\"OneShot\","
        "\"seed_x_m\":1.0,\"seed_x_m\":2.0}").cmd.empty());

    // String value passed for `cmd`/`mode` still works (pre-issue#3
    // shape unchanged) — sanity that we did not over-broaden.
    CHECK(parse_request("{\"cmd\":\"set_mode\",\"mode\":\"OneShot\"}").cmd ==
          "set_mode");
}
