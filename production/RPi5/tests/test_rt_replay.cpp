// End-to-end replay: spawn godo_tracker_rt with a PTY-slave as the FreeD
// port and a loopback UDP receiver as Unreal. Drive canned bytes in,
// capture the UDP bytes out, compare byte-for-byte to the expected
// post-offset packet.
//
// Linux-only (openpty()). macOS master-side termios behaves differently.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#ifndef __linux__

TEST_CASE("E2E replay — Linux only; skipped on this platform") {
    MESSAGE("skipped: tracker_rt replay is Linux-only");
}

#else

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <pty.h>
#include <signal.h>
#include <spawn.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

#include "core/constants.hpp"
#include "freed/d1_parser.hpp"

namespace {

struct Pty {
    int master = -1;
    std::string slave_name;
};

Pty open_pty_with_8o1() {
    Pty p;
    int slave = -1;
    termios tio{};
    cfmakeraw(&tio);
    cfsetispeed(&tio, B38400);
    cfsetospeed(&tio, B38400);
    tio.c_cflag |=  (PARENB | PARODD | CS8);
    tio.c_cflag &= ~CSTOPB;
    tio.c_cflag &= ~CRTSCTS;
    tio.c_cc[VMIN]  = 1;
    tio.c_cc[VTIME] = 1;

    char name[256] = {0};
    const int rc = ::openpty(&p.master, &slave, name, &tio, nullptr);
    REQUIRE(rc == 0);
    p.slave_name = name;
    ::close(slave);
    return p;
}

int open_udp_listener(std::uint16_t& port) {
    const int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
    REQUIRE(fd >= 0);
    sockaddr_in sa{};
    sa.sin_family      = AF_INET;
    sa.sin_port        = 0;
    sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    REQUIRE(::bind(fd, reinterpret_cast<const sockaddr*>(&sa), sizeof(sa)) == 0);
    sockaddr_in bound{};
    socklen_t bl = sizeof(bound);
    REQUIRE(::getsockname(fd, reinterpret_cast<sockaddr*>(&bound), &bl) == 0);
    port = ntohs(bound.sin_port);
    return fd;
}

// Locate the tracker binary relative to the test executable. CMake runs
// tests from the build dir; the binary is at build/src/godo_tracker_rt/.
std::string find_tracker_binary() {
    // Argv[0] of the test is unavailable here; rely on a CMake-injected
    // compile definition.
#ifndef GODO_TRACKER_RT_PATH
#error "GODO_TRACKER_RT_PATH must be set by CMake"
#endif
    return GODO_TRACKER_RT_PATH;
}

std::array<std::byte, 29> make_valid_d1(std::uint8_t cam_id,
                                        std::uint8_t pan_hi = 0) {
    std::array<std::byte, 29> p{};
    p[godo::constants::FreeD::OFF_TYPE]   = static_cast<std::byte>(0xD1);
    p[godo::constants::FreeD::OFF_CAM_ID] = static_cast<std::byte>(cam_id);
    p[godo::constants::FreeD::OFF_PAN]    = static_cast<std::byte>(pan_hi);
    p[godo::constants::FreeD::OFF_CHECKSUM] =
        static_cast<std::byte>(godo::freed::compute_checksum(
            p.data(), p.size()));
    return p;
}

}  // namespace

