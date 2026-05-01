#include "rt_flags.hpp"

namespace godo::rt {

std::atomic<bool>     g_running{true};
std::atomic<AmclMode> g_amcl_mode{AmclMode::Idle};

// issue#3 — calibrate hint storage. UDS handler is the sole writer of
// `g_calibrate_hint_data`; cold writer is the sole clearer of
// `g_calibrate_hint_valid` (consume-once after every OneShot
// completion). See rt_flags.hpp for the full memory-ordering contract.
Seqlock<HintBundle> g_calibrate_hint_data;
std::atomic<bool>   g_calibrate_hint_valid{false};

}  // namespace godo::rt
