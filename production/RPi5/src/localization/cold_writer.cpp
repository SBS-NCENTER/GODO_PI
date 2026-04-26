#include "cold_writer.hpp"

#include <atomic>
#include <chrono>
#include <cerrno>
#include <cstdio>
#include <exception>
#include <thread>
#include <utility>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "likelihood_field.hpp"

namespace godo::localization {

AmclResult run_one_iteration(const godo::core::Config&         cfg,
                             const godo::lidar::Frame&         frame,
                             const OccupancyGrid&              grid,
                             Amcl&                             amcl,
                             Rng&                              rng,
                             std::vector<RangeBeam>&           beams_buf,
                             Pose2D&                           last_pose_inout,
                             bool&                             first_run_inout,
                             godo::rt::Seqlock<godo::rt::Offset>& target_offset) {
    // 1. Decimate the scan into AMCL beams.
    downsample(frame,
               cfg.amcl_downsample_stride,
               cfg.amcl_range_min_m,
               cfg.amcl_range_max_m,
               beams_buf);

    // 2. Seed: global on first run, Gaussian-around-last_pose on subsequent.
    if (first_run_inout) {
        amcl.seed_global(grid, rng);
    } else {
        amcl.seed_around(last_pose_inout,
                         cfg.amcl_sigma_seed_xy_m,
                         cfg.amcl_sigma_seed_yaw_deg,
                         rng);
    }

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

    // 6. Publish — identity passthrough this phase. Phase 4-2 C deadband
    // drops in here:
    //   if (result.forced || !within_deadband(result.offset, last_written)) {
    //       target_offset.store(result.offset);
    //       last_written = result.offset;
    //   }
    target_offset.store(result.offset);

    last_pose_inout = result.pose;
    first_run_inout = false;
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

void log_live_stub_once(bool& already_logged) {
    if (already_logged) return;
    std::fprintf(stderr,
        "cold_writer: AmclMode::Live requested but not yet implemented "
        "(Phase 4-2 D); dropping back to Idle.\n");
    already_logged = true;
}

}  // namespace

void run_cold_writer(const godo::core::Config&            cfg,
                     godo::rt::Seqlock<godo::rt::Offset>& target_offset,
                     LidarFactory                         lidar_factory) {
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
    bool first_run     = true;
    bool live_logged   = false;

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
                    break;
                }
                if (!got_frame) {
                    // Source exited without delivering a frame (likely
                    // SIGTERM). If g_running is now false, top of the loop
                    // will exit.
                    godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                                std::memory_order_release);
                    break;
                }
                try {
                    (void)run_one_iteration(cfg, captured, grid, amcl, rng,
                                            beams_buf, last_pose, first_run,
                                            target_offset);
                } catch (const std::exception& e) {
                    std::fprintf(stderr,
                        "cold_writer: run_one_iteration threw: %s — "
                        "returning to Idle.\n", e.what());
                }
                godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                            std::memory_order_release);
                break;
            }

            case godo::rt::AmclMode::Live: {
                log_live_stub_once(live_logged);
                godo::rt::g_amcl_mode.store(godo::rt::AmclMode::Idle,
                                            std::memory_order_release);
                break;
            }
        }
    }

    // RAII tears down the SDK driver via the LidarSourceRplidar destructor
    // (unique_ptr → ~LidarSourceRplidar → ~Impl → stop_and_disconnect).
}

}  // namespace godo::localization