TEST_CASE("E2E: tracker_rt forwards FreeD-in to UDP-out with offset applied") {
    // 1. Set up PTY (FreeD in) and UDP listener (UE receiver).
    Pty pty = open_pty_with_8o1();
    std::uint16_t port = 0;
    const int udp_fd = open_udp_listener(port);
    REQUIRE(port != 0);

    // 2. Spawn godo_tracker_rt with --freed-port=<slave> --ue-host=127.0.0.1
    //    --ue-port=<ephemeral>. Force t-ramp=0 so offsets apply immediately,
    //    and pick RT cpu/prio that work without CAP_SYS_NICE (will log and
    //    continue).
    const std::string slave   = pty.slave_name;
    const std::string ue_port = std::to_string(port);

    // PR-1: tracker now requires a writable pidfile path. Point at a
    // tmp file so the test does not need /run/godo (which doesn't
    // exist in the CI sandbox by default). Per-run unique to avoid
    // colliding with parallel ctest invocations.
    char tmp_pid[256];
    std::snprintf(tmp_pid, sizeof(tmp_pid),
                  "/tmp/godo_rt_replay_%d.pid",
                  static_cast<int>(::getpid()));
    ::unlink(tmp_pid);  // sweep stale leftover from a prior crash.

    // Test isolation: force tracker to use an empty per-run TOML so the
    // production /var/lib/godo/tracker.toml on a developer host (which
    // may carry runtime-injected keys the in-tree Config struct doesn't
    // know about yet — e.g., during a stacked PR) cannot reach into
    // this E2E test. Without this override the tracker default-search
    // would land on the developer host's runtime TOML and fail with
    // "unknown TOML key" before the FreeD path is even exercised.
    char tmp_toml[256];
    std::snprintf(tmp_toml, sizeof(tmp_toml),
                  "/tmp/godo_rt_replay_%d.toml",
                  static_cast<int>(::getpid()));
    {
        std::ofstream(tmp_toml).close();  // create empty file
    }
    ::setenv("GODO_CONFIG_PATH", tmp_toml, /*overwrite=*/1);

    std::vector<std::string> args_store = {
        find_tracker_binary(),
        "--freed-port",   slave,
        "--ue-host",      "127.0.0.1",
        "--ue-port",      ue_port,
        "--t-ramp-ms",    "0",
        "--rt-cpu",       "0",
        "--rt-priority",  "1",
        "--pidfile",      tmp_pid,
        // Phase 4-2 B: cold writer fail-fasts on map-load error. Point at the
        // synthetic fixture so tracker boots; the LiDAR factory will fail
        // open() (no hardware in CI/test) which the cold writer treats as
        // non-fatal — OneShot triggers are ignored, hot path keeps running.
        "--amcl-map-path",
            std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm",
    };
    std::vector<char*> argv;
    for (auto& s : args_store) argv.push_back(const_cast<char*>(s.c_str()));
    argv.push_back(nullptr);

    pid_t pid = -1;
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    int rc = ::posix_spawn(&pid, args_store[0].c_str(), &fa, nullptr,
                           argv.data(), environ);
    posix_spawn_file_actions_destroy(&fa);
    REQUIRE(rc == 0);
    REQUIRE(pid > 0);

    // 3. Drive canned bytes on the PTY master.
    const auto pkt = make_valid_d1(0x42);
    // Write the same packet a few times — the tracker emits every 16.7 ms
    // so we want multiple FreeD updates to cross the loop.
    for (int i = 0; i < 10; ++i) {
        REQUIRE(::write(pty.master, pkt.data(), pkt.size()) ==
                static_cast<ssize_t>(pkt.size()));
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    // 4. Receive UDP. Set non-blocking; gather up to 8 packets in ~500 ms.
    int flags = ::fcntl(udp_fd, F_GETFL, 0);
    ::fcntl(udp_fd, F_SETFL, flags | O_NONBLOCK);

    std::vector<std::array<std::uint8_t, 29>> rx_packets;
    const auto t0 = std::chrono::steady_clock::now();
    while (std::chrono::steady_clock::now() - t0 <
           std::chrono::milliseconds(1500) && rx_packets.size() < 8) {
        std::array<std::uint8_t, 64> buf{};
        const ssize_t n = ::recv(udp_fd, buf.data(), buf.size(), 0);
        if (n == 29) {
            std::array<std::uint8_t, 29> dst{};
            std::memcpy(dst.data(), buf.data(), 29);
            rx_packets.push_back(dst);
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }

    // 5. Stop the tracker.
    ::kill(pid, SIGTERM);
    int status = 0;
    ::waitpid(pid, &status, 0);
    ::close(udp_fd);
    ::close(pty.master);

    // 6. Verify: we received at least one packet, its cam_id matches,
    //    and its checksum is valid. (The exact X/Y/Pan bytes depend on
    //    the stub cold writer's offset sequence, so we check the invariant
    //    layer — type byte, cam_id passthrough, checksum validity — not
    //    the offset arithmetic (which test_udp_apply_offset covers).)
    REQUIRE(!rx_packets.empty());
    for (const auto& r : rx_packets) {
        CHECK(r[godo::constants::FreeD::OFF_TYPE]   == 0xD1);
        CHECK(r[godo::constants::FreeD::OFF_CAM_ID] == 0x42);
        // Checksum must verify.
        std::array<std::byte, 29> tmp{};
        for (std::size_t i = 0; i < tmp.size(); ++i) {
            tmp[i] = static_cast<std::byte>(r[i]);
        }
        const std::uint8_t cs = godo::freed::compute_checksum(
            tmp.data(), tmp.size());
        CHECK(cs == r[godo::constants::FreeD::OFF_CHECKSUM]);
    }

    // Sweep tracker's tmp pidfile (dtor unlinks on graceful shutdown,
    // but a SIGKILL path leaves it). ENOENT is fine.
    ::unlink(tmp_pid);
    // Sweep the test isolation TOML + restore env.
    ::unlink(tmp_toml);
    ::unsetenv("GODO_CONFIG_PATH");
}

#endif  // __linux__
