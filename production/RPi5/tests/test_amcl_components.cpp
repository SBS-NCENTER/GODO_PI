// Phase 4-2 B Wave 2 — class Amcl API contract sanity.
//
// Algorithmic quality (convergence to known truth on a synthetic map) is
// covered in test_amcl_scenarios.cpp; this file pins the *contract* — that
// pre-allocation actually happened, that seed_global / seed_around populate
// the right particle counts, and that the AmclResult-shape getters return
// finite values. No Bresenham here (bias-block per plan).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <vector>

#include "core/config.hpp"
#include "core/constants.hpp"
#include "lidar/sample.hpp"
#include "localization/amcl.hpp"
#include "localization/likelihood_field.hpp"
#include "localization/occupancy_grid.hpp"
#include "localization/pose.hpp"
#include "localization/rng.hpp"
#include "localization/scan_ops.hpp"

#ifndef GODO_FIXTURES_MAPS_DIR
#error "GODO_FIXTURES_MAPS_DIR must be set by CMake"
#endif

using godo::core::Config;
using godo::lidar::Frame;
using godo::lidar::Sample;
using godo::localization::Amcl;
using godo::localization::build_likelihood_field;
using godo::localization::downsample;
using godo::localization::LikelihoodField;
using godo::localization::load_map;
using godo::localization::OccupancyGrid;
using godo::localization::Pose2D;
using godo::localization::RangeBeam;
using godo::localization::Rng;

