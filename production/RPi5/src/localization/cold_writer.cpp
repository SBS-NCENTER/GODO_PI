#include "cold_writer.hpp"

#include <atomic>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <limits>
#include <variant>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "core/rt_types.hpp"
#include "core/time.hpp"
#include "deadband.hpp"
#include "likelihood_field.hpp"

namespace godo::localization {

namespace {

// issue#11 P4-2-11-0 — Trim path Phase-0 instrumentation env latch.
//
// `GODO_PHASE0=1` enables per-scan stderr breakdown emit (PHASE0 lines
// that journald captures). Any other value (or unset) keeps the cold
// path zero-overhead. Latched once at static init time; immutable
// thereafter — operator must restart godo-tracker to flip the flag.
//
// Single TU-scope const: lives only in cold_writer.cpp, doesn't bleed
// into the hot path or other modules. TEMPORARY by design — reverts
// cleanly along with the rest of P4-2-11-0 once Mode-A round 2 of
// issue#11 absorbs the per-component numbers. See
// `.claude/tmp/plan_issue_11_phase0_instrumentation.md` "Trim path
// resolution" fold.
const bool kPhase0On = []() {
    const char* env = std::getenv("GODO_PHASE0");
    return env != nullptr && env[0] == '1' && env[1] == '\0';
}();

// Thread-local accumulators for the trim Phase-0 breakdown. Cold writer
// thread is the SOLE writer (anneal kernel + step both run on this
// thread). Reset to zero at scan-top inside each
// `run_*_iteration` wrapper; emitted at scan-bottom via fprintf.
//
// `g_phase0_lf_rebuild_ns_sum` aggregates LF rebuild time across all σ
// phases inside `run_anneal_kernel`. `g_phase0_inner_sum` aggregates the
// 4-stage Amcl::step breakdown across all anneal iters within a single
// scan. Both reset on every scan; the wrappers see only this scan's
// totals.
thread_local std::int64_t g_phase0_lf_rebuild_ns_sum = 0;
thread_local godo::rt::Phase0InnerBreakdown g_phase0_inner_sum{};
thread_local std::int64_t g_phase0_scan_seq = 0;

// Reset thread-local accumulators + capture scan-start mono ns. Called
// at the top of each `run_*_iteration` wrapper when kPhase0On.
[[gnu::cold]]
inline void phase0_reset_and_stamp_start(std::int64_t& scan_start_ns_out) {
    g_phase0_lf_rebuild_ns_sum  = 0;
    g_phase0_inner_sum          = godo::rt::Phase0InnerBreakdown{};
    scan_start_ns_out           = godo::rt::monotonic_ns();
}

// Emit one PHASE0 line to stderr (captured by journald). Called at the
// bottom of each `run_*_iteration` wrapper when kPhase0On. `path_label`
// distinguishes oneshot vs live vs live_pipelined; `iters` is the
// AmclResult.iterations value for this scan.
[[gnu::cold]]
inline void phase0_emit(const char* path_label,
                        std::int64_t scan_start_ns,
                        std::int32_t iters) {
    const std::int64_t total_ns = godo::rt::monotonic_ns() - scan_start_ns;
    ++g_phase0_scan_seq;
    std::fprintf(stderr,
        "PHASE0 path=%s scan=%lld iters=%d "
        "lf_rebuild_ns=%lld jitter_ns=%lld eval_ns=%lld norm_ns=%lld resamp_ns=%lld "
        "total_ns=%lld\n",
        path_label,
        static_cast<long long>(g_phase0_scan_seq),
        static_cast<int>(iters),
        static_cast<long long>(g_phase0_lf_rebuild_ns_sum),
        static_cast<long long>(g_phase0_inner_sum.jitter_ns),
        static_cast<long long>(g_phase0_inner_sum.evaluate_scan_ns),
        static_cast<long long>(g_phase0_inner_sum.normalize_ns),
        static_cast<long long>(g_phase0_inner_sum.resample_ns),
        static_cast<long long>(total_ns));
}

}  // namespace

// Track D-5 — Coarse-to-fine sigma_hit annealing for OneShot AMCL.
//
// Schedule length 1 falls through to this same body — runs
// cfg.amcl_anneal_iters_per_phase iters at the single σ. Operators wanting
// pre-Track-D-5 behaviour set BOTH amcl.sigma_hit_schedule_m = "0.05"
// AND amcl.anneal_iters_per_phase = 25.
//
// Yaw tripwire intentionally NOT checked here — caller does it once on
// final result (cold_writer.cpp:128, plan §P4-D5-5). Intermediate-phase
// poses are not tripwire candidates.
//
// 2026-04-29 23:20 KST update — auto-minima tracking with patience-2 early
// break. Empirical HIL on TS5 chroma studio (5cm-cell map) showed the
// 5-phase default ending at σ_hit=0.05 over-tightened the likelihood
// Gaussian into sub-cell discretization, producing σ_xy~0.036m at the
// final phase even though phase 2 (σ=0.2) had reached σ_xy~0.006m.
// Solution: track the best (min) σ_xy across phases and return THAT
// pose, not the final-phase pose. Allow up to 2 consecutive worse-than-
// best phases before declaring "we've passed the minimum, stop"
// (patience absorbs single-phase noise spikes; second consecutive bump
// signals real over-tightening). See .claude/memory/project_amcl_sigma_sweep_2026-04-29.md.
namespace {

// Phase-0 seed strategy. Determines what `phase_seed_for_index_0` does
// at the top of the anneal loop.
struct Phase0SeedHint {
    Pose2D pose;
    double sigma_xy_m;
    double sigma_yaw_deg;
};
struct Phase0SeedGlobal {};
using Phase0Seed = std::variant<Phase0SeedGlobal, Phase0SeedHint>;

// Per-phase seed_xy source. OneShot uses the length-matched
// `cfg.amcl_sigma_seed_xy_schedule_m` (entries 1..N-1 are doubles, entry
// 0 is NaN sentinel). Live carry derives seed_xy from a base σ_xy times
// σ_k / σ_0 — no separate length-matched schedule needed.
struct PerPhaseSeedFromSchedule {
    const std::vector<double>* schedule;  // length-matched to schedule_m
};
struct PerPhaseSeedFromBase {
    double base_xy_m;
};
using PerPhaseSeed = std::variant<PerPhaseSeedFromSchedule,
                                  PerPhaseSeedFromBase>;

// Shared anneal kernel. Single loop covers both OneShot (with possible
// hint) and Live carry. Phase 0 seeds per `phase0_seed`; phases k>0
// seed_around the carry pose with σ_xy from `per_phase_seed` and σ_yaw
// scaled linearly by σ_k / σ_0. Auto-minima tracking with patience-2
// early break is unchanged from the pre-issue#5 OneShot path.
AmclResult run_anneal_kernel(const godo::core::Config&     cfg,
                             const std::vector<RangeBeam>& beams,
                             const OccupancyGrid&          grid,
                             LikelihoodField&              field_inout,
                             Amcl&                         amcl,
                             const std::vector<double>&    schedule,
                             const Phase0Seed&             phase0_seed,
                             const PerPhaseSeed&           per_phase_seed,
                             Pose2D&                       pose_inout,
                             Rng&                          rng) {
    if (schedule.empty()) {
        AmclResult r{};
        r.iterations = 0;
        r.xy_std_m   = std::numeric_limits<double>::infinity();
        return r;
    }

    int total_iters = 0;
    const double sigma_0 = schedule.front();

    AmclResult  best_result{};
    best_result.forced    = false;
    best_result.xy_std_m  = std::numeric_limits<double>::infinity();
    Pose2D      best_pose{};
    int         bad_streak = 0;
    constexpr int kPatience = 2;

    for (std::size_t k = 0; k < schedule.size(); ++k) {
        const double sigma_k = schedule[k];

        // Rebuild EDT at σ_k. LikelihoodField is nothrow-move-assignable
        // (amcl.hpp static_assert), so a throw inside leaves the basic
        // exception guarantee intact.
        const std::int64_t t_lf_start = kPhase0On ? godo::rt::monotonic_ns() : 0;
        field_inout = build_likelihood_field(grid, sigma_k);
        if (kPhase0On) {
            g_phase0_lf_rebuild_ns_sum += godo::rt::monotonic_ns() - t_lf_start;
        }
        amcl.set_field(field_inout);

        // Seed.
        if (k == 0) {
            if (std::holds_alternative<Phase0SeedHint>(phase0_seed)) {
                const auto& h = std::get<Phase0SeedHint>(phase0_seed);
                amcl.seed_around(h.pose, h.sigma_xy_m, h.sigma_yaw_deg, rng);
                // Carry the hint pose so the phase-1 seed_around centres
                // on the operator's basin even if phase 0 ends with a
                // small drift from xy_std-tracking noise.
                pose_inout = h.pose;
            } else {
                amcl.seed_global(grid, rng);
            }
        } else {
            double seed_xy_k = 0.0;
            if (std::holds_alternative<PerPhaseSeedFromSchedule>(
                    per_phase_seed)) {
                const auto& s = std::get<PerPhaseSeedFromSchedule>(
                    per_phase_seed);
                seed_xy_k = (*s.schedule)[k];
            } else {
                const auto& b = std::get<PerPhaseSeedFromBase>(per_phase_seed);
                seed_xy_k = b.base_xy_m * (sigma_k / sigma_0);
            }
            const double seed_yaw_k = cfg.amcl_sigma_seed_yaw_deg *
                                      (sigma_k / sigma_0);
            amcl.seed_around(pose_inout, seed_xy_k, seed_yaw_k, rng);
        }

        // Inner loop — same early-exit rule as Amcl::converge.
        AmclResult phase_result{};
        const int max_iters = cfg.amcl_anneal_iters_per_phase;
        int iter = 0;
        for (; iter < max_iters; ++iter) {
            // issue#11 P4-2-11-0 — Trim Phase-0: when env latch is set,
            // route through the 3-arg overload so Amcl::step writes the
            // 4-stage breakdown into a local; we accumulate per-iter.
            if (kPhase0On) {
                godo::rt::Phase0InnerBreakdown phase0_inner_local{};
                phase_result = amcl.step(beams, rng, &phase0_inner_local);
                g_phase0_inner_sum.jitter_ns        += phase0_inner_local.jitter_ns;
                g_phase0_inner_sum.evaluate_scan_ns += phase0_inner_local.evaluate_scan_ns;
                g_phase0_inner_sum.normalize_ns     += phase0_inner_local.normalize_ns;
                g_phase0_inner_sum.resample_ns      += phase0_inner_local.resample_ns;
            } else {
                phase_result = amcl.step(beams, rng);
            }
            if (phase_result.converged && iter >= 2) {
                ++iter;
                break;
            }
        }

        total_iters += iter;
        if (phase_result.xy_std_m < best_result.xy_std_m) {
            best_result = phase_result;
            best_pose   = phase_result.pose;
            bad_streak  = 0;
        } else {
            ++bad_streak;
            if (bad_streak >= kPatience) {
                pose_inout = phase_result.pose;
                break;
            }
        }
        pose_inout = phase_result.pose;
    }

    pose_inout = best_pose;
    best_result.iterations = total_iters;
    return best_result;
}

}  // namespace

// issue#5 — Pure-kernel hint-driven anneal. Caller supplies the hint
// pose, the per-tick σ pair, and the schedule. NEVER touches
// g_calibrate_hint_*; consume-once is OneShot-only (run_one_iteration).
//
// Phase 0 always seed_arounds the hint with (sigma_xy_m, sigma_yaw_deg).
// Phases k>0 derive seed_xy from sigma_xy_m × σ_k / σ_0 (tight carry-σ
// shrinks in lockstep with the likelihood field). This keeps the kernel
// independent of OneShot's `amcl_sigma_seed_xy_schedule_m`, which is
// length-matched to the wide OneShot schedule and would over-spread the
// Live carry cloud.
AmclResult converge_anneal_with_hint(const godo::core::Config&     cfg,
                                     const std::vector<RangeBeam>& beams,
                                     const OccupancyGrid&          grid,
                                     LikelihoodField&              lf_inout,
                                     Amcl&                         amcl,
                                     const Pose2D&                 hint_pose,
                                     double                        sigma_xy_m,
                                     double                        sigma_yaw_deg,
                                     const std::vector<double>&    schedule_m,
                                     Pose2D&                       pose_inout,
                                     Rng&                          rng) {
    Phase0Seed   p0  = Phase0SeedHint{hint_pose, sigma_xy_m, sigma_yaw_deg};
    PerPhaseSeed pps = PerPhaseSeedFromBase{sigma_xy_m};
    return run_anneal_kernel(cfg, beams, grid, lf_inout, amcl,
                             schedule_m, p0, pps, pose_inout, rng);
}

AmclResult converge_anneal(const godo::core::Config&     cfg,
                           const std::vector<RangeBeam>& beams,
                           const OccupancyGrid&          grid,
                           LikelihoodField&              field_inout,
                           Amcl&                         amcl,
                           Pose2D&                       pose_inout,
                           Rng&                          rng) {
    // issue#3 — pose hint check. UDS handler stored a finite, in-range
    // bundle and lifted the flag with release ordering BEFORE
    // g_amcl_mode = OneShot was stored (uds_server.cpp Mode-A M3 pin).
    // Acquire-load here gives us happens-after on both the bundle bytes
    // and the OneShot mode that brought us into this kernel. Consume-once
    // clearing belongs to OneShot (run_one_iteration); this wrapper does
    // not touch the flag.
    const bool have_hint = godo::rt::g_calibrate_hint_valid.load(
        std::memory_order_acquire);

    if (have_hint) {
        const godo::rt::HintBundle hint =
            godo::rt::g_calibrate_hint_data.load();
        const double seed_xy_h = (hint.sigma_xy_m > 0.0)
            ? hint.sigma_xy_m
            : cfg.amcl_hint_sigma_xy_m_default;
        const double seed_yaw_h = (hint.sigma_yaw_deg > 0.0)
            ? hint.sigma_yaw_deg
            : cfg.amcl_hint_sigma_yaw_deg_default;
        Pose2D hint_pose{};
        hint_pose.x       = hint.x_m;
        hint_pose.y       = hint.y_m;
        hint_pose.yaw_deg = hint.yaw_deg;
        return converge_anneal_with_hint(cfg, beams, grid, field_inout, amcl,
                                         hint_pose, seed_xy_h, seed_yaw_h,
                                         cfg.amcl_sigma_hit_schedule_m,
                                         pose_inout, rng);
    }

    // No hint — phase 0 seeds globally (legacy OneShot path).
    Phase0Seed   p0  = Phase0SeedGlobal{};
    PerPhaseSeed pps = PerPhaseSeedFromSchedule{
        &cfg.amcl_sigma_seed_xy_schedule_m};
    return run_anneal_kernel(cfg, beams, grid, field_inout, amcl,
                             cfg.amcl_sigma_hit_schedule_m, p0, pps,
                             pose_inout, rng);
}

// Track D-5 (Q2 / S4) — At OneShot completion, rebuild `lf` back to
// cfg.amcl_sigma_hit_m and re-point `amcl` at it. Live re-entry then sees
// the operator-controlled σ field, never the annealing-leftover narrow
// final-phase field. Cost: one EDT rebuild (~50 ms) on the cold path
// between OneShot completion and the next Live entry — not on the 10 Hz
// Live tick.
void rebuild_lf_for_live(const godo::core::Config& cfg,
                         const OccupancyGrid&      grid,
                         LikelihoodField&          lf_inout,
                         Amcl&                     amcl) {
    lf_inout = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    amcl.set_field(lf_inout);
}

namespace {

// Build a LastScan snapshot from the same Frame the AMCL kernel just
// processed. Mirrors the `downsample()` filter rule from scan_ops.cpp
// (drop distance_mm <= 0 and out-of-range samples; respect stride) so
// the wire dots are aligned with the AMCL beams. Emits both arrays in
// LiDAR-frame polar; the SPA does the world-frame transform using the
// pose anchor baked into the same snapshot.
//
// The cold writer is intentionally OFF the [rt-alloc-grep] allow-list
// (build.sh:25-29 documents this); however this snapshot construction
// avoids std::vector / std::string regardless, since the LastScan is a
// fixed-size POD and the loop only writes into pre-allocated arrays.
void fill_last_scan(godo::rt::LastScan& snap,
                    const godo::core::Config& cfg,
                    const godo::lidar::Frame& frame,
                    const godo::localization::AmclResult& result) {
    snap.pose_x_m          = result.pose.x;
    snap.pose_y_m          = result.pose.y;
    snap.pose_yaw_deg      = result.pose.yaw_deg;
    snap.published_mono_ns =
        static_cast<std::uint64_t>(godo::rt::monotonic_ns());
    snap.iterations        = result.iterations;
    snap.valid             = 1;
    // forced + pose_valid are filled in by the caller (kernel knows mode).
    snap._pad0             = 0;
    snap._pad1             = 0;
    std::memset(snap._pad2, 0, sizeof(snap._pad2));

    const int stride_cfg = cfg.amcl_downsample_stride;
    const int stride = (stride_cfg > 0) ? stride_cfg : 1;
    const double range_min = cfg.amcl_range_min_m;
    const double range_max = cfg.amcl_range_max_m;

    constexpr std::size_t kCap =
        static_cast<std::size_t>(godo::constants::LAST_SCAN_RANGES_MAX);
    std::size_t out = 0;
    if (range_max > range_min) {
        for (std::size_t i = 0;
             i < frame.samples.size() && out < kCap;
             i += static_cast<std::size_t>(stride)) {
            const auto& s = frame.samples[i];
            if (s.distance_mm <= 0.0) continue;
            const double r_m = s.distance_mm / godo::constants::MM_PER_M;
            if (r_m < range_min || r_m > range_max) continue;
            snap.angles_deg[out] = s.angle_deg;
            snap.ranges_m[out]   = r_m;
            ++out;
        }
    }
    snap.n = static_cast<std::uint16_t>(out);
    // Zero-fill the unused tail so the seqlock payload is bit-exact across
    // publishes (Mode-A TB1 torn-read invariant relies on this).
    for (std::size_t i = out; i < kCap; ++i) {
        snap.angles_deg[i] = 0.0;
        snap.ranges_m[i]   = 0.0;
    }
}

}  // namespace

AmclResult run_one_iteration(const godo::core::Config&         cfg,
                             const godo::lidar::Frame&         frame,
                             const OccupancyGrid&              grid,
                             LikelihoodField&                  lf_inout,
                             Amcl&                             amcl,
                             Rng&                              rng,
                             std::vector<RangeBeam>&           beams_buf,
                             Pose2D&                           last_pose_inout,
                             bool&                             live_first_iter_inout,
                             godo::rt::Offset&                 last_written_inout,
                             godo::rt::Seqlock<godo::rt::Offset>& target_offset,
                             godo::rt::Seqlock<godo::rt::LastPose>& last_pose_seq,
                             godo::rt::Seqlock<godo::rt::LastScan>& last_scan_seq,
                             godo::rt::AmclRateAccumulator&    amcl_rate_accum,
                             godo::rt::Seqlock<godo::core::HotConfig>& hot_cfg_seq) {
    // issue#11 P4-2-11-0 — Trim Phase-0: reset thread-local accumulators
    // + capture scan-start mono ns when env latch is on. Zero overhead
    // when off (single bool branch).
    std::int64_t phase0_scan_start_ns = 0;
    if (kPhase0On) phase0_reset_and_stamp_start(phase0_scan_start_ns);

    // 0. PR-DIAG (Mode-A M2): record this AMCL iteration into the rate
    //    accumulator. Single seqlock store; no allocation; only the cold
    //    writer (this function + run_live_iteration) is allowed to call
    //    record(). [amcl-rate-publisher-grep] enforces.
    amcl_rate_accum.record(
        static_cast<std::uint64_t>(godo::rt::monotonic_ns()));

    // 0b. Track B-CONFIG (PR-CONFIG-β): pull the hot-class Tier-2 keys
    //     from the seqlock once per iteration. Wait-free read (~30 ns).
    //     `hot.valid == 0` only on a fixture that did not publish; fall
    //     back to `cfg` so the kernel stays correct under tests.
    const godo::core::HotConfig hot = hot_cfg_seq.load();
    const double deadband_mm  = hot.valid ? hot.deadband_mm  : cfg.deadband_mm;
    const double deadband_deg = hot.valid ? hot.deadband_deg : cfg.deadband_deg;
    const double yaw_tripwire = hot.valid ? hot.amcl_yaw_tripwire_deg
                                          : cfg.amcl_yaw_tripwire_deg;

    // 1. Decimate the scan into AMCL beams.
    downsample(frame,
               cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m,
               cfg.amcl_range_max_m,
               beams_buf);

    // 2. Track D-5 — Coarse-to-fine sigma_hit annealing. Replaces the
    //    Phase 4-2 D single-shot `seed_global → converge` pair. Phase 0
    //    seeds globally at wide σ for basin lock; subsequent phases
    //    seed_around the carried pose and tighten σ down to the
    //    production default. `lf_inout` is mutated in place across phases;
    //    we restore it to cfg.amcl_sigma_hit_m below so Live re-entry
    //    sees the operator-controlled σ field (Q2 / Mode-A S4).
    Pose2D anneal_pose{};
    AmclResult result = converge_anneal(cfg, beams_buf, grid,
                                        lf_inout, amcl, anneal_pose, rng);

    // 4. Tripwire — informational only. Runs ONCE on the final-phase
    //    result only (Mode-A M6); intermediate-phase poses are NOT
    //    tripwire candidates and converge_anneal deliberately does not
    //    check them.
    //
    // issue#28: yaw frame SSOT is the active map YAML `origin[2]`,
    // parsed into `grid.origin_yaw_deg`. The legacy cfg
    // `amcl.origin_yaw_deg` field was hard-removed in issue#28.1.
    if (apply_yaw_tripwire(result.pose,
                           grid.origin_yaw_deg,
                           yaw_tripwire)) {
        std::fprintf(stderr,
            "cold_writer: yaw tripwire fired — pose.yaw=%.3f deg "
            "vs origin.yaw=%.3f deg (tripwire=%.3f deg). Studio base "
            "may have rotated; re-run calibration when convenient.\n",
            result.pose.yaw_deg, grid.origin_yaw_deg,
            yaw_tripwire);
    }

    // 5. Compute Offset against calibration origin (M3 canonical-360 dyaw).
    Pose2D origin{};
    origin.x       = cfg.amcl_origin_x_m;
    origin.y       = cfg.amcl_origin_y_m;
    origin.yaw_deg = grid.origin_yaw_deg;
    result.offset = compute_offset(result.pose, origin);
    result.forced = true;

    // 6. Publish — deadband filter at the seqlock seam (§6.4.1). Forced
    //    OneShot bypasses the deadband; sub-threshold noise is dropped so
    //    the smoother keeps its current ramp instead of restarting.
    //    `last_written_inout` is the local reference only the cold writer
    //    sees (§6.4.1: "Thread-C-local, no atomic"); it stays in lock-step
    //    with the published seqlock value so a long sequence of sub-
    //    deadband updates cannot slow-drift past the threshold.
    (void)apply_deadband_publish(result.offset,
                                 result.forced,
                                 deadband_mm / 1000.0,
                                 deadband_deg,
                                 last_written_inout,
                                 target_offset);

    // 7. Track B — publish LastPose snapshot UNCONDITIONALLY (independent
    //    of the deadband decision above). The UDS `get_last_pose` reader
    //    needs to see every OneShot completion. uds_protocol.md §C.4.
    godo::rt::LastPose snap{};
    snap.x_m               = result.pose.x;
    snap.y_m               = result.pose.y;
    snap.yaw_deg           = result.pose.yaw_deg;
    snap.xy_std_m          = result.xy_std_m;
    snap.yaw_std_deg       = result.yaw_std_deg;
    snap.published_mono_ns = static_cast<std::uint64_t>(godo::rt::monotonic_ns());
    snap.iterations        = result.iterations;
    snap.valid             = 1;
    snap.converged         = result.converged ? std::uint8_t{1} : std::uint8_t{0};
    snap.forced            = std::uint8_t{1};
    snap._pad0             = 0;
    last_pose_seq.store(snap);

    // 8. Track D — publish LastScan snapshot UNCONDITIONALLY (same seam,
    //    same ordering discipline as LastPose). uds_protocol.md §C.5.
    //    Mode-A M3: pose_valid mirrors LastPose.converged so the SPA can
    //    distinguish a legitimate (0,0,0) anchor pose from a non-converged
    //    AMCL run that happened to publish (0,0,0) as garbage.
    godo::rt::LastScan scan_snap{};
    fill_last_scan(scan_snap, cfg, frame, result);
    scan_snap.forced     = std::uint8_t{1};
    scan_snap.pose_valid = result.converged ? std::uint8_t{1} : std::uint8_t{0};
    last_scan_seq.store(scan_snap);

    // `last_pose_inout` (the AMCL particle-cloud seed for the next
    // iteration) is updated unconditionally — a rejected publish is not
    // a rejected pose estimate (§6.4.1). `live_first_iter_inout` is
    // cleared so the operator-visible "OneShot then Live" sequence does
    // not double-seed-global on Live entry — but Live's `on_leave_live`
    // re-arms the latch on every Live exit, so this is mainly for state
    // hygiene (OneShot does not consult the latch for its own seed).
    last_pose_inout = result.pose;
    live_first_iter_inout = false;

    // Track D-5 (Q2) — Restore lf to cfg.amcl_sigma_hit_m so the next
    // Live entry uses the operator-controlled σ field, not the annealing
    // schedule's narrow final-phase σ. Cost: one EDT rebuild on the cold
    // path; off the 10 Hz Live tick.
    rebuild_lf_for_live(cfg, grid, lf_inout, amcl);

    // issue#3 — consume-once: cold writer is the SOLE clearer of the
    // calibrate-hint flag (production CODEBASE invariant (p)). Clearing
    // unconditionally is correct: if the flag was already false (no
    // hint this OneShot), the store is a no-op; if it was true, we just
    // consumed it and the next OneShot starts with a fresh global seed
    // unless the operator places a new hint via webctl.
    godo::rt::g_calibrate_hint_valid.store(false, std::memory_order_release);

    if (kPhase0On) phase0_emit("oneshot", phase0_scan_start_ns, result.iterations);
    return result;
}

AmclResult run_live_iteration(const godo::core::Config&         cfg,
                              const godo::lidar::Frame&         frame,
                              const OccupancyGrid&              grid,
                              Amcl&                             amcl,
                              Rng&                              rng,
                              std::vector<RangeBeam>&           beams_buf,
                              Pose2D&                           last_pose_inout,
                              bool&                             live_first_iter_inout,
                              godo::rt::Offset&                 last_written_inout,
                              godo::rt::Seqlock<godo::rt::Offset>& target_offset,
                              godo::rt::Seqlock<godo::rt::LastPose>& last_pose_seq,
                              godo::rt::Seqlock<godo::rt::LastScan>& last_scan_seq,
                              godo::rt::AmclRateAccumulator&    amcl_rate_accum,
                              godo::rt::Seqlock<godo::core::HotConfig>& hot_cfg_seq) {
    // issue#11 P4-2-11-0 — Trim Phase-0 (mirror of run_one_iteration).
    std::int64_t phase0_scan_start_ns = 0;
    if (kPhase0On) phase0_reset_and_stamp_start(phase0_scan_start_ns);

    // 0. PR-DIAG (Mode-A M2): record this AMCL iteration into the rate
    //    accumulator. Mirrors run_one_iteration's record() pin.
    amcl_rate_accum.record(
        static_cast<std::uint64_t>(godo::rt::monotonic_ns()));

    // 0b. Track B-CONFIG (PR-CONFIG-β): hot-class Tier-2 keys, see
    //     run_one_iteration for the contract pin.
    const godo::core::HotConfig hot = hot_cfg_seq.load();
    const double deadband_mm  = hot.valid ? hot.deadband_mm  : cfg.deadband_mm;
    const double deadband_deg = hot.valid ? hot.deadband_deg : cfg.deadband_deg;
    const double yaw_tripwire = hot.valid ? hot.amcl_yaw_tripwire_deg
                                          : cfg.amcl_yaw_tripwire_deg;

    // 1. Decimate the scan into AMCL beams (same shape as OneShot).
    downsample(frame,
               cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m,
               cfg.amcl_range_max_m,
               beams_buf);

    // 2. Seed branch. First Live iteration since (re-)entering Live mode
    //    seeds globally — the OneShot cloud may be tightly converged
    //    (xy_std < 15 mm), too tight for σ_live_xy = 15 mm to track a
    //    base moving at ~30 cm/s. A wide cloud at Live entry lets the
    //    sensor model refine on iteration 1; subsequent iterations re-
    //    seed around `last_pose` so the tracker does not throw away the
    //    pose it just refined.
    if (live_first_iter_inout) {
        amcl.seed_global(grid, rng);
    } else {
        amcl.seed_around(last_pose_inout,
                         cfg.amcl_sigma_seed_xy_m,
                         cfg.amcl_sigma_seed_yaw_deg,
                         rng);
    }

    // 3. Single AMCL iteration with the Live σ pair.
    AmclResult result = amcl.step(beams_buf, rng,
                                  cfg.amcl_sigma_xy_jitter_live_m,
                                  cfg.amcl_sigma_yaw_jitter_live_deg);

    // 4. Tripwire — informational only (same as OneShot).
    //    issue#28: yaw frame SSOT is grid.origin_yaw_deg.
    if (apply_yaw_tripwire(result.pose,
                           grid.origin_yaw_deg,
                           yaw_tripwire)) {
        std::fprintf(stderr,
            "cold_writer: yaw tripwire fired (Live) — pose.yaw=%.3f deg "
            "vs origin.yaw=%.3f deg (tripwire=%.3f deg). Studio base "
            "may have rotated; re-run calibration when convenient.\n",
            result.pose.yaw_deg, grid.origin_yaw_deg,
            yaw_tripwire);
    }

    // 5. Compute Offset against calibration origin (M3 canonical-360 dyaw).
    Pose2D origin{};
    origin.x       = cfg.amcl_origin_x_m;
    origin.y       = cfg.amcl_origin_y_m;
    origin.yaw_deg = grid.origin_yaw_deg;
    result.offset = compute_offset(result.pose, origin);
    result.forced = false;            // Live publishes through the deadband

    // 6. Publish — deadband filter at the seqlock seam (§6.4.1).
    (void)apply_deadband_publish(result.offset,
                                 result.forced,
                                 deadband_mm / 1000.0,
                                 deadband_deg,
                                 last_written_inout,
                                 target_offset);

    // 7. Track B — publish LastPose snapshot UNCONDITIONALLY (independent
    //    of the deadband decision above). uds_protocol.md §C.4.
    godo::rt::LastPose snap{};
    snap.x_m               = result.pose.x;
    snap.y_m               = result.pose.y;
    snap.yaw_deg           = result.pose.yaw_deg;
    snap.xy_std_m          = result.xy_std_m;
    snap.yaw_std_deg       = result.yaw_std_deg;
    snap.published_mono_ns = static_cast<std::uint64_t>(godo::rt::monotonic_ns());
    snap.iterations        = result.iterations;
    snap.valid             = 1;
    snap.converged         = result.converged ? std::uint8_t{1} : std::uint8_t{0};
    snap.forced            = std::uint8_t{0};       // Live publishes forced=0
    snap._pad0             = 0;
    last_pose_seq.store(snap);

    // 8. Track D — publish LastScan snapshot UNCONDITIONALLY (Live mirror
    //    of the OneShot publish; uds_protocol.md §C.5). Mode-A M3 pin:
    //    pose_valid mirrors AmclResult.converged so the SPA can dim the
    //    overlay when AMCL is still settling.
    godo::rt::LastScan scan_snap{};
    fill_last_scan(scan_snap, cfg, frame, result);
    scan_snap.forced     = std::uint8_t{0};         // Live publishes forced=0
    scan_snap.pose_valid = result.converged ? std::uint8_t{1} : std::uint8_t{0};
    last_scan_seq.store(scan_snap);

    // 9. Update Live state. `last_pose` is updated unconditionally;
    //    `live_first_iter` flips to false so the next iteration re-seeds
    //    around the freshly refined pose.
    last_pose_inout = result.pose;
    live_first_iter_inout = false;
    if (kPhase0On) phase0_emit("live_legacy", phase0_scan_start_ns, result.iterations);
    return result;
}

// issue#5 — Per-Live-iteration pipelined-hint kernel. Runs sequential K-step
// `converge_anneal_with_hint` driven by the previous-tick pose with tight σ
// and a short schedule. Sole caller of converge_anneal_with_hint from the
// Live cold-path branch (production CODEBASE invariant (q)).
//
// Hint source contract (`last_pose_inout`):
//   - tick t=0 after Live entry: `last_pose_inout` carries the most recent
//     OneShot pose OR the previous Live session's last pose (preserved
//     across Idle re-entry). The cold-start guard in run_cold_writer's
//     Live-case body ensures `last_pose_set` is true before this function
//     is reachable; we trust the caller and do NOT re-check here.
//   - tick t≥1: `last_pose_inout` is the previous tick's converged pose.
//
// σ pair: cfg.amcl_live_carry_sigma_xy_m / _yaw_deg. Tight, matched to
// inter-tick crane-base drift, NOT padded for AMCL search comfort
// (`project_hint_strong_command_semantics.md`). Operators widen via
// tracker.toml if HIL shows wider drift.
//
// Schedule: cfg.amcl_live_carry_schedule_m. Short by design — basin lock
// is automatic at σ=0.05 m carry-σ, so the wide-σ phases of OneShot
// (1.0, 0.5) waste depth. See config_defaults.hpp comment block.
//
// Side effects mirror run_live_iteration: deadband-filtered Offset
// publish, unconditional LastPose + LastScan publish, AMCL rate record.
// `result.forced = false` always; deadband applies. `live_first_iter_inout`
// is intentionally unused here (the latch belongs to the rollback path).
AmclResult run_live_iteration_pipelined(
    const godo::core::Config&                     cfg,
    const godo::lidar::Frame&                     frame,
    const OccupancyGrid&                          grid,
    LikelihoodField&                              lf_inout,
    Amcl&                                         amcl,
    Rng&                                          rng,
    std::vector<RangeBeam>&                       beams_buf,
    Pose2D&                                       last_pose_inout,
    godo::rt::Offset&                             last_written_inout,
    godo::rt::Seqlock<godo::rt::Offset>&          target_offset,
    godo::rt::Seqlock<godo::rt::LastPose>&        last_pose_seq,
    godo::rt::Seqlock<godo::rt::LastScan>&        last_scan_seq,
    godo::rt::AmclRateAccumulator&                amcl_rate_accum,
    godo::rt::Seqlock<godo::core::HotConfig>&     hot_cfg_seq) {
    // issue#11 P4-2-11-0 — Trim Phase-0 (mirror of run_one_iteration).
    std::int64_t phase0_scan_start_ns = 0;
    if (kPhase0On) phase0_reset_and_stamp_start(phase0_scan_start_ns);

    // 0. PR-DIAG (Mode-A M2): record this AMCL iteration into the rate
    //    accumulator. Mirrors run_one_iteration / run_live_iteration.
    amcl_rate_accum.record(
        static_cast<std::uint64_t>(godo::rt::monotonic_ns()));

    // 0b. Track B-CONFIG (PR-CONFIG-β): hot-class Tier-2 keys, see
    //     run_one_iteration for the contract pin.
    const godo::core::HotConfig hot = hot_cfg_seq.load();
    const double deadband_mm  = hot.valid ? hot.deadband_mm  : cfg.deadband_mm;
    const double deadband_deg = hot.valid ? hot.deadband_deg : cfg.deadband_deg;
    const double yaw_tripwire = hot.valid ? hot.amcl_yaw_tripwire_deg
                                          : cfg.amcl_yaw_tripwire_deg;

    // 1. Decimate the scan into AMCL beams.
    downsample(frame,
               cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m,
               cfg.amcl_range_max_m,
               beams_buf);

    // 2. Run the pipelined-hint kernel. Hint = previous-tick pose.
    //    Schedule + σ from the Live carry-keys (distinct from OneShot).
    Pose2D anneal_pose{};
    AmclResult result = converge_anneal_with_hint(
        cfg, beams_buf, grid, lf_inout, amcl,
        last_pose_inout,
        cfg.amcl_live_carry_sigma_xy_m,
        cfg.amcl_live_carry_sigma_yaw_deg,
        cfg.amcl_live_carry_schedule_m,
        anneal_pose, rng);

    // 3. Tripwire — informational only (mirror of OneShot / Live legacy).
    //    issue#28: yaw frame SSOT is grid.origin_yaw_deg.
    if (apply_yaw_tripwire(result.pose,
                           grid.origin_yaw_deg,
                           yaw_tripwire)) {
        std::fprintf(stderr,
            "cold_writer: yaw tripwire fired (Live pipelined) — pose.yaw=%.3f deg "
            "vs origin.yaw=%.3f deg (tripwire=%.3f deg). Studio base "
            "may have rotated; re-run calibration when convenient.\n",
            result.pose.yaw_deg, grid.origin_yaw_deg,
            yaw_tripwire);
    }

    // 4. Compute Offset against calibration origin.
    Pose2D origin{};
    origin.x       = cfg.amcl_origin_x_m;
    origin.y       = cfg.amcl_origin_y_m;
    origin.yaw_deg = grid.origin_yaw_deg;
    result.offset = compute_offset(result.pose, origin);
    result.forced = false;            // Live publishes through the deadband

    // 5. Publish — deadband filter at the seqlock seam (§6.4.1).
    (void)apply_deadband_publish(result.offset,
                                 result.forced,
                                 deadband_mm / 1000.0,
                                 deadband_deg,
                                 last_written_inout,
                                 target_offset);

    // 6. Track B — publish LastPose snapshot UNCONDITIONALLY.
    godo::rt::LastPose snap{};
    snap.x_m               = result.pose.x;
    snap.y_m               = result.pose.y;
    snap.yaw_deg           = result.pose.yaw_deg;
    snap.xy_std_m          = result.xy_std_m;
    snap.yaw_std_deg       = result.yaw_std_deg;
    snap.published_mono_ns = static_cast<std::uint64_t>(godo::rt::monotonic_ns());
    snap.iterations        = result.iterations;
    snap.valid             = 1;
    snap.converged         = result.converged ? std::uint8_t{1} : std::uint8_t{0};
    snap.forced            = std::uint8_t{0};       // Live publishes forced=0
    snap._pad0             = 0;
    last_pose_seq.store(snap);

    // 7. Track D — publish LastScan snapshot UNCONDITIONALLY.
    godo::rt::LastScan scan_snap{};
    fill_last_scan(scan_snap, cfg, frame, result);
    scan_snap.forced     = std::uint8_t{0};         // Live publishes forced=0
    scan_snap.pose_valid = result.converged ? std::uint8_t{1} : std::uint8_t{0};
    last_scan_seq.store(scan_snap);

    // 8. Update Live state. `last_pose_inout` is updated unconditionally;
    //    on the next tick this becomes the hint. Note: NEVER touch
    //    g_calibrate_hint_*; consume-once is OneShot-only. The legacy
    //    `live_first_iter` latch is intentionally not consulted on the
    //    pipelined path.
    last_pose_inout = result.pose;
    if (kPhase0On) phase0_emit("live_pipelined", phase0_scan_start_ns, result.iterations);
    return result;
}

namespace {

// Helper: convert a poll interval in milliseconds to a timespec for nanosleep.
timespec poll_period_ts(int poll_ms) noexcept {
    timespec ts{};
    if (poll_ms <= 0) { ts.tv_sec = 0; ts.tv_nsec = 1'000'000; return ts; }
    ts.tv_sec  = poll_ms / 1000;
    ts.tv_nsec = static_cast<long>(poll_ms % 1000) * 1'000'000L;
    return ts;
}

// Re-arm the live-first-iter latch on every Live → {Idle, OneShot} exit.
// Rationale: the next Live entry must seed_global so it can recover from
// a base move that happened while we were Idle. Without this reset, a
// tight OneShot/Live cloud would not have the spread to discover the new
// pose under motion, and σ_live_xy = 15 mm jitter alone would not pull
// the cloud across a multi-cm shift on the first scan after re-entry.
void on_leave_live(bool& live_first_iter_inout) noexcept {
    live_first_iter_inout = true;
}

}  // namespace

void run_cold_writer(const godo::core::Config&              cfg,
                     godo::rt::Seqlock<godo::rt::Offset>&   target_offset,
                     godo::rt::Seqlock<godo::rt::LastPose>& last_pose_seq,
                     godo::rt::Seqlock<godo::rt::LastScan>& last_scan_seq,
                     godo::rt::AmclRateAccumulator&         amcl_rate_accum,
                     godo::rt::Seqlock<godo::core::HotConfig>& hot_cfg_seq,
                     LidarFactory                           lidar_factory) {
    OccupancyGrid grid;
    LikelihoodField lf;
    try {
        grid = load_map(cfg.amcl_map_path);
        lf   = build_likelihood_field(grid, cfg.amcl_sigma_hit_m);
    } catch (const std::exception& e) {
        std::fprintf(stderr,
            "cold_writer: failed to load map '%s' or build likelihood "
            "field: %s\n",
            cfg.amcl_map_path.c_str(), e.what());
        godo::rt::g_running.store(false, std::memory_order_release);
        return;
    }

    Amcl amcl(cfg, lf);
    Rng  rng(cfg.amcl_seed);
    Pose2D last_pose{};
    bool live_first_iter = true;

    // issue#5 — Cold-start guard for the pipelined Live path. Set to true
    // ONLY after a successful OneShot completion (run_one_iteration end)
    // OR after the first successful pipelined Live tick (when seeding from
    // a prior OneShot pose has already produced a converged pose). Reading
    // this flag is preferred over comparing `last_pose` to (0,0,0): a
    // legitimate OneShot result of pose=(0.0, 0.0, 0.0°) is operator-allowed
    // (calibration origin defaults are 0), so a value-comparison guard
    // would falsely reject Live re-entry after such a OneShot.
    bool last_pose_set = false;

    // Thread-C-local reference for the deadband filter (§6.4.1).
    // Initialised to {0, 0, 0} to match the seqlock's default-constructed
    // payload and the smoother's `live = prev = target = {0, 0, 0}` start
    // state (§6.4.2) — the very first AMCL fix should always publish (any
    // non-zero Offset is supra-deadband against a zero baseline; an
    // exactly-zero first fix would be a no-op publish either way).
    godo::rt::Offset last_written{0.0, 0.0, 0.0};

    std::vector<RangeBeam> beams_buf;
    beams_buf.reserve(godo::constants::SCAN_BEAMS_MAX);

    std::unique_ptr<godo::lidar::LidarSourceRplidar> lidar;
    try {
        lidar = lidar_factory ? lidar_factory() : nullptr;
    } catch (const std::exception& e) {
        // Non-fatal: stay in Idle so the FreeD path remains functional even
        // when no LiDAR is plugged in (e.g. test_rt_replay E2E, dry-runs).
        // OneShot triggers will be rejected with an actionable error.
        std::fprintf(stderr,
            "cold_writer: lidar_factory threw: %s — continuing without "
            "LiDAR (OneShot triggers will be ignored until a source is "
            "available).\n", e.what());
        lidar.reset();
    }

    const timespec poll_ts = poll_period_ts(cfg.amcl_trigger_poll_ms);

    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        const auto mode = godo::rt::g_amcl_mode.load(std::memory_order_acquire);

        switch (mode) {
            case godo::rt::AmclMode::Idle: {
                // Sleep one poll period; SIGTERM EINTR exits immediately,
                // and on the next iteration g_running will be false.
                ::nanosleep(&poll_ts, nullptr);
                break;
            }

            case godo::rt::AmclMode::OneShot: {
                if (!lidar) {
                    std::fprintf(stderr,
                        "cold_writer: OneShot requested but no LiDAR source "
                        "available (factory returned nullptr); ignoring.\n");
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    on_leave_live(live_first_iter);
                    break;
                }
                godo::lidar::Frame captured{};
                bool got_frame = false;
                try {
                    lidar->scan_frames(1, [&](int /*idx*/,
                                              const godo::lidar::Frame& f) {
                        captured  = f;
                        got_frame = true;
                    });
                } catch (const std::exception& e) {
                    // M8 SIGTERM watchdog: the underlying SDK driver does
                    // not surface EINTR via errno (it loops on grabScanDataHq
                    // up to 5 times then throws "5 times in a row"). EINTR
                    // here is also unreliable because std::exception's
                    // string-buffer ctor and the unwinder may have
                    // clobbered it. We rely instead on the outer
                    // g_running check + the !got_frame branch + the SDK's
                    // 5-retry budget — within a few hundred ms of SIGTERM
                    // the loop top sees g_running=false and returns.
                    // (S3 mitigation, Mode-B follow-up.)
                    std::fprintf(stderr,
                        "cold_writer: scan_frames(1) threw: %s — "
                        "returning to Idle.\n", e.what());
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    on_leave_live(live_first_iter);
                    break;
                }
                if (!got_frame) {
                    // Source exited without delivering a frame (likely
                    // SIGTERM). If g_running is now false, top of the loop
                    // will exit.
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    on_leave_live(live_first_iter);
                    break;
                }
                try {
                    (void)run_one_iteration(cfg, captured, grid, lf, amcl, rng,
                                            beams_buf, last_pose,
                                            live_first_iter,
                                            last_written, target_offset,
                                            last_pose_seq, last_scan_seq,
                                            amcl_rate_accum, hot_cfg_seq);
                    // issue#5 — A successful OneShot anchors the cold-start
                    // for the pipelined Live path. Flag flips here, NEVER
                    // on a thrown converge.
                    last_pose_set = true;
                } catch (const std::exception& e) {
                    std::fprintf(stderr,
                        "cold_writer: run_one_iteration threw: %s — "
                        "returning to Idle.\n", e.what());
                    // Defensive: if converge_anneal threw mid-phase,
                    // lf may hold an intermediate σ. Restore for Live.
                    try {
                        rebuild_lf_for_live(cfg, grid, lf, amcl);
                    } catch (...) {
                        // If the rebuild itself fails, log + continue;
                        // the next OneShot will rebuild from scratch.
                        std::fprintf(stderr,
                            "cold_writer: rebuild_lf_for_live recovery "
                            "failed; lf may be in unspecified state.\n");
                    }
                }
                // SSOT: last_pose_seq.store BEFORE g_amcl_mode = Idle (Track B race pin).
                // Reader (godo-mapping/scripts/repeatability.py) polls get_mode==Idle
                // then reads get_last_pose; without this ordering the reader can see the
                // new Idle mode and the stale pose from a previous OneShot.
                godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                            std::memory_order_release);
                // OneShot → Idle is a Live exit too — re-arm so the next
                // operator Live toggle starts with seed_global.
                on_leave_live(live_first_iter);
                break;
            }

            case godo::rt::AmclMode::Live: {
                if (!lidar) {
                    std::fprintf(stderr,
                        "cold_writer: Live requested but no LiDAR source "
                        "available; returning to Idle.\n");
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    on_leave_live(live_first_iter);
                    break;
                }
                // issue#5 — Cold-start guard for the pipelined path.
                // Reject Live entry when (a) the operator selected the
                // pipelined kernel via cfg.live_carry_pose_as_hint AND
                // (b) no prior OneShot has run in this session (so
                // `last_pose` is the default-zero seed and is NOT a
                // converged pose). The rollback path is unaffected — its
                // first iteration runs seed_global so it can recover from
                // arbitrary state.
                if (cfg.live_carry_pose_as_hint && !last_pose_set) {
                    std::fprintf(stderr,
                        "cold_writer: Live (pipelined-hint kernel) requires "
                        "a prior OneShot or pose-hint-driven OneShot in this "
                        "session — `last_pose` is unset. Bouncing to Idle. "
                        "Run Calibrate first, then re-toggle Live.\n");
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    on_leave_live(live_first_iter);
                    break;
                }
                godo::lidar::Frame captured{};
                bool got_frame = false;
                try {
                    // scan_frames(1) blocks at the LiDAR's natural ~10 Hz
                    // spin rate, so the Live loop is rate-limited by the
                    // sensor itself — no nanosleep needed. (Audit: see
                    // LidarSourceRplidar::scan_frames; grabScanDataHq is
                    // SDK-blocking.) Plan §"Risks" tracks the spin-loop
                    // defence as a follow-up if the assumption breaks.
                    lidar->scan_frames(1, [&](int /*idx*/,
                                              const godo::lidar::Frame& f) {
                        captured  = f;
                        got_frame = true;
                    });
                } catch (const std::exception& e) {
                    // Same M8 SIGTERM pattern as OneShot.
                    std::fprintf(stderr,
                        "cold_writer: scan_frames(1) threw in Live: %s — "
                        "returning to Idle.\n", e.what());
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    on_leave_live(live_first_iter);
                    break;
                }
                if (!got_frame) {
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    on_leave_live(live_first_iter);
                    break;
                }
                // Re-check g_amcl_mode AFTER the blocking scan so a
                // Live → {Idle, OneShot} toggle mid-scan reaches the new
                // mode on the next iteration without first publishing a
                // stale Live update.
                if (godo::rt::g_amcl_mode.load(std::memory_order_acquire) !=
                    godo::rt::AmclMode::Live) {
                    on_leave_live(live_first_iter);
                    break;
                }
                try {
                    if (cfg.live_carry_pose_as_hint) {
                        // issue#5 — pipelined-hint Live kernel. last_pose
                        // is the carry source; flag enforced above ensures
                        // it's a converged pose (not default zero).
                        (void)run_live_iteration_pipelined(
                            cfg, captured, grid, lf, amcl, rng,
                            beams_buf, last_pose,
                            last_written, target_offset,
                            last_pose_seq, last_scan_seq,
                            amcl_rate_accum, hot_cfg_seq);
                        // After the first successful pipelined tick
                        // last_pose carries a fresh converged pose;
                        // a subsequent OneShot exit followed by another
                        // pipelined Live re-entry can rely on the flag
                        // even if the user did not run another Calibrate.
                        last_pose_set = true;
                    } else {
                        (void)run_live_iteration(cfg, captured, grid, amcl, rng,
                                                 beams_buf, last_pose,
                                                 live_first_iter,
                                                 last_written, target_offset,
                                                 last_pose_seq, last_scan_seq,
                                                 amcl_rate_accum, hot_cfg_seq);
                    }
                } catch (const std::exception& e) {
                    std::fprintf(stderr,
                        "cold_writer: Live iteration threw: %s — "
                        "returning to Idle.\n", e.what());
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    on_leave_live(live_first_iter);
                    break;
                }
                // Stay in Live; scan_frames(1) is the natural rate limiter.
                break;
            }
        }
    }

    // RAII tears down the SDK driver via the LidarSourceRplidar destructor
    // (unique_ptr → ~LidarSourceRplidar → ~Impl → stop_and_disconnect).
}

}  // namespace godo::localization
