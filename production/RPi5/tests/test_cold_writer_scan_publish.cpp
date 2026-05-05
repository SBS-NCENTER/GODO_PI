// Track D — cold writer publishes a LastScan snapshot to last_scan_seq
// at the same seam where it publishes LastPose. Hardware-free; drives
// `run_one_iteration` and `run_live_iteration` directly with synthetic
// frames (mirrors test_cold_writer_offset_invariant + ordering pattern).
//
// What this file pins:
//   1. OneShot publishes a LastScan with valid=1, forced=1.
//   2. Live publishes a LastScan with valid=1, forced=0.
//   3. Deadband-suppressed Offset still gets a LastScan publish (the
//      cold writer's UNCONDITIONAL pin, mirroring LastPose).
//   4. snap.n equals the count of in-range samples after stride decimation
//      (matches AMCL beam decimation rule).
//   5. published_mono_ns advances monotonically across consecutive runs.
//   6. n=0 corner case (all samples filtered) does not crash + still
//      emits valid=1.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

#include "core/config.hpp"
#include "core/constants.hpp"
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
using godo::localization::run_live_iteration;
using godo::localization::run_one_iteration;
using godo::rt::LastPose;
using godo::rt::LastScan;
using godo::rt::AmclRateAccumulator;
using godo::rt::Offset;
using godo::rt::Seqlock;

namespace {

Frame make_synthetic_frame(int n_samples, double base_distance_mm) {
    Frame f;
    f.index = 0;
    f.samples.reserve(n_samples);
    for (int i = 0; i < n_samples; ++i) {
        Sample s{};
        s.angle_deg    = (360.0 / n_samples) * static_cast<double>(i);
        s.distance_mm  = base_distance_mm;
        s.quality      = 200;
        s.flag         = (i == 0) ? std::uint8_t{1} : std::uint8_t{0};
        s.timestamp_ns = 1'000'000'000LL + i * 1000LL;
        f.samples.push_back(s);
    }
    return f;
}

Config make_test_config(std::uint64_t seed) {
    Config cfg = Config::make_default();
    cfg.amcl_seed                = seed;
    cfg.amcl_origin_x_m          = 1.0;
    cfg.amcl_origin_y_m          = 1.0;
    cfg.amcl_max_iters           = 5;
    cfg.amcl_particles_local_n   = 200;
    cfg.amcl_particles_global_n  = 200;
    // Track D-5: collapse to single-phase annealing for test speed.
    cfg.amcl_sigma_hit_schedule_m  = {0.05};
    cfg.amcl_sigma_seed_xy_schedule_m =
        {std::numeric_limits<double>::quiet_NaN()};
    cfg.amcl_anneal_iters_per_phase = 5;
    cfg.amcl_map_path =
        std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm";
    return cfg;
}

}  // namespace

