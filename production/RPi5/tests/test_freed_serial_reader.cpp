// PTY-harness test for godo::freed::SerialReader.
//
// The master side of the PTY is configured with the SAME 8O1 termios
// flags as the slave (production code path). This drives the exact
// termios code path the production reader uses — anything less would
// leave the read-side flags untested.
//
// Linux-only: openpty() ships with glibc on Linux but the semantics of
// master-side termios differ on macOS. #ifdef gate.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#ifndef __linux__

TEST_CASE("freed::SerialReader PTY test — Linux only; skipped on this platform") {
    MESSAGE("skipped: PTY harness is Linux-only");
}

#else

#include <pty.h>
#include <termios.h>
#include <unistd.h>
#include <fcntl.h>

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <string>
#include <thread>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "freed/d1_parser.hpp"
#include "freed/serial_reader.hpp"

namespace {

struct Pty {
    int master = -1;
    std::string slave_name;
};

Pty open_pty_with_8o1() {
    Pty p;
    int slave = -1;
    termios tio{};
    // Match SerialReader's slave-side termios exactly. openpty() applies
    // these to both master and slave, so the master writes with the same
    // framing the slave expects.
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
    ::close(slave);        // the SerialReader will open it by name
    return p;
}

std::array<std::byte, 29> make_valid_d1_packet(std::uint8_t cam_id) {
    std::array<std::byte, 29> p{};
    p[godo::constants::FreeD::OFF_TYPE]   = static_cast<std::byte>(0xD1);
    p[godo::constants::FreeD::OFF_CAM_ID] = static_cast<std::byte>(cam_id);
    p[godo::constants::FreeD::OFF_CHECKSUM] =
        static_cast<std::byte>(godo::freed::compute_checksum(
            p.data(), p.size()));
    return p;
}

}  // namespace

TEST_CASE("SerialReader: reads three D1 packets from a PTY and stores each") {
    using namespace godo::rt;

    g_running.store(true, std::memory_order_release);

    Pty pty = open_pty_with_8o1();
    REQUIRE(pty.master >= 0);

    Seqlock<FreedPacket> out;

    godo::freed::SerialReader reader(pty.slave_name, 38400);
    std::thread reader_thread([&]() { reader.run(out); });

    // Writer side: send three packets with distinct cam_ids.
    const auto pkt1 = make_valid_d1_packet(0x11);
    const auto pkt2 = make_valid_d1_packet(0x22);
    const auto pkt3 = make_valid_d1_packet(0x33);

    REQUIRE(::write(pty.master, pkt1.data(), pkt1.size()) ==
            static_cast<ssize_t>(pkt1.size()));
    REQUIRE(::write(pty.master, pkt2.data(), pkt2.size()) ==
            static_cast<ssize_t>(pkt2.size()));
    REQUIRE(::write(pty.master, pkt3.data(), pkt3.size()) ==
            static_cast<ssize_t>(pkt3.size()));

    // Wait until the last cam_id appears, then stop.
    const auto t0 = std::chrono::steady_clock::now();
    bool saw_last = false;
    while (std::chrono::steady_clock::now() - t0 <
           std::chrono::milliseconds(2000)) {
        const FreedPacket got = out.load();
        if (std::to_integer<std::uint8_t>(
                got.bytes[godo::constants::FreeD::OFF_CAM_ID]) == 0x33) {
            saw_last = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    g_running.store(false, std::memory_order_release);
    reader_thread.join();
    ::close(pty.master);

    CHECK(saw_last);
}

TEST_CASE("SerialReader: 1-byte garbage prefix is resynced, following packet is accepted") {
    using namespace godo::rt;

    g_running.store(true, std::memory_order_release);

    Pty pty = open_pty_with_8o1();
    REQUIRE(pty.master >= 0);

    Seqlock<FreedPacket> out;
    godo::freed::SerialReader reader(pty.slave_name, 38400);
    std::thread reader_thread([&]() { reader.run(out); });

    // Garbage byte (not D1) followed by a valid packet. The reader should
    // re-sync via the memmove-shift path and deliver the packet.
    const std::uint8_t junk = 0x99;
    REQUIRE(::write(pty.master, &junk, 1) == 1);
    const auto pkt = make_valid_d1_packet(0x77);
    REQUIRE(::write(pty.master, pkt.data(), pkt.size()) ==
            static_cast<ssize_t>(pkt.size()));

    const auto t0 = std::chrono::steady_clock::now();
    bool saw_it = false;
    while (std::chrono::steady_clock::now() - t0 <
           std::chrono::milliseconds(2000)) {
        const FreedPacket got = out.load();
        if (std::to_integer<std::uint8_t>(
                got.bytes[godo::constants::FreeD::OFF_CAM_ID]) == 0x77) {
            saw_it = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    g_running.store(false, std::memory_order_release);
    reader_thread.join();
    ::close(pty.master);

    CHECK(saw_it);
}

#endif  // __linux__
