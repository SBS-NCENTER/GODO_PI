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
//   D. Track D-5 — annealing recovers from global ambiguity. Programmatic
//      asymmetric grid (10×10 m room with an interior L-shaped obstacle)
//      breaks the rotational symmetry. Pin: single-σ converge() at σ=0.05
//      cannot recover from a uniform global seed cloud, but the annealing
//      path (cold_writer.cpp::converge_anneal) does. Sub-checks: (1)
//      single-σ baseline failure, (2) annealing happy path within tolerance
//      and 5 s wall-clock, (3) schedule length 1 runs single-phase
//      annealing.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
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

// ===========================================================================
// Scenario D — Track D-5 sigma annealing recovers from global ambiguity.
// ===========================================================================
//
// Programmatic asymmetric grid: 200×200 cells × 0.05 m = 10×10 m room
// with a single L-shaped interior obstacle (1 m × 2 m rectangle at world
// (3, 7)) that breaks rotational symmetry. We do NOT load this fixture
// from disk — it is built in-memory so the asymmetry property can be
// directly REQUIRE'd at the top of the test (Mode-A T1).
//
// Bias-block: the synthetic scans come from `synth_beams` (Bresenham)
// while AMCL runs through the EDT-derived likelihood field. Tolerances
// are external absolute thresholds. RNG seed is pinned so the test is
// reproducible; the seed was selected to reliably FAIL the single-σ
// baseline so the test pins a concrete failure pattern.

#include "localization/cold_writer.hpp"

#include <chrono>
#include <limits>

using godo::localization::converge_anneal;

namespace {

// Build a 200×200 grid (10×10 m at 0.05 m/cell) with multiple interior
// obstacles arranged asymmetrically + a missing chunk on the south wall
// to mimic a "doorway". Free cells = 255, occupied = 0. Origin at (0, 0).
//
// Asymmetry sources (so AMCL phase 0 can lock the pose, not just the
// basin set):
//   (a) L-shaped obstacle in the upper-right.
//   (b) 1×1 m square obstacle in the lower-left.
//   (c) 0.5 m doorway gap on the south wall (asymmetric column).
// Together these make the scene yaw-distinguishable AND xy-distinguishable
// from arbitrary global seeds.
OccupancyGrid build_scenario_d_grid() {
    OccupancyGrid grid;
    grid.width        = 200;
    grid.height       = 200;
    grid.resolution_m = 0.05;
    grid.origin_x_m   = 0.0;
    grid.origin_y_m   = 0.0;
    grid.cells.assign(static_cast<std::size_t>(grid.width) *
                      static_cast<std::size_t>(grid.height),
                      static_cast<std::uint8_t>(255));  // all free

    // 1-cell border (walls).
    for (int x = 0; x < grid.width; ++x) {
        grid.cells[static_cast<std::size_t>(x)] = 0;
        grid.cells[static_cast<std::size_t>(grid.height - 1) *
                   static_cast<std::size_t>(grid.width) +
                   static_cast<std::size_t>(x)] = 0;
    }
    for (int y = 0; y < grid.height; ++y) {
        grid.cells[static_cast<std::size_t>(y) *
                   static_cast<std::size_t>(grid.width)] = 0;
        grid.cells[static_cast<std::size_t>(y) *
                   static_cast<std::size_t>(grid.width) +
                   static_cast<std::size_t>(grid.width - 1)] = 0;
    }

    auto fill_rect = [&](int x0, int x1, int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            for (int x = x0; x < x1; ++x) {
                grid.cells[static_cast<std::size_t>(y) *
                           static_cast<std::size_t>(grid.width) +
                           static_cast<std::size_t>(x)] = 0;
            }
        }
    };
    auto open_rect = [&](int x0, int x1, int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            for (int x = x0; x < x1; ++x) {
                grid.cells[static_cast<std::size_t>(y) *
                           static_cast<std::size_t>(grid.width) +
                           static_cast<std::size_t>(x)] = 255;
            }
        }
    };

    // (a) Upper-right L-shape obstacle (1 m × 2 m vertical bar + 2 m × 0.5 m
    //     horizontal bar). Cells: x∈[140..160), y∈[120..160) +
    //     x∈[140..180), y∈[120..130).
    fill_rect(140, 160, 120, 160);
    fill_rect(140, 180, 120, 130);
    // (b) Lower-left 1×1 m obstacle: x∈[40..60), y∈[40..60).
    fill_rect(40, 60, 40, 60);
    // (c) Pillar at (6.5 m, 5 m) — adds a third feature.
    fill_rect(126, 134, 96, 104);
    // (d) South-wall doorway at x∈[80..90) (0.5 m wide).
    open_rect(80, 90, 0, 1);

    return grid;
}

