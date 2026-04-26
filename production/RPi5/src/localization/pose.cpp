#include "pose.hpp"

#include <cmath>

namespace godo::localization {

namespace {

constexpr double kDegToRad = 0.017453292519943295;  // π / 180
constexpr double kRadToDeg = 57.29577951308232;     // 180 / π
constexpr double k360      = 360.0;

// Canonicalize a degree value into [0, 360). std::fmod can return negative.
double wrap_360(double deg) noexcept {
    double r = std::fmod(deg, k360);
    if (r < 0.0) r += k360;
    return r;
}

}  // namespace

double circular_mean_yaw_deg(const Particle* particles,
                             std::size_t     n) noexcept {
    if (n == 0) return 0.0;
    double s = 0.0, c = 0.0, wsum = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        const double th = particles[i].pose.yaw_deg * kDegToRad;
        const double w  = particles[i].weight;
        s += std::sin(th) * w;
        c += std::cos(th) * w;
        wsum += w;
    }
    if (!(wsum > 0.0)) return 0.0;
    // atan2 of weighted sums; magnitude of (s, c) drops out for the angle.
    const double mean_rad = std::atan2(s, c);
    double mean_deg = mean_rad * kRadToDeg;
    if (mean_deg < 0.0) mean_deg += k360;
    return wrap_360(mean_deg);
}

double circular_std_yaw_deg(const Particle* particles,
                            std::size_t     n) noexcept {
    if (n == 0) return 0.0;
    double s = 0.0, c = 0.0, wsum = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        const double th = particles[i].pose.yaw_deg * kDegToRad;
        const double w  = particles[i].weight;
        s += std::sin(th) * w;
        c += std::cos(th) * w;
        wsum += w;
    }
    if (!(wsum > 0.0)) return 0.0;
    const double R = std::sqrt(s * s + c * c) / wsum;
    // R clipped to (0, 1]; near-degenerate distributions can floating-point
    // overshoot 1 by epsilon, and a perfectly-aligned cluster reports std=0.
    if (R >= 1.0) return 0.0;
    if (R <= 0.0) return std::sqrt(-2.0 * std::log(1e-300)) * kRadToDeg;
    const double std_rad = std::sqrt(-2.0 * std::log(R));
    return std_rad * kRadToDeg;
}

}  // namespace godo::localization
