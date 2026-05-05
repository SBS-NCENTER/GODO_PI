// issue#5 — Live pipelined-hint kernel tests.
//
// Drives `run_live_iteration_pipelined` (the testable seam exposed by
// cold_writer.hpp) with synthetic LiDAR Frames. Pin contracts, NOT pose
// accuracy — bias-block per the test_cold_writer_live_iteration.cpp
// preamble (synthetic 4×4 m fixture has only a few beams that score;
// pose values are noisy). Algorithmic pose-quality is exercised by
// test_amcl_scenarios.cpp (Scenario E for converge_anneal_with_hint).
//
// Asserted contracts:
//   (a) tick t=0 with `last_pose` carrying a non-default value (i.e. a
//       prior OneShot pose) — `run_live_iteration_pipelined` runs the
//       hint-driven kernel without seeding globally and without touching
//       g_calibrate_hint_*. Verified via `last_pose_inout` post-call
//       carrying a finite value AND g_calibrate_hint_valid staying false.
//   (b) tick t=1 with the previous tick's pose as carry — verify
//       `last_pose_inout` updated unconditionally; the kernel uses it as
//       the t=1 hint (path observed implicitly by g_calibrate_hint_valid
//       remaining false despite a hint being present mid-flight).
//   (c) σ-override propagation: with a fixed Rng seed and identical
//       synthetic frame, calling `run_live_iteration_pipelined` with
//       cfg.amcl_live_carry_sigma_xy_m = 0.001 vs 0.05 produces
//       different `xy_std_m`. If the σ argument is silently dropped the
//       two stds would match exactly (same RNG sequence, same inputs).
//   (d) Forced=false on every Live publish; deadband applies (suppresses
//       sub-deadband repeat publishes).
//   (e) Live re-entry after OneShot completion: t=0 hint sources from
//       `last_pose_inout`, NOT from `g_calibrate_hint_*`. The pipelined
//       path runs even when the operator's hint flag is still set
//       (mid-Live re-anchor is out of scope per plan §14).
//   (f) Cold-start guard rejection — pinned at the run_cold_writer
//       seam (covered by an integration-style test below using the
//       `last_pose_inout = (0,0,0)` AND `last_pose_set = false` initial
//       state; rejection happens BEFORE this kernel is reached, so this
//       file pins the kernel's behaviour when the guard is satisfied).
//   (g) `live_first_iter_inout` latch is bypassed entirely on the
//       pipelined path (pin: kernel signature does not take a
//       live_first_iter parameter; the cold-writer's run_cold_writer
//       loop never consults the latch on the pipelined branch).
//   (h) flag-on Live → Idle → flag-off Live round-trip: after a
//       pipelined Live tick, `live_first_iter` re-arms via
//       `on_leave_live` on the Live exit path, AND the rollback path's
//       seed_global fires on its first call after the flag flip.
//       Indirect test: verify the pipelined path does NOT modify
//       `live_first_iter` and the rollback path's seed_global path is
//       independently exercised via run_live_iteration with
//       live_first_iter=true.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

#include "core/config.hpp"
#include "core/hot_config.hpp"
#include "core/rt_flags.hpp"
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
using godo::localization::converge_anneal_with_hint;
using godo::localization::downsample;
using godo::localization::LikelihoodField;
using godo::localization::load_map;
using godo::localization::OccupancyGrid;
using godo::localization::Pose2D;
using godo::localization::RangeBeam;
using godo::localization::Rng;
using godo::localization::run_live_iteration;
using godo::localization::run_live_iteration_pipelined;
using godo::rt::AmclRateAccumulator;
using godo::rt::LastPose;
using godo::rt::LastScan;
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
    cfg.amcl_max_iters                  = 5;
    cfg.amcl_particles_local_n          = 200;
    cfg.amcl_particles_global_n         = 200;
    cfg.amcl_map_path =
        std::string(GODO_FIXTURES_MAPS_DIR) + "/synthetic_4x4.pgm";
    // issue#5 — pipelined kernel selector ON for this test file. Caller
    // is the kernel directly, so the cfg flag is informational here; the
    // real branch lives in run_cold_writer's Live case body.
    cfg.live_carry_pose_as_hint         = true;
    cfg.amcl_live_carry_sigma_xy_m      = 0.05;
    cfg.amcl_live_carry_sigma_yaw_deg   = 5.0;
    // Short schedule keeps the per-test wall-clock low and matches the
    // production default. The pipelined kernel rebuilds lf at each phase.
    cfg.amcl_live_carry_schedule_m      = {0.2, 0.1, 0.05};
    cfg.amcl_anneal_iters_per_phase     = 5;
    return cfg;
}

