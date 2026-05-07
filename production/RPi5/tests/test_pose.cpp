// Phase 4-2 B Wave 2 — compute_offset pose helper.
//
// Pinned semantics (M3): `Offset::dyaw = canonical_360(current.yaw - origin.yaw)`
// — the result is always in [0, 360). This matches udp::apply_offset_inplace's
// "add to signed-24 pan and wrap_signed24" path, so a 350° → 10° transition
// publishes dyaw = 20° (NOT -340°).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>

#include "core/rt_types.hpp"
#include "localization/amcl_result.hpp"
#include "localization/pose.hpp"

using godo::localization::Pose2D;
using godo::localization::compute_offset;

TEST_CASE("compute_offset — direction signs of dx / dy / dyaw match (current - origin)") {
    Pose2D current{1.0, 2.0, 10.0};
    Pose2D origin {0.5, 1.0,  5.0};
    const auto off = compute_offset(current, origin);

    CHECK(off.dx   == doctest::Approx(0.5));
    CHECK(off.dy   == doctest::Approx(1.0));
    CHECK(off.dyaw == doctest::Approx(5.0));
}

TEST_CASE("compute_offset — dyaw wraps 350° → 10° to 20°, not to -340°") {
    // 10° - 350° = -340°; canonical-360 normalisation → 20°.
    Pose2D current{0.0, 0.0,  10.0};
    Pose2D origin {0.0, 0.0, 350.0};
    const auto off = compute_offset(current, origin);

    CHECK(off.dyaw >= 0.0);
    CHECK(off.dyaw <  360.0);
    CHECK(off.dyaw == doctest::Approx(20.0));
}

TEST_CASE("compute_offset — negative dx / dy when current is left of / below origin") {
    Pose2D current{0.0, 0.0,  0.0};
    Pose2D origin {1.0, 2.0,  0.0};
    const auto off = compute_offset(current, origin);

    CHECK(off.dx < 0.0);
    CHECK(off.dy < 0.0);
    CHECK(off.dx == doctest::Approx(-1.0));
    CHECK(off.dy == doctest::Approx(-2.0));
    CHECK(off.dyaw == doctest::Approx(0.0));
}

TEST_CASE("compute_offset — yaw equality at 0° produces dyaw == 0, not 360") {
    Pose2D current{0.0, 0.0, 0.0};
    Pose2D origin {0.0, 0.0, 0.0};
    const auto off = compute_offset(current, origin);

    CHECK(off.dyaw == doctest::Approx(0.0));
    // Strict "< 360": pin the M3 canonical-360 convention.
    CHECK(off.dyaw <  360.0);
}

TEST_CASE("compute_offset — dyaw stays in [0, 360) for assorted inputs") {
    struct Case { double cur; double org; double expected; };
    Case cases[] = {
        {  0.0,    0.0,    0.0},
        {359.0,    0.0,  359.0},
        {  0.0,    1.0,  359.0},
        {180.0,  180.0,    0.0},
        {359.999, 0.001, 359.998},
        {  0.001, 359.999, 0.002},
    };
    for (auto& c : cases) {
        Pose2D current{0.0, 0.0, c.cur};
        Pose2D origin {0.0, 0.0, c.org};
        const auto off = compute_offset(current, origin);
        CAPTURE(c.cur);
        CAPTURE(c.org);
        CHECK(off.dyaw >= 0.0);
        CHECK(off.dyaw <  360.0);
        CHECK(off.dyaw == doctest::Approx(c.expected).epsilon(1e-6));
    }
}

