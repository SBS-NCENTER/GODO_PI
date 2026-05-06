#include "likelihood_field.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

#include "core/constants.hpp"
#include "parallel/parallel_eval_pool.hpp"

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

LikelihoodField build_likelihood_field(
    const OccupancyGrid&                grid,
    double                              sigma_hit_m,
    godo::parallel::ParallelEvalPool*   pool) {
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

    // Seed the source array: 0 at obstacles, +∞ elsewhere. Shared by
    // both sequential and parallel branches. Encoding cutoff is
    // OCCUPIED_CUTOFF_U8 (occupancy_grid.hpp) — same constant used by
    // Amcl::seed_global so EDT seed and AMCL seed cannot drift out of
    // sync (S5).
    std::vector<float> f(N, kInf);
    for (std::size_t i = 0; i < N; ++i) {
        if (grid.cells[i] < OCCUPIED_CUTOFF_U8) f[i] = 0.0f;
    }

    std::vector<float> intermediate(N, kInf);
    std::vector<float> sq_dist(N, 0.0f);

    // Decide path. Pool degraded ⇒ short-circuit to sequential (the
    // pool's degraded() flag is sticky for the rest of the process so
    // every subsequent build_likelihood_field call also short-circuits).
    const bool use_parallel = (pool != nullptr) && !pool->degraded();

    if (!use_parallel) {
        // ----- Sequential path — unchanged from pre-issue#19 main. -----
        std::vector<float> col_d(static_cast<std::size_t>(H), 0.0f);
        std::vector<float> col_f(static_cast<std::size_t>(H), 0.0f);
        std::vector<int>   v(static_cast<std::size_t>(std::max(W, H)), 0);
        std::vector<float> z(static_cast<std::size_t>(std::max(W, H) + 1),
                             0.0f);

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

        std::vector<float> row_d(static_cast<std::size_t>(W), 0.0f);
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
    } else {
        // ----- Parallel path (issue#19) -----
        //
        // Caller-owned per-worker scratch (D1). One std::vector<EdtScratch>
        // sized to max(1, pool->worker_count()) so the workers=0 inline
        // rollback path (TOML amcl.parallel_eval_workers = 1 → empty
        // cpus_to_pin → worker_count()==0) has exactly 1 scratch slot
        // for the dispatcher to invoke fn against. Each scratch sized
        // once to max(W, H). 4 vectors × max(W,H) × 4 B per worker
        // = ≤ 16 KB at 1000×1000, ≤ 32 KB at 2000×2000 — within
        // rt_setup.cpp 128 MiB mlockall headroom (D7).
        const std::size_t n_dispatch = pool->worker_count();
        const std::size_t n_scratch  = (n_dispatch == 0) ? 1 : n_dispatch;
        std::vector<EdtScratch> per_worker(n_scratch);
        const int max_dim = std::max(W, H);
        for (auto& s : per_worker) s.resize(max_dim);

        // Range-proportional deadline (D2 + project_range_proportional_
        // deadline_pattern.md). Anchored on EDT_PARALLEL_ANCHOR_DIM = 1000:
        // 1000×1000 → scale=1, deadline=50 ms;
        // 2000×2000 → scale=2, deadline=100 ms.
        const std::size_t dim = static_cast<std::size_t>(max_dim);
        const std::int64_t scale = std::max<std::int64_t>(1,
            static_cast<std::int64_t>(dim /
                godo::constants::EDT_PARALLEL_ANCHOR_DIM));
        const std::int64_t deadline_ns =
            godo::constants::EDT_PARALLEL_DEADLINE_BASE_NS * scale;

        // Cache-line-aligned column-pass partition (D4). 64 B Cortex-A76
        // line ⇒ 16 floats per line. Round chunk DOWN to a multiple of
        // 16 columns; last worker takes the residue so no column is
        // skipped. Bench `bench_lf_rebuild` case 2 verifies output is
        // bit-equal regardless of partition shape.
        //
        // n_logical is the number of "work slots" we partition the
        // columns / rows across. For workers>=1 it equals worker_count()
        // and the dispatch fans out across CPU 0..n-1; for workers==0
        // it is 1 and the dispatcher runs the single slot on the caller
        // thread (rollback path bit-equal to sequential).
        const std::size_t n_logical = n_scratch;
        constexpr std::size_t kCacheLineFloats = 16;
        const std::size_t total_x = static_cast<std::size_t>(W);
        const std::size_t naive_chunk =
            (total_x + n_logical - 1) / n_logical;
        const std::size_t aligned_chunk =
            (naive_chunk / kCacheLineFloats) * kCacheLineFloats;
        const std::size_t col_chunk =
            (aligned_chunk == 0) ? naive_chunk : aligned_chunk;

        // Column pass — outer index is wid, fn computes that slot's
        // [x_start, x_end). dispatch range is [0, n_logical).
        bool col_ok = pool->parallel_for_with_scratch<EdtScratch>(
            0, n_logical, per_worker,
            [&, col_chunk, total_x, n_logical, W, H]
            (std::size_t wid, EdtScratch& s) {
                const std::size_t x_start = wid * col_chunk;
                const std::size_t x_end_naive = x_start + col_chunk;
                const std::size_t x_end = (wid == n_logical - 1)
                    ? total_x
                    : (x_end_naive < total_x ? x_end_naive : total_x);
                if (x_start >= x_end) return;
                for (std::size_t x = x_start; x < x_end; ++x) {
                    for (int y = 0; y < H; ++y) {
                        s.pass_f[static_cast<std::size_t>(y)] =
                            f[static_cast<std::size_t>(y) *
                              static_cast<std::size_t>(W) + x];
                    }
                    edt_1d(s.pass_f.data(), s.pass_d.data(), H,
                           s.v.data(), s.z.data());
                    for (int y = 0; y < H; ++y) {
                        intermediate[static_cast<std::size_t>(y) *
                                     static_cast<std::size_t>(W) + x] =
                            s.pass_d[static_cast<std::size_t>(y)];
                    }
                }
            },
            deadline_ns);

        // Row pass — naive y-block partition. Consecutive rows are
        // W*sizeof(float) bytes apart (4000 B at W=1000) so worker
        // boundaries are naturally cache-line aligned (R5 / §3.4).
        bool row_ok = false;
        if (col_ok) {
            row_ok = pool->parallel_for_with_scratch<EdtScratch>(
                0, n_logical, per_worker,
                [&, n_logical, W, H]
                (std::size_t wid, EdtScratch& s) {
                    const std::size_t total_y = static_cast<std::size_t>(H);
                    const std::size_t chunk =
                        (total_y + n_logical - 1) / n_logical;
                    const std::size_t y_start = wid * chunk;
                    if (y_start >= total_y) return;
                    const std::size_t y_end = (wid == n_logical - 1)
                        ? total_y
                        : std::min(y_start + chunk, total_y);
                    for (std::size_t y = y_start; y < y_end; ++y) {
                        const std::size_t base =
                            y * static_cast<std::size_t>(W);
                        edt_1d(intermediate.data() + base,
                               s.pass_d.data(), W,
                               s.v.data(), s.z.data());
                        for (int x = 0; x < W; ++x) {
                            sq_dist[base + static_cast<std::size_t>(x)] =
                                s.pass_d[static_cast<std::size_t>(x)];
                        }
                    }
                },
                deadline_ns);
        }

        // Graceful fallback (R8 / §3.5). If either pass returned false
        // (pool degraded mid-call OR the column pass tripped before the
        // row pass dispatched), re-run the affected pass(es) sequentially
        // using per_worker[0]'s scratch. Subsequent calls see the pool
        // as degraded and short-circuit at the top.
        if (!col_ok) {
            std::fprintf(stderr,
                "build_likelihood_field: parallel column pass failed; "
                "falling back to sequential for this rebuild only.\n");
            EdtScratch& s = per_worker[0];
            for (int x = 0; x < W; ++x) {
                for (int y = 0; y < H; ++y) {
                    s.pass_f[static_cast<std::size_t>(y)] =
                        f[static_cast<std::size_t>(y) *
                          static_cast<std::size_t>(W) +
                          static_cast<std::size_t>(x)];
                }
                edt_1d(s.pass_f.data(), s.pass_d.data(), H,
                       s.v.data(), s.z.data());
                for (int y = 0; y < H; ++y) {
                    intermediate[static_cast<std::size_t>(y) *
                                 static_cast<std::size_t>(W) +
                                 static_cast<std::size_t>(x)] =
                        s.pass_d[static_cast<std::size_t>(y)];
                }
            }
        }
        if (!row_ok) {
            std::fprintf(stderr,
                "build_likelihood_field: parallel row pass failed; "
                "falling back to sequential for this rebuild only.\n");
            EdtScratch& s = per_worker[0];
            for (int y = 0; y < H; ++y) {
                const std::size_t base = static_cast<std::size_t>(y) *
                                         static_cast<std::size_t>(W);
                edt_1d(intermediate.data() + base, s.pass_d.data(), W,
                       s.v.data(), s.z.data());
                for (int x = 0; x < W; ++x) {
                    sq_dist[base + static_cast<std::size_t>(x)] =
                        s.pass_d[static_cast<std::size_t>(x)];
                }
            }
        }
    }

    // Convert squared cell-distance to metres² and apply the Gaussian.
    // Single sequential pass — not the bottleneck (~1 ms at 1000×1000)
    // and parallelising adds ABA risk on the float exp() ordering.
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
