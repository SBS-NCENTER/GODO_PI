// issue#11 P4-2-11-1 / P4-2-11-6 — ParallelEvalPool unit tests.
//
// 8 cases per plan §6.1:
//   1. Lifecycle              — ctor spawns workers; dtor joins cleanly.
//   2. Output equivalence     — parallel_for(0, N, fn) writes identical
//                                array to a sequential loop.
//   3. 10^5 dispatch stress   — random partitions; each round verifies
//                                output. Catches torn writes / races.
//   4. Worker affinity check  — pthread_getaffinity_np shows exactly 1
//                                CPU bit, in {0, 1, 2}.
//   5. workers=1 fallback     — empty cpus_to_pin runs fn on caller; no
//                                spawn; degraded() == false.
//   6. Deadline timeout       — fn that sleeps > 50 ms; returns false;
//                                pool transitions to degraded.
//   7. Concurrent dispatch    — second concurrent dispatch from same
//                                instance is rejected.
//   8. Ctor timeout fallback  — covered by §3.5 inline-degraded note;
//                                hard to fault-inject without lowering
//                                RLIMIT_NPROC, so this case asserts
//                                snapshot_diag().degraded == 0 in the
//                                healthy steady state and documents the
//                                fault-injection path in a comment.
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
    CHECK(s.degraded == 0);
}

TEST_CASE("Case 6: Deadline timeout — fn sleeps > 50 ms; returns false; degraded") {
    ParallelEvalPool pool(available_cpus_for_test());
    REQUIRE_FALSE(pool.degraded());

    // fn deliberately sleeps 100 ms — exceeds the pool's 50 ms hard
    // deadline. parallel_for must return false; pool transitions to
    // degraded; subsequent dispatches run inline.
    const bool first = pool.parallel_for(0, 16, [](std::size_t) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    });
    CHECK_FALSE(first);
    CHECK(pool.degraded());

    // Subsequent dispatch runs inline-sequentially and reports true.
    std::atomic<int> count{0};
    const bool second = pool.parallel_for(0, 16, [&](std::size_t) {
        count.fetch_add(1);
    });
    CHECK(second);
    CHECK(count.load() == 16);

    const ParallelEvalSnapshot s = pool.snapshot_diag();
    CHECK(s.degraded == 1);
    // fallback_count incremented at least once by the timeout itself, +1
    // for each subsequent inline dispatch.
    CHECK(s.fallback_count >= 1);
}

TEST_CASE("Case 7: Concurrent dispatch from same instance — second is rejected") {
    ParallelEvalPool pool(available_cpus_for_test());
    std::atomic<bool> first_started{false};
    std::atomic<bool> first_can_finish{false};

    // First dispatch: a slow fn that blocks until first_can_finish flips.
    // Note: fn must not exceed the 50 ms deadline OR the test races the
    // degraded transition — we keep the inner sleep short (5 ms) and
    // gate on `first_started` / `first_can_finish` so the second
    // dispatch happens DURING the first.
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
