// Phase 4-2 B Wave 2 — cold-writer Offset shape invariants (M3 + S6).
// Phase 4-2 D — second-call test now pins OneShot's always-`seed_global`
// behaviour: the iteration count of two back-to-back OneShot runs must
// stay within ±20% (with a small absolute floor for stochastic drift).
// If a warm-seed shortcut sneaks back in, r2.iterations would drop
// sharply on the second call and the bound would fail.
//
// Drives `run_one_iteration` directly (the testable seam in cold_writer.hpp)
// with a synthetic LiDAR Frame. We do NOT spawn a thread, do NOT touch
// g_amcl_mode, and do NOT need a real LidarSourceRplidar — the kernel
// pre-computes its grid and likelihood field, then the test injects the
// Frame and reads the published seqlock value.
//
// Asserted invariants:
//   - Offset has finite components (no NaN, no Inf).
//   - dyaw is in [0, 360) (canonical-360, M3-pinned).
//   - |dx|, |dy| < 50.0 (sane bound; far larger than any real studio).
//   - sizeof(Offset) == 24 and alignof(Offset) is 8 (matches rt_types.hpp).
//
// Bias-block: no Bresenham here. The synthetic frame's ranges don't have to
// be realistic — they just need to be finite so the AMCL kernel publishes
// something. Algorithmic quality is exercised by test_amcl_scenarios.cpp.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <string>
#include <vector>

#include "core/config.hpp"
#include "core/hot_config.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "rt/amcl_rate.hpp"
#include "lidar/sample.hpp"
#include "localization/amcl.hpp"
#include "localization/cold_writer.hpp"
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
using godo::localization::LikelihoodField;
using godo::localization::load_map;
using godo::localization::OccupancyGrid;
using godo::localization::Pose2D;
using godo::localization::RangeBeam;
using godo::localization::Rng;
using godo::localization::run_one_iteration;
using godo::rt::LastPose;
using godo::rt::LastScan;
using godo::rt::AmclRateAccumulator;
using godo::rt::Offset;
using godo::rt::Seqlock;

namespace {

Frame make_synthetic_frame(int n_samples = 360) {
    Frame f;
    f.index = 0;
    f.samples.reserve(n_samples);
    for (int i = 0; i < n_samples; ++i) {
        Sample s{};
        s.angle_deg    = (360.0 / n_samples) * static_cast<double>(i);
        // 1.5 m from the centre of a 4×4 m room is well inside; gives the
        // likelihood field something to score against without aliasing the
        // walls perfectly.
        s.distance_mm  = 1500.0;
        s.quality      = 200;
        s.flag         = (i == 0) ? std::uint8_t{1} : std::uint8_t{0};
        s.timestamp_ns = 1'000'000'000LL + i * 1000LL;
        f.samples.push_back(s);
    }
    return f;
}

}  // namespace

TEST_CASE("Offset — sizeof and alignof match rt_types.hpp ABI") {
    // rt_types.hpp pins sizeof(Offset)==24. alignof on a struct of three
    // doubles is 8 on every platform GODO targets (RPi 5 aarch64, x86_64).
    CHECK(sizeof(Offset)  == 24u);
    CHECK(alignof(Offset) == alignof(double));
    CHECK(alignof(Offset) == 8u);
}