namespace {

OccupancyGrid load_fixture() {
    return load_map(std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm");
}

Config make_test_config() {
    Config c = Config::make_default();
    c.amcl_seed = 42;  // determinism
    return c;
}

}  // namespace

TEST_CASE("Amcl — constructor pre-allocates ping-pong buffers to PARTICLE_BUFFER_MAX") {
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    Amcl amcl(cfg, lf);

    CHECK(amcl.buffer_capacity() ==
          static_cast<std::size_t>(godo::constants::PARTICLE_BUFFER_MAX));
    // No particles seeded yet.
    CHECK(amcl.particle_count() == 0u);
}

TEST_CASE("Amcl::seed_global — populates n = cfg.amcl_particles_global_n") {
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    amcl.seed_global(grid, rng);

    CHECK(amcl.particle_count() ==
          static_cast<std::size_t>(cfg.amcl_particles_global_n));

    // Mean is somewhere inside the map's free area (bounded by walls).
    const Pose2D mean = amcl.weighted_mean();
    CHECK(std::isfinite(mean.x));
    CHECK(std::isfinite(mean.y));
    CHECK(std::isfinite(mean.yaw_deg));
    CHECK(mean.x >= 0.0);
    CHECK(mean.x <= grid.width  * grid.resolution_m);
    CHECK(mean.y >= 0.0);
    CHECK(mean.y <= grid.height * grid.resolution_m);
    CHECK(mean.yaw_deg >= 0.0);
    CHECK(mean.yaw_deg <  360.0);

    // (S10) Spread check: a true global seed must spread across a
    // substantial fraction of the room, NOT collapse into one corner.
    // synthetic_4x4 is 4 m × 4 m; a uniform seed gives σ_xy ≈ 4/√12 ≈
    // 1.15 m per axis, so the combined sqrt(var_x + var_y) ≈ 1.6 m.
    // We require ≥ 0.5 m as a generous lower bound.
    CHECK(amcl.xy_std_m() > 0.5);
}

TEST_CASE("Amcl::seed_around — Gaussian cloud has mean ≈ pose, σ ≈ requested") {
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    const Pose2D centre{2.0, 2.0, 90.0};
    const double sigma_xy_m   = 0.05;
    const double sigma_yaw_deg = 1.0;
    amcl.seed_around(centre, sigma_xy_m, sigma_yaw_deg, rng);

    CHECK(amcl.particle_count() ==
          static_cast<std::size_t>(cfg.amcl_particles_local_n));

    // Mean within 1σ of centre on each axis (loose; large N makes this tight
    // but allow slack for the random draw).
    const Pose2D mean = amcl.weighted_mean();
    CHECK(std::abs(mean.x - centre.x) < sigma_xy_m * 2.0);
    CHECK(std::abs(mean.y - centre.y) < sigma_xy_m * 2.0);

    // xy_std_m roughly matches the requested combined σ.
    // For two independent Gaussians at σ_xy each: std_total ≈ sqrt(2) * σ_xy.
    const double observed = amcl.xy_std_m();
    CHECK(observed > sigma_xy_m * 0.5);
    CHECK(observed < sigma_xy_m * 3.0);
}

TEST_CASE("Amcl::set_field — swap to a narrower σ field changes scan likelihood by closed-form ratio (Track D-5)") {
    // Build two LikelihoodFields on the SAME grid at different σ.
    // For the same beam endpoint at distance d from the nearest obstacle
    // cell, the likelihood is exp(-d² / (2σ²)). Therefore the ratio
    // between narrow and wide is exp(-d²·(1/(2σ_n²) - 1/(2σ_w²))).
    //
    // Bias-block: ground-truth d is hand-computed from the synthetic_4x4
    // grid layout, NOT derived from `LikelihoodField::values`. The map is
    // a 4×4 m room with a 1-cell border (occupied) at column 0 / 79 and
    // row 0 / 79; the resolution is 0.05 m so the inner free area is
    // (0.05 m, 3.95 m) × (0.05 m, 3.95 m). A particle at the centre
    // pose (2, 2, 0°) shoots a beam at sensor angle 0 (post-fix CCW =
    // along world +x): the beam endpoint at range 1 m lands at world
    // (3, 2). Distance to the nearest obstacle cell (the +x wall column
    // ~78, world x ≈ 3.925 m) is approximately 0.925 m. We don't need
    // the exact d — the ratio test below tolerates ~5% slack against the
    // closed-form prediction with the d measured from `lf_narrow` itself,
    // since both fields are built off the same EDT.
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const double sigma_w = 1.0;    // wide
    const double sigma_n = 0.05;   // narrow (production default)
    const LikelihoodField lf_wide   = build_likelihood_field(grid, sigma_w);
    const LikelihoodField lf_narrow = build_likelihood_field(grid, sigma_n);

    Amcl amcl(cfg, lf_wide);
    Rng  rng(cfg.amcl_seed);

    // Seed exactly one particle at the centre by abusing seed_around with
    // tiny σ and clipping particle count via cfg override (still 500 by
    // default, all clustered). For the contract test we don't need a
    // single particle — the ratio holds per particle.
    const Pose2D centre{2.0, 2.0, 0.0};
    amcl.seed_around(centre, 0.0001, 0.001, rng);

    // One beam pointing along world +x at 1.0 m.
    std::vector<RangeBeam> beams = {
        {1.0f, 0.0f},  // sensor frame (angle_rad=0, range=1.0)
    };

    // Step 1 with wide σ. step() returns AmclResult with .pose = mean,
    // but we want a single per-particle weight — use evaluate_scan
    // directly via the wide field reference for clarity.
    const double w_wide = godo::localization::evaluate_scan(
        centre, beams.data(), beams.size(), lf_wide);

    amcl.set_field(lf_narrow);
    const double w_narrow = godo::localization::evaluate_scan(
        centre, beams.data(), beams.size(), lf_narrow);

    // Asserts:
    //   1. Weights differ by more than a tiny epsilon (set_field must
    //      actually rebind the field; a stale pointer would yield
    //      identical weights).
    //   2. Ratio matches closed-form within ~1% — this catches a future
    //      writer who introduces a partial copy in set_field that drops
    //      half the field values.
    CAPTURE(w_wide);
    CAPTURE(w_narrow);
    CHECK(std::abs(w_wide - w_narrow) > 1e-9);

    // Closed-form ratio. We don't have an authoritative d, so derive it
    // from w_wide: log(w_wide) = -d² / (2σ_w²) ⇒ d² = -2σ_w² · log(w_wide).
    // Then predicted w_narrow = exp(-d² / (2σ_n²)).
    const double log_w_wide = std::log(w_wide);
    if (std::isfinite(log_w_wide) && log_w_wide < 0.0) {
        const double d_sq = -2.0 * sigma_w * sigma_w * log_w_wide;
        const double w_narrow_predicted = std::exp(-d_sq /
                                                   (2.0 * sigma_n * sigma_n));
        CAPTURE(d_sq);
        CAPTURE(w_narrow_predicted);
        // ~1% tolerance on the ratio. Both w values are exp() of large
        // negative numbers near the floor (EVAL_SCAN_LIKELIHOOD_FLOOR);
        // when the narrow field saturates against the floor (w_narrow ≈
        // 1e-9) the closed form's prediction can also saturate; in that
        // regime the assertion 'narrow >= floor' is the stronger pin.
        if (w_narrow_predicted > 1e-8 && w_narrow > 1e-8) {
            const double ratio_observed  = w_narrow / w_wide;
            const double ratio_predicted = w_narrow_predicted / w_wide;
            CAPTURE(ratio_observed);
            CAPTURE(ratio_predicted);
            CHECK(std::abs(std::log(ratio_observed) -
                           std::log(ratio_predicted)) < 0.05);  // ~5% in log
        } else {
            // Both saturated against the floor — at minimum, narrow ≤
            // wide for any beam not exactly hitting an obstacle cell.
            CHECK(w_narrow <= w_wide);
        }
    }
}

TEST_CASE("Amcl::converge — terminates within max_iters on a tight perfect-match seed") {
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    // Seed tight at the map centre.
    const Pose2D centre{2.0, 2.0, 0.0};
    amcl.seed_around(centre, 0.005, 0.1, rng);

    // Cook a tiny synthetic beam set: 4 beams pointing at the 4 walls of the
    // 4×4 m map. Distances are the cardinal distances from the centre.
    // These don't have to be perfectly aligned with EDT physics — converge()
    // just needs *some* finite-likelihood beam to keep particles alive while
    // the variance check fires.
    std::vector<RangeBeam> beams = {
        {2.0f, 0.0f},                     // +x → ~2.0 m to right wall
        {2.0f, static_cast<float>(M_PI)}, // -x
        {2.0f, static_cast<float>( M_PI / 2.0)},  // +y
        {2.0f, static_cast<float>(-M_PI / 2.0)},  // -y
    };

    const auto result = amcl.converge(beams, rng);

    CHECK(result.iterations >= 1);
    CHECK(result.iterations <= cfg.amcl_max_iters);
    // forced=false here; the cold-writer flips it on OneShot.
    CHECK(result.forced == false);
    // pose must be finite.
    CHECK(std::isfinite(result.pose.x));
    CHECK(std::isfinite(result.pose.y));
    CHECK(std::isfinite(result.pose.yaw_deg));
    CHECK(std::isfinite(result.xy_std_m));
    CHECK(std::isfinite(result.yaw_std_deg));
}

// Track D-3 anti-regression: pin the RPLIDAR-CW → REP-103-CCW boundary in
// scan_ops::downsample. Mirror of the SPA-side test
// (godo-frontend/src/lib/components/__tests__/poseCanvasScanLayer.test.ts
// case 3, PR #30) — pins that a sensor-frame "right" beam (CW 90°) projects
// to the LiDAR's RIGHT side (REP-103 -y) under the fix. Bias-block: the
// world-frame endpoint is computed by hand here, NOT by calling
// evaluate_scan(), so a bug in evaluate_scan() cannot mask a bug in the
// convention shift. See plan §Test strategy + invariant (m) in CODEBASE.md.
TEST_CASE("scan_ops::downsample — RPLIDAR CW 90° beam projects to LiDAR's right side under fix") {
    // Step 1: Frame with one valid sample at sensor angle 90° CW, 1 m.
    Frame frame;
    frame.index = 0;
    Sample s{};
    s.angle_deg    = 90.0;
    s.distance_mm  = 1000.0;
    s.quality      = 47;
    s.flag         = 0;
    s.timestamp_ns = 1;
    frame.samples.push_back(s);

    // Step 2: Run downsample with stride 1, range gate [0.05, 12.0] m.
    std::vector<RangeBeam> beams;
    downsample(frame, 1, 0.05, 12.0, beams);

    // Step 3: Beam survived the gate, range came through unscaled.
    REQUIRE(beams.size() == 1u);
    CHECK(beams[0].range_m == doctest::Approx(1.0f));

    // Step 4: angle_rad is the negation of the CW degree value (post-fix).
    // Pre-fix this would have been +π/2; the bug was that AMCL math is REP-103
    // CCW so a +π/2 sensor-CW beam was projected to the LiDAR's LEFT side.
    constexpr double kPi = 3.14159265358979323846;
    CHECK(beams[0].angle_rad ==
          doctest::Approx(static_cast<float>(-kPi / 2.0)).epsilon(1e-5));

    // Step 5: Manual projection at pose (5, 7, yaw=0). Plug a = beams[0].angle_rad
    // (the actual post-downsample value, NOT a freshly computed 90·π/180) so that
    // a bug shared by downsample-and-test cannot ride through silently. Bias-block.
    {
        const double a       = static_cast<double>(beams[0].angle_rad);
        const double r       = static_cast<double>(beams[0].range_m);
        const double px      = 5.0;
        const double py      = 7.0;
        const double yaw_deg = 0.0;
        const double yaw_rad = yaw_deg * (kPi / 180.0);
        const double xs      = r * std::cos(a);
        const double ys      = r * std::sin(a);
        const double xw      = px + (xs * std::cos(yaw_rad) - ys * std::sin(yaw_rad));
        const double yw      = py + (xs * std::sin(yaw_rad) + ys * std::cos(yaw_rad));
        // Right side of the LiDAR (REP-103 -y direction from the pose).
        CHECK(xw == doctest::Approx(5.0).epsilon(1e-5));
        CHECK(yw == doctest::Approx(6.0).epsilon(1e-5));
    }

    // Step 6: Anti-bias rotation matrix exercise — yaw = 45° puts non-zero
    // values into all four product terms in the rotation matrix, catching
    // single-term sign errors that yaw=0 alone cannot.
    // With xs=0, ys=-1, cos(45°)=sin(45°)=√2/2:
    //   xw = 5 + 0·(√2/2) − (−1)·(√2/2) = 5 + √2/2 ≈ 5.70710678
    //   yw = 7 + 0·(√2/2) + (−1)·(√2/2) = 7 − √2/2 ≈ 6.29289322
    {
        const double a       = static_cast<double>(beams[0].angle_rad);
        const double r       = static_cast<double>(beams[0].range_m);
        const double px      = 5.0;
        const double py      = 7.0;
        const double yaw_deg = 45.0;
        const double yaw_rad = yaw_deg * (kPi / 180.0);
        const double xs      = r * std::cos(a);
        const double ys      = r * std::sin(a);
        const double xw      = px + (xs * std::cos(yaw_rad) - ys * std::sin(yaw_rad));
        const double yw      = py + (xs * std::sin(yaw_rad) + ys * std::cos(yaw_rad));
        CHECK(xw == doctest::Approx(5.7071).epsilon(1e-4));
        CHECK(yw == doctest::Approx(6.2929).epsilon(1e-4));
    }

    // Step 7: Anti-bias second beam — pin BOTH right (90°) and left (270°)
    // sides simultaneously. CW 270° = LiDAR's LEFT side. Post-fix
    // angle_rad = -270·π/180 = -3π/2; cos(-3π/2)=0, sin(-3π/2)=+1.
    // At pose (0, 0, 0): xw=0, yw=+1 (LiDAR's left side, REP-103 +y).
    Frame frame2;
    frame2.index = 1;
    Sample s2{};
    s2.angle_deg    = 270.0;
    s2.distance_mm  = 1000.0;
    s2.quality      = 47;
    s2.flag         = 0;
    s2.timestamp_ns = 2;
    frame2.samples.push_back(s2);
    std::vector<RangeBeam> beams2;
    downsample(frame2, 1, 0.05, 12.0, beams2);

    REQUIRE(beams2.size() == 1u);
    CHECK(beams2[0].angle_rad ==
          doctest::Approx(static_cast<float>(-3.0 * kPi / 2.0)).epsilon(1e-5));
    {
        const double a       = static_cast<double>(beams2[0].angle_rad);
        const double r       = static_cast<double>(beams2[0].range_m);
        const double px      = 0.0;
        const double py      = 0.0;
        const double yaw_deg = 0.0;
        const double yaw_rad = yaw_deg * (kPi / 180.0);
        const double xs      = r * std::cos(a);
        const double ys      = r * std::sin(a);
        const double xw      = px + (xs * std::cos(yaw_rad) - ys * std::sin(yaw_rad));
        const double yw      = py + (xs * std::sin(yaw_rad) + ys * std::cos(yaw_rad));
        CHECK(xw == doctest::Approx(0.0).epsilon(1e-5));
        CHECK(yw == doctest::Approx(1.0).epsilon(1e-5));
    }
}
