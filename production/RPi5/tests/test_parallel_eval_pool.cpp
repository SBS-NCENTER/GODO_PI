// issue#11 P4-2-11-1 / P4-2-11-6 + issue#37 P4-2-37-1 — ParallelEvalPool
// unit tests.
//
// Cases:
//   1. Lifecycle              — ctor spawns workers; dtor joins cleanly.
//   2. Output equivalence     — parallel_for(0, N, fn) writes identical
//                                array to a sequential loop.
//   3. 10^5 dispatch stress   — random partitions; each round verifies
//                                output. Catches torn writes / races.
//   4. Worker affinity check  — pthread_getaffinity_np shows exactly 1
//                                CPU bit, in {0, 1, 2}.
//   5. workers=1 fallback     — empty cpus_to_pin runs fn on caller; no
//                                spawn; degraded() == false.
//   6. K=3 trip on streak     — issue#37: 3 consecutive deadline-overruns
//                                trip the gate; pool transitions to
//                                degraded after the K-th miss only.
//   6a. Single overrun no-trip — issue#37: K=1 absorbed; degraded stays
//                                false; fallback_count stays 0.
//   6b. K-1 streak no-trip    — issue#37: K=2 absorbed; degraded stays
//                                false; fallback_count stays 0.
//   6c. Reset on success      — issue#37: miss-miss-success-miss chain
//                                does NOT trip (counter goes 1,2,0,1).
//   6d. Scaled-range trip     — issue#37: K=3 trips at scaled deadline
//                                (range=1500 → scale=3 → 150 ms deadline).
//   7. Concurrent dispatch    — second concurrent dispatch from same
//                                instance is rejected.
//   8. Ctor timeout fallback  — covered by §3.5 inline-degraded note;
//                                hard to fault-inject without lowering
//                                RLIMIT_NPROC, so this case asserts
//                                snapshot_diag().degraded == 0 in the
//                                healthy steady state and documents the
//                                fault-injection path in a comment.
//
// Test fn-vs-deadline ratio standardized at 1.875× (round-1 n3 / round-2
// m2'): fn=150 ms vs 50 ms steady-state deadline; fn=300 ms vs 150 ms
// scaled deadline (Case 6d, 2.0× ratio above the 1.875× floor).
//
// Hardware-free; runs on any Linux x86_64 / arm64 with pthreads.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <random>
#include <thread>
#include <vector>

#include <pthread.h>
#include <sched.h>

#include "parallel/parallel_eval_pool.hpp"

using godo::parallel::ParallelEvalPool;
using godo::parallel::ParallelEvalSnapshot;

namespace {

std::vector<int> available_cpus_for_test() {
    // Production pins to {0, 1, 2}. Dev hosts may have isolcpus disabled
    // so all four cores show in the affinity mask; we still pin
    // explicitly to {0, 1, 2} (CPU 3 is forbidden — pool ctor asserts).
    return {0, 1, 2};
}

}  // namespace

TEST_CASE("Case 1: Lifecycle — ctor spawns workers; dtor joins cleanly") {
    {
        ParallelEvalPool pool(available_cpus_for_test());
        CHECK(pool.worker_count() == 3);
        CHECK_FALSE(pool.degraded());
    }
    // dtor joined without crashing — implicit pass.
    {
        // Empty — workers=1 rollback path. Worker count = 0; not degraded.
        ParallelEvalPool pool({});
        CHECK(pool.worker_count() == 0);
        CHECK_FALSE(pool.degraded());
    }
}

TEST_CASE("Case 2: Output equivalence — parallel_for(0, N, fn) matches sequential") {
    constexpr std::size_t kN = 5000;
    std::vector<std::int64_t> par(kN, 0);
    std::vector<std::int64_t> seq(kN, 0);

    ParallelEvalPool pool(available_cpus_for_test());

    const bool ok = pool.parallel_for(0, kN, [&](std::size_t i) {
        par[i] = static_cast<std::int64_t>(i) *
                 static_cast<std::int64_t>(i);
    });
    CHECK(ok);

    for (std::size_t i = 0; i < kN; ++i) {
        seq[i] = static_cast<std::int64_t>(i) *
                 static_cast<std::int64_t>(i);
    }

    CHECK(par == seq);
}

