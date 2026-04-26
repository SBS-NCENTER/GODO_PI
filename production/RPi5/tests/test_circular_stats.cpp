// Phase 4-2 B Wave 2 — circular_mean_yaw_deg / circular_std_yaw_deg.
//
// Pinned semantics (M5): a yaw cluster that straddles the 0/360 seam must
// report a small std (≈ cluster spread), NOT ~180° as a naive linear std
// would. Mean must land near the *centre* of the cluster, also taken on
// the shortest arc.
//
// All tests use the [0, 360) canonical-degree convention exposed by
// `pose.{hpp,cpp}`.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <vector>

#include "localization/pose.hpp"

using namespace godo::localization;

namespace {

// Shortest-arc absolute distance between two canonical-360 angles, in
// degrees. Used to compare circular means without worrying about the seam.
double circular_dist_deg(double a, double b) {
    double d = std::fmod(a - b, 360.0);
    if (d > 180.0)  d -= 360.0;
    if (d <= -180.0) d += 360.0;
    return std::fabs(d);
}

Particle p(double yaw_deg, double weight) {
    return Particle{Pose2D{0.0, 0.0, yaw_deg}, weight};
}

}  // namespace

TEST_CASE("circular_stats — cluster across 0/360 boundary reports tight std") {
    // 4 particles at [359.0, 359.5, 0.0, 0.5] deg, equal weights.
    // Naive linear mean = (359.0 + 359.5 + 0.0 + 0.5) / 4 = 179.75 (WRONG).
    // Circular mean must be the centre of the arc — 359.75° (≡ -0.25°).
    // Std must reflect the actual cluster spread (~0.6°), not 180°.
    std::vector<Particle> ps = {
        p(359.0, 0.25),
        p(359.5, 0.25),
        p(0.0,   0.25),
        p(0.5,   0.25),
    };
    const double mean = circular_mean_yaw_deg(ps.data(), ps.size());
    const double std_ = circular_std_yaw_deg(ps.data(), ps.size());

    // Mean is in [0, 360).
    CHECK(mean >= 0.0);
    CHECK(mean <  360.0);
    // The cluster centre is 359.75° (or equivalently, the shortest-arc
    // distance from 359.75° to mean must be < 1°).
    CHECK(circular_dist_deg(mean, 359.75) < 1.0);
    // Tight cluster: std must be small (< 1.0°), and definitely NOT
    // ~180° as a naive linear std would yield.
    CHECK(std_ < 1.0);
    CHECK(std_ > 0.3);   // sanity: actually some spread, ~0.6°
    CHECK(std_ < 90.0);  // hard upper bound that excludes the broken case
}

TEST_CASE("circular_stats — half-arc cluster has wide but finite std") {
    // 6 equal-weight particles at 0, 30, 60, 90, 120, 150 deg.
    // Σsin = 0 + 0.5 + 0.866 + 1.0 + 0.866 + 0.5 = 3.732
    // Σcos = 1 + 0.866 + 0.5 + 0 - 0.5 - 0.866 = 1.000
    // atan2(3.732, 1.000) = 75° (NOT 90° — the tail past 90° pulls the
    // resultant back toward the dense end of the half-arc).
    std::vector<Particle> ps;
    for (int k = 0; k < 6; ++k) {
        ps.push_back(p(static_cast<double>(k) * 30.0, 1.0 / 6.0));
    }
    const double mean = circular_mean_yaw_deg(ps.data(), ps.size());
    const double std_ = circular_std_yaw_deg(ps.data(), ps.size());

    CHECK(circular_dist_deg(mean, 75.0) < 2.0);
    // Wide spread — std must be large compared to a tight cluster.
    CHECK(std_ > 30.0);
    // Finite (not inf or NaN).
    CHECK(std::isfinite(std_));
}

TEST_CASE("circular_stats — degenerate single particle has std = 0 and mean = its yaw") {
    Particle one[] = { p(123.5, 1.0) };
    const double mean = circular_mean_yaw_deg(one, 1);
    const double std_ = circular_std_yaw_deg(one, 1);

    CHECK(circular_dist_deg(mean, 123.5) < 1e-9);
    // R == 1 exactly → std == 0 by construction.
    CHECK(std_ == doctest::Approx(0.0));
}

TEST_CASE("circular_stats — symmetric pair {30°, 330°} yields mean ≈ 0° and std ≈ 30°") {
    std::vector<Particle> ps = {
        p( 30.0, 0.5),
        p(330.0, 0.5),
    };
    const double mean = circular_mean_yaw_deg(ps.data(), ps.size());
    const double std_ = circular_std_yaw_deg(ps.data(), ps.size());

    // Symmetric around 0°/360°. atan2(0, +) → 0.0, so mean is 0.0 (NOT 180°).
    CHECK(circular_dist_deg(mean, 0.0) < 1.0);
    // For two points at ±30°, R = cos(30°) = ~0.866, so
    //   std_rad = sqrt(-2 ln 0.866) ≈ 0.5365, → ~30.7° in degrees.
    CHECK(std_ == doctest::Approx(30.7).epsilon(0.05));
}

TEST_CASE("circular_stats — weighted asymmetry pulls mean toward the heavy side") {
    // {0° w=0.9, 180° w=0.1}: mean closer to 0° than to 90°.
    // For two opposite points the angle of the resultant is the angle of the
    // point with the larger weight (0° here), as long as |w0 - w180| > 0.
    std::vector<Particle> ps = {
        p(  0.0, 0.9),
        p(180.0, 0.1),
    };
    const double mean = circular_mean_yaw_deg(ps.data(), ps.size());
    CHECK(circular_dist_deg(mean,   0.0) < 1.0);
    CHECK(circular_dist_deg(mean,  90.0) > 80.0);
    CHECK(circular_dist_deg(mean, 180.0) > 170.0);
}

TEST_CASE("circular_stats — n == 0 returns 0 / 0 (defensive)") {
    Particle dummy{};
    CHECK(circular_mean_yaw_deg(&dummy, 0) == doctest::Approx(0.0));
    CHECK(circular_std_yaw_deg(&dummy, 0)  == doctest::Approx(0.0));
}

TEST_CASE("circular_stats — Σw == 0 returns 0 / 0 (defensive)") {
    std::vector<Particle> ps = {
        p( 10.0, 0.0),
        p( 20.0, 0.0),
    };
    CHECK(circular_mean_yaw_deg(ps.data(), ps.size()) == doctest::Approx(0.0));
    CHECK(circular_std_yaw_deg(ps.data(), ps.size())  == doctest::Approx(0.0));
}
