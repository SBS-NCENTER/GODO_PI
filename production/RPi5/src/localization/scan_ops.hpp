#pragma once

// Scan / particle helpers used by the AMCL kernel.
//
// All functions here are free functions (not class methods) so unit tests
// can exercise them without instantiating the full Amcl object. The
// `class Amcl` (Wave 2) composes these into one step() iteration.

#include <cstddef>
#include <vector>

#include "lidar/sample.hpp"
#include "likelihood_field.hpp"
#include "pose.hpp"
#include "rng.hpp"

namespace godo::localization {

// Compact view of one LiDAR beam after downsample / range gate.
//   range_m: in metres; > 0
//   angle_rad: sensor-frame bearing in radians (the AMCL kernel converts
//              to map frame using the particle's yaw)
struct RangeBeam {
    float range_m;
    float angle_rad;
};

// Decimate `frame.samples` by `stride` and gate by [range_min_m, range_max_m].
// Output size <= frame.samples.size() / stride; allocation amortized via
// caller-supplied output vector that is .clear()'ed and refilled.
//
// Beams with distance_mm == 0 (per SLAMTEC PDF Fig 4-5: invalid) are dropped.
void downsample(const godo::lidar::Frame& frame,
                int                       stride,
                double                    range_min_m,
                double                    range_max_m,
                std::vector<RangeBeam>&   out);

// Compute the un-normalized log-likelihood weight for one particle given a
// pre-built LikelihoodField. Implementation: for each beam, transform its
// endpoint into map coordinates using the particle pose, look up the field
// value, multiply (in log space sum). Returns weight = exp(Σ log_p_i).
double evaluate_scan(const Pose2D&                 pose,
                     const RangeBeam*              beams,
                     std::size_t                   n_beams,
                     const LikelihoodField&        field);

// Add Gaussian noise to all particles in-place: x += N(0, σ_xy), y += N(0, σ_xy),
// yaw += N(0, σ_yaw). Yaw is wrapped to [0, 360) after each draw.
void jitter_inplace(Particle*    particles,
                    std::size_t  n,
                    double       sigma_xy_m,
                    double       sigma_yaw_deg,
                    Rng&         rng);

// Low-variance resampler. `in` has `n` particles with positive weights;
// `out` is pre-allocated to capacity >= n by the caller. Output also has
// `n` entries written; weights normalized to 1/n.
//
// `cumsum_scratch` is a caller-allocated buffer of size >= n; never grown
// here so the resampler is allocation-free per call (S3 trade-off pinned
// in the plan: tested via capacity invariant, not absolute no-new).
//
// Returns the number of entries written (always == n on success).
// Throws std::invalid_argument if `out` lacks capacity or weights sum is
// non-positive.
std::size_t resample(const Particle* in,
                     std::size_t     n,
                     Particle*       out,
                     std::size_t     out_capacity,
                     double*         cumsum_scratch,
                     std::size_t     cumsum_capacity,
                     Rng&            rng);

}  // namespace godo::localization
