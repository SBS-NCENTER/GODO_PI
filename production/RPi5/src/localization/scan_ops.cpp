#include "scan_ops.hpp"

#include <cmath>
#include <stdexcept>

#include "core/constants.hpp"

namespace godo::localization {

namespace {

constexpr double kDegToRad = 0.017453292519943295;
constexpr double k360      = 360.0;

double wrap_360(double deg) noexcept {
    double r = std::fmod(deg, k360);
    if (r < 0.0) r += k360;
    return r;
}

}  // namespace

void downsample(const godo::lidar::Frame& frame,
                int                       stride,
                double                    range_min_m,
                double                    range_max_m,
                std::vector<RangeBeam>&   out) {
    out.clear();
    if (stride <= 0) return;
    if (!(range_max_m > range_min_m)) return;
    const auto& samples = frame.samples;
    // Caller (cold writer) pre-sizes `out` to godo::constants::SCAN_BEAMS_MAX
    // at thread startup, which covers any well-formed RPLIDAR C1 frame at
    // every supported stride. The reserve below catches the pathological case
    // of a malformed Frame whose samples.size() exceeds SCAN_BEAMS_MAX*stride;
    // it allocates lazily, which is acceptable per invariant (e) cold-path
    // scope but should never fire in production. (S7 mitigation.)
    if (out.capacity() < samples.size() / static_cast<std::size_t>(stride) + 1) {
        out.reserve(samples.size() / static_cast<std::size_t>(stride) + 1);
    }
    for (std::size_t i = 0; i < samples.size(); i += static_cast<std::size_t>(stride)) {
        const auto& s = samples[i];
        if (s.distance_mm <= 0.0) continue;
        const double r_m = s.distance_mm * 0.001;
        if (r_m < range_min_m || r_m > range_max_m) continue;
        RangeBeam b{};
        b.range_m   = static_cast<float>(r_m);
        b.angle_rad = static_cast<float>(s.angle_deg * kDegToRad);
        out.push_back(b);
    }
}

double evaluate_scan(const Pose2D&          pose,
                     const RangeBeam*       beams,
                     std::size_t            n_beams,
                     const LikelihoodField& field) {
    if (n_beams == 0) return 1.0;
    const double cos_yaw = std::cos(pose.yaw_deg * kDegToRad);
    const double sin_yaw = std::sin(pose.yaw_deg * kDegToRad);
    const double inv_res = (field.resolution_m > 0.0)
        ? 1.0 / field.resolution_m
        : 0.0;

    // log-sum to avoid double underflow on long scans. Cells with very
    // small likelihood are floored away from -inf with EVAL_SCAN_LIKELIHOOD_FLOOR
    // from core/constants.hpp (Tier-1; S4 mitigation).
    double log_w = 0.0;
    constexpr double kEps = godo::constants::EVAL_SCAN_LIKELIHOOD_FLOOR;
    for (std::size_t i = 0; i < n_beams; ++i) {
        const double r  = static_cast<double>(beams[i].range_m);
        const double a  = static_cast<double>(beams[i].angle_rad);
        // Beam endpoint in sensor frame.
        const double xs = r * std::cos(a);
        const double ys = r * std::sin(a);
        // Rotate into world frame and translate by particle pose.
        const double xw = pose.x + (xs * cos_yaw - ys * sin_yaw);
        const double yw = pose.y + (xs * sin_yaw + ys * cos_yaw);
        // Map world → cell. Origin is the lower-left of cell (0, 0).
        const int cx = static_cast<int>((xw - field.origin_x_m) * inv_res);
        const int cy = static_cast<int>((yw - field.origin_y_m) * inv_res);
        double p;
        if (cx < 0 || cy < 0 || cx >= field.width || cy >= field.height) {
            // Off-map: rare on a good map; clamp to a small floor so this
            // doesn't dominate the weight.
            p = kEps;
        } else {
            p = static_cast<double>(
                field.values[static_cast<std::size_t>(cy) *
                             static_cast<std::size_t>(field.width) +
                             static_cast<std::size_t>(cx)]);
            if (p < kEps) p = kEps;
        }
        log_w += std::log(p);
    }
    return std::exp(log_w);
}

void jitter_inplace(Particle*   particles,
                    std::size_t n,
                    double      sigma_xy_m,
                    double      sigma_yaw_deg,
                    Rng&        rng) {
    for (std::size_t i = 0; i < n; ++i) {
        particles[i].pose.x += rng.gauss(0.0, sigma_xy_m);
        particles[i].pose.y += rng.gauss(0.0, sigma_xy_m);
        particles[i].pose.yaw_deg = wrap_360(
            particles[i].pose.yaw_deg + rng.gauss(0.0, sigma_yaw_deg));
    }
}

std::size_t resample(const Particle* in,
                     std::size_t     n,
                     Particle*       out,
                     std::size_t     out_capacity,
                     double*         cumsum_scratch,
                     std::size_t     cumsum_capacity,
                     Rng&            rng) {
    if (n == 0) return 0;
    if (out_capacity < n) {
        throw std::invalid_argument(
            "resample: out_capacity < n; caller must pre-size particles_out");
    }
    if (cumsum_capacity < n) {
        throw std::invalid_argument(
            "resample: cumsum_capacity < n; caller must pre-size scratch");
    }

    // Cumulative weights.
    double total = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        const double w = in[i].weight;
        // Defensive: weights must be finite and non-negative on entry.
        if (!(w >= 0.0)) {
            throw std::invalid_argument(
                "resample: input weight is negative or NaN");
        }
        total += w;
        cumsum_scratch[i] = total;
    }
    if (!(total > 0.0)) {
        throw std::invalid_argument(
            "resample: input weights sum is non-positive");
    }

    // Low-variance / systematic resampling: single uniform draw, then n
    // equally-spaced steps along the cdf.
    const double step = total / static_cast<double>(n);
    const double r0   = rng.uniform() * step;

    std::size_t i = 0;  // pointer into cumsum_scratch
    const double new_w = 1.0 / static_cast<double>(n);
    for (std::size_t k = 0; k < n; ++k) {
        const double u = r0 + static_cast<double>(k) * step;
        while (i + 1 < n && cumsum_scratch[i] < u) ++i;
        out[k].pose   = in[i].pose;
        out[k].weight = new_w;
    }
    return n;
}

}  // namespace godo::localization
