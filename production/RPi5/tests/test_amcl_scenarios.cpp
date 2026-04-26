// Phase 4-2 B Wave 2 — AMCL convergence scenarios.
//
// **Bias-block (plan §Test strategy)**: synthetic scans are produced by a
// Bresenham line ray-caster local to this test. AMCL's evaluation path is
// the EDT-based LikelihoodField. The two implementations share NO code, so
// a passing test cannot be the result of a copy-paste error between fixture
// and production.
//
// Scenarios:
//   A. Perfect match — ground truth at the centre of synthetic_4x4; tight
//      seed_around; converge within tolerance.
//   B. Small displacement — ground truth offset by 30 cm + 5°; loose seed;
//      converge within tolerance.
//   C. Bad initial guess (global) — DEFERRED.
//      The synthetic_4x4 fixture is a 4×4 m square room with a uniform
//      1-cell border. That geometry has 4-fold rotational symmetry (and
//      mirror symmetries through the principal axes). Global seeding
//      cannot disambiguate yaw by definition on such a fixture: any of
//      the 4 yaw modes produces an identical scan. A reliable Scenario C
//      requires an asymmetric fixture (e.g. an interior obstacle in one
//      corner). Tracked as a Wave 2 deviation in CODEBASE.md; either
//      Phase 4-2 D adds a richer fixture or Phase 5 validates against a
//      real studio map (where the chroma-set / two-doors geometry breaks
//      the symmetry naturally).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <cstddef>
#include <string>
#include <vector>

#include "core/config.hpp"
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
using godo::localization::Amcl;
using godo::localization::build_likelihood_field;
using godo::localization::LikelihoodField;
using godo::localization::load_map;
using godo::localization::OccupancyGrid;
using godo::localization::Pose2D;
using godo::localization::RangeBeam;
using godo::localization::Rng;

