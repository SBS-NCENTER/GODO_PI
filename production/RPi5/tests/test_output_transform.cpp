// issue#27 — udp::output_transform tests.
//
// Per-channel coverage (X/Y/Z/Pan/Tilt/Roll): identity, offset-only,
// sign-only, combined, signed24 wrap boundary. Zoom + Focus pass-through
// pin. Checksum recomputation pin. Decode round-trip pin.
//
// Per-channel-perf micro-bench is documented in the plan but not added
// to the test target — the hot-path budget (≤ 200 ns at 60 Hz) is
// validated by the existing jitter benchmark on news-pi01 post-deploy
// (operator HIL).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <array>
#include <cstdint>

#include "core/constants.hpp"
#include "core/rt_types.hpp"
#include "freed/d1_parser.hpp"
#include "udp/output_transform.hpp"
#include "udp/wire_codec.hpp"

using godo::rt::FreedPacket;
using godo::rt::LastOutputFrame;
using godo::udp::OutputTransform;
using godo::udp::apply_output_transform_inplace;
using godo::udp::decode_last_output_from_packet;
using godo::udp::wire::decode_signed24_be;
using godo::udp::wire::encode_signed24_be;

namespace {

FreedPacket make_packet_with(
    std::int32_t x_lsb,
    std::int32_t y_lsb,
    std::int32_t z_lsb,
    std::int32_t pan_lsb,
    std::int32_t tilt_lsb,
    std::int32_t roll_lsb,
    std::uint32_t zoom_u24,
    std::uint32_t focus_u24
) noexcept {
    FreedPacket p{};
    std::byte* b = p.bytes.data();
    b[godo::constants::FreeD::OFF_TYPE] =
        static_cast<std::byte>(godo::constants::FreeD::TYPE_D1);
    encode_signed24_be(b + godo::constants::FreeD::OFF_X,    x_lsb);
    encode_signed24_be(b + godo::constants::FreeD::OFF_Y,    y_lsb);
    encode_signed24_be(b + godo::constants::FreeD::OFF_Z,    z_lsb);
    encode_signed24_be(b + godo::constants::FreeD::OFF_PAN,  pan_lsb);
    encode_signed24_be(b + godo::constants::FreeD::OFF_TILT, tilt_lsb);
    encode_signed24_be(b + godo::constants::FreeD::OFF_ROLL, roll_lsb);
    // Zoom + Focus are unsigned24 BE.
    auto encode_u24 = [](std::byte* dst, std::uint32_t v) noexcept {
        dst[0] = static_cast<std::byte>((v >> 16) & 0xFFU);
        dst[1] = static_cast<std::byte>((v >>  8) & 0xFFU);
        dst[2] = static_cast<std::byte>( v        & 0xFFU);
    };
    encode_u24(b + godo::constants::FreeD::OFF_ZOOM,  zoom_u24);
    encode_u24(b + godo::constants::FreeD::OFF_FOCUS, focus_u24);
    b[godo::constants::FreeD::OFF_CHECKSUM] = static_cast<std::byte>(
        godo::freed::compute_checksum(p.bytes.data(), p.bytes.size()));
    return p;
}

OutputTransform identity_transform() noexcept {
    return OutputTransform{};  // all defaults (offsets=0, signs=+1)
}

}  // namespace

TEST_CASE("apply_output_transform_inplace identity preserves payload") {
    FreedPacket p = make_packet_with(
        100, 200, 300, 400, 500, 600,
        0x080000U, 0x080001U);
    FreedPacket before = p;
    apply_output_transform_inplace(p, identity_transform());
    // Bytes 0..27 byte-identical (the transform recomputes checksum
    // from the same underlying bytes; identity is a no-op).
    for (std::size_t i = 0; i < godo::constants::FREED_PACKET_LEN; ++i) {
        CHECK(p.bytes[i] == before.bytes[i]);
    }
}

