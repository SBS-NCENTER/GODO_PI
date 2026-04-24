#include "rt_flags.hpp"

namespace godo::rt {

std::atomic<bool> g_running{true};
std::atomic<bool> calibrate_requested{false};

}  // namespace godo::rt
