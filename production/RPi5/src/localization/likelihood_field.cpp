#include "likelihood_field.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace godo::localization {

namespace {

// issue#19 — Per-worker scratch for the parallel column / row passes of
// `build_likelihood_field`. Caller-owned `std::vector<EdtScratch>(N)` lives
// for the duration of one `build_likelihood_field` call; sized once to
// `max(W, H)` so that every worker's `edt_1d` invocation uses the same
// buffer without reallocation. Members mirror the sequential path's
// scratch: `v` + `z` for `edt_1d`'s envelope, `pass_d` (output) + `pass_f`
// (input copy) for one column or row at a time.
//
// POD by design: trivially default-constructable so the `std::vector`
// allocation in the parallel branch is a single contiguous block.
struct EdtScratch {
    std::vector<int>   v;       // size max(W, H)
    std::vector<float> z;       // size max(W, H) + 1
    std::vector<float> pass_d;  // size max(W, H)   — per-iteration output
    std::vector<float> pass_f;  // size max(W, H)   — per-iteration input copy

    void resize(int max_dim) {
        const std::size_t M = static_cast<std::size_t>(max_dim);
        v.assign(M, 0);
        z.assign(M + 1, 0.0f);
        pass_d.assign(M, 0.0f);
        pass_f.assign(M, 0.0f);
    }
};

// Felzenszwalb 1D distance transform of the squared-distance source array
// `f` of length `n`. Output `d` has length `n`. Scratch buffers `v` (size
// n) and `z` (size n+1) are passed in to avoid re-allocation across rows.
//
// f[i] is interpreted as the squared distance to the nearest obstacle in
// the column / row already collapsed; ∞ if no obstacle yet. Output d[q]
// is the new squared-distance value after one sweep.
//
// Reference: Pedro F. Felzenszwalb & Daniel P. Huttenlocher,
// "Distance Transforms of Sampled Functions" (2012).
//
// Two non-obvious safeguards over the textbook listing:
//   1. The intersection formula `(fq + q²) - (fvk + vk²)` involves +inf
//      seeds for unset cells. `inf - inf = NaN` for inf-valued obstacle
//      seeds; we explicitly skip enrolling a column whose f[q] is +inf
//      (no parabola contributed) and never let a +inf-valued vk join the
//      lower envelope in the first place.
//   2. The all-inf row (no obstacles in the column / row pass) leaves
//      the output as +inf, which the second pass propagates correctly.
void edt_1d(const float* f, float* d, int n, int* v, float* z) {
    constexpr float kInf = std::numeric_limits<float>::infinity();
    // Find the first finite f[q]; if none, the whole output is +inf.
    int first = 0;
    while (first < n && !std::isfinite(f[first])) ++first;
    if (first == n) {
        for (int q = 0; q < n; ++q) d[q] = kInf;
        return;
    }
    int k = 0;
    v[0] = first;
    z[0] = -kInf;
    z[1] =  kInf;
    for (int q = first + 1; q < n; ++q) {
        // Skip cells with no obstacle contribution; they cannot tighten
        // the envelope (their parabola is at +inf).
        if (!std::isfinite(f[q])) continue;
        float s;
        for (;;) {
            const int   vk  = v[k];
            const float fvk = f[vk];
            const float fq  = f[q];
            const float num = (fq + static_cast<float>(q) * q) -
                              (fvk + static_cast<float>(vk) * vk);
            const float den = 2.0f * static_cast<float>(q - vk);
            s = num / den;
            if (s <= z[k]) {
                if (k == 0) break;
                --k;
            } else {
                break;
            }
        }
        ++k;
        v[k]     = q;
        z[k]     = s;
        z[k + 1] = kInf;
    }
    k = 0;
    for (int q = 0; q < n; ++q) {
        while (z[k + 1] < static_cast<float>(q)) ++k;
        const int   vk = v[k];
        const float dq = static_cast<float>(q - vk);
        d[q] = dq * dq + f[vk];
    }
}

}  // namespace

LikelihoodField build_likelihood_field(const OccupancyGrid& grid,
                                       double               sigma_hit_m) {
    if (grid.width <= 0 || grid.height <= 0 || grid.cells.empty()) {
        throw std::invalid_argument(
            "build_likelihood_field: grid is empty");
    }
    if (!(sigma_hit_m > 0.0)) {
        throw std::invalid_argument(
            "build_likelihood_field: sigma_hit_m must be > 0");
    }

    const int W = grid.width;
    const int H = grid.height;
    const std::size_t N = static_cast<std::size_t>(W) *
                          static_cast<std::size_t>(H);

    constexpr float kInf = std::numeric_limits<float>::infinity();

    // Seed the source array: 0 at obstacles, +∞ elsewhere.
    // Encoding cutoff lives in occupancy_grid.hpp as OCCUPIED_CUTOFF_U8 —
    // shared with Amcl::seed_global so the EDT and seed paths cannot drift
    // out of sync (S5).
    std::vector<float> f(N, kInf);
    for (std::size_t i = 0; i < N; ++i) {
        if (grid.cells[i] < OCCUPIED_CUTOFF_U8) f[i] = 0.0f;
    }

    // First pass: column-wise (along y).
    std::vector<float> col_d(static_cast<std::size_t>(H), 0.0f);
    std::vector<float> col_f(static_cast<std::size_t>(H), 0.0f);
    std::vector<int>   v(static_cast<std::size_t>(std::max(W, H)), 0);
    std::vector<float> z(static_cast<std::size_t>(std::max(W, H) + 1), 0.0f);

    std::vector<float> intermediate(N, kInf);
    for (int x = 0; x < W; ++x) {
        for (int y = 0; y < H; ++y) {
            col_f[static_cast<std::size_t>(y)] =
                f[static_cast<std::size_t>(y) *
                  static_cast<std::size_t>(W) +
                  static_cast<std::size_t>(x)];
        }
        edt_1d(col_f.data(), col_d.data(), H, v.data(), z.data());
        for (int y = 0; y < H; ++y) {
            intermediate[static_cast<std::size_t>(y) *
                         static_cast<std::size_t>(W) +
                         static_cast<std::size_t>(x)] =
                col_d[static_cast<std::size_t>(y)];
        }
    }

    // Second pass: row-wise (along x).
    std::vector<float> row_d(static_cast<std::size_t>(W), 0.0f);
    std::vector<float> sq_dist(N, 0.0f);
    for (int y = 0; y < H; ++y) {
        const std::size_t base = static_cast<std::size_t>(y) *
                                 static_cast<std::size_t>(W);
        edt_1d(intermediate.data() + base, row_d.data(), W,
               v.data(), z.data());
        for (int x = 0; x < W; ++x) {
            sq_dist[base + static_cast<std::size_t>(x)] =
                row_d[static_cast<std::size_t>(x)];
        }
    }

    // Convert squared cell-distance to metres² and apply the Gaussian.
    const double res_sq = grid.resolution_m * grid.resolution_m;
    const double two_sigma_sq = 2.0 * sigma_hit_m * sigma_hit_m;

    LikelihoodField out{};
    out.width        = W;
    out.height       = H;
    out.resolution_m = grid.resolution_m;
    out.origin_x_m   = grid.origin_x_m;
    out.origin_y_m   = grid.origin_y_m;
    out.values.assign(N, 0.0f);
    for (std::size_t i = 0; i < N; ++i) {
        const double d_m_sq = static_cast<double>(sq_dist[i]) * res_sq;
        out.values[i] = static_cast<float>(std::exp(-d_m_sq / two_sigma_sq));
    }
    return out;
}

}  // namespace godo::localization
