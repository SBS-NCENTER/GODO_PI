// issue#19 — `build_likelihood_field` × ParallelEvalPool integration tests.
//
// Per plan §6 + Mode-A fold n6 / n8. Bias-blocking pin: FNV-1a memcmp
// between sequential (`pool == nullptr`) and parallel (`pool == &p3`)
// outputs at three grid sizes (16×16, 256×256, 1000×1000). Brute-force
// EDT reference for case (1) reuses the existing fixture in
// `tests/test_likelihood_field.cpp` — n6 verified that
// `brute_force_sq_dist` already lives there; we re-derive it locally
// (small) so this TU stays self-contained.
//
// Hardware-free; runs in CI.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <random>
#include <thread>
#include <utility>
#include <vector>

#include "localization/likelihood_field.hpp"
#include "localization/occupancy_grid.hpp"
#include "parallel/parallel_eval_pool.hpp"

using godo::localization::build_likelihood_field;
using godo::localization::LikelihoodField;
using godo::localization::OccupancyGrid;
using godo::parallel::ParallelEvalPool;

namespace {

// FNV-1a 64-bit hash of a contiguous byte buffer. Plan §6 case 4 pin.
std::uint64_t fnv1a(const void* data, std::size_t nbytes) {
    std::uint64_t h = 14695981039346656037ULL;
    const auto* p = static_cast<const std::uint8_t*>(data);
    for (std::size_t i = 0; i < nbytes; ++i) {
        h ^= static_cast<std::uint64_t>(p[i]);
        h *= 1099511628211ULL;
    }
    return h;
}

// Synthesise a deterministic OccupancyGrid with a few obstacles. Seed
// fixed so cases are reproducible across CI hosts.
OccupancyGrid make_grid(int W, int H, std::uint64_t seed,
                        double resolution_m = 0.05) {
    OccupancyGrid g{};
    g.width        = W;
    g.height       = H;
    g.resolution_m = resolution_m;
    g.origin_x_m   = 0.0;
    g.origin_y_m   = 0.0;
    const std::size_t N = static_cast<std::size_t>(W) *
                          static_cast<std::size_t>(H);
    g.cells.assign(N, 255);  // all free initially
    std::mt19937_64 rng(seed);
    // Drop ~1% of cells as obstacles; keep them deterministic.
    const std::size_t n_obs = std::max<std::size_t>(8, N / 100);
    std::uniform_int_distribution<std::size_t> dist(0, N - 1);
    for (std::size_t i = 0; i < n_obs; ++i) {
        g.cells[dist(rng)] = 0;
    }
    return g;
}

// Brute-force squared cell-distance EDT (O(W²H²)). Used by case (1)
// against the smallest grid only — n6 fold (the regression net).
std::vector<float> brute_force_sq_dist(const OccupancyGrid& g) {
    const int W = g.width;
    const int H = g.height;
    const std::size_t N = static_cast<std::size_t>(W) *
                          static_cast<std::size_t>(H);
    std::vector<float> out(N, std::numeric_limits<float>::infinity());
    std::vector<std::pair<int, int>> obs;
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            if (g.cells[static_cast<std::size_t>(y) *
                        static_cast<std::size_t>(W) +
                        static_cast<std::size_t>(x)] < 100) {
                obs.emplace_back(x, y);
            }
        }
    }
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            float best = std::numeric_limits<float>::infinity();
            for (const auto& o : obs) {
                const float dx = static_cast<float>(x - o.first);
                const float dy = static_cast<float>(y - o.second);
                const float d2 = dx * dx + dy * dy;
                if (d2 < best) best = d2;
            }
            out[static_cast<std::size_t>(y) *
                static_cast<std::size_t>(W) +
                static_cast<std::size_t>(x)] = best;
        }
    }
    return out;
}

float field_to_sq_cells(float v, double sigma_hit_m, double res_m) {
    if (v >= 1.0f) return 0.0f;
    const double d_m_sq = -2.0 * sigma_hit_m * sigma_hit_m * std::log(v);
    const double d_cell_sq = d_m_sq / (res_m * res_m);
    return static_cast<float>(d_cell_sq);
}

constexpr double kSigma = 0.20;

}  // namespace

TEST_CASE("issue#19 (1): nullptr path matches brute-force EDT (regression)") {
    // n6 fold — the smallest grid uses brute-force as the third witness.
    OccupancyGrid g = make_grid(16, 16, 0xC0FFEE);
    LikelihoodField lf = build_likelihood_field(g, kSigma, nullptr);
    const auto bf = brute_force_sq_dist(g);

    REQUIRE(lf.values.size() == bf.size());
    for (std::size_t i = 0; i < bf.size(); ++i) {
        const float reconstructed =
            field_to_sq_cells(lf.values[i], kSigma, g.resolution_m);
        if (bf[i] < 50.0f) {
            CHECK(reconstructed == doctest::Approx(bf[i]).epsilon(0.01));
        }
    }
}

