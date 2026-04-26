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

#include <atomic>
#include <cstdint>

namespace godo::rt {

enum class AmclMode : std::uint8_t {
    Idle    = 0,   // poll g_amcl_mode every AMCL_TRIGGER_POLL_MS; cold path parked
    OneShot = 1,   // run converge() once on a fresh frame, publish, return to Idle
    Live    = 2,   // (4-2 D) per-scan step() loop until toggled off; 4-2 B stub
};

extern std::atomic<bool>     g_running;
extern std::atomic<AmclMode> g_amcl_mode;

}  // namespace godo::rt