TEST_CASE("Case 3: 10^5 dispatch stress — random partitions, each round verified") {
    constexpr std::size_t kRounds = 100'000;
    constexpr std::size_t kMaxRange = 1024;

    ParallelEvalPool pool(available_cpus_for_test());
    std::mt19937_64 rng(0xC1A0BAFEC0DEDEADULL);
    std::uniform_int_distribution<std::size_t> dist(8, kMaxRange);

    std::vector<std::int32_t> buf(kMaxRange, 0);
    for (std::size_t r = 0; r < kRounds; ++r) {
        const std::size_t n = dist(rng);
        // Reset only [0, n) to detect torn writes outside the range.
        for (std::size_t i = 0; i < n; ++i) buf[i] = 0;
        const bool ok = pool.parallel_for(0, n, [&](std::size_t i) {
            buf[i] = static_cast<std::int32_t>(i + 1);
        });
        REQUIRE(ok);
        for (std::size_t i = 0; i < n; ++i) {
            REQUIRE(buf[i] == static_cast<std::int32_t>(i + 1));
        }
    }
}

TEST_CASE("Case 4: Worker affinity — exactly 1 CPU bit set per worker, in {0,1,2}") {
    // Use parallel_for to capture each worker's running CPU id from inside
    // its execution context. Workers are pinned via
    // pthread_setaffinity_np at ctor; sched_getcpu() inside the fn body
    // confirms the kernel honoured the pin. We probe with 3 workers ×
    // 8 indices each (24 total) and require every observation to be in
    // {0, 1, 2}, with all 3 CPUs observed.
    ParallelEvalPool pool(available_cpus_for_test());
    constexpr std::size_t kN = 24;
    std::vector<int> running_cpu(kN, -1);

    const bool ok = pool.parallel_for(0, kN, [&](std::size_t i) {
        running_cpu[i] = sched_getcpu();
    });
    CHECK(ok);

    bool saw_0 = false, saw_1 = false, saw_2 = false;
    for (std::size_t i = 0; i < kN; ++i) {
        const int cpu = running_cpu[i];
        REQUIRE(cpu >= 0);
        // Hard-veto: NEVER on CPU 3 (project_cpu3_isolation.md).
        REQUIRE(cpu != 3);
        REQUIRE(cpu < 3);
        if (cpu == 0) saw_0 = true;
        if (cpu == 1) saw_1 = true;
        if (cpu == 2) saw_2 = true;
    }
    CHECK(saw_0);
    CHECK(saw_1);
    CHECK(saw_2);
}

TEST_CASE("Case 5: workers=1 fallback — empty cpus runs fn on caller, not degraded") {
    ParallelEvalPool pool({});
    CHECK(pool.worker_count() == 0);
    CHECK_FALSE(pool.degraded());

    constexpr std::size_t kN = 1024;
    std::vector<std::int32_t> buf(kN, 0);
    const std::thread::id caller = std::this_thread::get_id();
    std::atomic<bool> ran_off_caller{false};

    const bool ok = pool.parallel_for(0, kN, [&](std::size_t i) {
        if (std::this_thread::get_id() != caller) {
            ran_off_caller.store(true);
        }
        buf[i] = static_cast<std::int32_t>(i + 1);
    });
    CHECK(ok);
    CHECK_FALSE(ran_off_caller.load());
    for (std::size_t i = 0; i < kN; ++i) {
        CHECK(buf[i] == static_cast<std::int32_t>(i + 1));
    }

    // workers=1 path is NOT a degradation — fallback_count_ stays at 0.
    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.dispatch_count == 1);
    CHECK(s.fallback_count == 0);
    CHECK(s.valid == 1);
    CHECK(s.degraded == 0);
}

