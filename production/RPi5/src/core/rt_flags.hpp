#pragma once

// Process-wide RT control flags.
// g_running     — set false on SIGTERM/SIGINT; threads exit their loops.
// g_amcl_mode   — cold-writer state machine selector (§6.1.3). Replaces the
//                 Phase 4-1 boolean `calibrate_requested`. Idempotent;
//                 multiple writers may store the same value safely.
//
//   Idle    — cold writer polls and sleeps (AMCL_TRIGGER_POLL_MS).
//   OneShot — cold writer captures one frame, runs converge(), publishes
//             an Offset, then transitions back to Idle.
//   Live    — Phase 4-2 D body; Phase 4-2 B logs once and bounces to Idle.
//
// issue#3 — calibrate hint publish/consume (production CODEBASE.md
// invariant (p)):
//   - `g_calibrate_hint_data`  — Seqlock<HintBundle> carrying the
//                                operator-placed (x, y, yaw, σ_xy, σ_yaw)
//                                pose hint. UDS handler is the SOLE
//                                writer (single-writer Seqlock contract).
//   - `g_calibrate_hint_valid` — std::atomic<bool> sentinel. UDS handler
//                                stores `true` AFTER publishing the
//                                bundle; cold writer is the SOLE
//                                clearer (consume-once: stored back to
//                                `false` after every OneShot completion).
//
// Memory ordering (Mode-A M3):
//   UDS handler:
//     g_calibrate_hint_data.store(b);
//     g_calibrate_hint_valid.store(true,  memory_order_release);
//     g_amcl_mode.store(OneShot,         memory_order_release);
//   Cold writer:
//     mode = g_amcl_mode.load(            memory_order_acquire);
//     if (g_calibrate_hint_valid.load(    memory_order_acquire)) {
//         bundle = g_calibrate_hint_data.load();   // seqlock-fenced
//         …seed_around(bundle)…
//         g_calibrate_hint_valid.store(false, memory_order_release);  // consume-once
//     } else { …seed_global()… }

#include <atomic>
#include <cstdint>

#include "core/seqlock.hpp"

namespace godo::rt {

enum class AmclMode : std::uint8_t {
    Idle    = 0,   // poll g_amcl_mode every AMCL_TRIGGER_POLL_MS; cold path parked
    OneShot = 1,   // run converge() once on a fresh frame, publish, return to Idle
    Live    = 2,   // (4-2 D) per-scan step() loop until toggled off; 4-2 B stub
};

extern std::atomic<bool>     g_running;
extern std::atomic<AmclMode> g_amcl_mode;

// issue#3 — calibrate hint payload. Five doubles (40 B); plain POD,
// trivially copyable per the Seqlock<T> contract. The webctl all-or-none
// validator already guarantees the seed triple is fully populated; the
// tracker still re-checks finite + in-bounds in `uds_server.cpp` before
// publishing. σ overrides are 0.0 when the operator did not supply
// them — cold writer falls back to `cfg.amcl_hint_sigma_*_default`.
struct HintBundle {
    double x_m            = 0.0;
    double y_m            = 0.0;
    double yaw_deg        = 0.0;
    double sigma_xy_m     = 0.0;     // 0.0 = "use cfg default"
    double sigma_yaw_deg  = 0.0;     // 0.0 = "use cfg default"
};
static_assert(std::is_trivially_copyable_v<HintBundle>);

extern Seqlock<HintBundle>     g_calibrate_hint_data;
extern std::atomic<bool>       g_calibrate_hint_valid;

}  // namespace godo::rt
