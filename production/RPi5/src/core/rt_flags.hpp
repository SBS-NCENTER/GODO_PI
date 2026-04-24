#pragma once

// Process-wide RT control flags.
// g_running        — set false on SIGTERM/SIGINT; threads exit their loops.
// calibrate_requested — trigger primitive (§6.1.3), idempotent, multi-writer.

#include <atomic>

namespace godo::rt {

extern std::atomic<bool> g_running;
extern std::atomic<bool> calibrate_requested;

}  // namespace godo::rt
