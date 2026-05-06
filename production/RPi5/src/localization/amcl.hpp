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
#include <type_traits>
#include <vector>

#include "amcl_result.hpp"
#include "core/config.hpp"
#include "likelihood_field.hpp"
#include "occupancy_grid.hpp"
#include "pose.hpp"
#include "rng.hpp"
#include "scan_ops.hpp"

namespace godo::rt {
// issue#11 P4-2-11-0 — Trim path Phase-0 instrumentation out-param.
// Forward decl avoids dragging core/rt_types.hpp into amcl.hpp's
// include surface; full definition lives there.
struct Phase0InnerBreakdown;
}  // namespace godo::rt

namespace godo::parallel {
// issue#11 P4-2-11-2 — fork-join particle eval pool. Forward decl avoids
// dragging parallel_eval_pool.hpp (and its <mutex> in the .cpp) into
// every TU that includes amcl.hpp; cold_writer.cpp picks up the full
// type via its own include.
class ParallelEvalPool;
}  // namespace godo::parallel

namespace godo::localization {

// Track D-5 — `set_field` swaps `field_` between phases of the OneShot
// anneal loop. Pinned that the swap target is nothrow-move-assignable so
// `cold_writer::run_one_iteration`'s reuse pattern (`lf =
// build_likelihood_field(...)` between phases) is exception-safe.
static_assert(std::is_nothrow_move_assignable_v<LikelihoodField>);

class Amcl {
public:
    // The likelihood field is held by const-pointer; the caller (cold
    // writer) owns it and must keep it alive for the lifetime of the Amcl
    // instance. Pre-allocates ping-pong particle buffers + cumsum scratch.
    //
    // issue#11 P4-2-11-2 — `pool` is an optional fork-join particle eval
    // pool. When non-null, `step()` partitions the per-particle
    // `evaluate_scan` loop across the pool's workers; on a join timeout
    // the step transparently re-runs sequentially for the remainder of
    // that call, and the pool itself transitions to permanent-degraded
    // (subsequent steps still produce bit-equal results — the pool's
    // inline-sequential degraded mode equals the nullptr path here).
    // Pool ownership stays with the caller (production: main.cpp; tests:
    // test fixture); Amcl never deletes it.
    explicit Amcl(const godo::core::Config&         cfg,
                  const LikelihoodField&            field,
                  godo::parallel::ParallelEvalPool* pool = nullptr);

    // Single AMCL iteration: motion (jitter) → sensor (evaluate_scan) →
    // normalize → conditional resample (only if N_eff < neff_frac * N).
    // Sets `result.iterations = 1`, `result.converged = (xy_std + yaw_std
    // both inside cfg thresholds)`, `result.forced = false`.
    //
    // Overloads:
    //   - explicit-σ form: callers pick the per-call motion-model jitter
    //     (Phase 4-2 D Live mode passes the wider Live σ pair).
    //   - default form: forwards to the explicit form using
    //     cfg.amcl_sigma_xy_jitter_m / amcl_sigma_yaw_jitter_deg
    //     (OneShot semantics; converge() builds on this).
    //   - issue#11 P4-2-11-0 trim Phase-0 form: same as above but accepts
    //     a `godo::rt::Phase0InnerBreakdown*` out-param. When non-null,
    //     the body wraps each of the 4 inner stages (jitter, evaluate_scan
    //     loop, normalize, resample) with `monotonic_ns()` deltas. When
    //     null (the default), the path is zero-overhead — the existing 4-arg
    //     and 2-arg overloads delegate with `nullptr`.
    AmclResult step(const std::vector<RangeBeam>& beams,
                    Rng&                          rng,
                    double                        sigma_xy_m,
                    double                        sigma_yaw_deg,
                    godo::rt::Phase0InnerBreakdown* phase0_out);
    AmclResult step(const std::vector<RangeBeam>& beams,
                    Rng&                          rng,
                    double                        sigma_xy_m,
                    double                        sigma_yaw_deg);
    AmclResult step(const std::vector<RangeBeam>& beams,
                    Rng&                          rng,
                    godo::rt::Phase0InnerBreakdown* phase0_out);
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

    // Track D-5 — Swap the likelihood field used by subsequent step()
    // calls. The cold writer rebuilds `lf` at successively narrower σ_hit
    // values for OneShot annealing; this method lets it re-point `field_`
    // without reconstructing `Amcl` (which would discard the carried
    // particle cloud).
    //
    // Single-thread cold-writer use only. set_field and step are NOT atomic;
    // calling them concurrently from different threads is UB. Track D-5-P
    // (parallel) workers must serialize access via the cold-writer's per-
    // phase loop. See plan §P4-D5-2 (Mode-A M3) and CODEBASE.md invariant (n).
    void set_field(const LikelihoodField& field) noexcept;

    // Track D-5 — Read access to the currently bound likelihood field. The
    // cold writer's annealing path captures a reference at OneShot entry
    // and restores it (via `set_field`) at OneShot completion so Live mode
    // re-enters with the operator-controlled σ field, never an annealing-
    // leftover field. Plan §P4-D5-6 + Q2 resolution.
    [[nodiscard]] const LikelihoodField& field() const noexcept {
        return *field_;
    }

    // Public stats getters (also used by tests).
    [[nodiscard]] Pose2D weighted_mean() const noexcept;
    [[nodiscard]] double xy_std_m() const noexcept;
    [[nodiscard]] double circular_std_yaw_deg() const noexcept;
    [[nodiscard]] std::size_t particle_count() const noexcept { return n_; }

    // issue#19 — Forward access to the optional ParallelEvalPool. Cold
    // writer plumbs `amcl.pool()` into `build_likelihood_field` so the
    // EDT 2D Felzenszwalb passes share the same pool (and the same
    // CPU 3 hard-veto guarantee) as `Amcl::step`'s particle eval. The
    // pool is owned by the caller (production: main.cpp); Amcl never
    // deletes it. Returns the same nullptr passed at construction when
    // the operator booted with `amcl.parallel_eval_workers = 1` in the
    // pre-issue#11 surface OR when no pool was wired.
    [[nodiscard]] godo::parallel::ParallelEvalPool*
    pool() const noexcept { return pool_; }

    // Pre-allocated buffer capacity. `front`/`back` and `cumsum` all share
    // this size.
    [[nodiscard]] std::size_t buffer_capacity() const noexcept {
        return front_.capacity();
    }

private:
    void normalize_weights();

    const godo::core::Config&         cfg_;
    const LikelihoodField*            field_;
    godo::parallel::ParallelEvalPool* pool_{nullptr};

    // Ping-pong buffers (front_ = active particles; back_ = resampler dst).
    // Resized to `n_` per seed; capacity stays at PARTICLE_BUFFER_MAX.
    std::vector<Particle>     front_;
    std::vector<Particle>     back_;
    std::vector<double>       cumsum_scratch_;
    std::size_t               n_{0};
};

}  // namespace godo::localization
