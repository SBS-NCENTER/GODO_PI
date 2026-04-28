// Phase 4-2 D Wave A — Live iteration kernel tests.
//
// Drives `run_live_iteration` (the testable seam exposed by cold_writer.hpp)
// with synthetic LiDAR Frames, plus a direct σ-override probe of `Amcl::step`
// to pin that the σ pair argument actually feeds the motion model.
//
// Asserted contracts:
//   (a) Live result has `forced == false`. (Distinct from OneShot's
//       `forced == true` — the deadband filter applies in Live mode.)
//   (b) Two near-identical synthetic frames in sequence: the second
//       publish is suppressed by the deadband. `target_offset.generation()`
//       does NOT advance on the second call.
//   (c) Two clearly-different synthetic frames in sequence: the second
//       publish is accepted, generation advances.
//   (d) `live_first_iter_inout` flips to false after the first call;
//       second call uses `seed_around` instead of `seed_global` (the path
//       is observed implicitly via the latch state).
//   (e) σ-override propagation pin: with a fixed `Rng` seed and identical
//       synthetic frame, `Amcl::step(beams, rng, σ_low, …)` and
//       `Amcl::step(beams, rng, σ_high, …)` produce `xy_std_m` that differ
//       by > 1e-6. If the σ argument is silently dropped the two stds
//       would match exactly (same RNG sequence, same input).
//
// Bias-block: this test does NOT assert AMCL pose accuracy. The synthetic
// 4×4 m fixture has only a few beams that score; pose values are noisy.
// What's pinned is the kernel's contract (forced flag, deadband seam,
// latch flip, σ-overload threading), NOT algorithmic quality. Algorithmic
// pose-quality is exercised by test_amcl_scenarios.cpp.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <cstdint>
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
using godo::localization::downsample;
using godo::localization::LikelihoodField;
using godo::localization::load_map;
using godo::localization::OccupancyGrid;
using godo::localization::Pose2D;
using godo::localization::RangeBeam;
using godo::localization::Rng;
using godo::localization::run_live_iteration;
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
    cfg.amcl_seed                       = seed;
    cfg.amcl_origin_x_m                 = 1.0;
    cfg.amcl_origin_y_m                 = 1.0;
    cfg.amcl_origin_yaw_deg             = 0.0;
    cfg.amcl_max_iters                  = 5;
    cfg.amcl_particles_local_n          = 200;
    cfg.amcl_particles_global_n         = 200;
    cfg.amcl_map_path =
        std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm";
    return cfg;
}

}  // namespace

