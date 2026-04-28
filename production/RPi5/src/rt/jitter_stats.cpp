#include "jitter_stats.hpp"

#include <algorithm>
#include <cstring>

namespace godo::rt {

std::int64_t compute_percentile(const std::int64_t* sorted_data,
                                std::size_t n,
                                double p) noexcept {
    if (n == 0 || sorted_data == nullptr) return 0;
    if (p < 0.0) p = 0.0;
    if (p > 1.0) p = 1.0;
    // Lower-quantile convention (matches godo_jitter Phase 4-1 harness):
    // index = floor(p × (n - 1)).
    const double idx_d = p * static_cast<double>(n - 1);
    const std::size_t idx = static_cast<std::size_t>(idx_d);
    return sorted_data[idx];
}

void compute_summary(std::int64_t* data,
                     std::size_t n,
                     JitterSnapshot& out) noexcept {
    // Always start from a known shape; caller may pass a default-zero
    // out and we fill every wire field explicitly (no leaked padding).
    std::memset(&out, 0, sizeof(out));
    out.sample_count = static_cast<std::uint64_t>(n);

    if (n == 0 || data == nullptr) {
        // valid stays 0 — publisher writes a sentinel snapshot.
        return;
    }

    std::sort(data, data + n);
    out.p50_ns = compute_percentile(data, n, 0.50);
    out.p95_ns = compute_percentile(data, n, 0.95);
    out.p99_ns = compute_percentile(data, n, 0.99);
    out.max_ns = data[n - 1];

    // Mean: signed accumulation. At N=2048 with delta_ns ≤ 1e9 each, the
    // sum stays well inside int64 range.
    std::int64_t sum = 0;
    for (std::size_t i = 0; i < n; ++i) sum += data[i];
    out.mean_ns = sum / static_cast<std::int64_t>(n);

    out.valid = 1;
}

}  // namespace godo::rt
