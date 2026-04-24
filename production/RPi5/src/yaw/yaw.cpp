#include "yaw.hpp"

#include <cmath>

namespace godo::yaw {

double lerp_angle(double a, double b, double frac) noexcept {
    const double d = std::fmod(b - a + 540.0, 360.0) - 180.0;  // (-180, +180]
    double y = a + d * frac;
    y = std::fmod(y, 360.0);
    if (y < 0.0) y += 360.0;
    return y;
}

std::int32_t wrap_signed24(std::int64_t v) noexcept {
    constexpr std::int64_t R = std::int64_t{1} << 24;   // full turn (lsb)
    constexpr std::int64_t H = std::int64_t{1} << 23;   // half turn
    v = ((v % R) + R) % R;                              // [0, R)
    if (v >= H) v -= R;                                 // [-H, +H)
    return static_cast<std::int32_t>(v);
}

}  // namespace godo::yaw
