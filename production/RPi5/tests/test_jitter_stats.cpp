// PR-DIAG — jitter_stats percentile + summary correctness.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <array>
#include <cstdint>

#include "core/rt_types.hpp"
#include "rt/jitter_stats.hpp"

using godo::rt::compute_percentile;
using godo::rt::compute_summary;
using godo::rt::JitterSnapshot;

TEST_CASE("compute_percentile — p50 of odd-length sorted data picks the middle") {
    std::array<std::int64_t, 5> v{1, 2, 3, 4, 5};
    CHECK(compute_percentile(v.data(), v.size(), 0.5) == 3);
}

TEST_CASE("compute_percentile — p50 of even-length data uses lower-quantile") {
    // p50 of [1,2,3,4] with index = floor(0.5 × 3) = 1 → value 2.
    std::array<std::int64_t, 4> v{1, 2, 3, 4};
    CHECK(compute_percentile(v.data(), v.size(), 0.5) == 2);
}

TEST_CASE("compute_percentile — p99 of single-sample input returns that sample") {
    std::array<std::int64_t, 1> v{42};
    CHECK(compute_percentile(v.data(), v.size(), 0.99) == 42);
}

TEST_CASE("compute_percentile — empty input returns 0") {
    CHECK(compute_percentile(nullptr, 0, 0.5) == 0);
}

TEST_CASE("compute_summary — empty input yields valid=0 + zeros") {
    JitterSnapshot snap{};
    snap.valid = 1;  // pre-fill to detect that the function clears it
    compute_summary(nullptr, 0, snap);
    CHECK(snap.valid == 0);
    CHECK(snap.p50_ns == 0);
    CHECK(snap.p95_ns == 0);
    CHECK(snap.p99_ns == 0);
    CHECK(snap.max_ns == 0);
    CHECK(snap.mean_ns == 0);
    CHECK(snap.sample_count == 0u);
}

TEST_CASE("compute_summary — content correctness on shaped input") {
    // Mode-A TB2 fold: feeding [1, 100, 1000] → p50=100 (the median).
    std::array<std::int64_t, 3> v{1, 100, 1000};
    JitterSnapshot snap{};
    compute_summary(v.data(), v.size(), snap);
    CHECK(snap.valid == 1);
    CHECK(snap.p50_ns == 100);
    CHECK(snap.max_ns == 1000);
    CHECK(snap.mean_ns == (1 + 100 + 1000) / 3);
    CHECK(snap.sample_count == 3u);
}

TEST_CASE("compute_summary — sorts in place; mean correctness over [1..5]") {
    std::array<std::int64_t, 5> v{5, 1, 4, 2, 3};
    JitterSnapshot snap{};
    compute_summary(v.data(), v.size(), snap);
    CHECK(snap.valid == 1);
    CHECK(snap.mean_ns == 3);
    CHECK(snap.max_ns == 5);
    // After in-place sort, v is ascending.
    for (std::size_t i = 0; i + 1 < v.size(); ++i) {
        CHECK(v[i] <= v[i + 1]);
    }
}