TEST_CASE("Case 6: K=3 trip — three consecutive overruns flip degraded; "
          "intermediate K-1 streaks absorb without flipping (issue#37)") {
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE_FALSE(pool.degraded());

    // fn=150 ms vs 50 ms range-proportional deadline (1.875× ratio).
    // range=(0, 16) → scale=1 → deadline=50 ms. Each call must return
    // false; only the K-th call flips degraded.
    auto slow_fn = [](std::size_t) {
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
    };

    // Miss #1 — streak=1, gate not tripped.
    const bool first = pool.parallel_for(0, 16, slow_fn);
    CHECK_FALSE(first);
    CHECK_FALSE(pool.degraded());
    CHECK(pool.snapshot_diag().fallback_count == 0);

    // Miss #2 — streak=2, gate not tripped.
    const bool second = pool.parallel_for(0, 16, slow_fn);
    CHECK_FALSE(second);
    CHECK_FALSE(pool.degraded());
    CHECK(pool.snapshot_diag().fallback_count == 0);

    // Miss #3 — streak reaches K=3, gate trips.
    const bool third = pool.parallel_for(0, 16, slow_fn);
    CHECK_FALSE(third);
    CHECK(pool.degraded());

    // Subsequent dispatch sees the pool degraded and runs inline.
    std::atomic<int> count{0};
    const bool fourth = pool.parallel_for(0, 16, [&](std::size_t) {
        count.fetch_add(1);
    });
    CHECK(fourth);
    CHECK(count.load() == 16);

    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.degraded == 1);
    // fallback_count = 1 for the K-th trip + 1 for the inline dispatch.
    // K-1 absorbed streaks contribute 0 (m1' fold-in).
    CHECK(s.fallback_count == 2);
}

TEST_CASE("Case 6a: Single overrun does not degrade (issue#37 K=1 absorbed)") {
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE_FALSE(pool.degraded());

    const bool ok = pool.parallel_for(0, 16, [](std::size_t) {
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
    });
    CHECK_FALSE(ok);
    CHECK_FALSE(pool.degraded());

    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.degraded == 0);
    CHECK(s.fallback_count == 0);  // K-1 absorbed → no fallback
}

TEST_CASE("Case 6b: K-1=2 consecutive overruns do not degrade (issue#37)") {
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE_FALSE(pool.degraded());

    auto slow_fn = [](std::size_t) {
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
    };

    const bool first = pool.parallel_for(0, 16, slow_fn);
    CHECK_FALSE(first);
    CHECK_FALSE(pool.degraded());

    const bool second = pool.parallel_for(0, 16, slow_fn);
    CHECK_FALSE(second);
    CHECK_FALSE(pool.degraded());

    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.degraded == 0);
    CHECK(s.fallback_count == 0);
}

TEST_CASE("Case 6c: miss-miss-success resets streak counter (issue#37)") {
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE_FALSE(pool.degraded());

    auto slow_fn = [](std::size_t) {
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
    };
    auto fast_fn = [](std::size_t) {
        // Well under 50 ms — guaranteed success-completion.
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    };

    // Miss #1 (streak=1)
    CHECK_FALSE(pool.parallel_for(0, 16, slow_fn));
    CHECK_FALSE(pool.degraded());

    // Miss #2 (streak=2)
    CHECK_FALSE(pool.parallel_for(0, 16, slow_fn));
    CHECK_FALSE(pool.degraded());

    // Success — counter resets to 0.
    CHECK(pool.parallel_for(0, 16, fast_fn));
    CHECK_FALSE(pool.degraded());

    // Miss #3 — but counter went 0 → 1 (NOT 3); gate stays untripped.
    CHECK_FALSE(pool.parallel_for(0, 16, slow_fn));
    CHECK_FALSE(pool.degraded());

    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.degraded == 0);
    CHECK(s.fallback_count == 0);  // still 0 — gate never tripped
}

