#pragma once

// Cold-path deadband filter (SYSTEM_DESIGN.md §6.4.1).
//
// AMCL produces sub-cm jitter even when the true pose is static. If every
// AMCL call wrote `target_offset`, the smoother would restart its ramp on
// every scan and `live` would hover a fraction of the way to a target that
// moved before the ramp could finish. The deadband filter sits at the cold
// writer's publish seam: it compares the freshly produced Offset against
// `last_written` (the last value the cold writer actually published) and
// suppresses the seqlock store when all three components are within their
// per-axis thresholds.
//
// Per-axis check (matches the spec — NOT Euclidean):
//   |new.dx  - last_written.dx|         < DEADBAND_MM (in metres)  AND
//   |new.dy  - last_written.dy|         < DEADBAND_MM (in metres)  AND
//   |shortest_arc(new.dyaw, last.dyaw)| < DEADBAND_DEG
//
// Units note: `Config::deadband_mm` is millimetres on the wire/TOML side,
// but `Offset::dx/dy` is metres. Callers convert: `deadband_xy_m =
// cfg.deadband_mm / 1000.0`.
//
// Boundary: strict `<` per the §6.4.1 spec — equality at the deadband is
// supra (publish). This keeps `last_written` from ever being further than
// DEADBAND from the true pose just because we saw a sequence of exactly-on-
// the-line samples.
//
// Forced bypass is the caller's responsibility (`if (forced ||
// !within_deadband(...))` at the seam). A pure predicate keeps this header
// trivially testable and free of seqlock / Config coupling.

#include <cmath>

#include "core/rt_types.hpp"
#include "core/seqlock.hpp"

namespace godo::localization {

// Shortest signed arc (degrees) from `from` to `to` on the unit circle:
// returns a value in (-180, +180]. Mirrors the helper in amcl_result.cpp
// (which lives in an anonymous namespace there); kept inline here to avoid
// pulling that translation unit into deadband-only test targets.
inline double deadband_shortest_arc_deg(double from, double to) noexcept {
    constexpr double k360 = 360.0;
    double d = std::fmod(to - from, k360);
    if (d >  180.0) d -= k360;
    if (d <= -180.0) d += k360;
    return d;
}

// Returns true iff every component of `b - a` is strictly inside its
// per-axis threshold (i.e. the update is noise that should be suppressed).
//
// `deadband_xy_m` is metres (caller already divided millimetres by 1000).
// `deadband_deg`  is degrees, applied to the shortest signed arc.
inline bool within_deadband(const godo::rt::Offset& a,
                            const godo::rt::Offset& b,
                            double deadband_xy_m,
                            double deadband_deg) noexcept {
    const double dxy_x = std::fabs(b.dx - a.dx);
    const double dxy_y = std::fabs(b.dy - a.dy);
    const double dyaw  = std::fabs(deadband_shortest_arc_deg(a.dyaw, b.dyaw));
    return dxy_x < deadband_xy_m
        && dxy_y < deadband_xy_m
        && dyaw  < deadband_deg;
}

// Publish-seam helper. Mirrors the §6.4.1 spec exactly:
//   if (forced || !within_deadband(new, last_written)) {
//       target_offset.store(new);
//       last_written = new;
//   }
// Returns true iff the seqlock was written (i.e. the generation advanced).
// Exposed so tests can exercise the seam without spinning up the AMCL
// pipeline; the cold writer composes this from its own seam (SSOT-DRY).
inline bool apply_deadband_publish(
    const godo::rt::Offset&            new_offset,
    bool                               forced,
    double                             deadband_xy_m,
    double                             deadband_deg,
    godo::rt::Offset&                  last_written_inout,
    godo::rt::Seqlock<godo::rt::Offset>& target_offset) noexcept {
    if (forced ||
        !within_deadband(new_offset, last_written_inout,
                         deadband_xy_m, deadband_deg)) {
        target_offset.store(new_offset);
        last_written_inout = new_offset;
        return true;
    }
    return false;
}

}  // namespace godo::localization