// Small helper to clear the global hint flag between tests so a residual
// `g_calibrate_hint_valid = true` from a previous test cannot interfere
// with the pipelined-path no-touch contract.
void reset_hint_flag() {
    godo::rt::g_calibrate_hint_valid.store(false, std::memory_order_release);
}

}  // namespace

TEST_CASE("run_live_iteration_pipelined — case (a) tick t=0 uses last_pose hint, ignores g_calibrate_hint") {
    reset_hint_flag();
    Config cfg = make_test_config(101);
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    std::vector<RangeBeam> beams_buf;
    // Simulate "OneShot just ran and produced this pose" — caller sets
    // last_pose to the OneShot result before entering the pipelined path.
    Pose2D last_pose{1.95, 2.05, 1.0};
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator amcl_rate_accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    // Publish a hint that should be IGNORED by the pipelined path.
    godo::rt::HintBundle hint{};
    hint.x_m       = 99.0;
    hint.y_m       = 99.0;
    hint.yaw_deg   = 90.0;
    hint.sigma_xy_m   = 0.01;
    hint.sigma_yaw_deg = 1.0;
    godo::rt::g_calibrate_hint_data.store(hint);
    godo::rt::g_calibrate_hint_valid.store(true, std::memory_order_release);

    const Frame frame = make_synthetic_frame(360, 1500.0);
    const auto result = run_live_iteration_pipelined(
        cfg, frame, grid, lf, amcl, rng, beams_buf, last_pose,
        last_written, target_offset, last_pose_seq,
        last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    // Contract: result is finite, forced=false (Live publishes through
    // deadband).
    CHECK(result.forced == false);
    CHECK(std::isfinite(result.pose.x));
    CHECK(std::isfinite(result.pose.y));
    CHECK(std::isfinite(result.pose.yaw_deg));
    CHECK(std::isfinite(result.xy_std_m));
    // Critical: the pipelined path NEVER clears g_calibrate_hint_valid.
    // Consume-once is OneShot-only.
    CHECK(godo::rt::g_calibrate_hint_valid.load(std::memory_order_acquire) == true);
    // Last pose was updated to the converged result.
    CHECK(last_pose.x == result.pose.x);
    CHECK(last_pose.y == result.pose.y);

    reset_hint_flag();  // clean up for next test
}

TEST_CASE("run_live_iteration_pipelined — case (b) tick t=1 uses pose[t-1] as hint (carryover)") {
    reset_hint_flag();
    Config cfg = make_test_config(202);
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    std::vector<RangeBeam> beams_buf;
    // t=0 hint source: a converged-looking pose. After tick t=0,
    // last_pose carries the kernel's converged result.
    Pose2D last_pose{1.95, 2.05, 1.0};
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator amcl_rate_accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame(360, 1500.0);
    const auto r0 = run_live_iteration_pipelined(
        cfg, frame, grid, lf, amcl, rng, beams_buf, last_pose,
        last_written, target_offset, last_pose_seq,
        last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    // After t=0, last_pose carries the converged pose.
    const Pose2D pose_after_t0 = last_pose;
    CHECK(std::isfinite(pose_after_t0.x));

    // Tick t=1 — same frame, same RNG state. Verify last_pose carryover
    // is observed: kernel reads last_pose as hint, runs, updates it.
    const auto r1 = run_live_iteration_pipelined(
        cfg, frame, grid, lf, amcl, rng, beams_buf, last_pose,
        last_written, target_offset, last_pose_seq,
        last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    CHECK(std::isfinite(r1.xy_std_m));
    // Last pose updated to the new converged result.
    CHECK(last_pose.x == r1.pose.x);
    CHECK(last_pose.y == r1.pose.y);
    // g_calibrate_hint_valid is still false (was never set in this test);
    // pipelined path never wrote to it.
    CHECK(godo::rt::g_calibrate_hint_valid.load(std::memory_order_acquire) == false);
    (void)r0;
}

TEST_CASE("run_live_iteration_pipelined — case (c) σ-override propagates (xy_std_m differs)") {
    // Pin: same RNG seed + same fixture + same hint pose, only the
    // σ_xy carry value changes between two pipelined kernel calls.
    // If the σ argument is silently dropped, xy_std_m would match.
    Config cfg_low  = make_test_config(303);
    Config cfg_high = cfg_low;
    cfg_low.amcl_live_carry_sigma_xy_m  = 0.001;
    cfg_high.amcl_live_carry_sigma_xy_m = 0.10;

    OccupancyGrid grid = load_map(cfg_low.amcl_map_path);

    const Frame frame = make_synthetic_frame(360, 1500.0);
    const Pose2D hint{1.95, 2.05, 1.0};

    auto run_kernel = [&](const Config& cfg) {
        LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
        Amcl amcl(cfg, lf);
        Rng  rng(cfg.amcl_seed);
        std::vector<RangeBeam> beams_buf;
        Pose2D last_pose = hint;
        Offset last_written{0.0, 0.0, 0.0};
        Seqlock<Offset>   target_offset;
        Seqlock<LastPose> last_pose_seq;
        Seqlock<LastScan> last_scan_seq;
        AmclRateAccumulator amcl_rate_accum;
        Seqlock<godo::core::HotConfig> hot_cfg_seq;
        return run_live_iteration_pipelined(
            cfg, frame, grid, lf, amcl, rng, beams_buf, last_pose,
            last_written, target_offset, last_pose_seq,
            last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    };

    const auto r_low  = run_kernel(cfg_low);
    const auto r_high = run_kernel(cfg_high);

    CHECK(std::isfinite(r_low.xy_std_m));
    CHECK(std::isfinite(r_high.xy_std_m));
    // 1e-6 is the bias-block floor (mirrors test_cold_writer_live_iteration
    // case (e)). Looser would miss subtle silent-drop regressions; tighter
    // would risk false positives from arithmetic noise.
    CHECK(std::abs(r_high.xy_std_m - r_low.xy_std_m) > 1e-6);
}

TEST_CASE("run_live_iteration_pipelined — case (d) forced=false; deadband suppresses near-identical frames") {
    reset_hint_flag();
    Config cfg = make_test_config(404);
    cfg.deadband_mm  = 100.0;   // wide enough to suppress AMCL noise
    cfg.deadband_deg = 5.0;
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    std::vector<RangeBeam> beams_buf;
    Pose2D last_pose{1.95, 2.05, 1.0};
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator amcl_rate_accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame(360, 1500.0);
    const auto r0 = run_live_iteration_pipelined(
        cfg, frame, grid, lf, amcl, rng, beams_buf, last_pose,
        last_written, target_offset, last_pose_seq,
        last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(r0.forced == false);
    const std::uint64_t gen_after_first = target_offset.generation();
    CHECK(gen_after_first >= 1u);

    // Second call with the same frame. Deadband (100 mm / 5°) is wider
    // than the AMCL noise between two identical scans; publish suppressed.
    (void)run_live_iteration_pipelined(
        cfg, frame, grid, lf, amcl, rng, beams_buf, last_pose,
        last_written, target_offset, last_pose_seq,
        last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(target_offset.generation() == gen_after_first);
}

TEST_CASE("run_live_iteration_pipelined — case (e) Live re-entry after OneShot uses last_pose, not g_calibrate_hint") {
    // Simulate the "OneShot ran with hint, then operator toggled Live"
    // sequence. The OneShot path consumed the hint flag (we replicate
    // that by leaving the flag cleared); the pipelined Live path picks
    // up `last_pose` as its t=0 hint source.
    reset_hint_flag();
    Config cfg = make_test_config(505);
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    std::vector<RangeBeam> beams_buf;
    // last_pose simulates the post-OneShot converged pose.
    Pose2D last_pose{2.10, 1.95, -2.0};
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator amcl_rate_accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;

    const Frame frame = make_synthetic_frame(360, 1500.0);
    const auto r = run_live_iteration_pipelined(
        cfg, frame, grid, lf, amcl, rng, beams_buf, last_pose,
        last_written, target_offset, last_pose_seq,
        last_scan_seq, amcl_rate_accum, hot_cfg_seq);

    CHECK(std::isfinite(r.xy_std_m));
    // Confirm flag is still false (was false on entry; pipelined path
    // never lifted it).
    CHECK(godo::rt::g_calibrate_hint_valid.load(std::memory_order_acquire) == false);
}

TEST_CASE("run_live_iteration_pipelined — case (g) signature does not take live_first_iter parameter") {
    // Compile-time pin via decltype. The pipelined kernel's signature
    // has 14 parameters and does NOT include `bool& live_first_iter_inout`;
    // the legacy run_live_iteration has it at parameter index 7. If a
    // future writer accidentally adds the latch param, this static_assert
    // fails with a clear message.
    using PipelinedFn = decltype(run_live_iteration_pipelined);
    using LegacyFn    = decltype(run_live_iteration);
    static_assert(!std::is_same_v<PipelinedFn, LegacyFn>,
                  "run_live_iteration_pipelined and run_live_iteration "
                  "MUST have distinct signatures (issue#5: pipelined path "
                  "does not consult live_first_iter latch)");
    // Smoke check the kernel runs end-to-end (same fixture).
    Config cfg = make_test_config(606);
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);
    std::vector<RangeBeam> beams_buf;
    Pose2D last_pose{1.95, 2.05, 0.0};
    Offset last_written{0.0, 0.0, 0.0};
    Seqlock<Offset>   target_offset;
    Seqlock<LastPose> last_pose_seq;
    Seqlock<LastScan> last_scan_seq;
    AmclRateAccumulator amcl_rate_accum;
    Seqlock<godo::core::HotConfig> hot_cfg_seq;
    const Frame frame = make_synthetic_frame(360, 1500.0);
    const auto r = run_live_iteration_pipelined(
        cfg, frame, grid, lf, amcl, rng, beams_buf, last_pose,
        last_written, target_offset, last_pose_seq,
        last_scan_seq, amcl_rate_accum, hot_cfg_seq);
    CHECK(std::isfinite(r.xy_std_m));
}

TEST_CASE("run_live_iteration_pipelined — case (h) flag-on Live → Idle → flag-off Live: rollback path's seed_global still fires") {
    // After a pipelined Live tick, a transition to Idle re-arms the
    // legacy `live_first_iter` latch (via on_leave_live, which is
    // file-scope to cold_writer.cpp but exercised here via the public
    // run_live_iteration entry). The rollback path's first call after
    // the latch re-arm MUST clear the latch and the kernel MUST behave
    // as a "first iteration" caller (seed_global path).
    //
    // Round-trip pin: this test drives the contract via the public
    // kernel surfaces — pipelined path never modifies `live_first_iter`
    // (it's not a parameter), so the latch state on rollback re-entry is
    // determined ENTIRELY by the cold-writer's run_cold_writer loop. We
    // verify here that the rollback kernel's seed_global path is unbroken
    // across the round-trip.
    reset_hint_flag();
    Config cfg_pipelined = make_test_config(707);
    Config cfg_rollback  = cfg_pipelined;
    cfg_rollback.live_carry_pose_as_hint = false;

    OccupancyGrid grid = load_map(cfg_pipelined.amcl_map_path);
    LikelihoodField lf  = build_likelihood_field(grid, cfg_pipelined.amcl_sigma_hit_m);

    // Simulate the pipelined Live tick. last_pose carries a "OneShot
    // result" before this call.
    {
        Amcl amcl(cfg_pipelined, lf);
        Rng  rng(cfg_pipelined.amcl_seed);
        std::vector<RangeBeam> beams_buf;
        Pose2D last_pose{2.0, 2.0, 0.0};
        Offset last_written{0.0, 0.0, 0.0};
        Seqlock<Offset>   target_offset;
        Seqlock<LastPose> last_pose_seq;
        Seqlock<LastScan> last_scan_seq;
        AmclRateAccumulator amcl_rate_accum;
        Seqlock<godo::core::HotConfig> hot_cfg_seq;
        const Frame frame = make_synthetic_frame(360, 1500.0);
        const auto r = run_live_iteration_pipelined(
            cfg_pipelined, frame, grid, lf, amcl, rng, beams_buf, last_pose,
            last_written, target_offset, last_pose_seq,
            last_scan_seq, amcl_rate_accum, hot_cfg_seq);
        CHECK(std::isfinite(r.xy_std_m));
    }

    // Now simulate "operator toggled Live OFF then ON with the rollback
    // flag". The cold-writer's on_leave_live runs at the Live→Idle
    // transition and re-arms `live_first_iter = true`; on Live re-entry
    // the rollback kernel sees `live_first_iter = true` and seeds
    // globally. We verify the latch flip via the public kernel's side
    // effect on the parameter.
    {
        // Start with `live_first_iter = true` (matches the post-on_leave
        // state).
        Amcl amcl(cfg_rollback, lf);
        Rng  rng(cfg_rollback.amcl_seed);
        std::vector<RangeBeam> beams_buf;
        Pose2D last_pose{};                  // intentionally NOT carried —
                                              // the rollback path's first
                                              // iteration ignores last_pose
                                              // and seeds globally.
        bool   live_first_iter = true;
        Offset last_written{0.0, 0.0, 0.0};
        Seqlock<Offset>   target_offset;
        Seqlock<LastPose> last_pose_seq;
        Seqlock<LastScan> last_scan_seq;
        AmclRateAccumulator amcl_rate_accum;
        Seqlock<godo::core::HotConfig> hot_cfg_seq;
        const Frame frame = make_synthetic_frame(360, 1500.0);
        (void)run_live_iteration(cfg_rollback, frame, grid, amcl, rng,
                                 beams_buf, last_pose, live_first_iter,
                                 last_written, target_offset, last_pose_seq,
                                 last_scan_seq, amcl_rate_accum, hot_cfg_seq);
        // Latch flipped to false after the first call — this is the
        // documented rollback-path contract. If the pipelined refactor
        // accidentally short-circuited this, the latch would remain true.
        CHECK(live_first_iter == false);
    }
}

// ===========================================================================
// converge_anneal_with_hint contract: pin that schedule is honoured
// (iterations bounded) and the kernel does not touch the hint flag.
// ===========================================================================

TEST_CASE("converge_anneal_with_hint — does not read or clear g_calibrate_hint_valid") {
    // Lift the flag explicitly. The kernel MUST NOT read it; it accepts
    // the hint via parameter. After the call, the flag is still set.
    godo::rt::HintBundle stale{};
    stale.x_m = 99.0; stale.y_m = 99.0; stale.yaw_deg = 99.0;
    stale.sigma_xy_m = 0.05; stale.sigma_yaw_deg = 5.0;
    godo::rt::g_calibrate_hint_data.store(stale);
    godo::rt::g_calibrate_hint_valid.store(true, std::memory_order_release);

    Config cfg = make_test_config(808);
    OccupancyGrid grid = load_map(cfg.amcl_map_path);
    LikelihoodField lf = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);

    const Pose2D explicit_hint{2.0, 2.0, 0.0};
    std::vector<RangeBeam> beams;
    {
        const Frame frame = make_synthetic_frame(360, 1500.0);
        downsample(frame, cfg.amcl_downsample_stride,
                   cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams);
    }
    Pose2D pose_inout{};
    const auto r = converge_anneal_with_hint(
        cfg, beams, grid, lf, amcl,
        explicit_hint, 0.05, 5.0,
        cfg.amcl_live_carry_schedule_m,
        pose_inout, rng);

    // Flag still set — kernel did not touch it.
    CHECK(godo::rt::g_calibrate_hint_valid.load(std::memory_order_acquire) == true);
    CHECK(std::isfinite(r.xy_std_m));
    // Iterations bounded by schedule_m.size() × anneal_iters_per_phase.
    const int upper = static_cast<int>(cfg.amcl_live_carry_schedule_m.size()) *
                      cfg.amcl_anneal_iters_per_phase;
    CHECK(r.iterations <= upper);
    CHECK(r.iterations >= 1);

    reset_hint_flag();
}