Config make_scenario_d_config() {
    Config c = Config::make_default();
    c.amcl_seed                  = 42;
    c.amcl_converge_xy_std_m     = 0.05;
    c.amcl_converge_yaw_std_deg  = 1.0;
    c.amcl_max_iters             = 20;     // single-σ baseline budget
    c.amcl_particles_local_n     = 1000;
    c.amcl_particles_global_n    = 3000;   // enough to hit the truth basin
    c.amcl_sigma_seed_yaw_deg    = 10.0;
    return c;
}

// First-K ranges in beam-INDEX order (NOT sorted) — fixture-asymmetry
// signature (Mode-A T1). NB: sorting the ranges would mask yaw rotation
// because rotating the LiDAR yaw only permutes the beam index → range
// mapping; the multiset of ranges is yaw-invariant. Keeping beam order
// preserves the rotation phase so signatures at yaw 0/90/180/270° differ
// when the scene is asymmetric.
std::vector<double> scan_signature(const std::vector<RangeBeam>& beams,
                                   std::size_t k) {
    std::vector<double> ranges;
    ranges.reserve(beams.size());
    for (const auto& b : beams) {
        ranges.push_back(static_cast<double>(b.range_m));
    }
    if (ranges.size() > k) ranges.resize(k);
    return ranges;
}

bool signatures_differ(const std::vector<double>& a,
                       const std::vector<double>& b,
                       double tol = 0.01) {
    if (a.size() != b.size()) return true;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (std::abs(a[i] - b[i]) > tol) return true;
    }
    return false;
}

}  // namespace

