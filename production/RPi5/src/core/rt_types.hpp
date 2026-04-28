#pragma once

// Types exchanged across the hot/cold path boundary.
// See SYSTEM_DESIGN.md §6.1.1.

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

#include "constants.hpp"

namespace godo::rt {

struct Offset {
    double dx;    // metres, world-frame
    double dy;    // metres, world-frame
    double dyaw;  // degrees, [0, 360) canonical (see yaw/lerp_angle)
};

static_assert(sizeof(Offset) == 24, "Offset layout is ABI-visible");
static_assert(std::is_trivially_copyable_v<Offset>,
              "Offset must be trivially copyable for Seqlock payload");

struct FreedPacket {
    std::array<std::byte, godo::constants::FREED_PACKET_LEN> bytes;
};

static_assert(sizeof(FreedPacket) == godo::constants::FREED_PACKET_LEN,
              "FreedPacket layout is ABI-visible");
static_assert(std::is_trivially_copyable_v<FreedPacket>,
              "FreedPacket must be trivially copyable for Seqlock payload");

// Last AMCL pose snapshot, published by the cold writer at the OneShot
// success path and consumed via UDS `get_last_pose` (see
// production/RPi5/doc/uds_protocol.md §C.4 + Track B repeatability harness).
//
// Layout pinned (Track B plan F1+F7): 5×8 + 8 + 4 + 4×1 = 56 bytes,
// 8-byte aligned. Field order is ABI-visible — the JSON formatter in
// uds/json_mini.cpp::format_ok_pose mirrors this order; the Python mirror
// godo-webctl/protocol.py::LAST_POSE_FIELDS pins it at test time.
//
// `xy_std_m` is the combined-variance scalar produced by
// localization/amcl.cpp::xy_std_m (L272-300): sqrt(weighted_var_x +
// weighted_var_y). See uds_protocol.md §C.4 (F18) for the formula citation.
//
// `published_mono_ns` is set to godo::rt::monotonic_ns() at publish; readers
// can detect a stale snapshot by comparing this against their own
// monotonic clock + a freshness budget.
struct LastPose {
    double        x_m;                  // metres, world frame
    double        y_m;                  // metres, world frame
    double        yaw_deg;              // [0, 360) canonical
    double        xy_std_m;             // sqrt(var_x + var_y); amcl.cpp:272-300
    double        yaw_std_deg;          // circular std, degrees
    std::uint64_t published_mono_ns;    // monotonic_ns() at publish (F7)
    std::int32_t  iterations;           // AMCL iters; -1 = no run yet
    std::uint8_t  valid;                // 0 = no pose ever published, 1 = published
    std::uint8_t  converged;            // 0 = diverged, 1 = converged
    std::uint8_t  forced;               // OneShot=1; Live=0
    std::uint8_t  _pad0;                // reserved; keep zero
};

static_assert(sizeof(LastPose) == 56, "LastPose layout is ABI-visible");
static_assert(alignof(LastPose) == 8, "LastPose must be 8-aligned");
static_assert(std::is_trivially_copyable_v<LastPose>,
              "LastPose must be trivially copyable for Seqlock payload");

// Track D — last scan snapshot, published by the cold writer at the same
// seam as LastPose (run_one_iteration / run_live_iteration). Consumed via
// UDS `get_last_scan` (production/RPi5/doc/uds_protocol.md §C.5). The SPA
// renders the polar samples as a third canvas layer on top of the static
// map underlay so an operator can verify AMCL convergence visually.
//
// Mode-A folds (M1, M3, N6) shape the layout:
//   - M1: parallel `angles_deg[]` instead of (angle_min, increment) — the
//     downsample() step in scan_ops.cpp filters non-uniformly, so
//     parametrizing as `angle_min + i × increment` is wrong.
//   - M3: `pose_valid` flag distinguishes legitimate (0,0,0) anchor poses
//     from "no AMCL run yet" zeroes — the SPA gates the overlay on this.
//   - N6: `angles_deg[0]` lands at offset 56 already 8-aligned without a
//     trailing pad; no _pad3 needed.
//
// Field order is ABI-visible — the JSON formatter in
// uds/json_mini.cpp::format_ok_scan mirrors this order; the Python mirror
// godo-webctl/protocol.py::LAST_SCAN_HEADER_FIELDS is regex-extracted
// from this struct's source by tests/test_protocol.py and pinned at test
// time.
//
// Trivially copyable + fixed size = safe inside Seqlock<T>::payload_;
// no heap traffic on the cold-writer publish path.
struct LastScan {
    // Anchor pose used by the same-iteration AMCL converge/step. The SPA
    // uses these to do polar→Cartesian without needing a second SSE
    // correlation against /api/last_pose (Mode-A TM5).
    double  pose_x_m;
    double  pose_y_m;
    double  pose_yaw_deg;       // [0, 360) canonical

    // Publish timestamp (CLOCK_MONOTONIC ns); SPA gates "fresh vs stale"
    // ordering only — wall-clock freshness uses arrival-time per Mode-A M2.
    std::uint64_t published_mono_ns;

    // Header.
    std::int32_t  iterations;   // AMCL iters; -1 = no run yet
    std::uint8_t  valid;        // 0 = no scan ever published, 1 = published
    std::uint8_t  forced;       // 1 = OneShot, 0 = Live (mirrors LastPose.forced)
    std::uint8_t  pose_valid;   // 0 = AMCL pose not yet converged, 1 = valid
    std::uint8_t  _pad0;        // reserved; keep zero

