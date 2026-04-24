#include "d1_parser.hpp"

#include <atomic>
#include <cstdio>
#include <cstring>

#include "core/constants.hpp"

namespace godo::freed {

namespace {

std::atomic<std::uint64_t> g_unknown_type_count{0};
std::atomic<bool>          g_unknown_type_logged_once{false};

}  // namespace

std::uint8_t compute_checksum(const std::byte* bytes, std::size_t len) noexcept {
    // FreeD standard: checksum = (64 - sum(packet[0:28])) mod 256.
    // Mirrors XR_FreeD_to_UDP/src/main.cpp L185-191.
    const std::size_t n =
        (len < static_cast<std::size_t>(godo::constants::FreeD::OFF_CHECKSUM))
            ? len
            : static_cast<std::size_t>(godo::constants::FreeD::OFF_CHECKSUM);
    std::uint16_t sum = 0;
    for (std::size_t i = 0; i < n; ++i) {
        sum = static_cast<std::uint16_t>(
            sum + std::to_integer<std::uint8_t>(bytes[i]));
    }
    return static_cast<std::uint8_t>((64 - (sum & 0xFF)) & 0xFF);
}

ParseResult parse_d1(const std::byte* bytes, std::size_t len) noexcept {
    ParseResult r{};

    if (len < static_cast<std::size_t>(godo::constants::FREED_PACKET_LEN)) {
        r.status = ParseResult::Status::short_buffer;
        return r;
    }

    const std::uint8_t type = std::to_integer<std::uint8_t>(
        bytes[godo::constants::FreeD::OFF_TYPE]);

    if (type != godo::constants::FreeD::TYPE_D1) {
        g_unknown_type_count.fetch_add(1, std::memory_order_relaxed);
        if (!g_unknown_type_logged_once.exchange(true, std::memory_order_acq_rel)) {
            std::fprintf(stderr,
                "freed::parse_d1: first non-D1 type byte 0x%02X; further "
                "occurrences counted silently\n",
                type);
        }
        r.status = ParseResult::Status::unknown_type;
        return r;
    }

    const std::uint8_t expected = compute_checksum(
        bytes, static_cast<std::size_t>(godo::constants::FREED_PACKET_LEN));
    const std::uint8_t actual = std::to_integer<std::uint8_t>(
        bytes[godo::constants::FreeD::OFF_CHECKSUM]);
    if (expected != actual) {
        r.status = ParseResult::Status::bad_checksum;
        return r;
    }

    std::memcpy(r.packet.bytes.data(), bytes,
                static_cast<std::size_t>(godo::constants::FREED_PACKET_LEN));
    r.status = ParseResult::Status::ok;
    return r;
}

std::uint64_t unknown_type_count() noexcept {
    return g_unknown_type_count.load(std::memory_order_relaxed);
}

}  // namespace godo::freed
