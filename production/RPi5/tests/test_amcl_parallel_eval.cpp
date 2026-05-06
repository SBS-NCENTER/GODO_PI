// issue#11 P4-2-11-2 / P4-2-11-6 — AMCL × ParallelEvalPool integration tests.
//
// Per plan §6.2 — 4 cases:
//   1. Bit-equal step output, parallel vs sequential, same RNG seed.
//      RNG capture pattern: deep-copy a single seeded Rng for each
//      branch; weighted_mean's sequential summation guarantees identical
//      pose output (plan §3.6 proof).
//   2. Live carry path — converge_anneal_with_hint output equivalence.
//   3. OneShot anneal — converge_anneal output equivalence.
//   4. Pool null-safety — Amcl(cfg, lf, nullptr).step() continues to
//      work with the same fixture shape (no regression in sequential
//      path).
//
// Hardware-free; uses the synthetic 4×4 fixture map shared with
// test_phase0_env / test_amcl_components.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdint>
#include <cstring>
#include <vector>

#include "core/config.hpp"
#include "core/rt_types.hpp"
#include "lidar/sample.hpp"
#include "localization/amcl.hpp"
#include "localization/cold_writer.hpp"
#include "localization/likelihood_field.hpp"
#include "localization/occupancy_grid.hpp"
#include "localization/pose.hpp"
#include "localization/rng.hpp"
#include "localization/scan_ops.hpp"
#include "parallel/parallel_eval_pool.hpp"

#ifndef GODO_FIXTURES_MAPS_DIR
#error "GODO_FIXTURES_MAPS_DIR must be set by CMake"
#endif

using godo::core::Config;
using godo::lidar::Frame;
using godo::lidar::Sample;
using godo::localization::Amcl;
using godo::localization::AmclResult;
using godo::localization::build_likelihood_field;
using godo::localization::converge_anneal;
using godo::localization::converge_anneal_with_hint;
using godo::localization::downsample;
using godo::localization::LikelihoodField;
using godo::localization::load_map;
using godo::localization::OccupancyGrid;
using godo::localization::Pose2D;
using godo::localization::RangeBeam;
using godo::localization::Rng;
using godo::parallel::ParallelEvalPool;

namespace {

OccupancyGrid load_fixture() {
    return load_map(std::string(GODO_FIXTURES_MAPS_DIR) +
                    "/synthetic_4x4.pgm");
}

Config make_test_config() {
    Config c = Config::make_default();
    c.amcl_seed = 42;
    return c;
}

Frame make_synthetic_frame() {
    Frame f{};
    f.samples.reserve(360);
    for (int i = 0; i < 360; ++i) {
        Sample s{};
        s.angle_deg   = static_cast<double>(i);
        s.distance_mm = 1500.0;
        s.quality     = 50;
        f.samples.push_back(s);
    }
    return f;
}

bool bit_equal_double(double a, double b) noexcept {
    std::uint64_t ua, ub;
    std::memcpy(&ua, &a, sizeof(double));
    std::memcpy(&ub, &b, sizeof(double));
    return ua == ub;
}

}  // namespace

TEST_CASE("Case 1: bit-equal Amcl::step output — parallel vs sequential, same RNG seed") {
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    std::vector<RangeBeam> beams;
    const Frame frame = make_synthetic_frame();
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams);

    // RNG capture pattern: seed once, deep-copy for each side. The
    // implicit copy ctor on godo::localization::Rng captures
    // mt19937_64's full internal state, so the two branches consume
    // identical draws.
    const Rng rng_seed(7777);

    // Sequential branch.
    Amcl amcl_seq(cfg, lf, nullptr);
    Rng  rng_a = rng_seed;
    amcl_seq.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.05, 5.0, rng_a);
    const AmclResult res_seq = amcl_seq.step(beams, rng_a);

    // Parallel branch — same fixture, identical RNG state.
    ParallelEvalPool pool({0, 1, 2});
    Amcl  amcl_par(cfg, lf, &pool);
    Rng   rng_b = rng_seed;
    amcl_par.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.05, 5.0, rng_b);
    const AmclResult res_par = amcl_par.step(beams, rng_b);

    // Bit-equal pose — strongest possible threshold (plan §3.6 / §6.3).
    CHECK(bit_equal_double(res_seq.pose.x,        res_par.pose.x));
    CHECK(bit_equal_double(res_seq.pose.y,        res_par.pose.y));
    CHECK(bit_equal_double(res_seq.pose.yaw_deg,  res_par.pose.yaw_deg));
    CHECK(bit_equal_double(res_seq.xy_std_m,      res_par.xy_std_m));
    CHECK(bit_equal_double(res_seq.yaw_std_deg,   res_par.yaw_std_deg));
}

