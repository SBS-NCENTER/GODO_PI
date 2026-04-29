#include "amcl.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

#include "core/constants.hpp"

namespace godo::localization {

namespace {

constexpr double k360 = 360.0;

// Conditional-resample threshold: only resample when the effective sample
// size N_eff = (Σw)² / Σw² drops below this fraction of N. 0.5 is the
// textbook AMCL choice; bumping it causes more aggressive resampling.
constexpr double kResampleNeffFrac = 0.5;

double wrap_360(double deg) noexcept {
    double r = std::fmod(deg, k360);
    if (r < 0.0) r += k360;
    return r;
}

}  // namespace

void Amcl::set_field(const LikelihoodField& field) noexcept {
    field_ = &field;
}

Amcl::Amcl(const godo::core::Config& cfg, const LikelihoodField& field)
    : cfg_(cfg), field_(&field) {
    // Pre-allocate ping-pong buffers + cumsum scratch ONCE. Subsequent
    // seed_global / seed_around / step / converge do not grow these (S3:
    // capacity invariant pinned by test_amcl_components and test_resampler).
    const std::size_t cap =
        static_cast<std::size_t>(godo::constants::PARTICLE_BUFFER_MAX);
    front_.reserve(cap);
    back_.reserve(cap);
    cumsum_scratch_.assign(cap, 0.0);
    n_ = 0;
}

void Amcl::seed_global(const OccupancyGrid& grid, Rng& rng) {
    const std::size_t n = static_cast<std::size_t>(cfg_.amcl_particles_global_n);
    if (n == 0 || n > front_.capacity()) {
        throw std::invalid_argument(
            "Amcl::seed_global: amcl_particles_global_n exceeds "
            "PARTICLE_BUFFER_MAX or is zero");
    }
    if (grid.width <= 0 || grid.height <= 0 || grid.cells.empty()) {
        throw std::invalid_argument(
            "Amcl::seed_global: empty occupancy grid");
    }

    // Build a list of free-cell indices once. The fixture is small enough
    // (<= EDT_MAX_CELLS) that this is acceptable per invariant (e) cold-
    // path scope. Uses local std::vector — this is the cold writer's seed
    // path, not a per-step kernel.
    std::vector<int> free_idx;
    free_idx.reserve(grid.cells.size());
    for (int y = 0; y < grid.height; ++y) {
        for (int x = 0; x < grid.width; ++x) {
            const std::size_t k = static_cast<std::size_t>(y) *
                                  static_cast<std::size_t>(grid.width) +
                                  static_cast<std::size_t>(x);
            // Free-cell test uses the shared OCCUPIED_CUTOFF_U8 from
            // occupancy_grid.hpp — same threshold the EDT uses, so the
            // seed cloud cannot include cells the likelihood field treats
            // as obstacles (S5).
            if (grid.cells[k] >= OCCUPIED_CUTOFF_U8) {
                free_idx.push_back(static_cast<int>(k));
            }
        }
    }
    if (free_idx.empty()) {
        throw std::runtime_error(
            "Amcl::seed_global: occupancy grid has zero free cells");
    }

    front_.resize(n);
    const double w0 = 1.0 / static_cast<double>(n);
    for (std::size_t i = 0; i < n; ++i) {
        const int idx = free_idx[rng.uniform_index(free_idx.size())];
        const int cy  = idx / grid.width;
        const int cx  = idx - cy * grid.width;
        // Sample within the cell (uniform-in-cell). The +0.5 centre-of-cell
        // is fine; we add a small uniform perturbation so two particles
        // sharing a cell index don't end up at the same coords.
        const double x = grid.origin_x_m +
                         (static_cast<double>(cx) + rng.uniform()) *
                         grid.resolution_m;
        const double y = grid.origin_y_m +
                         (static_cast<double>(cy) + rng.uniform()) *
                         grid.resolution_m;
        front_[i].pose.x       = x;
        front_[i].pose.y       = y;
        front_[i].pose.yaw_deg = rng.uniform() * k360;
        front_[i].weight       = w0;
    }
    n_ = n;
}

void Amcl::seed_around(const Pose2D& pose,
                       double        sigma_xy_m,
                       double        sigma_yaw_deg,
                       Rng&          rng) {
    const std::size_t n = static_cast<std::size_t>(cfg_.amcl_particles_local_n);
    if (n == 0 || n > front_.capacity()) {
        throw std::invalid_argument(
            "Amcl::seed_around: amcl_particles_local_n exceeds "
            "PARTICLE_BUFFER_MAX or is zero");
    }
    if (!(sigma_xy_m > 0.0) || !(sigma_yaw_deg > 0.0)) {
        throw std::invalid_argument(
            "Amcl::seed_around: sigma_xy_m / sigma_yaw_deg must be > 0");
    }

    front_.resize(n);
    const double w0 = 1.0 / static_cast<double>(n);
    for (std::size_t i = 0; i < n; ++i) {
        front_[i].pose.x       = rng.gauss(pose.x, sigma_xy_m);
        front_[i].pose.y       = rng.gauss(pose.y, sigma_xy_m);
        front_[i].pose.yaw_deg = wrap_360(rng.gauss(pose.yaw_deg,
                                                    sigma_yaw_deg));
        front_[i].weight       = w0;
    }
    n_ = n;
}

void Amcl::normalize_weights() {
    if (n_ == 0) return;
    // Treat current weights as log-likelihoods? In our pipeline,
    // evaluate_scan() returns exp(Σ log_p_i) directly — i.e. a non-log
    // likelihood. To stay numerically stable across thousands of beams
    // we re-derive log-weights from the input, subtract the max, then
    // exponentiate. This is the "log-sum-exp" pattern.
    //
    // weight here is stored as exp(log_w). Convert back to log via std::log,
    // subtract the max, exp again, sum, normalize. We only do this once
    // per step() so the cost is acceptable.
    double max_log = -std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i < n_; ++i) {
        const double w = front_[i].weight;
        const double lw = (w > 0.0)
            ? std::log(w)
            : -std::numeric_limits<double>::infinity();
        front_[i].weight = lw;  // overwrite with log-weight in place
        if (lw > max_log) max_log = lw;
    }
    if (!std::isfinite(max_log)) {
        // Degenerate: every particle weighed zero. Reset to uniform so the
        // resampler does not throw; the next step will produce useful
        // weights once the cloud drifts onto the map.
        const double w0 = 1.0 / static_cast<double>(n_);
        for (std::size_t i = 0; i < n_; ++i) front_[i].weight = w0;
        return;
    }
    double sum = 0.0;
    for (std::size_t i = 0; i < n_; ++i) {
        const double rel = std::exp(front_[i].weight - max_log);
        front_[i].weight = rel;
        sum += rel;
    }
    if (sum <= 0.0) {
        const double w0 = 1.0 / static_cast<double>(n_);
        for (std::size_t i = 0; i < n_; ++i) front_[i].weight = w0;
        return;
    }
    const double inv = 1.0 / sum;
    for (std::size_t i = 0; i < n_; ++i) front_[i].weight *= inv;
}