TEST_CASE("AMCL Scenario D — annealing recovers from global ambiguity") {
    const OccupancyGrid grid = build_scenario_d_grid();
    Config cfg = make_scenario_d_config();

    // Ground truth: a non-symmetric pose where the L-shaped obstacle is
    // visibly to the upper-right of the LiDAR. Avoids placing the LiDAR
    // anywhere near the obstacle to keep beam ranges well-defined.
    const Pose2D truth{2.0, 3.0, 30.0};

    // ---------- Mode-A T1: asymmetry REQUIRE step ----------
    // Build 4 synthetic scans at xy=truth with yaw ∈ {0°, 90°, 180°, 270°}.
    // Assert all 4 scan signatures pairwise differ. If a future fixture
    // tweak re-symmetrizes the obstacle, this REQUIRE fails BEFORE the
    // annealing test runs.
    {
        std::vector<std::vector<double>> sigs;
        sigs.reserve(4);
        for (double yaw : {0.0, 90.0, 180.0, 270.0}) {
            const Pose2D p{truth.x, truth.y, yaw};
            const auto beams_p = synth_beams(grid, p, 360);
            REQUIRE(beams_p.size() > 100u);
            sigs.push_back(scan_signature(beams_p, 10));
        }
        for (std::size_t i = 0; i < sigs.size(); ++i) {
            for (std::size_t j = i + 1; j < sigs.size(); ++j) {
                CAPTURE(i);
                CAPTURE(j);
                REQUIRE(signatures_differ(sigs[i], sigs[j]));
            }
        }
    }

    // Synth a high-density scan at the truth pose for the convergence
    // sub-checks below. 360 beams ensures the asymmetric obstacle is
    // sampled.
    const auto beams = synth_beams(grid, truth, 360);
    REQUIRE(beams.size() > 200u);

    // ---------- Sub-check 1: single-σ baseline failure (Mode-A T2) ----------
    // With σ_hit = 0.05 + cfg.amcl_seed = 42, single-σ converge() from a
    // global seed cloud should fail to land on the truth basin (either
    // !converged OR xy_err > 1.0 m). Loose negative — pinned to a
    // verified-failing seed so a future writer cannot trivially pass it
    // by tightening σ_hit. If the fixture ever changes such that seed=42
    // converges, try seeds 0, 1, 7, 100; document which fails.
    {
        cfg.amcl_seed = 42;
        const LikelihoodField lf_narrow =
            build_likelihood_field(grid, 0.05);
        Amcl amcl(cfg, lf_narrow);
        Rng  rng(cfg.amcl_seed);
        amcl.seed_global(grid, rng);
        const auto result = amcl.converge(beams, rng);

        const double xy_err = std::hypot(result.pose.x - truth.x,
                                         result.pose.y - truth.y);
        CAPTURE(result.converged);
        CAPTURE(result.iterations);
        CAPTURE(result.pose.x);
        CAPTURE(result.pose.y);
        CAPTURE(result.pose.yaw_deg);
        CAPTURE(xy_err);
        // Negative assertion — annotated for future debugging if the
        // fixture changes.
        const bool failed = (!result.converged) || (xy_err > 1.0);
        CHECK(failed);
    }

    // ---------- Sub-check 2: annealing happy path (Mode-A T3) ----------
    // converge_anneal with schedule [1.0, 0.2, 0.05] should land within
    // 10 cm of truth. Wall-clock CHECK pinned at 5 s on the 200×200
    // fixture (Mode-A S3).
    {
        cfg.amcl_seed = 42;
        cfg.amcl_sigma_hit_schedule_m   = {1.0, 0.2, 0.05};
        cfg.amcl_sigma_seed_xy_schedule_m = {
            std::numeric_limits<double>::quiet_NaN(),
            0.10, 0.05,
        };
        cfg.amcl_anneal_iters_per_phase = 10;

        // Build lf at the first σ; converge_anneal will rebuild per phase.
        LikelihoodField lf =
            build_likelihood_field(grid, cfg.amcl_sigma_hit_schedule_m[0]);
        Amcl amcl(cfg, lf);
        Rng  rng(cfg.amcl_seed);
        Pose2D pose{};

        const auto t0 = std::chrono::steady_clock::now();
        const auto result = converge_anneal(cfg, beams, grid, lf, amcl,
                                            pose, rng);
        const auto elapsed = std::chrono::steady_clock::now() - t0;

        const double xy_err = std::hypot(result.pose.x - truth.x,
                                         result.pose.y - truth.y);
        CAPTURE(result.converged);
        CAPTURE(result.iterations);
        CAPTURE(result.pose.x);
        CAPTURE(result.pose.y);
        CAPTURE(result.pose.yaw_deg);
        CAPTURE(xy_err);
        CHECK(result.converged);
        CHECK(xy_err < 0.10);
        CHECK(elapsed < std::chrono::seconds(5));
    }

    // ---------- Sub-check 3: schedule length 1 runs single-phase
    //             annealing (Mode-A N5) ----------
    // converge_anneal with schedule [0.05] should run AT MOST
    // cfg.amcl_anneal_iters_per_phase iterations total. Tolerance-only
    // assertion — RNG draw sequence is schedule-length-dependent (see
    // CODEBASE.md invariant (n)).
    {
        cfg.amcl_seed = 42;
        cfg.amcl_sigma_hit_schedule_m   = {0.05};
        cfg.amcl_sigma_seed_xy_schedule_m = {
            std::numeric_limits<double>::quiet_NaN(),
        };
        cfg.amcl_anneal_iters_per_phase = 7;

        LikelihoodField lf =
            build_likelihood_field(grid, cfg.amcl_sigma_hit_schedule_m[0]);
        Amcl amcl(cfg, lf);
        Rng  rng(cfg.amcl_seed);
        Pose2D pose{};

        const auto result = converge_anneal(cfg, beams, grid, lf, amcl,
                                            pose, rng);
        CAPTURE(result.iterations);
        CHECK(result.iterations <= cfg.amcl_anneal_iters_per_phase);
        CHECK(result.iterations >= 1);
        CHECK(std::isfinite(result.pose.x));
        CHECK(std::isfinite(result.pose.y));
        CHECK(std::isfinite(result.pose.yaw_deg));
    }
}
