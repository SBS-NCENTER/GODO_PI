// issue#11 P4-2-11-6 — AMCL converge / Amcl::step wallclock benchmark.
//
// Per plan §6.4: records sequential vs parallel timing for Amcl::step at
// N=500 (steady-state Live) and N=5000 (first-tick OneShot global).
// Asserts a regression band — parallel must be ≥ 2× faster than
// sequential per step at N=500. Below → fail. Phase-0 numbers project
// ~3× speedup (94.85 ms → ~33 ms, 2.87×); the 2× floor is conservative
// against dev-host CPU isolation (CI runners often have all 4 cores
// shared; production Pi 5 has CPU 3 isolcpus'd so the speedup is
// closer to 3×).
//
// Hardware-free; uses the synthetic 4×4 fixture map. The benchmark is
// labelled "hardware-free" so it runs in CI (it's a regression band,
// not a tuning loop).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "core/config.hpp"
#include "core/time.hpp"
#include "lidar/sample.hpp"
#include "localization/amcl.hpp"
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
using godo::localization::build_likelihood_field;
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

Config make_test_config(int particles_local_n) {
    Config c = Config::make_default();
    c.amcl_seed = 42;
    c.amcl_particles_local_n = particles_local_n;
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

struct BenchResult {
    std::int64_t p50_ns = 0;
    std::int64_t p99_ns = 0;
    std::int64_t mean_ns = 0;
    std::size_t  iters = 0;
};

BenchResult time_steps(Amcl& amcl, std::vector<RangeBeam>& beams, Rng& rng,
                       std::size_t n_iters) {
    std::vector<std::int64_t> samples;
    samples.reserve(n_iters);
    for (std::size_t i = 0; i < n_iters; ++i) {
        const std::int64_t t0 = godo::rt::monotonic_ns();
        (void)amcl.step(beams, rng);
        samples.push_back(godo::rt::monotonic_ns() - t0);
    }
    std::sort(samples.begin(), samples.end());
    BenchResult r;
    r.iters = samples.size();
    r.p50_ns = samples[samples.size() / 2];
    r.p99_ns = samples[(samples.size() * 99) / 100];
    std::int64_t sum = 0;
    for (auto v : samples) sum += v;
    r.mean_ns = sum / static_cast<std::int64_t>(samples.size());
    return r;
}

}  // namespace

TEST_CASE("bench_amcl_converge — Amcl::step at N=500 parallel ≥ 2× faster than sequential") {
    constexpr int kN     = 500;
    constexpr std::size_t kIters = 100;

    const Config        cfg  = make_test_config(kN);
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    std::vector<RangeBeam> beams_seq;
    std::vector<RangeBeam> beams_par;
    const Frame frame = make_synthetic_frame();
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams_seq);
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams_par);

    // Sequential.
    Amcl amcl_seq(cfg, lf, nullptr);
    Rng  rng_a(7777);
    amcl_seq.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.05, 5.0, rng_a);
    // Warm-up — first call may include cache fill etc.
    (void)amcl_seq.step(beams_seq, rng_a);
    const BenchResult seq = time_steps(amcl_seq, beams_seq, rng_a, kIters);

    // Parallel.
    ParallelEvalPool pool({0, 1, 2});
    Amcl amcl_par(cfg, lf, &pool);
    Rng  rng_b(7777);
    amcl_par.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.05, 5.0, rng_b);
    (void)amcl_par.step(beams_par, rng_b);
    const BenchResult par = time_steps(amcl_par, beams_par, rng_b, kIters);

    // Print to stdout so the operator can read the numbers in CI logs.
    std::printf("[bench_amcl_converge N=500 iters=%zu]\n", kIters);
    std::printf("  sequential: p50=%lld ns p99=%lld ns mean=%lld ns\n",
                static_cast<long long>(seq.p50_ns),
                static_cast<long long>(seq.p99_ns),
                static_cast<long long>(seq.mean_ns));
    std::printf("  parallel:   p50=%lld ns p99=%lld ns mean=%lld ns\n",
                static_cast<long long>(par.p50_ns),
                static_cast<long long>(par.p99_ns),
                static_cast<long long>(par.mean_ns));
    const double speedup =
        static_cast<double>(seq.p50_ns) / static_cast<double>(par.p50_ns);
    std::printf("  speedup p50: %.2fx (target ≥ 2.0x; ~3.0x expected)\n",
                speedup);

    // Regression band: parallel must be ≥ 2× faster than sequential at
    // p50. Phase-0 projects ~3× speedup; failure here likely means
    // workers were oversubscribed on the test host (other build jobs
    // hot on cores 0/1/2) OR a regression in the pool partitioning.
    CHECK_MESSAGE(par.p50_ns * 2 <= seq.p50_ns,
        "AMCL parallel step at N=500 is < 2x faster than sequential — "
        "Phase-0 expected ~3x. Investigate pool partitioning, cache "
        "topology, or test-host CPU oversubscription.");
}

