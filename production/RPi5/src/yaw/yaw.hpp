#pragma once

// Yaw-wrap primitives, both pure free functions. See SYSTEM_DESIGN.md §6.5.
//
// Site 1: lerp_angle     — smoother interpolation, float degrees [0, 360).
// Site 2: wrap_signed24  — FreeD pan re-encode, signed 24-bit lsb.

#include <cstdint>

namespace godo::yaw {

// Shortest-arc linear interpolation of two angles in degrees.
// Precondition: |b - a| < 360 on the raw float difference. AMCL does not
// produce multi-turn deltas, so this precondition is met by construction.
// Returns a value in [0, 360).
double lerp_angle(double a, double b, double frac) noexcept;

// Fold a 64-bit signed integer into [-2^23, +2^23) modulo 2^24.
// Used at two sites — both are protocol-mandated ±2^23 lsb folds on
// 24-bit signed wire fields:
//   (a) FreeD D1 pan re-encode after a dyaw offset (1/32768 deg per lsb;
//       encoded range ±256°, NOT a mechanical crane limit).
//   (b) FreeD D1 X/Y re-encode after a dx/dy offset (1/64 mm per lsb;
//       encoded range ±131'072 mm ≈ ±131 m — well beyond any studio).
// The wrap at site (b) is the FreeD-spec behaviour at overflow, not a
// GODO-invented policy. Callers in `udp::apply_offset_inplace` exploit
// both uses. Keeping this helper domain-agnostic avoids duplicating the
// fold logic; see SYSTEM_DESIGN.md §6.5.
std::int32_t wrap_signed24(std::int64_t v) noexcept;

}  // namespace godo::yaw
