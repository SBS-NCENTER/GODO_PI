#include "cold_writer.hpp"

#include <atomic>
#include <cerrno>
#include <cstdio>
#include <exception>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "core/time.hpp"
#include "deadband.hpp"
#include "likelihood_field.hpp"

namespace godo::localization {

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
                             godo::rt::Seqlock<godo::rt::LastPose>& last_pose_seq) {
    // 1. Decimate the scan into AMCL beams.
    downsample(frame,
               cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m,
               cfg.amcl_range_max_m,
               beams_buf);

    // 2. Phase 4-2 D — OneShot ALWAYS seeds globally. The Phase 4-2 B
    //    "warm-seed on subsequent calls" branch is removed: an operator-
    //    triggered calibrate after a base move must not be biased toward
    //    the pre-move pose. `live_first_iter_inout` is left to its caller-
    //    set value here and only the Live kernel consults it for its own
    //    seed branch.
    amcl.seed_global(grid, rng);

    // 3. Iterate to convergence.
    AmclResult result = amcl.converge(beams_buf, rng);

    // 4. Tripwire — informational only.
    if (apply_yaw_tripwire(result.pose,
                           cfg.amcl_origin_yaw_deg,
                           cfg.amcl_yaw_tripwire_deg)) {
        std::fprintf(stderr,
            "cold_writer: yaw tripwire fired — pose.yaw=%.3f deg "
            "vs origin.yaw=%.3f deg (tripwire=%.3f deg). Studio base "
            "may have rotated; re-run calibration when convenient.\n",
            result.pose.yaw_deg, cfg.amcl_origin_yaw_deg,
            cfg.amcl_yaw_tripwire_deg);
    }

    // 5. Compute Offset against calibration origin (M3 canonical-360 dyaw).
    Pose2D origin{};
    origin.x       = cfg.amcl_origin_x_m;
    origin.y       = cfg.amcl_origin_y_m;
    origin.yaw_deg = cfg.amcl_origin_yaw_deg;
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
                                 cfg.deadband_mm / 1000.0,
                                 cfg.deadband_deg,
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

    // `last_pose_inout` (the AMCL particle-cloud seed for the next
    // iteration) is updated unconditionally — a rejected publish is not
    // a rejected pose estimate (§6.4.1). `live_first_iter_inout` is
    // cleared so the operator-visible "OneShot then Live" sequence does
    // not double-seed-global on Live entry — but Live's `on_leave_live`
    // re-arms the latch on every Live exit, so this is mainly for state
    // hygiene (OneShot does not consult the latch for its own seed).
    last_pose_inout = result.pose;
    live_first_iter_inout = false;
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
                              godo::rt::Seqlock<godo::rt::LastPose>& last_pose_seq) {
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
    if (apply_yaw_tripwire(result.pose,
                           cfg.amcl_origin_yaw_deg,
                           cfg.amcl_yaw_tripwire_deg)) {
        std::fprintf(stderr,
            "cold_writer: yaw tripwire fired (Live) — pose.yaw=%.3f deg "
            "vs origin.yaw=%.3f deg (tripwire=%.3f deg). Studio base "
            "may have rotated; re-run calibration when convenient.\n",
            result.pose.yaw_deg, cfg.amcl_origin_yaw_deg,
            cfg.amcl_yaw_tripwire_deg);
    }

    // 5. Compute Offset against calibration origin (M3 canonical-360 dyaw).
    Pose2D origin{};
    origin.x       = cfg.amcl_origin_x_m;
    origin.y       = cfg.amcl_origin_y_m;
    origin.yaw_deg = cfg.amcl_origin_yaw_deg;
    result.offset = compute_offset(result.pose, origin);
    result.forced = false;            // Live publishes through the deadband

    // 6. Publish — deadband filter at the seqlock seam (§6.4.1).
    (void)apply_deadband_publish(result.offset,
                                 result.forced,
                                 cfg.deadband_mm / 1000.0,
                                 cfg.deadband_deg,
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

    // 8. Update Live state. `last_pose` is updated unconditionally;
    //    `live_first_iter` flips to false so the next iteration re-seeds
    //    around the freshly refined pose.
    last_pose_inout = result.pose;
    live_first_iter_inout = false;
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
                    (void)run_one_iteration(cfg, captured, grid, amcl, rng,
                                            beams_buf, last_pose,
                                            live_first_iter,
                                            last_written, target_offset,
                                            last_pose_seq);
                } catch (const std::exception& e) {
                    std::fprintf(stderr,
                        "cold_writer: run_one_iteration threw: %s — "
                        "returning to Idle.\n", e.what());
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
                    (void)run_live_iteration(cfg, captured, grid, amcl, rng,
                                             beams_buf, last_pose,
                                             live_first_iter,
                                             last_written, target_offset,
                                             last_pose_seq);
                } catch (const std::exception& e) {
                    std::fprintf(stderr,
                        "cold_writer: run_live_iteration threw: %s — "
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
