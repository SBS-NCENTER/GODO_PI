// Tests for godo::udp::apply_offset_inplace — per-field decode/encode
// round trips, checksum recomputation, pan wrap at ±256°.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <array>
#include <cstddef>
#include <cstdint>

#include "core/constants.hpp"
#include "core/rt_types.hpp"
#include "freed/d1_parser.hpp"
#include "udp/sender.hpp"

using godo::rt::FreedPacket;
using godo::rt::Offset;
using godo::udp::apply_offset_inplace;

namespace {

std::int32_t decode_s24(const std::byte* b) noexcept {
    const std::uint32_t u =
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[0])) << 16) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[1])) <<  8) |
         static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[2]));
    const std::uint32_t sign = (u & 0x00800000U) ? 0xFF000000U : 0U;
    return static_cast<std::int32_t>(u | sign);
}

void encode_s24(std::byte* b, std::int32_t v) noexcept {
    const std::uint32_t u = static_cast<std::uint32_t>(v) & 0x00FFFFFFU;
    b[0] = static_cast<std::byte>((u >> 16) & 0xFFU);
    b[1] = static_cast<std::byte>((u >>  8) & 0xFFU);
    b[2] = static_cast<std::byte>( u        & 0xFFU);
}

FreedPacket make_packet(std::int32_t x_lsb,
                        std::int32_t y_lsb,
                        std::int32_t pan_lsb) noexcept {
    FreedPacket p{};
    std::byte* b = p.bytes.data();
    b[godo::constants::FreeD::OFF_TYPE] =
        static_cast<std::byte>(godo::constants::FreeD::TYPE_D1);
    encode_s24(b + godo::constants::FreeD::OFF_X,   x_lsb);
    encode_s24(b + godo::constants::FreeD::OFF_Y,   y_lsb);
    encode_s24(b + godo::constants::FreeD::OFF_PAN, pan_lsb);
    b[godo::constants::FreeD::OFF_CHECKSUM] =
        static_cast<std::byte>(godo::freed::compute_checksum(
            p.bytes.data(), p.bytes.size()));
    return p;
}

}  // namespace

TEST_CASE("apply_offset_inplace: zero offset is a perfect passthrough") {
    const FreedPacket in = make_packet(100, 200, 300);
    FreedPacket out = in;
    apply_offset_inplace(out, Offset{0.0, 0.0, 0.0});
    for (std::size_t i = 0; i < in.bytes.size(); ++i) {
        CHECK(out.bytes[i] == in.bytes[i]);
    }
}

TEST_CASE("apply_offset_inplace: positive metre offset increases X/Y in lsb") {
    FreedPacket p = make_packet(0, 0, 0);
    // +1 m on X = +64000 lsb, +2 m on Y = +128000 lsb.
    apply_offset_inplace(p, Offset{1.0, 2.0, 0.0});
    const std::int32_t x = decode_s24(p.bytes.data() + godo::constants::FreeD::OFF_X);
    const std::int32_t y = decode_s24(p.bytes.data() + godo::constants::FreeD::OFF_Y);
    CHECK(x == 64000);
    CHECK(y == 128000);
}

TEST_CASE("apply_offset_inplace: negative metre offset decreases X/Y in lsb") {
    FreedPacket p = make_packet(200000, 100000, 0);
    apply_offset_inplace(p, Offset{-1.0, -1.0, 0.0});
    const std::int32_t x = decode_s24(p.bytes.data() + godo::constants::FreeD::OFF_X);
    const std::int32_t y = decode_s24(p.bytes.data() + godo::constants::FreeD::OFF_Y);
    CHECK(x == 200000 - 64000);
    CHECK(y == 100000 - 64000);
}

TEST_CASE("apply_offset_inplace: pan wrap beyond +256 deg folds to negative") {
    // Start at +250 deg encoded. Add +20 deg (dyaw = 20.0). 270 > +256
    // so wrap_signed24 folds the result into the negative half.
    constexpr std::int32_t deg_250_lsb = static_cast<std::int32_t>(250.0 * 32768.0);
    FreedPacket p = make_packet(0, 0, deg_250_lsb);
    apply_offset_inplace(p, Offset{0.0, 0.0, 20.0});
    const std::int32_t pan = decode_s24(p.bytes.data() + godo::constants::FreeD::OFF_PAN);
    // 270 - 512 = -242 deg expected (the signed-24 fold is mod 512 deg).
    constexpr std::int32_t H = 1 << 23;      // +256 deg
    CHECK(pan <  H);
    CHECK(pan < 0);
    // Exact value: 270 deg in lsb = 270 * 32768 = 8_847_360. Minus 2^24
    // (= 16_777_216) = -7_929_856.
    CHECK(pan == 270 * 32768 - (1 << 24));
}

TEST_CASE("apply_offset_inplace: checksum is recomputed") {
    FreedPacket p = make_packet(500, 600, 700);
    const std::uint8_t original_cs = std::to_integer<std::uint8_t>(
        p.bytes[godo::constants::FreeD::OFF_CHECKSUM]);
    apply_offset_inplace(p, Offset{0.123, -0.456, 7.89});
    const std::uint8_t new_cs = std::to_integer<std::uint8_t>(
        p.bytes[godo::constants::FreeD::OFF_CHECKSUM]);
    // New checksum must match the recomputation on the NEW payload.
    const std::uint8_t expected_cs =
        godo::freed::compute_checksum(p.bytes.data(), p.bytes.size());
    CHECK(new_cs == expected_cs);
    // And it should differ from the original (the payload changed).
    CHECK(new_cs != original_cs);
}