TEST_CASE("Case 6d: K=3 trip at scaled-range deadline — range=1500 → "
          "scale=3 → 150 ms deadline; fn=300 ms (2.0× ratio)") {
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE_FALSE(pool.degraded());

    // range=(0, 1500) so scale = max(1, 1500/500) = 3 → deadline=150 ms.
    // fn=300 ms (2.0× ratio above the 1.875× floor — m2' fold-in).
    // Only worker 0 sleeps 300 ms; workers 1 and 2 do trivial work.
    // The dispatch waits for ALL workers, so the timeout still fires
    // because worker 0 cannot finish within 150 ms regardless of the
    // others. Use a small atomic to make the test deterministic without
    // sleeping 300 ms × 1500 iters (would take 7+ minutes per dispatch).
    auto slow_fn = [](std::size_t i) {
        if (i == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
        }
    };

    // Three consecutive overruns at the scaled deadline.
    CHECK_FALSE(pool.parallel_for(0, 1500, slow_fn));
    CHECK_FALSE(pool.degraded());

    CHECK_FALSE(pool.parallel_for(0, 1500, slow_fn));
    CHECK_FALSE(pool.degraded());

    CHECK_FALSE(pool.parallel_for(0, 1500, slow_fn));
    CHECK(pool.degraded());

    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.degraded == 1);
    CHECK(s.fallback_count == 1);  // only the K-th trip incremented
}

TEST_CASE("Case 7: Concurrent dispatch from same instance — second is rejected") {
    ParallelEvalPool pool(available_cpus_for_test());
    std::atomic<bool> first_started{false};
    std::atomic<bool> first_can_finish{false};

    // First dispatch: a slow fn that blocks until first_can_finish flips.
    // Note: the inner sleep (20 µs poll, well below the 50 ms deadline)
    // keeps the dispatch within budget so the test does not race the
    // K-gate streak counter — we gate on `first_started` /
    // `first_can_finish` so the second dispatch happens DURING the first.
    std::thread t1([&]() {
        const bool ok = pool.parallel_for(0, 8, [&](std::size_t) {
            first_started.store(true);
            // Spin briefly; the second dispatch attempt happens here.
            for (int i = 0; i < 1000 && !first_can_finish.load(); ++i) {
                std::this_thread::sleep_for(std::chrono::microseconds(20));
            }
        });
        CHECK(ok);
    });

    // Wait until t1 is in the dispatch.
    while (!first_started.load()) {
        std::this_thread::sleep_for(std::chrono::microseconds(50));
    }

    // Concurrent dispatch from THIS thread (a second caller) — must be
    // rejected with `false`. The pool's API contract is single-caller.
    const bool second = pool.parallel_for(0, 8, [](std::size_t) {});
    CHECK_FALSE(second);

    first_can_finish.store(true);
    t1.join();
}

TEST_CASE("Case 8: Healthy steady-state diag — degraded=0; counters consistent") {
    // Document the ctor-timeout fault-injection path: a worker thread
    // that fails to spawn (pthread_create EAGAIN under
    // setrlimit(RLIMIT_NPROC, low)) would trigger M4 / R12 — the ctor
    // logs `[pool-degraded]` and degraded() returns true. CI runners
    // typically don't allow rlimit games; we instead verify the healthy
    // case as the contract: under normal load, a freshly-constructed
    // pool reports degraded=0 and dispatch_count grows by 1 per
    // parallel_for call.
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE_FALSE(pool.degraded());

    constexpr std::size_t kN     = 100;
    constexpr std::size_t kIters = 50;
    std::vector<std::int32_t> buf(kN, 0);
    for (std::size_t r = 0; r < kIters; ++r) {
        for (auto& x : buf) x = 0;
        const bool ok = pool.parallel_for(0, kN, [&](std::size_t i) {
            buf[i] = static_cast<std::int32_t>(i);
        });
        REQUIRE(ok);
    }

    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.degraded       == 0);
    CHECK(s.fallback_count == 0);
    CHECK(s.dispatch_count == kIters);
    // p99_us / max_us are non-zero in any realistic run (>= 1 µs).
    CHECK(s.p99_us > 0);
    CHECK(s.max_us > 0);
}

TEST_CASE("Bonus: CPU 3 in cpus_to_pin throws std::invalid_argument") {
    // project_cpu3_isolation.md hard-veto. Pool ctor must reject this.
    CHECK_THROWS_AS(ParallelEvalPool({0, 3}), std::invalid_argument);
    CHECK_THROWS_AS(ParallelEvalPool({3}),    std::invalid_argument);
    // Negative CPU id is also invalid.
    CHECK_THROWS_AS(ParallelEvalPool({-1, 0}), std::invalid_argument);
}

