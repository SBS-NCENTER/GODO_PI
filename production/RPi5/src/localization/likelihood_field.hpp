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

namespace godo::parallel {
// issue#19 — forward declare ParallelEvalPool. Avoids dragging the full
// parallel_eval_pool.hpp (and its <atomic>) into every TU that includes
// likelihood_field.hpp; consumers that pass a non-null pool include the
// full header in their .cpp directly.
class ParallelEvalPool;
}  // namespace godo::parallel

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
//
// issue#19 — `pool` parameter is optional. `nullptr` (default) selects
// the existing sequential Felzenszwalb path, byte-identical to pre-
// issue#19 behaviour. Non-null pool dispatches the column + row passes
// 3-way (workers pinned to {CPU 0, 1, 2} per the pool's ctor); the
// Gaussian conversion stays sequential (not the bottleneck). Pool path
// is bit-equal to sequential — workers write disjoint output subranges
// (column pass: x-block; row pass: y-block) and `edt_1d` is invoked per-
// column / per-row sequentially within that span; no cross-worker
// reduction. Pinned by FNV-1a memcmp in
// `tests/test_likelihood_field_parallel.cpp`.
LikelihoodField build_likelihood_field(
    const OccupancyGrid&                grid,
    double                              sigma_hit_m,
    godo::parallel::ParallelEvalPool*   pool = nullptr);

}  // namespace godo::localization
