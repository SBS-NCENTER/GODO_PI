#include "amcl_result.hpp"

#include <cmath>

namespace godo::localization {

namespace {

constexpr double k360 = 360.0;

// Canonicalize a degree value into [0, 360). std::fmod can return a negative
// result for negative inputs, so the +k360 + fmod step is required.
double canonical_360(double deg) noexcept {
    double r = std::fmod(deg, k360);
    if (r < 0.0) r += k360;
    // Guard the boundary: fmod(360.0, 360.0) is 0 already, but a negative
    // input with magnitude < 360 plus the +360 above can land exactly on 360
    // when r == 0 but deg was a tiny negative; clip to keep [0, 360).
    if (r >= k360) r -= k360;
    return r;
}

// Shortest signed arc (degrees) from `from` to `to` on the unit circle:
// returns a value in (-180, 180].
double shortest_arc_deg(double from, double to) noexcept {
    double d = std::fmod(to - from, k360);
    if (d > 180.0)  d -= k360;
    if (d <= -180.0) d += k360;
    return d;
}

}  // namespace

godo::rt::Offset compute_offset(const Pose2D& current,
                                const Pose2D& origin) noexcept {
    godo::rt::Offset off{};
    off.dx   = current.x - origin.x;
    off.dy   = current.y - origin.y;
    off.dyaw = canonical_360(current.yaw_deg - origin.yaw_deg);
    return off;
}

bool apply_yaw_tripwire(const Pose2D& pose,
                        double        origin_yaw_deg,
                        double        tripwire_deg) noexcept {
    if (!(tripwire_deg > 0.0)) return false;  // disabled
    return std::fabs(shortest_arc_deg(origin_yaw_deg, pose.yaw_deg)) >
           tripwire_deg;
}

}  // namespace godo::localization
