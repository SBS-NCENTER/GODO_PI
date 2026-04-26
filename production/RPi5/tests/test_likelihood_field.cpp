// Phase 4-2 B Wave 1 — LikelihoodField (Felzenszwalb 2D EDT + Gaussian).
//
// Bias-block: brute-force EDT reference, NOT Bresenham. Bresenham is
// reserved for synthetic-scan generation in Wave 2's
// test_amcl_scenarios.cpp; mixing the two would risk hidden agreement
// between the field-builder and the scan-generator.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <utility>
#include <vector>

#include "localization/likelihood_field.hpp"
#include "localization/occupancy_grid.hpp"

using godo::localization::LikelihoodField;
using godo::localization::OccupancyGrid;
using godo::localization::build_likelihood_field;

namespace {

// Build an OccupancyGrid from a tiny ASCII pattern. '#' = occupied, '.' = free.
// Rows are listed top-to-bottom in the input but stored bottom-to-top is NOT
// required; the EDT only cares about cell coordinates, so we use index-as-given.
OccupancyGrid grid_from_ascii(const std::vector<std::string>& rows,
                              double resolution_m = 0.10) {
    REQUIRE(!rows.empty());
    const int H = static_cast<int>(rows.size());
    const int W = static_cast<int>(rows[0].size());
    OccupancyGrid g{};
    g.width        = W;
    g.height       = H;
    g.resolution_m = resolution_m;
    g.origin_x_m   = 0.0;
    g.origin_y_m   = 0.0;
    g.cells.assign(static_cast<std::size_t>(W) *
                   static_cast<std::size_t>(H), 0);
    for (int y = 0; y < H; ++y) {
        REQUIRE(static_cast<int>(rows[static_cast<std::size_t>(y)].size()) == W);
        for (int x = 0; x < W; ++x) {
            const char c = rows[static_cast<std::size_t>(y)]
                              [static_cast<std::size_t>(x)];
            g.cells[static_cast<std::size_t>(y) *
                    static_cast<std::size_t>(W) +
                    static_cast<std::size_t>(x)] =
                (c == '#') ? std::uint8_t{0} : std::uint8_t{255};
        }
    }
    return g;
}

// Brute-force squared-cell-distance EDT (O(W²H²)) for cross-check.
std::vector<float> brute_force_sq_dist(const OccupancyGrid& g) {
    const int W = g.width;
    const int H = g.height;
    const std::size_t N = static_cast<std::size_t>(W) *
                          static_cast<std::size_t>(H);
    std::vector<float> out(N, std::numeric_limits<float>::infinity());
    // Collect obstacle coords.
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

// Recover cell-distance-squared from a likelihood-field value:
//   v = exp(-d_m² / (2σ²))   ⇒   d_m² = -2σ² ln v
// then convert metres² back to cells².
float field_to_sq_cells(float v, double sigma_hit_m, double res_m) {
    if (v >= 1.0f) return 0.0f;
    const double d_m_sq = -2.0 * sigma_hit_m * sigma_hit_m * std::log(v);
    const double d_cell_sq = d_m_sq / (res_m * res_m);
    return static_cast<float>(d_cell_sq);
}

}  // namespace

TEST_CASE("build_likelihood_field — rejects empty grid / zero sigma") {
    OccupancyGrid empty{};
    CHECK_THROWS_AS(build_likelihood_field(empty, 0.05),
                    std::invalid_argument);

    OccupancyGrid g = grid_from_ascii({"#."});
    CHECK_THROWS_AS(build_likelihood_field(g, 0.0),
                    std::invalid_argument);
    CHECK_THROWS_AS(build_likelihood_field(g, -1.0),
                    std::invalid_argument);
}

TEST_CASE("build_likelihood_field — Felzenszwalb matches brute-force on 8x8") {
    // Single obstacle at (2, 3); rest free. Smallest non-trivial case.
    std::vector<std::string> rows(8, std::string(8, '.'));
    rows[3][2] = '#';
    OccupancyGrid g = grid_from_ascii(rows, 0.10);
    const double sigma = 0.20;

    LikelihoodField lf = build_likelihood_field(g, sigma);
    const auto bf = brute_force_sq_dist(g);

    REQUIRE(lf.values.size() == bf.size());
    for (std::size_t i = 0; i < bf.size(); ++i) {
        const float reconstructed =
            field_to_sq_cells(lf.values[i], sigma, g.resolution_m);
        // Floating-point round-trip via exp/log loses precision for very
        // distant cells where v underflows toward 0. Either tight match for
        // small d², or both quantities are in their "far away" regime.
        if (bf[i] < 50.0f) {
            CHECK(reconstructed == doctest::Approx(bf[i]).epsilon(0.01));
        }
    }
}

TEST_CASE("build_likelihood_field — Felzenszwalb matches brute-force on 16x16") {
    std::vector<std::string> rows(16, std::string(16, '.'));
    rows[2][2]   = '#';
    rows[8][12]  = '#';
    rows[14][5]  = '#';
    OccupancyGrid g = grid_from_ascii(rows, 0.10);
    const double sigma = 0.30;

    LikelihoodField lf = build_likelihood_field(g, sigma);
    const auto bf = brute_force_sq_dist(g);

    REQUIRE(lf.values.size() == bf.size());
    for (std::size_t i = 0; i < bf.size(); ++i) {
        const float reconstructed =
            field_to_sq_cells(lf.values[i], sigma, g.resolution_m);
        if (bf[i] < 100.0f) {
            CHECK(reconstructed == doctest::Approx(bf[i]).epsilon(0.01));
        }
    }
}

TEST_CASE("build_likelihood_field — Felzenszwalb matches brute-force on 32x32") {
    // Border-of-obstacles + 2 interior obstacles.
    std::vector<std::string> rows;
    for (int y = 0; y < 32; ++y) {
        std::string row(32, '.');
        if (y == 0 || y == 31) std::fill(row.begin(), row.end(), '#');
        else { row[0] = '#'; row[31] = '#'; }
        rows.push_back(row);
    }
    rows[10][10] = '#';
    rows[22][20] = '#';
    OccupancyGrid g = grid_from_ascii(rows, 0.05);
    const double sigma = 0.10;

    LikelihoodField lf = build_likelihood_field(g, sigma);
    const auto bf = brute_force_sq_dist(g);

    REQUIRE(lf.values.size() == bf.size());
    for (std::size_t i = 0; i < bf.size(); ++i) {
        const float reconstructed =
            field_to_sq_cells(lf.values[i], sigma, g.resolution_m);
        if (bf[i] < 200.0f) {
            CHECK(reconstructed == doctest::Approx(bf[i]).epsilon(0.02));
        }
    }
}

TEST_CASE("build_likelihood_field — Gaussian decay shape: 0 at obstacle, monotone falloff") {
    std::vector<std::string> rows(16, std::string(16, '.'));
    rows[8][8] = '#';
    OccupancyGrid g = grid_from_ascii(rows, 0.10);
    const double sigma = 0.30;
    LikelihoodField lf = build_likelihood_field(g, sigma);

    auto at = [&](int x, int y) {
        return lf.values[static_cast<std::size_t>(y) *
                         static_cast<std::size_t>(g.width) +
                         static_cast<std::size_t>(x)];
    };

    // At obstacle cell: distance is 0 → exp(0) = 1.0.
    CHECK(at(8, 8) == doctest::Approx(1.0f));
    // 1 cell away: distance² = 1 cell² = 0.01 m² → exp(-0.01 / (2*0.09))
    //  = exp(-0.0556) ~= 0.946.
    CHECK(at(9, 8) == doctest::Approx(static_cast<float>(
        std::exp(-0.01 / (2.0 * 0.09)))).epsilon(0.001));
    // Monotone non-increasing along the +x axis:
    CHECK(at(8, 8) >= at(9, 8));
    CHECK(at(9, 8) >= at(10, 8));
    CHECK(at(10, 8) >= at(11, 8));
    // Symmetric in 4 directions:
    CHECK(at(7, 8) == doctest::Approx(at(9, 8)));
    CHECK(at(8, 7) == doctest::Approx(at(8, 9)));
}
