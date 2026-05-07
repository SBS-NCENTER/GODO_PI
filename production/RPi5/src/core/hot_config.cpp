#include "hot_config.hpp"

#include "config.hpp"

namespace godo::core {

HotConfig snapshot_hot(const Config& cfg) noexcept {
    HotConfig h{};
    h.deadband_mm           = cfg.deadband_mm;
    h.deadband_deg          = cfg.deadband_deg;
    h.published_mono_ns     = 0;  // filled by caller at publish.
    h.valid                 = 1;
    return h;
}

}  // namespace godo::core
