#include "rng.hpp"

#include <chrono>

namespace godo::localization {

namespace {

std::uint64_t resolve_seed(std::uint64_t seed) noexcept {
    if (seed != 0) return seed;
    // Time-derived; OK to call once per Rng instance.
    return static_cast<std::uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
}

}  // namespace

Rng::Rng(std::uint64_t seed)
    : engine_(resolve_seed(seed)) {}

double Rng::uniform() noexcept {
    return u01_(engine_);
}

double Rng::gauss(double mean, double stddev) noexcept {
    return mean + n01_(engine_) * stddev;
}

std::size_t Rng::uniform_index(std::size_t n) noexcept {
    if (n <= 1) return 0;
    // Avoid std::uniform_int_distribution's locale-flavoured allocator path.
    // Floor of u01 * n is unbiased to within FP rounding for the n we ever use.
    const double u = u01_(engine_);
    auto idx = static_cast<std::size_t>(u * static_cast<double>(n));
    if (idx >= n) idx = n - 1;
    return idx;
}

}  // namespace godo::localization