    std::uint16_t n;            // [0, LAST_SCAN_RANGES_MAX]; valid sample count
    std::uint16_t _pad1;
    std::uint8_t  _pad2[4];     // align ranges/angles arrays to 8 B

    // Parallel arrays — angles_deg[i] is the bearing of ranges_m[i] in
    // the LiDAR frame. Both fixed-size to keep the type trivially
    // copyable (no std::vector, no heap).
    double angles_deg[godo::constants::LAST_SCAN_RANGES_MAX];
    double ranges_m[godo::constants::LAST_SCAN_RANGES_MAX];
};

// Layout pin: 24 (pose) + 8 (mono_ns) + 4 (iter) + 4 (flags+_pad0) +
// 2 (n) + 2 (_pad1) + 4 (_pad2) + 5760 (angles) + 5760 (ranges) = 11568 B.
// 11568 is 8-aligned (1446 × 8); no trailing pad needed (Mode-A N6).
static_assert(sizeof(LastScan) == 11568, "LastScan layout is ABI-visible");
static_assert(alignof(LastScan) == 8, "LastScan must be 8-aligned");
static_assert(std::is_trivially_copyable_v<LastScan>,
              "LastScan must be trivially copyable for Seqlock payload");

// Track B-DIAG (PR-DIAG) — RT-thread scheduling-jitter snapshot, published
// by rt/diag_publisher.cpp at JITTER_PUBLISH_INTERVAL_MS cadence and
// consumed via UDS `get_jitter` (uds_protocol.md §C.6 to be added).
//
// Producer: rt/diag_publisher.cpp computes p50/p95/p99/max/mean over a
// snapshot of the JitterRing buffer (single-writer Thread D, single-
// reader the publisher). Sort + percentile lives in jitter_stats.cpp;
// Thread D itself never references this struct or `jitter_seq` (build-
// time pin: scripts/build.sh::[hot-path-jitter-grep]).
//
// Field order is ABI-visible — the JSON formatter in
// uds/json_mini.cpp::format_ok_jitter mirrors this order; the Python
// mirror godo-webctl/protocol.py::JITTER_FIELDS is regex-pinned against
// the format string at test time.
//
// Layout pin: 5×8 (p-tiles + mean) + 8 (sample_count) + 8 (mono_ns) +
// 4×1 (valid + 3 byte pads) + 4 (trailing pad) = 64 B exact. Trivially
// copyable + 8-aligned for Seqlock<T>::payload_ safety.
struct JitterSnapshot {
    std::int64_t  p50_ns;
    std::int64_t  p95_ns;
    std::int64_t  p99_ns;
    std::int64_t  max_ns;
    std::int64_t  mean_ns;          // signed — small negatives possible if
                                    // scheduler runs early (Mode-A OQ-DIAG-5)

    std::uint64_t sample_count;     // ring entries used for this percentile
    std::uint64_t published_mono_ns;

    std::uint8_t  valid;            // 0 = no publish yet, 1 = populated
    std::uint8_t  _pad0;
    std::uint8_t  _pad1;
    std::uint8_t  _pad2;
    std::uint8_t  _pad3[4];         // align trailing to 8 B
};

// Note (Mode-A N1 fold): trailing pad is 1 (valid) + 3 (pad0..pad2)
// + 4 (_pad3) = 8 B; the _pad3[4] is layout-only and not a 4-element
// semantic field.
static_assert(sizeof(JitterSnapshot) == 64, "JitterSnapshot layout is ABI-visible");
static_assert(alignof(JitterSnapshot) == 8, "JitterSnapshot must be 8-aligned");
static_assert(std::is_trivially_copyable_v<JitterSnapshot>,
              "JitterSnapshot must be trivially copyable for Seqlock payload");

// Track B-DIAG (Mode-A M2 fold) — AMCL iteration-rate snapshot. Renamed
// from `ScanRate` per Mode-A reviewer (the metric measures cold-writer
// publish cadence, NOT raw LiDAR scan rate; in Idle the LiDAR is parked
// and the rate is 0 Hz by design). Published by rt/diag_publisher.cpp
// alongside JitterSnapshot at the same 1 Hz cadence.
//
// Producer: cold writer (`run_one_iteration` / `run_live_iteration`)
// records each AMCL iteration via the accumulator's record method (see
// rt/amcl_rate.hpp); the publisher differences `total_count` and
// `last_iteration_mono_ns` against its own prior snapshot to compute Hz
// over the last publisher tick (a two-tick differencing window — plan
// §"Scan-rate publication").
//
// Field order is ABI-visible — `format_ok_amcl_rate` mirrors this order;
// `protocol.py::AMCL_RATE_FIELDS` is regex-pinned at test time.
//
// Layout pin: 8 (hz) + 8 + 8 + 8 (mono_ns) + 1 (valid) + 7 (pad) = 40 B.
struct AmclIterationRate {
    double        hz;                         // sliding-window over AMCL_RATE_WINDOW_S
    std::uint64_t last_iteration_mono_ns;     // time of the last recorded iteration
    std::uint64_t total_iteration_count;      // monotonic; never wraps in practice
    std::uint64_t published_mono_ns;
    std::uint8_t  valid;                      // 0 = no iteration recorded yet, 1 = populated
    std::uint8_t  _pad0[7];                   // align to 8 B
};

static_assert(sizeof(AmclIterationRate) == 40, "AmclIterationRate layout is ABI-visible");
static_assert(alignof(AmclIterationRate) == 8, "AmclIterationRate must be 8-aligned");
static_assert(std::is_trivially_copyable_v<AmclIterationRate>,
              "AmclIterationRate must be trivially copyable for Seqlock payload");

}  // namespace godo::rt