AmclResult Amcl::step(const std::vector<RangeBeam>& beams,
                      Rng&                          rng,
                      double                        sigma_xy_m,
                      double                        sigma_yaw_deg) {
    AmclResult res{};
    res.forced     = false;
    res.iterations = 1;

    // 1. Motion (Gaussian jitter on every particle).
    //    σ pair comes from the caller — OneShot keeps the cfg-default pair
    //    via the no-σ overload below; Live mode passes the wider Live pair
    //    so a fast-moving base does not collapse the cloud.
    jitter_inplace(front_.data(), n_,
                   sigma_xy_m,
                   sigma_yaw_deg,
                   rng);

    // 2. Sensor — evaluate_scan returns a non-log likelihood per particle.
    for (std::size_t i = 0; i < n_; ++i) {
        front_[i].weight = evaluate_scan(front_[i].pose,
                                         beams.data(),
                                         beams.size(),
                                         *field_);
    }

    // 3. Normalize (log-sum-exp re-stabilization in case any particle
    // returned a very large or very small weight).
    normalize_weights();

    // 4. Effective sample size: only resample when the cloud has lost
    // diversity.
    double sum_sq = 0.0;
    for (std::size_t i = 0; i < n_; ++i) {
        sum_sq += front_[i].weight * front_[i].weight;
    }
    const double n_eff = (sum_sq > 0.0) ? 1.0 / sum_sq : 0.0;
    const double n_eff_thresh = kResampleNeffFrac * static_cast<double>(n_);
    if (n_eff < n_eff_thresh) {
        back_.resize(n_);
        resample(front_.data(), n_,
                 back_.data(), back_.capacity(),
                 cumsum_scratch_.data(), cumsum_scratch_.size(),
                 rng);
        std::swap(front_, back_);
    }

    // 5. Stats + convergence assessment.
    res.pose         = weighted_mean();
    res.xy_std_m     = xy_std_m();
    res.yaw_std_deg  = circular_std_yaw_deg();
    res.converged    = (res.xy_std_m    < cfg_.amcl_converge_xy_std_m) &&
                       (res.yaw_std_deg < cfg_.amcl_converge_yaw_std_deg);
    res.offset       = godo::rt::Offset{};  // cold writer fills this in
    return res;
}

