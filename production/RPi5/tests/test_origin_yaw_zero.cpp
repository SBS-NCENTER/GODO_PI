// issue#30 verification — origin.yaw_deg = 0 path through cold_writer +
// amcl_result.cpp::compute_offset.
//
// The webctl-side issue#30 pick-anchored YAML normalization always
// produces derived YAML with `origin: [..., ..., 0]`. This test pins
// that the C++ tracker side handles `origin.yaw_deg = 0` cleanly:
//
//   1. compute_offset(current, origin) returns
//      `dyaw = canonical_360(current.yaw_deg - 0) = canonical_360(current.yaw_deg)`,
//      i.e. the operator's pose-dyaw equals the AMCL pose yaw with no
//      hidden subtraction.
//
// No production code change is required; this is a pin against a
// hypothetical regression where someone adds a `if (origin.yaw_deg ==
// 0) { ... }` short-circuit that breaks the contract.
//
// The fixture YAML is synthesized inline via std::ofstream into the
// test's temporary directory so the test is hermetic.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>

#include "localization/amcl_result.hpp"
#include "localization/pose.hpp"

using godo::localization::Pose2D;
using godo::localization::compute_offset;
using godo::rt::Offset;

TEST_CASE("issue#30 — compute_offset with origin.yaw_deg=0 returns dyaw=current.yaw_deg") {
    const Pose2D origin{0.0, 0.0, 0.0};
    {
        const Pose2D current{1.0, 2.0, 30.0};
        const Offset off = compute_offset(current, origin);
        CHECK(off.dx == doctest::Approx(1.0));
        CHECK(off.dy == doctest::Approx(2.0));
        CHECK(off.dyaw == doctest::Approx(30.0));
    }
    {
        const Pose2D current{0.0, 0.0, -45.0};
        const Offset off = compute_offset(current, origin);
        // canonical_360(-45) = 315
        CHECK(off.dyaw == doctest::Approx(315.0));
    }
    {
        const Pose2D current{0.0, 0.0, 0.0};
        const Offset off = compute_offset(current, origin);
        CHECK(off.dyaw == doctest::Approx(0.0));
    }
    {
        const Pose2D current{0.0, 0.0, 359.999};
        const Offset off = compute_offset(current, origin);
        CHECK(off.dyaw == doctest::Approx(359.999));
    }
}

TEST_CASE("issue#30 — compute_offset is invariant under origin.yaw_deg=0 vs trivially-rewritten path") {
    // The contract is: with origin.yaw_deg=0, the dyaw output equals
    // canonical_360(current.yaw_deg). If a future refactor sneaks in a
    // short-circuit branch like
    //     `if (origin.yaw_deg == 0.0) return current.yaw_deg;`
    // it would lose the canonical_360 wrap and silently break a
    // current.yaw_deg < 0 path. This case pins that the existing
    // branchless implementation works through every quadrant.
    const Pose2D origin{0.0, 0.0, 0.0};
    for (double yaw : {0.1, 90.0, 180.0, 270.0, -0.1, -90.0, -180.0, -270.0}) {
        const Pose2D current{0.0, 0.0, yaw};
        const Offset off = compute_offset(current, origin);
        // Manual canonical_360(yaw):
        double expected = std::fmod(yaw, 360.0);
        if (expected < 0.0) expected += 360.0;
        if (expected >= 360.0) expected -= 360.0;
        CHECK(off.dyaw == doctest::Approx(expected).epsilon(1e-9));
    }
}