TEST_CASE("run_one_iteration — published Offset is NaN/Inf-free with canonical dyaw") {
    Config cfg = Config::make_default();
    cfg.amcl_seed                   = 42;
    cfg.amcl_origin_x_m             = 1.0;
    cfg.amcl_origin_y_m             = 1.0;
    cfg.amcl_origin_yaw_deg         = 0.0;
    cfg.amcl_max_iters              = 5;     // keep test fast
    cfg.amcl_particles_local_n      = 200;   // smaller for speed; still > N_eff threshold
    cfg.amcl_particles_global_n     = 200;
    // Track D-5: collapse to single-phase annealing for test speed.
    cfg.amcl_sigma_hit_schedule_m   = {0.05};
    cfg.amcl_sigma_seed_xy_schedule_m = {std::numeric_limits<double>::quiet_NaN()};
    cfg.amcl_anneal_iters_per_phase = 5;
    cfg.amcl_map_path =
        std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm";

    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf  = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    std::vector<RangeBeam> beams_buf;
    Pose2D last_pose{};
    bool   live_first_iter = true;
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator amcl_rate_accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame(360);
    const auto result = run_one_iteration(cfg, frame, grid, lf, amcl, rng,
                                          beams_buf, last_pose,
                                          live_first_iter, last_written,
                                          target_offset, last_pose_seq,
                                          last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    // forced=true because run_one_iteration is the OneShot kernel.
    CHECK(result.forced == true);

    // Offset components are finite.
    CHECK(std::isfinite(result.offset.dx));
    CHECK(std::isfinite(result.offset.dy));
    CHECK(std::isfinite(result.offset.dyaw));

    // dyaw canonical-360 (M3).
    CHECK(result.offset.dyaw >= 0.0);
    CHECK(result.offset.dyaw <  360.0);

    // |dx|, |dy| within sane bound (the room is 4×4 m, so any pose is
    // < 4 m from any origin — well inside 50 m).
    CHECK(std::abs(result.offset.dx) < 50.0);
    CHECK(std::abs(result.offset.dy) < 50.0);

    // The seqlock observed the same value (round-trip via store/load).
    const Offset published = target_offset.load();
    CHECK(published.dx   == result.offset.dx);
    CHECK(published.dy   == result.offset.dy);
    CHECK(published.dyaw == result.offset.dyaw);

    // live_first_iter cleared by the OneShot kernel (state hygiene); the
    // OneShot seed branch did NOT consult it.
    CHECK(live_first_iter == false);
    CHECK(std::isfinite(last_pose.x));
    CHECK(std::isfinite(last_pose.y));
    CHECK(std::isfinite(last_pose.yaw_deg));
    CHECK(last_pose.yaw_deg >= 0.0);
    CHECK(last_pose.yaw_deg <  360.0);
}

TEST_CASE("run_one_iteration — second call still uses seed_global (no warm-seed shortcut)") {
    // Phase 4-2 D pin: OneShot phase 0 is unconditionally seed_global. The
    // pre-Phase-4-2-D behaviour was first call seed_global, subsequent
    // seed_around — which let r2.iterations drop sharply on the second
    // call. Now both runs start from the same global seed cloud, so the
    // iteration counts must stay within ±20% (or ±2 iters, whichever is
    // larger — covers the small-iter floor where 20% rounds to zero).
    //
    // Track D-5: schedule collapsed to length 1 so phase k>0 (which DOES
    // seed_around) does not enter the picture; the test continues to pin
    // the OneShot-phase-0 always-seed_global guarantee.
    //
    // If a warm-seed regression silently re-introduces seed_around for
    // OneShot phase 0, r2.iterations would collapse and this CHECK
    // would fail.
    Config cfg = Config::make_default();
    cfg.amcl_seed              = 7;
    cfg.amcl_max_iters         = 5;
    cfg.amcl_particles_local_n = 200;
    cfg.amcl_particles_global_n= 200;
    cfg.amcl_sigma_hit_schedule_m   = {0.05};
    cfg.amcl_sigma_seed_xy_schedule_m = {std::numeric_limits<double>::quiet_NaN()};
    cfg.amcl_anneal_iters_per_phase = 5;
    cfg.amcl_map_path =
        std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm";

    OccupancyGrid   grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf   = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    std::vector<RangeBeam> beams_buf;
    Pose2D last_pose{};
    bool   live_first_iter = true;
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator amcl_rate_accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;
    const Frame    frame = make_synthetic_frame(360);

    const auto r1 = run_one_iteration(cfg, frame, grid, lf, amcl, rng,
                                      beams_buf, last_pose, live_first_iter,
                                      last_written, target_offset,
                                      last_pose_seq, last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(live_first_iter == false);
    CHECK(r1.iterations >= 1);
    CHECK(r1.iterations <= cfg.amcl_anneal_iters_per_phase);

    // Second call: still seed_global per Phase 4-2 D. Iteration count
    // should be within ±20% of r1 (or ±2, whichever is larger).
    const auto r2 = run_one_iteration(cfg, frame, grid, lf, amcl, rng,
                                      beams_buf, last_pose, live_first_iter,
                                      last_written, target_offset,
                                      last_pose_seq, last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(live_first_iter == false);
    CHECK(r2.iterations >= 1);
    CHECK(r2.iterations <= cfg.amcl_anneal_iters_per_phase);
    CHECK(std::isfinite(r2.offset.dx));
    CHECK(std::isfinite(r2.offset.dy));
    CHECK(std::isfinite(r2.offset.dyaw));
    CHECK(r2.offset.dyaw >= 0.0);
    CHECK(r2.offset.dyaw <  360.0);

    const int delta  = std::abs(r2.iterations - r1.iterations);
    const int budget = std::max(2, r1.iterations / 5);    // ±20% or ±2
    CHECK(delta <= budget);
}
