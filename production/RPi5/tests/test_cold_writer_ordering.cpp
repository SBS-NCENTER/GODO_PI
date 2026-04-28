// Track B (F5) — ordering pin: cold writer publishes `last_pose_seq`
// before the OneShot success path stores `g_amcl_mode = Idle`. The
// repeatability harness polls get_mode==Idle and then reads
// get_last_pose; without this ordering the reader can see the new Idle
// mode and the stale pose from a previous OneShot.
//
// What this test pins: after `run_one_iteration` returns, the
// `last_pose_seq` Seqlock has been published with valid=1. This is the
// kernel-level pin — the caller-level "Idle store happens AFTER kernel
// return" is enforced by the structure of cold_writer.cpp's switch
// (the store(Idle) is below the kernel call), and removing the verbatim
// comment at L302 would also drop this test's premise.
//
// Bias-block: this test does NOT spawn the cold writer thread or drive
// the LiDAR factory. It exercises the testable seam (run_one_iteration)
// which is where the publish lives, then asserts the seqlock generation
// advanced.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

#include "core/config.hpp"
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
using godo::localization::run_live_iteration;
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
        s.distance_mm  = 1500.0;
        s.quality      = 200;
        s.flag         = (i == 0) ? std::uint8_t{1} : std::uint8_t{0};
        s.timestamp_ns = 1'000'000'000LL + i * 1000LL;
        f.samples.push_back(s);
    }
    return f;
}

Config make_test_config(std::uint64_t seed) {
    Config cfg = Config::make_default();
    cfg.amcl_seed              = seed;
    cfg.amcl_origin_x_m        = 1.0;
    cfg.amcl_origin_y_m        = 1.0;
    cfg.amcl_origin_yaw_deg    = 0.0;
    cfg.amcl_max_iters         = 5;
    cfg.amcl_particles_local_n = 200;
    cfg.amcl_particles_global_n= 200;
    cfg.amcl_map_path =
        std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm";
    return cfg;
}

}  // namespace

TEST_CASE("last_pose_seq_published_before_idle_store") {
    // Pin: run_one_iteration MUST publish to last_pose_seq before
    // returning. The cold writer's case OneShot then stores g_amcl_mode
    // = Idle (cold_writer.cpp success path with the verbatim F5 comment).
    // Removing the publish call would leave the seqlock at generation 0;
    // the reader would observe Idle + stale pose.
    Config cfg = make_test_config(909);
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
    AmclRateAccumulator amcl_rate_accum;

    // Initial generation is 0 — never published.
    CHECK(last_pose_seq.generation() == 0u);

    const Frame frame = make_synthetic_frame(360);
    (void)run_one_iteration(cfg, frame, grid, amcl, rng, beams_buf,
                            last_pose, live_first_iter, last_written,
                            target_offset, last_pose_seq, last_scan_seq, amcl_rate_accum);

    // After run_one_iteration: seqlock generation MUST have advanced
    // (publish happened) and the snapshot MUST be marked valid + forced.
    CHECK(last_pose_seq.generation() >= 2u);   // store advances by 2
    const LastPose snap = last_pose_seq.load();
    CHECK(snap.valid == 1);
    CHECK(snap.forced == 1);                   // OneShot kernel
    CHECK(snap.iterations >= 1);
    CHECK(std::isfinite(snap.x_m));
    CHECK(std::isfinite(snap.y_m));
    CHECK(std::isfinite(snap.yaw_deg));
    CHECK(snap.published_mono_ns > 0ULL);
}

TEST_CASE("last_pose_seq published by run_live_iteration with forced=0") {
    // Live publishes the pose snapshot too, with forced=0 distinguishing
    // it from a OneShot publish. pose_watch.py needs this so the
    // operator can see "is the tracker in OneShot or Live mode" in the
    // pose stream itself, not just via get_mode.
    Config cfg = make_test_config(818);
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
    AmclRateAccumulator amcl_rate_accum;

    const Frame frame = make_synthetic_frame(360);
    (void)run_live_iteration(cfg, frame, grid, amcl, rng, beams_buf,
                             last_pose, live_first_iter, last_written,
                             target_offset, last_pose_seq, last_scan_seq, amcl_rate_accum);

    CHECK(last_pose_seq.generation() >= 2u);
    const LastPose snap = last_pose_seq.load();
    CHECK(snap.valid == 1);
    CHECK(snap.forced == 0);                   // Live kernel
    CHECK(std::isfinite(snap.x_m));
}