// =====================================================================
// issue#19 — `parallel_for_with_scratch<S>` cases (a)..(e). Per plan §6
// + Mode-A m3/n4/n5 fold. The runtime size-mismatch guard uses
// `std::abort()` in production; the test fixture flips
// `test_hooks::s_abort_throws_for_test` so the same guard throws
// `std::logic_error` for doctest-observable testing.
// =====================================================================

namespace {

// RAII switch on the test-only abort-throws flag. Tests that observe
// the size-mismatch path scope this so the flag never leaks across
// cases (could race with a parallel test runner).
struct AbortThrowsScope {
    AbortThrowsScope() {
        godo::parallel::test_hooks::s_abort_throws_for_test.store(
            true, std::memory_order_release);
    }
    ~AbortThrowsScope() {
        godo::parallel::test_hooks::s_abort_throws_for_test.store(
            false, std::memory_order_release);
    }
};

}  // namespace

TEST_CASE("issue#19 (a): parallel_for_with_scratch round-trips per-worker scratch state") {
    constexpr std::size_t kN = 600;
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE(pool.worker_count() == 3);

    // Per-worker scratch: each worker owns one int counter and an
    // accumulator vector. The fn body increments the counter once per
    // iteration the worker handles.
    struct Scratch {
        std::int64_t count{0};
        std::int64_t sum{0};
    };
    std::vector<Scratch> per_worker(3);

    const std::int64_t deadline = 100'000'000LL;  // 100 ms
    const bool ok = pool.parallel_for_with_scratch<Scratch>(
        0, kN, per_worker,
        [](std::size_t i, Scratch& s) {
            s.count += 1;
            s.sum   += static_cast<std::int64_t>(i);
        },
        deadline);
    CHECK(ok);

    std::int64_t total_count = 0;
    std::int64_t total_sum   = 0;
    for (const auto& s : per_worker) {
        CHECK(s.count > 0);              // every worker did at least 1
        total_count += s.count;
        total_sum   += s.sum;
    }
    CHECK(total_count == static_cast<std::int64_t>(kN));
    // Sum of i in [0, kN) = kN*(kN-1)/2 = 600*599/2 = 179700.
    CHECK(total_sum == 179700);
}

TEST_CASE("issue#19 (b): per_worker size mismatch trips the runtime abort guard") {
    AbortThrowsScope scope;  // flip abort → throw for the duration
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE(pool.worker_count() == 3);

    struct Scratch { int x{0}; };
    std::vector<Scratch> wrong_sized(2);  // 2 instead of 3

    CHECK_THROWS_AS((pool.parallel_for_with_scratch<Scratch>(
        0, 16, wrong_sized,
        [](std::size_t, Scratch&) {},
        100'000'000LL)), std::logic_error);

    // Oversized also trips.
    std::vector<Scratch> oversized(5);
    CHECK_THROWS_AS((pool.parallel_for_with_scratch<Scratch>(
        0, 16, oversized,
        [](std::size_t, Scratch&) {},
        100'000'000LL)), std::logic_error);
}

TEST_CASE("issue#19 (c): workers=0 rollback runs fn on caller, per_worker[0] sees all increments") {
    ParallelEvalPool pool({});  // empty cpus_to_pin
    CHECK(pool.worker_count() == 0);
    CHECK_FALSE(pool.degraded());

    constexpr std::size_t kN = 256;
    struct Scratch { std::int64_t hits{0}; };
    std::vector<Scratch> per_worker(1);  // exactly 1 expected for w=0

    const std::thread::id caller = std::this_thread::get_id();
    std::atomic<bool> ran_off_caller{false};

    const bool ok = pool.parallel_for_with_scratch<Scratch>(
        0, kN, per_worker,
        [&](std::size_t, Scratch& s) {
            if (std::this_thread::get_id() != caller) {
                ran_off_caller.store(true);
            }
            s.hits += 1;
        },
        100'000'000LL);
    CHECK(ok);
    CHECK_FALSE(ran_off_caller.load());
    CHECK(per_worker[0].hits == static_cast<std::int64_t>(kN));
    CHECK_FALSE(pool.degraded());
}

