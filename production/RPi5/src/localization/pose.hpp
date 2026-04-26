#pragma once

// 2D pose + particle types and circular-statistics free helpers.
//
// Yaw is in degrees throughout the public API. Internal trig converts to
// radians at function boundaries. All output yaw values are canonicalized
// to [0, 360) (matches godo::yaw::lerp_angle and Offset::dyaw convention).

#include <cstddef>

namespace godo::localization {

struct Pose2D {
    double x;        // metres, world frame
    double y;        // metres, world frame
    double yaw_deg;  // degrees, [0, 360)
};

struct Particle {
    Pose2D pose;
    double weight;   // sum-normalized in steady state, > 0
};

// Weighted circular mean of yaw_deg over `n` particles.
// Implementation: atan2(Σ sin(θᵢ) wᵢ, Σ cos(θᵢ) wᵢ).
// Pinned by the [359°, 1°) cluster test in Wave 2's test_circular_stats.cpp.
// Returns a value in [0, 360). When Σw == 0, returns 0.
double circular_mean_yaw_deg(const Particle* particles,
                             std::size_t     n) noexcept;

// Weighted circular standard deviation of yaw_deg over `n` particles.
//   R   = sqrt((Σ sin θᵢ wᵢ)² + (Σ cos θᵢ wᵢ)²) / Σwᵢ
//   std = sqrt(-2 ln R) in radians, converted to degrees.
// For tightly clustered angles R → 1 → std → 0; the [359°, 1°) cluster
// returns ~0.6° rather than the ~180° a naive linear std would yield.
// When n == 0 or Σw == 0, returns 0.
double circular_std_yaw_deg(const Particle* particles,
                            std::size_t     n) noexcept;

}  // namespace godo::localization