TEST_CASE("apply_output_transform_inplace x_offset_m only") {
    FreedPacket p = make_packet_with(0, 0, 0, 0, 0, 0, 0, 0);
    OutputTransform t = identity_transform();
    t.x_offset_m = 1.0;
    apply_output_transform_inplace(p, t);
    const std::int32_t x = decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_X);
    CHECK(x == 64000);  // +1 m × 64000 lsb/m
    // Y/Z/Pan/Tilt/Roll untouched.
    CHECK(decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_Y) == 0);
    CHECK(decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_Z) == 0);
    CHECK(decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_PAN) == 0);
    CHECK(decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_TILT) == 0);
    CHECK(decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_ROLL) == 0);
}

TEST_CASE("apply_output_transform_inplace x_sign=-1 flips encoded value") {
    FreedPacket p = make_packet_with(64000, 0, 0, 0, 0, 0, 0, 0);  // +1 m
    OutputTransform t = identity_transform();
    t.x_sign = -1;
    apply_output_transform_inplace(p, t);
    const std::int32_t x = decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_X);
    CHECK(x == -64000);  // sign * (raw + 0) = -1 * 1.0 m
}

TEST_CASE("apply_output_transform_inplace combined offset + sign on X") {
    FreedPacket p = make_packet_with(64000, 0, 0, 0, 0, 0, 0, 0);  // +1 m
    OutputTransform t = identity_transform();
    t.x_offset_m = 1.0;
    t.x_sign = -1;
    apply_output_transform_inplace(p, t);
    const std::int32_t x = decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_X);
    // final = sign * (raw + offset) = -1 * (1.0 + 1.0) = -2.0 m
    CHECK(x == -128000);
}

TEST_CASE("apply_output_transform_inplace per-channel coverage Y/Z/Pan/Tilt/Roll") {
    SUBCASE("Y offset") {
        FreedPacket p = make_packet_with(0, 0, 0, 0, 0, 0, 0, 0);
        OutputTransform t = identity_transform();
        t.y_offset_m = 2.0;
        apply_output_transform_inplace(p, t);
        CHECK(decode_signed24_be(
            p.bytes.data() + godo::constants::FreeD::OFF_Y) == 128000);
    }
    SUBCASE("Z offset") {
        FreedPacket p = make_packet_with(0, 0, 0, 0, 0, 0, 0, 0);
        OutputTransform t = identity_transform();
        t.z_offset_m = -0.5;
        apply_output_transform_inplace(p, t);
        CHECK(decode_signed24_be(
            p.bytes.data() + godo::constants::FreeD::OFF_Z) == -32000);
    }
    SUBCASE("Pan offset") {
        FreedPacket p = make_packet_with(0, 0, 0, 0, 0, 0, 0, 0);
        OutputTransform t = identity_transform();
        t.pan_offset_deg = 45.0;
        apply_output_transform_inplace(p, t);
        const std::int32_t pan = decode_signed24_be(
            p.bytes.data() + godo::constants::FreeD::OFF_PAN);
        // 45° × 32768 lsb/° = 1474560
        CHECK(pan == 1474560);
    }
    SUBCASE("Tilt sign + offset") {
        FreedPacket p = make_packet_with(
            0, 0, 0, 0, 32768, 0, 0, 0);  // +1°
        OutputTransform t = identity_transform();
        t.tilt_offset_deg = 1.0;
        t.tilt_sign = -1;
        apply_output_transform_inplace(p, t);
        const std::int32_t tilt = decode_signed24_be(
            p.bytes.data() + godo::constants::FreeD::OFF_TILT);
        // final = -1 * (1.0 + 1.0) = -2°
        CHECK(tilt == -65536);
    }
    SUBCASE("Roll sign only") {
        FreedPacket p = make_packet_with(
            0, 0, 0, 0, 0, 32768, 0, 0);  // +1°
        OutputTransform t = identity_transform();
        t.roll_sign = -1;
        apply_output_transform_inplace(p, t);
        const std::int32_t roll = decode_signed24_be(
            p.bytes.data() + godo::constants::FreeD::OFF_ROLL);
        CHECK(roll == -32768);
    }
}

