#pragma once

// Pre-computed likelihood field over an OccupancyGrid.
//
// For each free cell, `values[]` holds exp(-d² / (2σ²)) where d is the
// Euclidean distance (metres) to the nearest obstacle. AMCL evaluates a
// scan beam by transforming its endpoint into map coordinates and looking
// up the field value (one bilinear sample per beam, no per-evaluation
// distance computation).
//
// The distance transform is Felzenszwalb 2012 — separable 1D parabola
// envelopes. Reference brute-force EDT lives in test_likelihood_field.cpp
// (NOT Bresenham; Bresenham is reserved for synthetic-scan generation in
// test_amcl_scenarios.cpp per the plan's bias-block).

#include <vector>

#include "occupancy_grid.hpp"

namespace godo::localization {

struct LikelihoodField {
    int    width{};
    int    height{};
    double resolution_m{};
    double origin_x_m{};
    double origin_y_m{};
    std::vector<float> values;  // size = width * height; row-major
};

// Build the likelihood field. `sigma_hit_m` is the LiDAR hit-noise σ in
// metres; AMCL uses cfg.amcl_sigma_hit_m. Throws std::invalid_argument if
// the grid is empty or σ is non-positive.
LikelihoodField build_likelihood_field(const OccupancyGrid& grid,
                                       double               sigma_hit_m);

}  // namespace godo::localization