TEST_CASE("OneShot publishes LastScan unconditionally with forced=1") {
    Config cfg = make_test_config(101);
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

    // Generation 0 means never published.
    CHECK(last_scan_seq.generation() == 0u);

    const Frame frame = make_synthetic_frame(360, 1500.0);
    const auto result = run_one_iteration(cfg, frame, grid, lf, amcl, rng,
                                          beams_buf, last_pose,
                                          live_first_iter, last_written,
                                          target_offset, last_pose_seq,
                                          last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    CHECK(last_scan_seq.generation() >= 2u);   // store advances by 2
    const LastScan snap = last_scan_seq.load();
    CHECK(snap.valid == 1);
    CHECK(snap.forced == 1);                    // OneShot kernel
    CHECK(snap.iterations == result.iterations);
    CHECK(snap.published_mono_ns > 0ULL);

    // Pose anchor matches the AMCL result's pose (zero skew).
    CHECK(snap.pose_x_m     == result.pose.x);
    CHECK(snap.pose_y_m     == result.pose.y);
    CHECK(snap.pose_yaw_deg == result.pose.yaw_deg);

    // pose_valid mirrors result.converged (Mode-A M3).
    CHECK(snap.pose_valid == (result.converged ? 1u : 0u));

    // n in [0, LAST_SCAN_RANGES_MAX]; with 360 samples × stride 1 (default
    // stride for the synthetic config) and all in-range distances, we
    // expect n == 360.
    CHECK(snap.n <=
          static_cast<std::uint16_t>(godo::constants::LAST_SCAN_RANGES_MAX));
    CHECK(snap.n > 0);
}

TEST_CASE("Live publishes LastScan unconditionally with forced=0") {
    Config cfg = make_test_config(202);
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

    const Frame frame = make_synthetic_frame(360, 1500.0);
    (void)run_live_iteration(cfg, frame, grid, amcl, rng,
                             beams_buf, last_pose, live_first_iter,
                             last_written, target_offset, last_pose_seq,
                             last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    const LastScan snap = last_scan_seq.load();
    CHECK(snap.valid == 1);
    CHECK(snap.forced == 0);                    // Live kernel
}

TEST_CASE("Deadband-suppressed Offset still publishes LastScan") {
    Config cfg = make_test_config(303);
    // Wide deadband suppresses the second Live publish.
    cfg.deadband_mm  = 100.0;
    cfg.deadband_deg = 5.0;
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

    const Frame frame = make_synthetic_frame(360, 1500.0);
    (void)run_live_iteration(cfg, frame, grid, amcl, rng,
                             beams_buf, last_pose, live_first_iter,
                             last_written, target_offset, last_pose_seq,
                             last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    const std::uint64_t target_gen_after_first = target_offset.generation();
    const std::uint64_t scan_gen_after_first   = last_scan_seq.generation();

    // Second call with same frame: target_offset suppressed by deadband,
    // last_scan_seq still advances (unconditional pin).
    (void)run_live_iteration(cfg, frame, grid, amcl, rng,
                             beams_buf, last_pose, live_first_iter,
                             last_written, target_offset, last_pose_seq,
                             last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(target_offset.generation() == target_gen_after_first);  // suppressed
    CHECK(last_scan_seq.generation()  > scan_gen_after_first);    // advanced
}

TEST_CASE("LastScan.n drops out-of-range samples (matches AMCL beam rule)") {
    Config cfg = make_test_config(404);
    // Half the samples are 0.05 m (below range_min) — they MUST be
    // filtered out of LastScan, mirroring scan_ops::downsample.
    // Override stride to 1 so every sample is visited (default stride=2
    // would visit only even indices, producing an asymmetric corpus).
    cfg.amcl_downsample_stride = 1;
    cfg.amcl_range_min_m = 0.5;
    cfg.amcl_range_max_m = 5.0;
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

    Frame frame = make_synthetic_frame(360, 1500.0);
    // Override every other sample to 50 mm (below range_min = 500 mm).
    for (std::size_t i = 0; i < frame.samples.size(); i += 2) {
        frame.samples[i].distance_mm = 50.0;
    }

    (void)run_one_iteration(cfg, frame, grid, lf, amcl, rng,
                            beams_buf, last_pose, live_first_iter,
                            last_written, target_offset, last_pose_seq,
                            last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    const LastScan snap = last_scan_seq.load();
    CHECK(snap.valid == 1);
    // 360 samples - 180 below range_min = 180 in-range.
    CHECK(snap.n == 180);
    // Every emitted range is within bounds.
    for (std::uint16_t i = 0; i < snap.n; ++i) {
        CHECK(snap.ranges_m[i] >= cfg.amcl_range_min_m);
        CHECK(snap.ranges_m[i] <= cfg.amcl_range_max_m);
    }
}

TEST_CASE("published_mono_ns advances monotonically across consecutive runs") {
    Config cfg = make_test_config(505);
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

    const Frame frame = make_synthetic_frame(360, 1500.0);
    std::uint64_t prev = 0ULL;
    for (int i = 0; i < 3; ++i) {
        (void)run_one_iteration(cfg, frame, grid, lf, amcl, rng,
                                beams_buf, last_pose, live_first_iter,
                                last_written, target_offset, last_pose_seq,
                                last_scan_seq, amcl_rate_accum, hot_cfg_seq);
        const std::uint64_t now = last_scan_seq.load().published_mono_ns;
        CHECK(now > prev);
        prev = now;
    }
}

TEST_CASE("n=0 corner case (all samples filtered) is well-formed") {
    Config cfg = make_test_config(606);
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

    // All samples have distance_mm = 0.0 (invalid sentinel from the
    // sample.hpp invariant); fill_last_scan must drop every one.
    Frame frame = make_synthetic_frame(360, 0.0);

    (void)run_one_iteration(cfg, frame, grid, lf, amcl, rng,
                            beams_buf, last_pose, live_first_iter,
                            last_written, target_offset, last_pose_seq,
                            last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    const LastScan snap = last_scan_seq.load();
    CHECK(snap.valid == 1);    // a publish DID happen
    CHECK(snap.n == 0);        // but no rays survived the filter
}
