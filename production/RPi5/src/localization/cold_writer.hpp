#pragma once

// Cold writer — AMCL state machine that publishes Offsets to the hot path.
//
// State machine (see plan §6.1.3):
//   Idle    — poll g_amcl_mode every cfg.amcl_trigger_poll_ms; sleep otherwise.
//   OneShot — capture one frame, run Amcl::converge, publish Offset, return
//             to Idle. Sets `result.forced = true` so Phase 4-2 C deadband
//             can pass operator-driven calibrates through unconditionally.
//   Live    — Phase 4-2 D body. Wave 2 implementation: log-once and bounce
//             back to Idle. The branch lives in the state machine so 4-2 D
//             becomes "fill the body", not "rewrite the cold path".
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
// unconditionally.
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
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "lidar/lidar_source_rplidar.hpp"
#include "lidar/sample.hpp"
#include "occupancy_grid.hpp"
#include "pose.hpp"
#include "rng.hpp"
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
//   - mutates `amcl` (re-seeds, runs converge)
//   - mutates `last_pose_inout`    (set to the result.pose, regardless of
//                                   whether the deadband filter accepts —
//                                   the AMCL particle seed for the next
//                                   iteration is independent of the
//                                   publish state per §6.4.1)
//   - mutates `first_run_inout`    (sets to false on first invocation)
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
AmclResult run_one_iteration(const godo::core::Config&         cfg,
                             const godo::lidar::Frame&         frame,
                             const OccupancyGrid&              grid,
                             Amcl&                             amcl,
                             Rng&                              rng,
                             std::vector<RangeBeam>&           beams_buf,
                             Pose2D&                           last_pose_inout,
                             bool&                             first_run_inout,
                             godo::rt::Offset&                 last_written_inout,
                             godo::rt::Seqlock<godo::rt::Offset>& target_offset);

// Run the cold writer until godo::rt::g_running is false. Idempotent on
// repeated trigger; safe to call once per process lifetime.
void run_cold_writer(const godo::core::Config&     cfg,
                     godo::rt::Seqlock<godo::rt::Offset>& target_offset,
                     LidarFactory                  lidar_factory);

}  // namespace godo::localization