TEST_CASE("bench_amcl_converge — Amcl::step at N=5000 (first-tick OneShot) parallel ≥ 1.5× sequential") {
    // First-tick OneShot uses N=5000 (global cloud). Speedup expectation
    // is slightly lower because the work-per-particle is the same but
    // the partition + dispatch overhead is amortised over more particles
    // — Phase-0 projects ~3.05× (580 ms / 190 ms). The 1.5× floor is
    // conservative for dev hosts.
    constexpr int kN     = 5000;
    constexpr std::size_t kIters = 20;  // fewer iters because each is ~50 ms

    const Config        cfg  = make_test_config(kN);
    const OccupancyGrid grid = load_fixture();
    const LikelihoodField lf =
        build_likelihood_field(grid, cfg.amcl_sigma_hit_m);

    std::vector<RangeBeam> beams_seq;
    std::vector<RangeBeam> beams_par;
    const Frame frame = make_synthetic_frame();
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams_seq);
    downsample(frame, cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m, cfg.amcl_range_max_m, beams_par);

    Amcl amcl_seq(cfg, lf, nullptr);
    Rng  rng_a(123);
    amcl_seq.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.20, 10.0, rng_a);
    (void)amcl_seq.step(beams_seq, rng_a);
    const BenchResult seq = time_steps(amcl_seq, beams_seq, rng_a, kIters);

    ParallelEvalPool pool({0, 1, 2});
    Amcl amcl_par(cfg, lf, &pool);
    Rng  rng_b(123);
    amcl_par.seed_around(Pose2D{0.5, 0.5, 30.0}, 0.20, 10.0, rng_b);
    (void)amcl_par.step(beams_par, rng_b);
    const BenchResult par = time_steps(amcl_par, beams_par, rng_b, kIters);

    std::printf("[bench_amcl_converge N=5000 iters=%zu]\n", kIters);
    std::printf("  sequential: p50=%lld ns p99=%lld ns mean=%lld ns\n",
                static_cast<long long>(seq.p50_ns),
                static_cast<long long>(seq.p99_ns),
                static_cast<long long>(seq.mean_ns));
    std::printf("  parallel:   p50=%lld ns p99=%lld ns mean=%lld ns\n",
                static_cast<long long>(par.p50_ns),
                static_cast<long long>(par.p99_ns),
                static_cast<long long>(par.mean_ns));
    const double speedup =
        static_cast<double>(seq.p50_ns) / static_cast<double>(par.p50_ns);
    std::printf("  speedup p50: %.2fx (target ≥ 1.5x; ~3.0x expected)\n",
                speedup);

    CHECK_MESSAGE(par.p50_ns * 3 <= seq.p50_ns * 2,
        "AMCL parallel step at N=5000 is < 1.5x faster than sequential — "
        "Phase-0 expected ~3x. Investigate pool / partition / "
        "test-host CPU oversubscription.");
}
