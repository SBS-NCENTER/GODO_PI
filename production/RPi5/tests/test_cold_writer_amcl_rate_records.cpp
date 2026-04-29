// PR-DIAG (Mode-A M2 fold) — pin that run_one_iteration /
// run_live_iteration each call amcl_rate_accum.record() exactly once
// at the top of their body (before any early return). The kernel-level
// contract; the build-grep [amcl-rate-publisher-grep] enforces that
// no other module records.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdint>
#include <limits>
#include <string>
#include <vector>

#include "core/config.hpp"
#include "core/hot_config.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "lidar/sample.hpp"
#include "localization/amcl.hpp"
#include "localization/cold_writer.hpp"
#include "localization/likelihood_field.hpp"
#include "localization/occupancy_grid.hpp"
#include "localization/pose.hpp"
#include "localization/rng.hpp"
#include "localization/scan_ops.hpp"
#include "rt/amcl_rate.hpp"

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
using godo::localization::run_live_iteration;
using godo::localization::run_one_iteration;
using godo::rt::AmclRateAccumulator;
using godo::rt::LastPose;
using godo::rt::LastScan;
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
        s.distance_mm  = 1500.0;
        s.quality      = 200;
        s.flag         = (i == 0) ? std::uint8_t{1} : std::uint8_t{0};
        s.timestamp_ns = 1'000'000'000LL + i * 1000LL;
        f.samples.push_back(s);
    }
    return f;
}

Config make_test_config(int seed) {
    Config cfg = Config::make_default();
    cfg.amcl_seed              = seed;
    cfg.amcl_max_iters         = 5;
    cfg.amcl_particles_local_n = 200;
    cfg.amcl_particles_global_n= 200;
    cfg.amcl_map_path =
        std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm";
    // Track D-5: collapse to single-phase annealing for test speed and
    // for the rate accumulator's "exactly 1 record() per kernel call"
    // contract — phase count does not affect record() count, but we
    // keep this small to bound test wall-clock.
    cfg.amcl_sigma_hit_schedule_m  = {0.05};
    cfg.amcl_sigma_seed_xy_schedule_m = {std::numeric_limits<double>::quiet_NaN()};
    cfg.amcl_anneal_iters_per_phase = 1;
    return cfg;
}

}  // namespace

TEST_CASE("run_one_iteration increments amcl_rate_accum exactly once") {
    Config cfg = make_test_config(1);
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);
    std::vector<RangeBeam> beams_buf;
    Pose2D last_pose{};
    bool   live_first_iter = true;
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame();
    (void)run_one_iteration(cfg, frame, grid, lf, amcl, rng, beams_buf,
                            last_pose, live_first_iter, last_written,
                            target_offset, last_pose_seq, last_scan_seq,
                            accum, hot_cfg_seq);
    CHECK(accum.snapshot().count == 1u);
}

TEST_CASE("run_live_iteration increments amcl_rate_accum exactly once") {
    Config cfg = make_test_config(2);
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);
    std::vector<RangeBeam> beams_buf;
    Pose2D last_pose{};
    bool   live_first_iter = true;
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame();
    (void)run_live_iteration(cfg, frame, grid, amcl, rng, beams_buf,
                             last_pose, live_first_iter, last_written,
                             target_offset, last_pose_seq, last_scan_seq,
                             accum, hot_cfg_seq);
    CHECK(accum.snapshot().count == 1u);
}

TEST_CASE("Three back-to-back kernel calls advance count by 3 and last_ns is monotonic") {
    Config cfg = make_test_config(3);
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);
    std::vector<RangeBeam> beams_buf;
    Pose2D last_pose{};
    bool   live_first_iter = true;
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame();
    std::uint64_t prev_last_ns = 0;
    for (int i = 0; i < 3; ++i) {
        (void)run_live_iteration(cfg, frame, grid, amcl, rng, beams_buf,
                                 last_pose, live_first_iter, last_written,
                                 target_offset, last_pose_seq, last_scan_seq,
                                 accum, hot_cfg_seq);
        const auto rec = accum.snapshot();
        CHECK(rec.count == static_cast<std::uint64_t>(i + 1));
        CHECK(rec.last_ns >= prev_last_ns);
        prev_last_ns = rec.last_ns;
    }
}
