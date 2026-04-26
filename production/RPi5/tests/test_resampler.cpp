// Phase 4-2 B Wave 1 — low-variance resampler + capacity invariant.
//
// S3 trade-off pinned in the plan: the capacity invariant is a proxy for
// "no realloc"; absolute "no `new`" would require overriding operator new,
// which is over-engineering for this scope. The invariant we DO assert:
// `particles_out.capacity()` is unchanged after every resample() call,
// given a sufficiently pre-sized output vector.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstddef>
#include <limits>
#include <stdexcept>
#include <vector>

#include "localization/pose.hpp"
#include "localization/rng.hpp"
#include "localization/scan_ops.hpp"

using godo::localization::Particle;
using godo::localization::Pose2D;
using godo::localization::Rng;
using godo::localization::resample;

namespace {

Particle make_p(double x, double y, double yaw_deg, double w) {
    return Particle{Pose2D{x, y, yaw_deg}, w};
}

}  // namespace

TEST_CASE("resample — uniform weights: every output is drawn from the input set, "
          "weights normalised, and at least 3 distinct inputs survive (S9)") {
    // Note: the low-variance / systematic resampler does NOT guarantee a
    // permutation under uniform weights — duplicates are possible when the
    // single uniform draw lands near a CDF boundary. We assert (a) every
    // output is from the input set, (b) all weights are 1/n, (c) at least
    // 3 of the 4 input X values appear in the output (proves we are not
    // collapsing to a single particle).
    Rng rng(42);
    std::vector<Particle> in = {
        make_p(0.0, 0.0, 0.0, 1.0),
        make_p(1.0, 0.0, 0.0, 1.0),
        make_p(2.0, 0.0, 0.0, 1.0),
        make_p(3.0, 0.0, 0.0, 1.0),
    };
    std::vector<Particle> out(4);
    std::vector<double>   scratch(4);

    const std::size_t n = resample(in.data(), in.size(),
                                   out.data(), out.size(),
                                   scratch.data(), scratch.size(),
                                   rng);
    CHECK(n == 4u);
    // (b) All output weights are 1/n.
    for (auto& p : out) CHECK(p.weight == doctest::Approx(0.25));
    // (a) Each output particle's pose.x is one of the input X values.
    bool seen[4] = {false, false, false, false};
    for (auto& p : out) {
        const int xi = static_cast<int>(p.pose.x);
        CHECK(xi >= 0);
        CHECK(xi <= 3);
        seen[xi] = true;
    }
    // (c) At least 3 distinct inputs survive — guards against silent
    // collapse to a single particle.
    int distinct = 0;
    for (bool b : seen) if (b) ++distinct;
    CHECK(distinct >= 3);
}

TEST_CASE("resample — heavy-weighted particle is favoured") {
    // One particle at x=10 with weight 99, others negligible.
    Rng rng(123);
    std::vector<Particle> in = {
        make_p( 0.0, 0.0, 0.0, 0.001),
        make_p( 5.0, 0.0, 0.0, 0.001),
        make_p(10.0, 0.0, 0.0, 99.0),
        make_p(15.0, 0.0, 0.0, 0.001),
    };
    std::vector<Particle> out(4);
    std::vector<double>   scratch(4);
    resample(in.data(), in.size(),
             out.data(), out.size(),
             scratch.data(), scratch.size(),
             rng);
    int hits_at_10 = 0;
    for (auto& p : out) if (p.pose.x == 10.0) ++hits_at_10;
    // Almost certainly all 4 since weight ratio is ~33000:1.
    CHECK(hits_at_10 >= 3);
}

TEST_CASE("resample — output capacity invariant: no growth across calls") {
    // Pre-size output to a known capacity. After resample(), capacity must
    // be unchanged — proxy for "no realloc happened inside the call".
    Rng rng(1);
    constexpr std::size_t N = 100;
    std::vector<Particle> in;
    in.reserve(N);
    for (std::size_t i = 0; i < N; ++i) {
        in.push_back(make_p(static_cast<double>(i), 0.0, 0.0, 1.0));
    }
    std::vector<Particle> out;
    out.reserve(N);
    out.resize(N);
    const std::size_t cap_before = out.capacity();
    REQUIRE(cap_before >= N);

    std::vector<double> scratch;
    scratch.reserve(N);
    scratch.resize(N);
    const std::size_t scratch_cap_before = scratch.capacity();
    REQUIRE(scratch_cap_before >= N);

    for (int run = 0; run < 5; ++run) {
        resample(in.data(), in.size(),
                 out.data(), out.size(),
                 scratch.data(), scratch.size(),
                 rng);
        CHECK(out.capacity()     == cap_before);
        CHECK(scratch.capacity() == scratch_cap_before);
    }
}

TEST_CASE("resample — out_capacity < n is rejected") {
    Rng rng(7);
    std::vector<Particle> in = { make_p(0, 0, 0, 1.0), make_p(1, 0, 0, 1.0) };
    std::vector<Particle> out(1);
    std::vector<double>   scratch(2);
    CHECK_THROWS_AS(
        resample(in.data(), in.size(),
                 out.data(), out.size(),
                 scratch.data(), scratch.size(),
                 rng),
        std::invalid_argument);
}

TEST_CASE("resample — cumsum_capacity < n is rejected") {
    Rng rng(7);
    std::vector<Particle> in = { make_p(0, 0, 0, 1.0), make_p(1, 0, 0, 1.0) };
    std::vector<Particle> out(2);
    std::vector<double>   scratch(1);
    CHECK_THROWS_AS(
        resample(in.data(), in.size(),
                 out.data(), out.size(),
                 scratch.data(), scratch.size(),
                 rng),
        std::invalid_argument);
}

TEST_CASE("resample — zero-sum weights rejected") {
    Rng rng(7);
    std::vector<Particle> in = { make_p(0, 0, 0, 0.0), make_p(1, 0, 0, 0.0) };
    std::vector<Particle> out(2);
    std::vector<double>   scratch(2);
    CHECK_THROWS_AS(
        resample(in.data(), in.size(),
                 out.data(), out.size(),
                 scratch.data(), scratch.size(),
                 rng),
        std::invalid_argument);
}

TEST_CASE("resample — negative or NaN input weight rejected") {
    Rng rng(7);
    {
        std::vector<Particle> in = { make_p(0, 0, 0, -0.1), make_p(1, 0, 0, 1.0) };
        std::vector<Particle> out(2);
        std::vector<double>   scratch(2);
        CHECK_THROWS_AS(
            resample(in.data(), in.size(),
                     out.data(), out.size(),
                     scratch.data(), scratch.size(),
                     rng),
            std::invalid_argument);
    }
    {
        const double nan_v = std::numeric_limits<double>::quiet_NaN();
        std::vector<Particle> in = { make_p(0, 0, 0, nan_v), make_p(1, 0, 0, 1.0) };
        std::vector<Particle> out(2);
        std::vector<double>   scratch(2);
        CHECK_THROWS_AS(
            resample(in.data(), in.size(),
                     out.data(), out.size(),
                     scratch.data(), scratch.size(),
                     rng),
            std::invalid_argument);
    }
}

TEST_CASE("resample — empty input returns 0 entries written") {
    Rng rng(7);
    Particle dummy{};
    double   scratch = 0.0;
    const std::size_t n = resample(&dummy, 0, &dummy, 1, &scratch, 1, rng);
    CHECK(n == 0u);
}