TEST_CASE("apply_output_transform_inplace zoom + focus byte-identical") {
    const std::uint32_t zoom_in = 0x012345U;
    const std::uint32_t focus_in = 0x067890U;
    FreedPacket p = make_packet_with(0, 0, 0, 0, 0, 0, zoom_in, focus_in);
    OutputTransform t = identity_transform();
    // Set every transformed channel's offset + sign so we know the
    // transform is non-trivial; zoom + focus must still pass through.
    t.x_offset_m = 1.0; t.x_sign = -1;
    t.y_offset_m = 2.0; t.y_sign = -1;
    t.z_offset_m = 3.0; t.z_sign = -1;
    t.pan_offset_deg = 30.0; t.pan_sign = -1;
    t.tilt_offset_deg = 15.0; t.tilt_sign = -1;
    t.roll_offset_deg = 7.5; t.roll_sign = -1;
    apply_output_transform_inplace(p, t);
    auto decode_u24 = [](const std::byte* b) noexcept -> std::uint32_t {
        return (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[0])) << 16) |
               (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[1])) <<  8) |
                static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[2]));
    };
    CHECK(decode_u24(p.bytes.data() + godo::constants::FreeD::OFF_ZOOM)  == zoom_in);
    CHECK(decode_u24(p.bytes.data() + godo::constants::FreeD::OFF_FOCUS) == focus_in);
}

TEST_CASE("apply_output_transform_inplace recomputes checksum") {
    FreedPacket p = make_packet_with(100, 200, 300, 400, 500, 600, 0, 0);
    OutputTransform t = identity_transform();
    t.x_offset_m = 0.5;
    apply_output_transform_inplace(p, t);
    const std::uint8_t actual = std::to_integer<std::uint8_t>(
        p.bytes[godo::constants::FreeD::OFF_CHECKSUM]);
    const std::uint8_t expected = godo::freed::compute_checksum(
        p.bytes.data(), godo::constants::FREED_PACKET_LEN);
    CHECK(actual == expected);
}

TEST_CASE("apply_output_transform_inplace signed24 wrap at boundary") {
    // Pan: encode +250° then add +20° via offset. The wrap_signed24
    // mod-2^24 fold lands at -242°, mirroring apply_offset_inplace.
    const std::int32_t deg_250_lsb = static_cast<std::int32_t>(250.0 * 32768.0);
    FreedPacket p = make_packet_with(0, 0, 0, deg_250_lsb, 0, 0, 0, 0);
    OutputTransform t = identity_transform();
    t.pan_offset_deg = 20.0;
    apply_output_transform_inplace(p, t);
    const std::int32_t pan = decode_signed24_be(
        p.bytes.data() + godo::constants::FreeD::OFF_PAN);
    // 270 deg in lsb = 270 * 32768 = 8'847'360. Minus 2^24 (16'777'216)
    // = -7'929'856. Same as test_udp_apply_offset's pan-wrap case.
    CHECK(pan == 270 * 32768 - (1 << 24));
}

TEST_CASE("decode_last_output_from_packet round-trip") {
    // Encode known values, run the transform with identity, then decode.
    // Round-trip error must be ≤ 1 lsb per channel (real-unit precision).
    FreedPacket p = make_packet_with(
        64000,    // X = +1.000 m
        -32000,   // Y = -0.500 m
        12800,    // Z = +0.200 m
        1474560,  // Pan  = +45°
        -65536,   // Tilt = -2°
        16384,    // Roll = +0.5°
        0x080000U,  // Zoom raw = 524288
        0x07ABCDU); // Focus raw = 0x07ABCD = 502733
    apply_output_transform_inplace(p, identity_transform());
    LastOutputFrame f = decode_last_output_from_packet(p);
    CHECK(f.x_m       == doctest::Approx(1.0).epsilon(1e-9));
    CHECK(f.y_m       == doctest::Approx(-0.5).epsilon(1e-9));
    CHECK(f.z_m       == doctest::Approx(0.2).epsilon(1e-9));
    CHECK(f.pan_deg   == doctest::Approx(45.0).epsilon(1e-9));
    CHECK(f.tilt_deg  == doctest::Approx(-2.0).epsilon(1e-9));
    CHECK(f.roll_deg  == doctest::Approx(0.5).epsilon(1e-9));
    CHECK(f.zoom      == doctest::Approx(524288.0));
    CHECK(f.focus     == doctest::Approx(502733.0));
    // valid + published_mono_ns are NOT touched by the decoder; the
    // caller (Thread D) sets them after this call.
    CHECK(f.valid == 0);
    CHECK(f.published_mono_ns == 0);
}
