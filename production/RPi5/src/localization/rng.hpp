#pragma once

// Deterministic-or-time-seeded RNG used by the AMCL pipeline.
//
// seed = 0  → time-derived, non-deterministic (production behaviour).
// seed != 0 → deterministic across runs (test fixtures / replays).
//
// std::mt19937_64 is fine here: AMCL needs ~PARTICLE_BUFFER_MAX×iters draws
// per cold-write, well within mt19937_64's period. xorshift would be marginal
// faster but lose statistical guarantees against the chi-square fixture.

#include <cstdint>
#include <random>

namespace godo::localization {

class Rng {
public:
    explicit Rng(std::uint64_t seed);

    // Uniform in [0, 1).
    double uniform() noexcept;

    // Gaussian with given mean / stddev. stddev must be > 0; the AMCL
    // pipeline never draws from a degenerate distribution (the σ defaults
    // are all > 0 and validated by Config).
    double gauss(double mean, double stddev) noexcept;

    // Integer in [0, n) for a non-zero n. Used by the resampler bootstrap.
    std::size_t uniform_index(std::size_t n) noexcept;

private:
    std::mt19937_64                        engine_;
    std::uniform_real_distribution<double> u01_{0.0, 1.0};
    std::normal_distribution<double>       n01_{0.0, 1.0};
};

}  // namespace godo::localization