TEST_CASE("run_live_iteration — forced=false (deadband applies in Live)") {
    Config cfg = make_test_config(101);
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
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame(360, 1500.0);
    const auto result = run_live_iteration(cfg, frame, grid, amcl, rng,
                                           beams_buf, last_pose,
                                           live_first_iter, last_written,
                                           target_offset, last_pose_seq,
                                           last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    CHECK(result.forced == false);   // distinct from OneShot's true
    CHECK(std::isfinite(result.offset.dx));
    CHECK(std::isfinite(result.offset.dy));
    CHECK(std::isfinite(result.offset.dyaw));
    CHECK(result.offset.dyaw >= 0.0);
    CHECK(result.offset.dyaw <  360.0);
    CHECK(std::isfinite(result.xy_std_m));
    CHECK(std::isfinite(result.yaw_std_deg));
}

TEST_CASE("run_live_iteration — live_first_iter latch flips after first call") {
    Config cfg = make_test_config(202);
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
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame(360, 1500.0);
    (void)run_live_iteration(cfg, frame, grid, amcl, rng,
                             beams_buf, last_pose, live_first_iter,
                             last_written, target_offset, last_pose_seq,
                             last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    // After the first call the latch is cleared so the next iteration
    // takes the seed_around branch.
    CHECK(live_first_iter == false);

    // Second call: still finite output, latch stays false (the kernel
    // only re-seeds globally when the latch is true on entry).
    const auto r2 = run_live_iteration(cfg, frame, grid, amcl, rng,
                                       beams_buf, last_pose, live_first_iter,
                                       last_written, target_offset,
                                       last_pose_seq, last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(live_first_iter == false);
    CHECK(std::isfinite(r2.xy_std_m));
    CHECK(std::isfinite(r2.yaw_std_deg));
}

TEST_CASE("run_live_iteration — near-identical frames: second publish suppressed by deadband") {
    Config cfg = make_test_config(303);
    // Tighten the deadband to a value that the AMCL sub-cm jitter cannot
    // exceed against the LAST WRITTEN reference (default cfg.deadband_mm
    // is 10 mm; we pin at 100 mm here to ensure suppression even with
    // noisy AMCL pose between two identical frames).
    cfg.deadband_mm  = 100.0;
    cfg.deadband_deg = 5.0;
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
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame(360, 1500.0);
    (void)run_live_iteration(cfg, frame, grid, amcl, rng,
                             beams_buf, last_pose, live_first_iter,
                             last_written, target_offset, last_pose_seq,
                             last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    const std::uint64_t gen_after_first = target_offset.generation();
    CHECK(gen_after_first >= 1u);

    // Second call with the same frame. Deadband (100 mm / 5°) is wider
    // than the AMCL noise between two identical scans, so the publish
    // is suppressed and `generation()` does NOT advance.
    (void)run_live_iteration(cfg, frame, grid, amcl, rng,
                             beams_buf, last_pose, live_first_iter,
                             last_written, target_offset, last_pose_seq,
                             last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(target_offset.generation() == gen_after_first);
}

TEST_CASE("run_live_iteration — clearly-different frames: second publish accepted") {
    Config cfg = make_test_config(404);
    // Tight deadband so any non-trivial pose change advances the
    // generation. Default 10 mm / 0.1° is already small; keep defaults.
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
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    // Frame A — beams at 1.5 m. Frame B — beams at 0.8 m. Different
    // ranges shift the AMCL weighted-mean pose well beyond 10 mm /
    // 0.1°, which makes the second publish supra-deadband.
    const Frame frame_a = make_synthetic_frame(360, 1500.0);
    const Frame frame_b = make_synthetic_frame(360, 800.0);

    (void)run_live_iteration(cfg, frame_a, grid, amcl, rng,
                             beams_buf, last_pose, live_first_iter,
                             last_written, target_offset, last_pose_seq,
                             last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    const std::uint64_t gen_after_first = target_offset.generation();

    (void)run_live_iteration(cfg, frame_b, grid, amcl, rng,
                             beams_buf, last_pose, live_first_iter,
                             last_written, target_offset, last_pose_seq,
                             last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(target_offset.generation() > gen_after_first);
}

TEST_CASE("Amcl::step — σ argument feeds motion model (xy_std_m differs across σ)") {
    // Phase 4-2 D amendment S4: pin that the σ overload's argument
    // actually drives the jitter draw. Same RNG seed, same fixture, same
    // frame; only the σ argument changes between two `step()` calls run
    // on freshly-seeded Amcl instances.
    Config cfg = make_test_config(505);

    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    const Frame frame = make_synthetic_frame(360, 1500.0);

    // Path 1: tight σ.
    Amcl amcl_low(cfg, lf);
    Rng  rng_low(cfg.amcl_seed);
    amcl_low.seed_global(grid, rng_low);
    std::vector<RangeBeam> beams_low;
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams_low);
    const auto r_low = amcl_low.step(beams_low, rng_low, 0.001, 0.05);

    // Path 2: loose σ. Fresh Amcl, fresh RNG with the SAME seed so the
    // gauss draws differ only by the σ scale.
    Amcl amcl_high(cfg, lf);
    Rng  rng_high(cfg.amcl_seed);
    amcl_high.seed_global(grid, rng_high);
    std::vector<RangeBeam> beams_high;
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams_high);
    const auto r_high = amcl_high.step(beams_high, rng_high, 0.100, 5.0);

    CHECK(std::isfinite(r_low.xy_std_m));
    CHECK(std::isfinite(r_high.xy_std_m));
    // Wider σ produces a wider particle cloud; the diff must be
    // numerically detectable, not zero. 1e-6 is the bias-block floor:
    // anything tighter would risk false positives from arithmetic noise,
    // anything looser would miss subtle silent-drop regressions.
    CHECK(std::abs(r_high.xy_std_m - r_low.xy_std_m) > 1e-6);
}