AmclResult Amcl::step(const std::vector<RangeBeam>& beams, Rng& rng) {
    return step(beams, rng,
                cfg_.amcl_sigma_xy_jitter_m,
                cfg_.amcl_sigma_yaw_jitter_deg);
}

AmclResult Amcl::converge(const std::vector<RangeBeam>& beams, Rng& rng) {
    AmclResult res{};
    res.forced = false;
    const int max_iters = cfg_.amcl_max_iters;
    int iter = 0;
    for (; iter < max_iters; ++iter) {
        res = step(beams, rng);
        // Require at least 3 iterations to avoid declaring convergence
        // off the seed cloud's natural variance before the sensor model
        // has had a chance to reshape it.
        if (res.converged && iter >= 2) {
            ++iter;          // count the iteration that fired the early-exit
            break;
        }
    }
    res.iterations = iter;
    return res;
}

Pose2D Amcl::weighted_mean() const noexcept {
    Pose2D out{};
    if (n_ == 0) return out;
    double wsum = 0.0;
    double wx = 0.0, wy = 0.0;
    for (std::size_t i = 0; i < n_; ++i) {
        const double w = front_[i].weight;
        wsum += w;
        wx   += front_[i].pose.x * w;
        wy   += front_[i].pose.y * w;
    }
    if (wsum > 0.0) {
        out.x = wx / wsum;
        out.y = wy / wsum;
    }
    out.yaw_deg = circular_mean_yaw_deg(front_.data(), n_);
    return out;
}

double Amcl::xy_std_m() const noexcept {
    if (n_ == 0) return 0.0;
    // sqrt(weighted_var_x + weighted_var_y).
    // Choice: combined-variance scalar — gives a single "spread" number that
    // matches the convergence threshold's units (metres). An L2-norm of
    // (std_x, std_y) would also work but converges to the same geometric
    // intuition; the variance-sum form avoids one extra sqrt per particle.
    double wsum = 0.0, mx = 0.0, my = 0.0;
    for (std::size_t i = 0; i < n_; ++i) {
        const double w = front_[i].weight;
        wsum += w;
        mx   += front_[i].pose.x * w;
        my   += front_[i].pose.y * w;
    }
    if (!(wsum > 0.0)) return 0.0;
    mx /= wsum;
    my /= wsum;
    double vx = 0.0, vy = 0.0;
    for (std::size_t i = 0; i < n_; ++i) {
        const double w = front_[i].weight;
        const double dx = front_[i].pose.x - mx;
        const double dy = front_[i].pose.y - my;
        vx += w * dx * dx;
        vy += w * dy * dy;
    }
    vx /= wsum;
    vy /= wsum;
    return std::sqrt(vx + vy);
}

double Amcl::circular_std_yaw_deg() const noexcept {
    return ::godo::localization::circular_std_yaw_deg(front_.data(), n_);
}

}  // namespace godo::localization
