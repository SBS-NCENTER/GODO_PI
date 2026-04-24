#include "sender.hpp"

#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <system_error>

#include "core/constants.hpp"
#include "freed/d1_parser.hpp"
#include "yaw/yaw.hpp"

namespace godo::udp {

namespace {

using namespace godo::constants;

// Decode a 24-bit big-endian signed integer from `b[off..off+3)`.
// Sign-extended from bit 23.
std::int32_t decode_signed24_be(const std::byte* b) noexcept {
    const std::uint32_t u =
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[0])) << 16) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[1])) <<  8) |
         static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[2]));
    // Sign-extend from 24 bits.
    const std::uint32_t sign = (u & 0x00800000U) ? 0xFF000000U : 0U;
    return static_cast<std::int32_t>(u | sign);
}

void encode_signed24_be(std::byte* b, std::int32_t v) noexcept {
    const std::uint32_t u = static_cast<std::uint32_t>(v) & 0x00FFFFFFU;
    b[0] = static_cast<std::byte>((u >> 16) & 0xFFU);
    b[1] = static_cast<std::byte>((u >>  8) & 0xFFU);
    b[2] = static_cast<std::byte>((u      ) & 0xFFU);
}

bool is_all_zero(const godo::rt::FreedPacket& p) noexcept {
    for (auto b : p.bytes) {
        if (std::to_integer<std::uint8_t>(b) != 0U) return false;
    }
    return true;
}

}  // namespace

void apply_offset_inplace(godo::rt::FreedPacket& p,
                          const godo::rt::Offset& off) noexcept {
    std::byte* const bytes = p.bytes.data();

    // X, Y: signed 24-bit, 1/64 mm per lsb. off.dx/off.dy are metres.
    // metres → mm is ×1000; mm → lsb is ×64. Combined: ×64000.
    const std::int32_t x_in = decode_signed24_be(bytes + FreeD::OFF_X);
    const std::int32_t y_in = decode_signed24_be(bytes + FreeD::OFF_Y);
    const std::int64_t x_out = static_cast<std::int64_t>(x_in) +
        static_cast<std::int64_t>(std::llround(off.dx * 1000.0 * 64.0));
    const std::int64_t y_out = static_cast<std::int64_t>(y_in) +
        static_cast<std::int64_t>(std::llround(off.dy * 1000.0 * 64.0));
    encode_signed24_be(bytes + FreeD::OFF_X, godo::yaw::wrap_signed24(x_out));
    encode_signed24_be(bytes + FreeD::OFF_Y, godo::yaw::wrap_signed24(y_out));

    // Pan: signed 24-bit, 1/32768 deg per lsb. off.dyaw is degrees.
    const std::int32_t pan_in = decode_signed24_be(bytes + FreeD::OFF_PAN);
    const std::int64_t pan_out = static_cast<std::int64_t>(pan_in) +
        static_cast<std::int64_t>(std::llround(off.dyaw * 32768.0));
    encode_signed24_be(bytes + FreeD::OFF_PAN, godo::yaw::wrap_signed24(pan_out));

    // Recompute checksum over bytes 0..27.
    bytes[FreeD::OFF_CHECKSUM] = static_cast<std::byte>(
        godo::freed::compute_checksum(bytes, FREED_PACKET_LEN));
}

UdpSender::UdpSender(std::string host, int port)
    : host_(std::move(host)), port_(port) {
    fd_ = ::socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK, 0);
    if (fd_ < 0) {
        throw std::system_error(errno, std::generic_category(),
                                "udp::UdpSender: socket()");
    }

    sockaddr_in sa{};
    sa.sin_family = AF_INET;
    sa.sin_port   = htons(static_cast<std::uint16_t>(port_));
    if (::inet_pton(AF_INET, host_.c_str(), &sa.sin_addr) != 1) {
        // Try hostname resolution (getaddrinfo) as a fallback.
        addrinfo hints{};
        hints.ai_family   = AF_INET;
        hints.ai_socktype = SOCK_DGRAM;
        addrinfo* res = nullptr;
        const int rc = ::getaddrinfo(host_.c_str(), nullptr, &hints, &res);
        if (rc != 0 || res == nullptr) {
            ::close(fd_);
            fd_ = -1;
            throw std::runtime_error(
                std::string("udp::UdpSender: cannot resolve '") + host_ +
                "': " + (rc != 0 ? gai_strerror(rc) : "no results"));
        }
        sa = *reinterpret_cast<const sockaddr_in*>(res->ai_addr);
        sa.sin_port = htons(static_cast<std::uint16_t>(port_));
        ::freeaddrinfo(res);
    }

    if (::connect(fd_, reinterpret_cast<const sockaddr*>(&sa), sizeof(sa)) != 0) {
        const int err = errno;
        ::close(fd_);
        fd_ = -1;
        throw std::system_error(err, std::generic_category(),
                                "udp::UdpSender: connect()");
    }
}

UdpSender::~UdpSender() noexcept {
    if (fd_ >= 0) ::close(fd_);
}

bool UdpSender::send(const godo::rt::FreedPacket& p) noexcept {
    if (is_all_zero(p)) {
        if (!empty_frame_logged_) {
            std::fprintf(stderr,
                "udp::UdpSender: empty (all-zero) FreeD packet — crane "
                "likely not connected yet; further empty frames are "
                "silent\n");
            empty_frame_logged_ = true;
        }
        return true;
    }

    const ssize_t n = ::send(fd_, p.bytes.data(),
                             godo::constants::FREED_PACKET_LEN, 0);
    if (n == godo::constants::FREED_PACKET_LEN) return true;

    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        ++eagain_miss_count_;
        if (eagain_miss_count_ % 1000U == 0U) {
            std::fprintf(stderr,
                "udp::UdpSender: %lu consecutive send() EAGAIN — receiver "
                "may be dead or socket buffer overfull\n",
                static_cast<unsigned long>(eagain_miss_count_));
        }
        return false;
    }

    std::fprintf(stderr,
        "udp::UdpSender: send() returned %zd errno=%d (%s)\n",
        n, errno, std::strerror(errno));
    return false;
}

}  // namespace godo::udp