TEST_CASE("issue#19 (2): 16x16 grid — parallel == sequential bit-for-bit (FNV-1a memcmp)") {
    OccupancyGrid g = make_grid(16, 16, 0xC0FFEE);

    LikelihoodField seq = build_likelihood_field(g, kSigma, nullptr);

    ParallelEvalPool pool({0, 1, 2});
    LikelihoodField par = build_likelihood_field(g, kSigma, &pool);

    REQUIRE(seq.values.size() == par.values.size());
    const std::size_t nb = seq.values.size() * sizeof(float);
    CHECK(std::memcmp(seq.values.data(), par.values.data(), nb) == 0);
    CHECK(fnv1a(seq.values.data(), nb) == fnv1a(par.values.data(), nb));
}

TEST_CASE("issue#19 (3): 256x256 grid — parallel == sequential bit-for-bit") {
    OccupancyGrid g = make_grid(256, 256, 0xBEEF);

    LikelihoodField seq = build_likelihood_field(g, kSigma, nullptr);

    ParallelEvalPool pool({0, 1, 2});
    LikelihoodField par = build_likelihood_field(g, kSigma, &pool);

    REQUIRE(seq.values.size() == par.values.size());
    const std::size_t nb = seq.values.size() * sizeof(float);
    CHECK(std::memcmp(seq.values.data(), par.values.data(), nb) == 0);
    CHECK(fnv1a(seq.values.data(), nb) == fnv1a(par.values.data(), nb));
}

TEST_CASE("issue#19 (4): 1000x1000 grid (1M cells) — parallel == sequential bit-for-bit") {
    // Production scale. The pin that closes the bias-blocking question
    // for the production hot path.
    OccupancyGrid g = make_grid(1000, 1000, 0xF00DCAFE);

    LikelihoodField seq = build_likelihood_field(g, kSigma, nullptr);

    ParallelEvalPool pool({0, 1, 2});
    LikelihoodField par = build_likelihood_field(g, kSigma, &pool);

    REQUIRE(seq.values.size() == par.values.size());
    const std::size_t nb = seq.values.size() * sizeof(float);
    CHECK(std::memcmp(seq.values.data(), par.values.data(), nb) == 0);
    CHECK(fnv1a(seq.values.data(), nb) == fnv1a(par.values.data(), nb));
}

TEST_CASE("issue#19 (5): degraded pool — output bit-equal to sequential (graceful fallback)") {
    // Drive the pool into permanent-degraded mode via 3 consecutive
    // 100 ms-fn-vs-1 ms-deadline overruns (issue#37 K=3 gate; mirrors
    // test_parallel_eval_pool case 6 / 19d). Then build_likelihood_field
    // with the now-degraded pool must still produce a bit-equal result
    // by short-circuiting to the sequential path
    // (`use_parallel = !pool->degraded()`).
    ParallelEvalPool pool({0, 1, 2});
    REQUIRE_FALSE(pool.degraded());

    struct Scratch { int x{0}; };
    std::vector<Scratch> per_worker(3);
    auto slow_fn = [](std::size_t, Scratch&) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    };
    // 3 consecutive overruns to trip K=3 gate.
    for (int i = 0; i < 3; ++i) {
        const bool ok = pool.parallel_for_with_scratch<Scratch>(
            0, 16, per_worker, slow_fn, 1'000'000LL);
        CHECK_FALSE(ok);
    }
    REQUIRE(pool.degraded());

    OccupancyGrid g = make_grid(64, 64, 0xDEAD);
    LikelihoodField seq = build_likelihood_field(g, kSigma, nullptr);
    LikelihoodField par = build_likelihood_field(g, kSigma, &pool);

    const std::size_t nb = seq.values.size() * sizeof(float);
    CHECK(std::memcmp(seq.values.data(), par.values.data(), nb) == 0);
    CHECK(fnv1a(seq.values.data(), nb) == fnv1a(par.values.data(), nb));
}

TEST_CASE("issue#19 (6): workers=0 (empty cpus) path bit-equal to nullptr path") {
    // Plan §"CODEBASE.md / SYSTEM_DESIGN.md cascade": the rollback lever
    // (TOML amcl.parallel_eval_workers = 1) maps int=1 → cpus_to_pin=={}.
    // Empty pool ⇒ `parallel_for_with_scratch` runs fn inline on caller
    // ⇒ bit-equal to the nullptr (sequential) path. This pins the D5
    // single-rollback-lever claim deterministically.
    OccupancyGrid g = make_grid(128, 128, 0x12345);

    LikelihoodField via_null  = build_likelihood_field(g, kSigma, nullptr);

    ParallelEvalPool empty_pool({});
    LikelihoodField via_empty = build_likelihood_field(g, kSigma, &empty_pool);

    const std::size_t nb = via_null.values.size() * sizeof(float);
    CHECK(std::memcmp(via_null.values.data(), via_empty.values.data(), nb)
          == 0);
}