namespace {

// Bresenham line ray-cast: walk integer cells from `(cx, cy)` along
// direction angle (radians, sensor frame) until we hit an occupied cell or
// run off the grid. Returns the Euclidean distance to the hit (metres) or
// -1.0 if no hit was found within max_steps.
//
// Cell encoding: 255 = free, 0 = occupied (matches OccupancyGrid).
//
// This implementation is deliberately distinct from the EDT-based
// LikelihoodField (bias-block).
double bresenham_range_m(const OccupancyGrid& grid,
                         double               world_x,
                         double               world_y,
                         double               angle_rad_world) {
    const double res = grid.resolution_m;
    if (res <= 0.0) return -1.0;
    // Convert world → grid coords.
    const double cx0 = (world_x - grid.origin_x_m) / res;
    const double cy0 = (world_y - grid.origin_y_m) / res;

    const double step = 0.25;  // 1/4 cell step — fine enough for 5cm cells
    const double dx   = std::cos(angle_rad_world) * step;
    const double dy   = std::sin(angle_rad_world) * step;

    double cx = cx0;
    double cy = cy0;
    const int max_steps = 4 * (grid.width + grid.height);
    for (int s = 0; s < max_steps; ++s) {
        cx += dx;
        cy += dy;
        const int ix = static_cast<int>(std::floor(cx));
        const int iy = static_cast<int>(std::floor(cy));
        if (ix < 0 || ix >= grid.width || iy < 0 || iy >= grid.height) {
            return -1.0;
        }
        const std::size_t idx =
            static_cast<std::size_t>(iy) * static_cast<std::size_t>(grid.width)
            + static_cast<std::size_t>(ix);
        if (grid.cells[idx] < 128) {  // occupied
            const double mx = grid.origin_x_m + (cx + 0.5) * res;
            const double my = grid.origin_y_m + (cy + 0.5) * res;
            return std::hypot(mx - world_x, my - world_y);
        }
    }
    return -1.0;
}

// Synthesize a beam set at `pose` against `grid` using Bresenham. Beams are
// uniformly spaced over [0, 2π) at `n_beams` density. Yaw of the pose is
// added so that beam (i)'s sensor-frame angle is (2π·i/n) and its world-
// frame direction is (yaw_rad + 2π·i/n).
std::vector<RangeBeam> synth_beams(const OccupancyGrid& grid,
                                   const Pose2D&        pose,
                                   int                  n_beams) {
    std::vector<RangeBeam> beams;
    beams.reserve(n_beams);
    const double yaw_rad = pose.yaw_deg * (M_PI / 180.0);
    for (int i = 0; i < n_beams; ++i) {
        const double a_sensor = (2.0 * M_PI / n_beams) *
                                static_cast<double>(i);
        const double a_world  = yaw_rad + a_sensor;
        const double r = bresenham_range_m(grid, pose.x, pose.y, a_world);
        if (r > 0.0 && r < 100.0) {
            RangeBeam b;
            b.range_m   = static_cast<float>(r);
            b.angle_rad = static_cast<float>(a_sensor);
            beams.push_back(b);
        }
    }
    return beams;
}

OccupancyGrid load_fixture() {
    return load_map(std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm");
}

Config make_test_config() {
    Config c = Config::make_default();
    c.amcl_seed                 = 42;
    // Loosen tolerances slightly: the 80×80 fixture + ~180 beams gives a
    // discretization floor of ~half a cell = 2.5 cm; tightening below that
    // is asking for flakes. Tolerance of 5 cm and 1° below is well within
    // the 1–2 cm overall budget when paired with a real studio map.
    c.amcl_converge_xy_std_m     = 0.05;
    c.amcl_converge_yaw_std_deg  = 1.0;
    c.amcl_max_iters             = 30;
    c.amcl_particles_local_n     = 800;  // smaller than default for test speed
    c.amcl_particles_global_n    = 800;
    return c;
}

}  // namespace

TEST_CASE("AMCL Scenario A — perfect match converges within tolerance") {
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    // Ground truth: centre of the 4×4 m room.
    const Pose2D truth{2.0, 2.0, 0.0};
    amcl.seed_around(truth, 0.05, 0.5, rng);

    const auto beams = synth_beams(grid, truth, 180);
    REQUIRE(beams.size() > 60u);  // most beams should hit the 4 walls

    const auto result = amcl.converge(beams, rng);

    CHECK(result.iterations >= 1);
    CHECK(result.iterations <= cfg.amcl_max_iters);
    CHECK(std::isfinite(result.pose.x));
    CHECK(std::isfinite(result.pose.y));
    CHECK(std::isfinite(result.pose.yaw_deg));

    // Mean within the convergence-tolerance disk of truth.
    const double err_xy = std::hypot(result.pose.x - truth.x,
                                     result.pose.y - truth.y);
    CAPTURE(result.pose.x);
    CAPTURE(result.pose.y);
    CAPTURE(result.pose.yaw_deg);
    CAPTURE(result.iterations);
    CAPTURE(result.xy_std_m);
    CAPTURE(result.yaw_std_deg);
    CHECK(err_xy < 0.10);  // 10 cm of truth (loose; tight seed should give ≤ 5 cm)
}

TEST_CASE("AMCL Scenario B — small displacement converges with loose seed") {
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    const Pose2D truth{2.30, 2.05, 5.0};   // 30 cm displacement + 5° yaw
    const Pose2D guess{2.00, 2.00, 0.0};   // operator's last known pose

    amcl.seed_around(guess, 0.10, 5.0, rng);

    const auto beams = synth_beams(grid, truth, 180);
    REQUIRE(beams.size() > 60u);

    const auto result = amcl.converge(beams, rng);

    CHECK(result.iterations <= cfg.amcl_max_iters);
    const double err_xy = std::hypot(result.pose.x - truth.x,
                                     result.pose.y - truth.y);
    CAPTURE(result.pose.x);
    CAPTURE(result.pose.y);
    CAPTURE(result.pose.yaw_deg);
    CAPTURE(result.iterations);
    CAPTURE(result.xy_std_m);
    CAPTURE(result.yaw_std_deg);
    // Loose tolerance — Scenario B is harder than A. 15 cm catches "we
    // tracked the displacement at all" while excluding "we got stuck at the
    // initial guess".
    CHECK(err_xy < 0.15);
}

// Scenario C is intentionally NOT a TEST_CASE — see file-top comment for
// rationale. Documented in CODEBASE.md "2026-04-26 — Phase 4-2 B Wave 2"
// deviations. Phase 4-2 D revives it once the fixture has an asymmetric
// feature, OR Phase 5 validates global-seed convergence on the real studio
// map directly.
