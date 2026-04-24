#include "offset_smoother.hpp"

#include "yaw/yaw.hpp"

namespace godo::smoother {

OffsetSmoother::OffsetSmoother(std::int64_t t_ramp_ns) noexcept
    : t_ramp_ns_(t_ramp_ns) {}

void OffsetSmoother::tick(const godo::rt::Offset& target_new,
                          std::uint64_t            gen_new,
                          std::int64_t             now_ns) noexcept {
    if (gen_new != target_g_) {
        prev_     = live_;
        target_   = target_new;
        target_g_ = gen_new;
        t_start_  = now_ns;
    }

    // Before the very first gen bump, keep live_ at its initial value.
    if (t_start_ == kSentinelNotStarted) {
        return;
    }

    const std::int64_t elapsed = now_ns - t_start_;
    if (elapsed >= t_ramp_ns_) {
        live_ = target_;                                 // snap (value-copy)
        return;
    }
    const double frac =
        static_cast<double>(elapsed) / static_cast<double>(t_ramp_ns_);
    live_.dx   = prev_.dx + (target_.dx - prev_.dx) * frac;
    live_.dy   = prev_.dy + (target_.dy - prev_.dy) * frac;
    live_.dyaw = godo::yaw::lerp_angle(prev_.dyaw, target_.dyaw, frac);
}

}  // namespace godo::smoother
