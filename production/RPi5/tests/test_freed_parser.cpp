// FreeD D1 parser tests — synthesized fixtures.
// Byte-layout citations: XR_FreeD_to_UDP/src/main.cpp
//   L17-31   wire format
//   L67-85   field offsets (TYPE, PAN, TILT, ROLL, X, Y, Z, ZOOM, FOCUS,
//            STATUS, CHECKSUM)
//   L185-191 checksum = (64 - sum(bytes[0:28])) & 0xFF

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <array>
#include <cstddef>
#include <cstdint>

#include "core/constants.hpp"
#include "freed/d1_parser.hpp"

using godo::freed::compute_checksum;
using godo::freed::parse_d1;
using godo::freed::ParseResult;

namespace {

using Packet = std::array<std::byte, 29>;

// Build a zero-filled D1 packet with the correct checksum applied.
Packet make_d1_zeros() noexcept {
    Packet p{};
    p[godo::constants::FreeD::OFF_TYPE] =
        static_cast<std::byte>(godo::constants::FreeD::TYPE_D1);
    // sum(0xD1, 0, 0, ...) = 0xD1 = 209; checksum = (64 - 209) & 0xFF = 0x6F.
    const std::uint8_t cs = compute_checksum(p.data(), p.size());
    p[godo::constants::FreeD::OFF_CHECKSUM] = static_cast<std::byte>(cs);
    return p;
}

}  // namespace

TEST_CASE("parse_d1: ok path on a canonical zero packet") {
    const Packet p = make_d1_zeros();
    const ParseResult r = parse_d1(p.data(), p.size());
    CHECK(r.status == ParseResult::Status::ok);
    // Copy-out is byte-identical.
    for (std::size_t i = 0; i < p.size(); ++i) {
        CHECK(r.packet.bytes[i] == p[i]);
    }
}

TEST_CASE("parse_d1: short buffer returns short_buffer") {
    const std::array<std::byte, 10> tiny{};
    const ParseResult r = parse_d1(tiny.data(), tiny.size());
    CHECK(r.status == ParseResult::Status::short_buffer);
}

TEST_CASE("parse_d1: non-D1 type returns unknown_type") {
    Packet p = make_d1_zeros();
    p[godo::constants::FreeD::OFF_TYPE] = static_cast<std::byte>(0xAB);
    const ParseResult r = parse_d1(p.data(), p.size());
    CHECK(r.status == ParseResult::Status::unknown_type);
}

TEST_CASE("parse_d1: bad checksum returns bad_checksum") {
    Packet p = make_d1_zeros();
    // Corrupt the checksum byte directly.
    p[godo::constants::FreeD::OFF_CHECKSUM] = static_cast<std::byte>(0x00);
    const ParseResult r = parse_d1(p.data(), p.size());
    CHECK(r.status == ParseResult::Status::bad_checksum);
}

TEST_CASE("parse_d1: compute_checksum on all-zero-plus-header gives 0x6F") {
    // sum(0xD1) & 0xFF = 0xD1; (64 - 0xD1) & 0xFF = (0x40 - 0xD1) & 0xFF
    // = (0x40 - 0xD1 mod 256) = (64 - 209 mod 256) = -145 mod 256 = 111 = 0x6F.
    std::array<std::byte, 29> p{};
    p[0] = static_cast<std::byte>(0xD1);
    const std::uint8_t cs = compute_checksum(p.data(), p.size());
    CHECK(cs == 0x6F);
}

TEST_CASE("parse_d1: compute_checksum stops at OFF_CHECKSUM") {
    // Byte 28 itself is NOT included in the sum; toggling it must not
    // change the computed checksum.
    std::array<std::byte, 29> p{};
    p[0] = static_cast<std::byte>(0xD1);
    const std::uint8_t cs_zero = compute_checksum(p.data(), p.size());
    p[28] = static_cast<std::byte>(0xFF);
    const std::uint8_t cs_ff   = compute_checksum(p.data(), p.size());
    CHECK(cs_zero == cs_ff);
}

TEST_CASE("parse_d1: checksum round-trip on a populated packet") {
    // Populate the payload bytes with a distinctive pattern, recompute the
    // checksum, then prove parse_d1 accepts it.
    Packet p{};
    p[godo::constants::FreeD::OFF_TYPE]   = static_cast<std::byte>(0xD1);
    p[godo::constants::FreeD::OFF_CAM_ID] = static_cast<std::byte>(0x01);
    // Pan = 0x010203 (signed 24-bit big-endian).
    p[godo::constants::FreeD::OFF_PAN + 0] = static_cast<std::byte>(0x01);
    p[godo::constants::FreeD::OFF_PAN + 1] = static_cast<std::byte>(0x02);
    p[godo::constants::FreeD::OFF_PAN + 2] = static_cast<std::byte>(0x03);
    // X = 0x0A0B0C.
    p[godo::constants::FreeD::OFF_X + 0] = static_cast<std::byte>(0x0A);
    p[godo::constants::FreeD::OFF_X + 1] = static_cast<std::byte>(0x0B);
    p[godo::constants::FreeD::OFF_X + 2] = static_cast<std::byte>(0x0C);
    p[godo::constants::FreeD::OFF_CHECKSUM] =
        static_cast<std::byte>(compute_checksum(p.data(), p.size()));

    const ParseResult r = parse_d1(p.data(), p.size());
    CHECK(r.status == ParseResult::Status::ok);
}

TEST_CASE("parse_d1: unknown_type count is monotonic") {
    const std::uint64_t before = godo::freed::unknown_type_count();
    Packet p = make_d1_zeros();
    p[godo::constants::FreeD::OFF_TYPE] = static_cast<std::byte>(0x42);
    (void)parse_d1(p.data(), p.size());
    (void)parse_d1(p.data(), p.size());
    const std::uint64_t after = godo::freed::unknown_type_count();
    CHECK(after >= before + 2);
}
