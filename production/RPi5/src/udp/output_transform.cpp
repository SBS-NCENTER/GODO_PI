#include "output_transform.hpp"

#include <cmath>
#include <cstdint>

#include "core/constants.hpp"
#include "freed/d1_parser.hpp"
#include "udp/wire_codec.hpp"
#include "yaw/yaw.hpp"

namespace godo::udp {

namespace {

using namespace godo::constants;
using godo::udp::wire::decode_signed24_be;
using godo::udp::wire::encode_signed24_be;

// Apply `final = sign * (raw_lsb / lsb_per_unit + offset_unit)` in
// scaled-double space, then re-encode as signed24 with wrap. The
// double round-trip preserves the operator-readable units (m, °) while
// the existing wrap_signed24 keeps the ±256° / ±131 m wraparound
// semantics consistent with `apply_offset_inplace`.
void transform_signed24_channel(std::byte* bytes,
                                int        offset,
                                double     lsb_per_unit,
                                double     offset_unit,
                                int        sign) noexcept {
    const std::int32_t raw = decode_signed24_be(bytes + offset);
    const double raw_unit = static_cast<double>(raw) / lsb_per_unit;
    const double final_unit = static_cast<double>(sign) * (raw_unit + offset_unit);
    const std::int64_t out_lsb =
        static_cast<std::int64_t>(std::llround(final_unit * lsb_per_unit));
    encode_signed24_be(bytes + offset, godo::yaw::wrap_signed24(out_lsb));
}

}  // namespace

void apply_output_transform_inplace(godo::rt::FreedPacket& p,
                                    const OutputTransform& t) noexcept {
    std::byte* const bytes = p.bytes.data();

    transform_signed24_channel(
        bytes, FreeD::OFF_X, FREED_POS_LSB_PER_M,
        t.x_offset_m, t.x_sign);
    transform_signed24_channel(
        bytes, FreeD::OFF_Y, FREED_POS_LSB_PER_M,
        t.y_offset_m, t.y_sign);
    transform_signed24_channel(
        bytes, FreeD::OFF_Z, FREED_POS_LSB_PER_M,
        t.z_offset_m, t.z_sign);
    transform_signed24_channel(
        bytes, FreeD::OFF_PAN, FREED_PAN_LSB_PER_DEG,
        t.pan_offset_deg, t.pan_sign);
    transform_signed24_channel(
        bytes, FreeD::OFF_TILT, FREED_PAN_LSB_PER_DEG,
        t.tilt_offset_deg, t.tilt_sign);
    transform_signed24_channel(
        bytes, FreeD::OFF_ROLL, FREED_PAN_LSB_PER_DEG,
        t.roll_offset_deg, t.roll_sign);

    bytes[FreeD::OFF_CHECKSUM] = static_cast<std::byte>(
        godo::freed::compute_checksum(bytes, FREED_PACKET_LEN));
}

godo::rt::LastOutputFrame decode_last_output_from_packet(
    const godo::rt::FreedPacket& p) noexcept {
    const std::byte* const bytes = p.bytes.data();
    godo::rt::LastOutputFrame out{};

    out.x_m = static_cast<double>(
        decode_signed24_be(bytes + FreeD::OFF_X)) / FREED_POS_LSB_PER_M;
    out.y_m = static_cast<double>(
        decode_signed24_be(bytes + FreeD::OFF_Y)) / FREED_POS_LSB_PER_M;
    out.z_m = static_cast<double>(
        decode_signed24_be(bytes + FreeD::OFF_Z)) / FREED_POS_LSB_PER_M;
    out.pan_deg = static_cast<double>(
        decode_signed24_be(bytes + FreeD::OFF_PAN)) / FREED_PAN_LSB_PER_DEG;
    out.tilt_deg = static_cast<double>(
        decode_signed24_be(bytes + FreeD::OFF_TILT)) / FREED_PAN_LSB_PER_DEG;
    out.roll_deg = static_cast<double>(
        decode_signed24_be(bytes + FreeD::OFF_ROLL)) / FREED_PAN_LSB_PER_DEG;

    // Zoom + Focus pass-through: raw unsigned24 cast to double. The
    // FreeD D1 0x080000 offset is preserved on-wire; the SPA renders
    // the raw value so a future operator who needs FreeD's "lens
    // position" semantics can subtract 0x080000 client-side without a
    // wire shape change.
    auto decode_u24 = [](const std::byte* b) noexcept -> std::uint32_t {
        return (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[0])) << 16) |
               (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[1])) <<  8) |
                static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[2]));
    };
    out.zoom  = static_cast<double>(decode_u24(bytes + FreeD::OFF_ZOOM));
    out.focus = static_cast<double>(decode_u24(bytes + FreeD::OFF_FOCUS));

    return out;
}

}  // namespace godo::udp
