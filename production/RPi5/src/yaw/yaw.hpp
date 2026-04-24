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
// Used to re-encode FreeD D1 pan after we add a dyaw offset; the pan field
// is a signed 24-bit integer with 1/32768 degree per lsb (encoded range
// ±256°, NOT a mechanical crane limit).
std::int32_t wrap_signed24(std::int64_t v) noexcept;

}  // namespace godo::yaw
