#pragma once

// AMCL — adaptive monte-carlo localization, OneShot flavour.
//
// Pre-allocates two ping-pong particle buffers + a cumsum scratch sized to
// `core::PARTICLE_BUFFER_MAX` once at construction. `step()` and `converge()`
// run without further heap allocation (S3 trade-off: capacity invariant,
// not absolute no-new). `seed_global` and `seed_around` (re)populate the
// active buffer with `n` particles drawn from the requested distribution.
//
// Invariant (f) (Wave 2): NO virtual methods. Particle-filter swap-out is
// by `Amcl` template parameter, NOT by ABC. Reuses invariant (a)'s no-ABC
// philosophy across the localization module.

#include <cstddef>
#include <vector>

#include "amcl_result.hpp"
#include "core/config.hpp"
#include "likelihood_field.hpp"
#include "occupancy_grid.hpp"
#include "pose.hpp"
#include "rng.hpp"
#include "scan_ops.hpp"

namespace godo::localization {

class Amcl {
public:
    // The likelihood field is held by const-pointer; the caller (cold
    // writer) owns it and must keep it alive for the lifetime of the Amcl
    // instance. Pre-allocates ping-pong particle buffers + cumsum scratch.
    explicit Amcl(const godo::core::Config& cfg, const LikelihoodField& field);

    // Single AMCL iteration: motion (jitter) → sensor (evaluate_scan) →
    // normalize → conditional resample (only if N_eff < neff_frac * N).
    // Sets `result.iterations = 1`, `result.converged = (xy_std + yaw_std
    // both inside cfg thresholds)`, `result.forced = false`.
    //
    // Two overloads:
    //   - explicit-σ form: callers pick the per-call motion-model jitter
    //     (Phase 4-2 D Live mode passes the wider Live σ pair).
    //   - default form: forwards to the explicit form using
    //     cfg.amcl_sigma_xy_jitter_m / amcl_sigma_yaw_jitter_deg
    //     (OneShot semantics; converge() builds on this).
    AmclResult step(const std::vector<RangeBeam>& beams,
                    Rng&                          rng,
                    double                        sigma_xy_m,
                    double                        sigma_yaw_deg);
    AmclResult step(const std::vector<RangeBeam>& beams, Rng& rng);

    // Loop on top of step() up to `cfg.amcl_max_iters`. Early-exits when
    // `xy_std_m() < cfg.amcl_converge_xy_std_m` AND
    // `circular_std_yaw_deg() < cfg.amcl_converge_yaw_std_deg` AND
    // `iters >= 3`. `result.forced = false` (cold writer flips this).
    AmclResult converge(const std::vector<RangeBeam>& beams, Rng& rng);

    // Uniformly sample over free cells of `grid` for global localization.
    // Yaw is uniform on [0, 360). `n = cfg.amcl_particles_global_n`.
    void seed_global(const OccupancyGrid& grid, Rng& rng);

    // Gaussian cloud around `pose`. `n = cfg.amcl_particles_local_n`.
    // sigma_xy_m / sigma_yaw_deg passed in so callers can pick a per-call
    // tightness; cfg.amcl_sigma_seed_xy_m / _yaw_deg are the production
    // defaults.
    void seed_around(const Pose2D& pose,
                     double        sigma_xy_m,
                     double        sigma_yaw_deg,
                     Rng&          rng);

    // Public stats getters (also used by tests).
    [[nodiscard]] Pose2D weighted_mean() const noexcept;
    [[nodiscard]] double xy_std_m() const noexcept;
    [[nodiscard]] double circular_std_yaw_deg() const noexcept;
    [[nodiscard]] std::size_t particle_count() const noexcept { return n_; }

    // Pre-allocated buffer capacity. `front`/`back` and `cumsum` all share
    // this size.
    [[nodiscard]] std::size_t buffer_capacity() const noexcept {
        return front_.capacity();
    }

private:
    void normalize_weights();

    const godo::core::Config& cfg_;
    const LikelihoodField*    field_;

    // Ping-pong buffers (front_ = active particles; back_ = resampler dst).
    // Resized to `n_` per seed; capacity stays at PARTICLE_BUFFER_MAX.
    std::vector<Particle>     front_;
    std::vector<Particle>     back_;
    std::vector<double>       cumsum_scratch_;
    std::size_t               n_{0};
};

}  // namespace godo::localization