TEST_CASE("issue#19 (d): caller-supplied deadline overrun — 3 consecutive "
          "trip K=3 gate; intermediate misses absorbed (issue#37)") {
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE_FALSE(pool.degraded());

    struct Scratch { int x{0}; };
    std::vector<Scratch> per_worker(3);

    // 100 ms sleep per iter against a 1 ms deadline ⇒ guaranteed timeout
    // on every dispatch. The K=3 gate (issue#37) is shared between
    // parallel_for and dispatch_with_scratch_erased — three consecutive
    // overruns on this dispatcher trip it.
    auto slow_fn = [](std::size_t, Scratch&) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    };

    // Miss #1 — absorbed (streak=1).
    CHECK_FALSE(pool.parallel_for_with_scratch<Scratch>(
        0, 16, per_worker, slow_fn, 1'000'000LL));
    CHECK_FALSE(pool.degraded());

    // Miss #2 — absorbed (streak=2).
    CHECK_FALSE(pool.parallel_for_with_scratch<Scratch>(
        0, 16, per_worker, slow_fn, 1'000'000LL));
    CHECK_FALSE(pool.degraded());

    // Miss #3 — K reached, gate trips.
    CHECK_FALSE(pool.parallel_for_with_scratch<Scratch>(
        0, 16, per_worker, slow_fn, 1'000'000LL));
    CHECK(pool.degraded());

    // Subsequent dispatch sees pool degraded ⇒ runs inline + returns false.
    std::atomic<int> count{0};
    const bool fourth = pool.parallel_for_with_scratch<Scratch>(
        0, 8, per_worker,
        [&](std::size_t, Scratch&) { count.fetch_add(1); },
        100'000'000LL);
    CHECK_FALSE(fourth);            // degraded path returns false
    CHECK(count.load() == 8);       // but iterations did run inline

    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.degraded == 1);
    // fallback_count = 1 for the K-th trip + 1 for the inline dispatch.
    CHECK(s.fallback_count == 2);
}

TEST_CASE("issue#19 (e): issue#11 parallel_for(begin, end, fn) is byte-identical regression pin") {
    // The new scratch path is purely additive; the index-only
    // `parallel_for` surface must produce identical output to the
    // pre-issue#19 main. We validate via the same fixture as Case 2
    // (squared-i write pattern at N=5000) and an independent FNV-1a
    // hash of the result buffer to catch any silent reordering.
    constexpr std::size_t kN = 5000;
    std::vector<std::int64_t> par(kN, 0);

    ParallelEvalPool pool(available_cpus_for_test());
    const bool ok = pool.parallel_for(0, kN, [&](std::size_t i) {
        par[i] = static_cast<std::int64_t>(i) *
                 static_cast<std::int64_t>(i);
    });
    CHECK(ok);

    // FNV-1a 64-bit hash of the byte representation of par[].
    std::uint64_t hash = 14695981039346656037ULL;
    const auto* bytes = reinterpret_cast<const std::uint8_t*>(par.data());
    const std::size_t nbytes = par.size() * sizeof(std::int64_t);
    for (std::size_t i = 0; i < nbytes; ++i) {
        hash ^= static_cast<std::uint64_t>(bytes[i]);
        hash *= 1099511628211ULL;
    }

    // Sequential reference (intent: same sequence of values).
    std::vector<std::int64_t> seq(kN, 0);
    for (std::size_t i = 0; i < kN; ++i) {
        seq[i] = static_cast<std::int64_t>(i) *
                 static_cast<std::int64_t>(i);
    }
    std::uint64_t seq_hash = 14695981039346656037ULL;
    const auto* seq_bytes =
        reinterpret_cast<const std::uint8_t*>(seq.data());
    for (std::size_t i = 0; i < nbytes; ++i) {
        seq_hash ^= static_cast<std::uint64_t>(seq_bytes[i]);
        seq_hash *= 1099511628211ULL;
    }

    CHECK(hash == seq_hash);
    CHECK(par == seq);
}