TEST_CASE("Case 2: Live carry path — converge_anneal_with_hint, parallel vs sequential within tolerance") {
    Config cfg = make_test_config();
    // Use the live-carry schedule for a Live-flavour anneal.
    cfg.amcl_live_carry_schedule_m = std::vector<double>{0.2, 0.1, 0.05};

    const OccupancyGrid grid = load_fixture();
    LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    std::vector<RangeBeam> beams;
    const Frame frame = make_synthetic_frame();
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams);

    const Pose2D hint{0.5, 0.5, 30.0};
    const Rng    rng_seed(1234);

    // Sequential
    Amcl amcl_seq(cfg, lf, nullptr);
    Rng  rng_a = rng_seed;
    Pose2D pose_seq = hint;
    LikelihoodField lf_seq =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl_seq2(cfg, lf_seq, nullptr);
    const AmclResult res_seq = converge_anneal_with_hint(
        cfg, beams, grid, lf_seq, amcl_seq2, hint,
        cfg.amcl_live_carry_sigma_xy_m,
        cfg.amcl_live_carry_sigma_yaw_deg,
        cfg.amcl_live_carry_schedule_m, pose_seq, rng_a);

    // Parallel
    ParallelEvalPool pool({0, 1, 2});
    Rng  rng_b = rng_seed;
    Pose2D pose_par = hint;
    LikelihoodField lf_par =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl_par(cfg, lf_par, &pool);
    const AmclResult res_par = converge_anneal_with_hint(
        cfg, beams, grid, lf_par, amcl_par, hint,
        cfg.amcl_live_carry_sigma_xy_m,
        cfg.amcl_live_carry_sigma_yaw_deg,
        cfg.amcl_live_carry_schedule_m, pose_par, rng_b);

    // Tight tolerance — plan §6.2 case 2 allows tiny FP reordering at the
    // wider call-site level (1e-9 m / 1e-9°). Bit-equality is preserved
    // for `evaluate_scan` per case 1; this case checks the kernel-level
    // composition tolerates the same RNG path.
    CHECK(std::abs(res_seq.pose.x - res_par.pose.x) < 1e-9);
    CHECK(std::abs(res_seq.pose.y - res_par.pose.y) < 1e-9);
    CHECK(std::abs(res_seq.pose.yaw_deg - res_par.pose.yaw_deg) < 1e-9);
    CHECK(res_seq.iterations == res_par.iterations);
}

TEST_CASE("Case 3: OneShot converge_anneal — parallel vs sequential within tolerance") {
    Config cfg = make_test_config();

    const OccupancyGrid grid = load_fixture();

    std::vector<RangeBeam> beams;
    const Frame frame = make_synthetic_frame();
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams);

    const Rng rng_seed(99);

    // Sequential.
    LikelihoodField lf_seq =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl_seq(cfg, lf_seq, nullptr);
    Rng  rng_a = rng_seed;
    Pose2D pose_seq{};
    const AmclResult res_seq = converge_anneal(
        cfg, beams, grid, lf_seq, amcl_seq, pose_seq, rng_a);

    // Parallel.
    ParallelEvalPool pool({0, 1, 2});
    LikelihoodField lf_par =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    Amcl amcl_par(cfg, lf_par, &pool);
    Rng  rng_b = rng_seed;
    Pose2D pose_par{};
    const AmclResult res_par = converge_anneal(
        cfg, beams, grid, lf_par, amcl_par, pose_par, rng_b);

    CHECK(std::abs(res_seq.pose.x - res_par.pose.x) < 1e-9);
    CHECK(std::abs(res_seq.pose.y - res_par.pose.y) < 1e-9);
    CHECK(std::abs(res_seq.pose.yaw_deg - res_par.pose.yaw_deg) < 1e-9);
    CHECK(res_seq.iterations == res_par.iterations);
}

TEST_CASE("Case 4: Pool null-safety — Amcl(cfg, lf, nullptr).step continues to work") {
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    Amcl amcl(cfg, lf, nullptr);
    Rng  rng(cfg.amcl_seed);
    amcl.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.05, 5.0, rng);

    std::vector<RangeBeam> beams;
    const Frame frame = make_synthetic_frame();
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams);

    const AmclResult res = amcl.step(beams, rng);
    CHECK(res.iterations == 1);
    CHECK(std::isfinite(res.xy_std_m));
    CHECK(std::isfinite(res.yaw_std_deg));
}

TEST_CASE("Case 5 (bonus): Pool empty cpus path is bit-equal to nullptr path") {
    // Plan §6.1 case 5 says workers=1 fallback runs fn on caller thread.
    // Combined with case 1's bit-equality proof, an Amcl wired to an
    // empty-cpus pool must produce IDENTICAL output to a nullptr-pool
    // Amcl on the same RNG seed. This pins the rollback path semantics.
    const Config        cfg  = make_test_config();
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    std::vector<RangeBeam> beams;
    const Frame frame = make_synthetic_frame();
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams);

    const Rng rng_seed(54321);

    Amcl amcl_null(cfg, lf, nullptr);
    Rng  rng_a = rng_seed;
    amcl_null.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.05, 5.0, rng_a);
    const AmclResult res_null = amcl_null.step(beams, rng_a);

    ParallelEvalPool empty_pool({});
    Amcl amcl_empty(cfg, lf, &empty_pool);
    Rng  rng_b = rng_seed;
    amcl_empty.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.05, 5.0, rng_b);
    const AmclResult res_empty = amcl_empty.step(beams, rng_b);

    CHECK(bit_equal_double(res_null.pose.x,        res_empty.pose.x));
    CHECK(bit_equal_double(res_null.pose.y,        res_empty.pose.y));
    CHECK(bit_equal_double(res_null.pose.yaw_deg,  res_empty.pose.yaw_deg));
}
