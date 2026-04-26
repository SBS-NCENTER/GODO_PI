#include "rt_flags.hpp"

namespace godo::rt {

std::atomic<bool>     g_running{true};
std::atomic<AmclMode> g_amcl_mode{AmclMode::Idle};

}  // namespace godo::rt
