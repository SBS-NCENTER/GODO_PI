#pragma once

// Tier-1 protocol / algorithmic invariants. Changing any of these requires
// a coordinated downstream update (UE project file, legacy Arduino rollback).
// See SYSTEM_DESIGN.md §11.1.

#include <cstdint>

namespace godo::constants {

// FreeD D1 protocol — pinned by the wire format, not tunable.
// Byte layout cross-reference: XR_FreeD_to_UDP/src/main.cpp L17-31.
inline constexpr int      FREED_PACKET_LEN = 29;
inline constexpr double   FREED_PAN_Q      = 1.0 / 32768.0;  // deg per lsb
inline constexpr double   FREED_POS_Q      = 1.0 / 64.0;     // mm per lsb

// Derived multipliers for Offset → wire-lsb re-encoding in apply_offset_inplace.
// Named so sender.cpp has no magic literals. Changing Tier-1 quanta cascades.
inline constexpr double   MM_PER_M              = 1000.0;
inline constexpr double   FREED_POS_LSB_PER_M   = MM_PER_M / FREED_POS_Q;   // 64'000 lsb/m
inline constexpr double   FREED_PAN_LSB_PER_DEG = 1.0 / FREED_PAN_Q;        // 32'768 lsb/deg

// SLAMTEC C1 sample decoding — pinned by the SDK.
inline constexpr double   RPLIDAR_Q14_DEG  = 90.0 / 16384.0;
inline constexpr double   RPLIDAR_Q2_MM    = 1.0 / 4.0;

// Hot-path cadence — pinned by UE's 59.94 fps project standard.
inline constexpr double   FRAME_RATE_HZ    = 60000.0 / 1001.0;
inline constexpr int64_t  FRAME_PERIOD_NS  = 16'683'350;

// AMCL / EDT bounds — Tier-1 because changing them requires re-deriving
// the EDT scratch buffer math or the seeded particle buffer footprint.
inline constexpr int      PARTICLE_BUFFER_MAX = 10000;
inline constexpr int      SCAN_BEAMS_MAX      = 720;
inline constexpr int      EDT_TABLE_SIZE      = 1024;
inline constexpr std::int64_t EDT_MAX_CELLS   = 4'000'000;

// Track D — fixed cap on the per-frame range count published by the cold
// writer to LastScan. Mirrors SCAN_BEAMS_MAX so the AMCL beam decimation
// and the LastScan ranges array are sample-aligned (one stride, one
// upper bound). The SLAMTEC C1 nominal sample rate is ~600/scan @ 10 Hz,
// well under this cap; the cap protects against a future config change
// pushing the stride lower than 1.
inline constexpr int      LAST_SCAN_RANGES_MAX = 720;

// JSON scratch budget for format_ok_scan (Track D — Mode-A M1 fold).
// Worst-case payload: 720 ranges × ~10 chars + 720 angles × ~10 chars +
// fixed scalar header (~250 B) + array brackets/commas (~50 B) ≈ 14.7 KiB.
// 24 KiB scratch buffer leaves >50% headroom for any future precision
// bump; pinned by static_assert in json_mini.cpp's format_ok_scan body.
inline constexpr int      JSON_SCRATCH_BYTES = 24576;

// Floor for off-map / very-low-likelihood beam contributions in
// evaluate_scan(). Bumping this changes AMCL math: too small lets a
// single off-map beam dominate the log-sum; too large erodes
// discrimination between near-truth and far-truth poses. Tier-1 because
// re-validating the convergence test fixtures is required after any
// change. (S4 mitigation, Mode-B follow-up.)
inline constexpr double   EVAL_SCAN_LIKELIHOOD_FLOOR = 1e-6;

// Phase 4-2 D — GPIO + UDS Tier-1 constants. None of these is operator-
// tunable: changing GPIO_DEBOUNCE_NS would invalidate the bounce-filter
// reasoning; UDS_REQUEST_MAX_BYTES caps the hand-rolled JSON parser's
// scratch buffer; SHUTDOWN_POLL_TIMEOUT_MS bounds the worst-case
// shutdown latency for the GPIO + UDS threads (200 ms total budget at
// two 100 ms polls); GPIO_MAX_BCM_PIN reflects the Pi 5 40-pin header
// upper BCM bound. Wave A lands these so Wave B can drop in cleanly.
inline constexpr std::int64_t GPIO_DEBOUNCE_NS         = 50'000'000;  // 50 ms
inline constexpr int          UDS_REQUEST_MAX_BYTES    = 4096;        // 4 KiB
inline constexpr int          SHUTDOWN_POLL_TIMEOUT_MS = 100;
inline constexpr int          GPIO_MAX_BCM_PIN         = 27;

// UDS server protocol-shape invariants (Mode-B SHOULD-FIX S1):
// - LISTEN_BACKLOG: kernel SOMAXCONN ceiling for unaccepted clients;
//   single-client serial server, so 4 is generous.
// - CONN_READ_TIMEOUT_SEC: a stalled client must not block the accept
//   loop forever (M1). One second is well above any honest webctl
//   round-trip yet bounds the lockout cleanly.
inline constexpr int          UDS_LISTEN_BACKLOG       = 4;
inline constexpr int          UDS_CONN_READ_TIMEOUT_SEC = 1;

// issue#18 — UDS bootstrap audit (SF3 + MF3). Tier-1 because changing
// these alters operator-visible boot semantics.
//
// UDS_STALE_SIBLING_MIN_AGE_SEC: SF3 sweep mtime threshold. Sockets with
// mtime newer than (now - this) are left alone (defence in depth — the
// pidfile invariant (l) already rules out a concurrent tracker, but the
// threshold guards against any future code path that creates a `<pid>.tmp`
// before the boot-time sweep runs). 2 s is short enough to never miss a
// truly-stale sibling and long enough that 1-s tmpfs mtime granularity
// does not cause false negatives.
//
// UDS_BOOT_AUDIT_SIBLING_LIST_CAP: MF3 audit-line truncation cap. Caps
// the boot-audit log line at a parseable single-line length. A pathological
// sibling list (>3) is itself a finding; the truncation marker `[...]`
// surfaces it to operators without flooding journalctl.
inline constexpr int          UDS_STALE_SIBLING_MIN_AGE_SEC   = 2;
inline constexpr int          UDS_BOOT_AUDIT_SIBLING_LIST_CAP = 3;

// libgpiod edge-event drain depth (Mode-B SHOULD-FIX S2). One real button
// press emits at most a handful of bounce events before the debounce
// window closes; 16 is a generous ceiling that keeps wait_edge_events
// from re-entering on the same press.
inline constexpr int          GPIO_EDGE_EVENT_BUFFER_DEPTH = 16;

// Track B-DIAG (PR-DIAG) — diagnostics page Tier-1 invariants.
//
// JITTER_RING_DEPTH: Thread D's per-tick scheduling-jitter sample buffer.
// 2048 entries × 16.683 ms tick ≈ 34 s lookback, generous against the
// publisher's 1 Hz cadence and against transient sub-second spikes.
// Changing it invalidates the documented ~34 s window characterization.
//
// JITTER_PUBLISH_INTERVAL_MS: cadence the diag publisher thread tickets
// at. 1000 ms keeps `compute_summary` (sort + percentile, ~30 µs at
// N=2048 on Cortex-A76) at 0.003% CPU. Changing it invalidates the
// publisher's CPU-budget reasoning.
//
// AMCL_RATE_WINDOW_S: documented "the AMCL-iteration-rate metric is
// meaningful over a window roughly this long" comment value (Mode-A
// fold M2 renamed scan_rate → amcl_iteration_rate). The actual rate
// math uses two-tick differencing in the publisher; this constant is
// informational only — see plan §"Scan-rate publication".
inline constexpr int          JITTER_RING_DEPTH         = 2048;
inline constexpr int          JITTER_PUBLISH_INTERVAL_MS = 1000;
inline constexpr double       AMCL_RATE_WINDOW_S        = 5.0;

// PR-DIAG json_mini scratch budgets. Worst case per-frame:
//   - format_ok_jitter ≈ 5×8 (p-tiles + mean) doubles + scalars ≈ 220 B.
//   - format_ok_amcl_rate ≈ 1 double + 3 uint64 + flags ≈ 130 B.
// 512 B leaves >2× headroom; pinned by static_assert in json_mini.cpp.
inline constexpr int          JITTER_FORMAT_SCRATCH_BYTES    = 512;
inline constexpr int          AMCL_RATE_FORMAT_SCRATCH_BYTES = 256;

// FreeD D1 field offsets within the 29-byte packet.
// Source of truth: XR_FreeD_to_UDP/src/main.cpp L67-85.
namespace FreeD {
    inline constexpr int OFF_TYPE     = 0;
    inline constexpr int OFF_CAM_ID   = 1;
    inline constexpr int OFF_PAN      = 2;
    inline constexpr int OFF_TILT     = 5;
    inline constexpr int OFF_ROLL     = 8;
    inline constexpr int OFF_X        = 11;
    inline constexpr int OFF_Y        = 14;
    inline constexpr int OFF_Z        = 17;
    inline constexpr int OFF_ZOOM     = 20;
    inline constexpr int OFF_FOCUS    = 23;
    inline constexpr int OFF_STATUS   = 26;
    inline constexpr int OFF_CHECKSUM = 28;

    inline constexpr std::uint8_t TYPE_D1 = 0xD1;
}  // namespace FreeD

}  // namespace godo::constants
