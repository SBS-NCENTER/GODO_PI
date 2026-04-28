#pragma once

// Cold writer — AMCL state machine that publishes Offsets to the hot path.
//
// State machine (see plan §6.1.3):
//   Idle    — poll g_amcl_mode every cfg.amcl_trigger_poll_ms; sleep otherwise.
//   OneShot — capture one frame, run Amcl::converge, publish Offset, return
//             to Idle. Sets `result.forced = true` so Phase 4-2 C deadband
//             can pass operator-driven calibrates through unconditionally.
//             Phase 4-2 D: ALWAYS seeds globally (no warm-seed shortcut),
//             so a calibrate after a base move converges reliably.
//   Live    — Phase 4-2 D body. Per-scan single Amcl::step() with the wider
//             Live σ pair (cfg.amcl_sigma_xy_jitter_live_m /
//             _yaw_jitter_live_deg), publishing through the deadband
//             (forced=false). Stays in Live until g_amcl_mode is toggled
//             elsewhere (GPIO/UDS in Wave B). On Live entry the
//             `live_first_iter_inout` latch forces a `seed_global` for the
//             first iteration so Live can always pick up after a base
//             move; subsequent iterations re-seed around `last_pose`.
//
// Wait-free contract (M1): no std::mutex / std::shared_mutex /
// std::condition_variable inside this module. The seqlock store is the
// sole synchronization primitive on the AMCL → Thread D path. Pinned by
// scripts/build.sh's no-mutex grep on cold_writer.cpp.
//
// Publish seam (M2): the deadband filter (SYSTEM_DESIGN.md §6.4.1) lives at
// this seam. The cold writer compares `result.offset` against the local
// `last_written` and skips the seqlock store + the `last_written` update
// when every component is strictly inside its per-axis threshold.
// `result.forced == true` (operator-driven OneShot) bypasses the deadband
// unconditionally; Live mode publishes with `forced=false` so noise is
// suppressed and the smoother stays on its current ramp.
//
// SIGTERM watchdog (M8): EINTR returns from any blocking SDK call inside
// `scan_frames` are treated as clean cancellation. `godo_tracker_rt::main`
// calls `pthread_kill(cold_writer_tid, SIGTERM)` on shutdown so a
// blocking `scan_frames(1)` does not delay process exit indefinitely.

#include <functional>
#include <memory>

#include "amcl.hpp"
#include "amcl_result.hpp"
#include "core/config.hpp"
#include "core/hot_config.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "lidar/lidar_source_rplidar.hpp"
#include "lidar/sample.hpp"
#include "occupancy_grid.hpp"
#include "pose.hpp"
#include "rng.hpp"
#include "rt/amcl_rate.hpp"
#include "scan_ops.hpp"

