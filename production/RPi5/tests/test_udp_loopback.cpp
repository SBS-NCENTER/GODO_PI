// UDP sender loopback test — AF_INET on 127.0.0.1, byte-identical
// send/recv. Ensures UdpSender actually wires up the socket correctly
// (connect() semantics, non-blocking send, etc.).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <cstdint>
#include <cstring>

#include "core/constants.hpp"
#include "core/rt_types.hpp"
#include "udp/sender.hpp"

using godo::rt::FreedPacket;

namespace {

// Open a receiver on 127.0.0.1:0 (ephemeral port); return (fd, port).
int open_receiver(std::uint16_t& port_out) {
    int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
    REQUIRE(fd >= 0);
    sockaddr_in sa{};
    sa.sin_family      = AF_INET;
    sa.sin_port        = 0;
    sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    REQUIRE(::bind(fd, reinterpret_cast<const sockaddr*>(&sa), sizeof(sa)) == 0);
    sockaddr_in bound{};
    socklen_t bound_len = sizeof(bound);
    REQUIRE(::getsockname(fd, reinterpret_cast<sockaddr*>(&bound), &bound_len) == 0);
    port_out = ntohs(bound.sin_port);
    return fd;
}

}  // namespace

TEST_CASE("UdpSender: loopback send/recv is byte-identical") {
    std::uint16_t port = 0;
    const int rx = open_receiver(port);
    REQUIRE(port != 0);

    godo::udp::UdpSender sender("127.0.0.1", static_cast<int>(port));

    FreedPacket p{};
    p.bytes[godo::constants::FreeD::OFF_TYPE] =
        static_cast<std::byte>(godo::constants::FreeD::TYPE_D1);
    for (std::size_t i = 1; i < p.bytes.size() - 1; ++i) {
        p.bytes[i] = static_cast<std::byte>(i & 0xFFU);
    }
    p.bytes[p.bytes.size() - 1] = static_cast<std::byte>(0xAA);

    CHECK(sender.send(p));

    std::array<std::uint8_t, 64> buf{};
    const ssize_t n = ::recv(rx, buf.data(), buf.size(), 0);
    REQUIRE(n == static_cast<ssize_t>(godo::constants::FREED_PACKET_LEN));
    for (std::size_t i = 0; i < static_cast<std::size_t>(n); ++i) {
        CHECK(buf[i] == std::to_integer<std::uint8_t>(p.bytes[i]));
    }

    ::close(rx);
}

TEST_CASE("UdpSender: all-zero packet is skipped and send() still returns true") {
    std::uint16_t port = 0;
    const int rx = open_receiver(port);
    REQUIRE(port != 0);

    godo::udp::UdpSender sender("127.0.0.1", static_cast<int>(port));
    FreedPacket zero{};                       // all zero bytes
    CHECK(sender.send(zero));                 // skipped, not an error

    // Set socket non-blocking so recv returns immediately when nothing arrived.
    int flags = ::fcntl(rx, F_GETFL, 0);
    ::fcntl(rx, F_SETFL, flags | O_NONBLOCK);
    std::array<std::uint8_t, 64> buf{};
    const ssize_t n = ::recv(rx, buf.data(), buf.size(), 0);
    CHECK(n < 0);
    CHECK((errno == EAGAIN || errno == EWOULDBLOCK));

    ::close(rx);
}
