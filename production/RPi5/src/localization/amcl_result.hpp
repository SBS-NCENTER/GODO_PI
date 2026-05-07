#pragma once

// AMCL convergence result + offset helpers.
//
// `AmclResult` is the public output of `class Amcl::converge` and `step`. The
// `forced` flag is true only when the cold writer triggered a OneShot run; a
// raw `step()`/`converge()` invocation always yields `forced=false`. Phase
// 4-2 C deadband filter consumes `forced` at the cold-writer publish seam to
// pass operator-driven calibrates through unconditionally.
//
// Convention pin (M3): `Offset::dyaw = canonical_360(current.yaw_deg -
// origin.yaw_deg)`. This matches `udp::apply_offset_inplace`'s "add to
// signed-24 pan and `wrap_signed24`" path. `dyaw` is always in [0, 360).

#include <cstddef>

#include "core/rt_types.hpp"
#include "pose.hpp"

namespace godo::localization {

struct AmclResult {
    Pose2D           pose;          // weighted-mean pose at convergence end
    godo::rt::Offset offset;        // pose - origin, canonical-360 yaw
    bool             forced;        // cold-writer OneShot triggered this run
    bool             converged;     // step()-loop early-exit fired
    int              iterations;    // total step() calls made
    double           xy_std_m;      // sqrt(weighted_var_x + weighted_var_y)
    double           yaw_std_deg;   // circular std (M5)
};

// Compute the canonical (dx, dy, dyaw) offset between a pose and the
// calibration origin. `dyaw = canonical_360(current.yaw_deg - origin.yaw_deg)`
// — wraps via `fmod(fmod(a, 360) + 360, 360)` so the result is always in
// [0, 360) and matches the wire-format expectations of
// `udp::apply_offset_inplace`.
godo::rt::Offset compute_offset(const Pose2D& current,
                                const Pose2D& origin) noexcept;

}  // namespace godo::localization