namespace godo::localization {

// Factory that constructs (and `open()`s) a fresh LidarSourceRplidar.
// Injected to keep the production cold writer testable without hardware.
// Production passes a closure that builds a real
// `LidarSourceRplidar(port, baud)`; tests typically bypass the factory and
// drive `run_one_iteration` directly with a synthetic frame.
using LidarFactory =
    std::function<std::unique_ptr<godo::lidar::LidarSourceRplidar>()>;

// Per-OneShot kernel. Visible for tests so they can drive a deterministic
// synthetic Frame through the AMCL pipeline without the LiDAR factory or a
// thread spawn (test_cold_writer_offset_invariant). The production loop
// (`run_cold_writer`) calls this on every OneShot transition (SSOT-DRY).
//
// Side effects:
//   - mutates `amcl` (re-seeds globally, runs converge)
//   - mutates `last_pose_inout`    (set to the result.pose, regardless of
//                                   whether the deadband filter accepts —
//                                   the AMCL particle seed for the next
//                                   iteration is independent of the
//                                   publish state per §6.4.1)
//   - mutates `live_first_iter_inout` (sets to false; OneShot does not
//                                   consult it for its own seed branch —
//                                   OneShot is unconditionally
//                                   `seed_global` per Phase 4-2 D — but
//                                   leaving the latch true after a OneShot
//                                   would be misleading state for a
//                                   subsequent Live entry)
//   - mutates `beams_buf`          (downsample output target)
//   - sets `result.forced = true`  (operator-driven OneShot)
//   - mutates `last_written_inout` ONLY when the deadband filter accepts
//     (or `result.forced` is true) — kept in lock-step with the published
//     seqlock value so a sequence of sub-deadband updates cannot slow-drift
//     the reference past the threshold (§6.4.1)
//   - publishes the resulting Offset to `target_offset` ONLY when the
//     deadband filter accepts or `result.forced` is true; otherwise the
//     seqlock generation is unchanged and the smoother stays on its
//     current ramp
//   - publishes the resulting AMCL pose snapshot to `last_pose_seq`
//     UNCONDITIONALLY (Track B): the UDS `get_last_pose` reader needs to
//     see every OneShot completion, including poses suppressed by the
//     deadband filter. The store happens BEFORE g_amcl_mode = Idle is
//     written by the caller (cold_writer.cpp ordering pin); see F5.
//   - publishes a LastScan snapshot to `last_scan_seq` UNCONDITIONALLY
//     (Track D): the UDS `get_last_scan` reader needs to see every
//     OneShot/Live completion so the SPA's overlay updates at the cold
//     writer's natural cadence. Same ordering discipline as last_pose_seq.
// Track B-CONFIG (PR-CONFIG-β): the kernel reads `hot_cfg_seq.load()`
// once at the head of each iteration to pick up operator edits to the
// Hot-class Tier-2 keys (deadband_mm, deadband_deg, amcl_yaw_tripwire_deg)
// without restart. The non-hot fields of `cfg` (origin, sigma_*, range_*,
// downsample_stride, etc.) are still read directly because they are
// `restart` or `recalibrate` class — changes take effect on next boot or
// next OneShot, not mid-iteration.
//
// `hot.valid == 0` is the boot sentinel (Seqlock<HotConfig> default-
// constructed); the kernel falls back to `cfg.deadband_*` /
// `cfg.amcl_yaw_tripwire_deg` so the OneShot path stays correct even if
// the test fixture forgets to publish before calling. Pinned by
// `test_cold_writer_reads_hot_config.cpp`.
AmclResult run_one_iteration(const godo::core::Config&         cfg,
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
                             godo::rt::Seqlock<godo::core::HotConfig>& hot_cfg_seq);

// Per-Live-iteration kernel. Visible for tests so they can drive a
// deterministic synthetic Frame through the Live AMCL pipeline without
// spawning the cold writer thread. The production loop
// (`run_cold_writer`) calls this on every scan while `g_amcl_mode == Live`.
//
// Differences from `run_one_iteration`:
//   - seeds with `seed_global` only when `live_first_iter_inout == true`,
//     otherwise re-seeds with `seed_around(last_pose, …)`;
//   - calls `Amcl::step(beams, rng, σ_live_xy, σ_live_yaw)` (single
//     iteration with the wider Live motion-model σ pair) instead of
//     `converge()`;
//   - sets `result.forced = false` so the deadband filter applies;
//   - `live_first_iter_inout` is always reset to false at the end of the
//     call (next Live iteration uses `seed_around`).
//
// Other side effects mirror `run_one_iteration`. Returns the AmclResult
// produced by `Amcl::step` (with `result.offset` and `result.forced`
// filled in by this function before publishing).
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
                              godo::rt::Seqlock<godo::core::HotConfig>& hot_cfg_seq);

// Run the cold writer until godo::rt::g_running is false. Idempotent on
// repeated trigger; safe to call once per process lifetime.
//
// `last_pose_seq` (Track B): published UNCONDITIONALLY at the OneShot
// success path (before the deadband filter), so the UDS `get_last_pose`
// reader sees every converged pose even when the deadband filter
// suppresses an Offset publish for a sub-threshold change. See
// production/RPi5/doc/uds_protocol.md §C.4.
//
// `amcl_rate_accum` (PR-DIAG, Mode-A M2 fold): cold writer increments
// this on every OneShot/Live AMCL iteration so the diag publisher can
// derive the AMCL iteration rate exposed via UDS `get_amcl_rate`.
// Build-grep `[amcl-rate-publisher-grep]` enforces that only the cold
// writer (here) calls `record(...)` on this accumulator.
void run_cold_writer(const godo::core::Config&              cfg,
                     godo::rt::Seqlock<godo::rt::Offset>&   target_offset,
                     godo::rt::Seqlock<godo::rt::LastPose>& last_pose_seq,
                     godo::rt::Seqlock<godo::rt::LastScan>& last_scan_seq,
                     godo::rt::AmclRateAccumulator&         amcl_rate_accum,
                     godo::rt::Seqlock<godo::core::HotConfig>& hot_cfg_seq,
                     LidarFactory                           lidar_factory);

}  // namespace godo::localization
