#pragma once

// FreeD signed24 big-endian wire codec — namespace-internal helpers,
// SOLE owner of decode/encode for the 3-byte signed-24 fields used by
// X / Y / Z (positions, 1/64 mm per LSB) and Pan / Tilt / Roll (angles,
// 1/32768° per LSB).
//
// Issue#27 — extracted from `udp/sender.cpp`'s file-private `static`
// helpers so `udp/output_transform.cpp` can reuse them without
// duplication. SSOT for the encode/decode math; sender.cpp consumes via
// this header.
//
// Inline so the call sites stay branch-free at -O2 (the existing hot
// path in `apply_offset_inplace` runs ~50 ns; `apply_output_transform_
// inplace` adds ~150 ns on top — see `tests/test_output_transform.cpp`
// micro-bench).
//
// Build-grep deferral: a future PR that introduces a SECOND consumer
// outside udp/ should re-evaluate `[wire-codec-grep]` enforcement; the
// surface today (sender.cpp + output_transform.cpp) doesn't justify it.

#include <cstdint>
#include <cstddef>

namespace godo::udp::wire {

// Decode a 24-bit big-endian signed integer from `b[0..3)`. Sign-extended
// from bit 23.
inline std::int32_t decode_signed24_be(const std::byte* b) noexcept {
    const std::uint32_t u =
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[0])) << 16) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[1])) <<  8) |
         static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(b[2]));
    const std::uint32_t sign = (u & 0x00800000U) ? 0xFF000000U : 0U;
    return static_cast<std::int32_t>(u | sign);
}

inline void encode_signed24_be(std::byte* b, std::int32_t v) noexcept {
    const std::uint32_t u = static_cast<std::uint32_t>(v) & 0x00FFFFFFU;
    b[0] = static_cast<std::byte>((u >> 16) & 0xFFU);
    b[1] = static_cast<std::byte>((u >>  8) & 0xFFU);
    b[2] = static_cast<std::byte>((u      ) & 0xFFU);
}

}  // namespace godo::udp::wire
