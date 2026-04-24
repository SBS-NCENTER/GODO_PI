// Offset smoother acceptance tests, per SYSTEM_DESIGN.md §6.4.4.
// Test 3 is rescoped per plan v2: "equal-gen tick is a no-op".

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdint>

#include "core/rt_types.hpp"
#include "smoother/offset_smoother.hpp"

using godo::rt::Offset;
using godo::smoother::OffsetSmoother;

namespace {

constexpr std::int64_t kRampNs = 500'000'000;  // 500 ms

bool offset_eq_exact(const Offset& a, const Offset& b) noexcept {
    return a.dx == b.dx && a.dy == b.dy && a.dyaw == b.dyaw;
}

}  // namespace

TEST_CASE("smoother: single step update reaches target at T_ramp and snaps") {
    OffsetSmoother s(kRampNs);
    const Offset target{1.0, 0.0, 0.0};

    std::int64_t t = 0;
    s.tick(target, 2, t);              // gen-bump, ramp begins at t=0

    // Part-way through the ramp, live should be between prev and target.
    t = kRampNs / 2;
    s.tick(target, 2, t);              // same gen; continues the ramp
    const Offset mid = s.live();
    CHECK(mid.dx > 0.0);
    CHECK(mid.dx < 1.0);

    // At exactly T_ramp: snap path triggered, value-copy exact.
    t = kRampNs;
    s.tick(target, 2, t);
    CHECK(offset_eq_exact(s.live(), target));
}

TEST_CASE("smoother: 10 seconds of no updates leave live == target exactly") {
    OffsetSmoother s(kRampNs);
    const Offset target{0.37, -0.25, 17.5};

    s.tick(target, 4, 0);
    s.tick(target, 4, kRampNs);        // snap

    // Simulate 10 s of hot-path ticks with no new gen. live must remain
    // byte-identical to target — float drift would be a bug.
    const std::int64_t hz = 60;        // approx; exact rate irrelevant
    for (std::int64_t i = 0; i < 10 * hz; ++i) {
        s.tick(target, 4, kRampNs + i * 1'000'000LL);
    }
    CHECK(offset_eq_exact(s.live(), target));
}

TEST_CASE("smoother: equal-gen tick is a no-op (test 3)") {
    // Rescoped per plan v2: the deadband filter lives in Thread C, so the
    // smoother-facing contract is "if gen is unchanged, no ramp restart,
    // no live re-initialisation". Call tick twice with the same gen and
    // confirm the ramp state is unchanged.
    OffsetSmoother s(kRampNs);
    const Offset t1{0.5, 0.0, 0.0};

    s.tick(t1, 2, 0);                     // gen-bump: ramp starts at t=0
    s.tick(t1, 2, kRampNs / 4);           // same gen, +125 ms
    const Offset a = s.live();
    s.tick(t1, 2, kRampNs / 4);           // same gen, same time → same live
    const Offset b = s.live();
    CHECK(offset_eq_exact(a, b));
}

TEST_CASE("smoother: rapid updates within T_ramp — no overshoot, fresh ramp") {
    OffsetSmoother s(kRampNs);
    // Three distinct gens at t=0, 20 ms, 40 ms. All still within one ramp.
    s.tick(Offset{1.0, 0.0, 0.0}, 2, 0);
    s.tick(Offset{2.0, 0.0, 0.0}, 4, 20'000'000LL);
    s.tick(Offset{3.0, 0.0, 0.0}, 6, 40'000'000LL);

    // T_ramp from the final gen tick = 40 ms + kRampNs = 540 ms → live == target.
    s.tick(Offset{3.0, 0.0, 0.0}, 6, 40'000'000LL + kRampNs);
    const Offset final_live = s.live();
    CHECK(final_live.dx == 3.0);
    CHECK(final_live.dy == 0.0);
    CHECK(final_live.dyaw == 0.0);
}

TEST_CASE("smoother: yaw wrap 359 -> 1 traverses the short arc") {
    OffsetSmoother s(kRampNs);
    // Establish prev.dyaw = 359 with a snap-done ramp.
    s.tick(Offset{0.0, 0.0, 359.0}, 2, 0);
    s.tick(Offset{0.0, 0.0, 359.0}, 2, kRampNs);
    CHECK(s.live().dyaw == 359.0);

    // New target at 1°; halfway through, live.dyaw should be at 0° (the
    // short arc), NOT 180° (the long arc).
    s.tick(Offset{0.0, 0.0, 1.0}, 4, kRampNs);
    s.tick(Offset{0.0, 0.0, 1.0}, 4, kRampNs + kRampNs / 2);
    CHECK(s.live().dyaw == 0.0);
}

TEST_CASE("smoother: init state — live defaults to zero before any gen bump") {
    OffsetSmoother s(kRampNs);
    // Plan v2: gen == 0 is treated as "never seen"; first non-zero gen
    // triggers a ramp. Initialisation sanity: live starts at {0,0,0} and
    // does not move until a gen bump arrives.
    s.tick(Offset{0.0, 0.0, 0.0}, 0, 1'000'000LL);
    const Offset live = s.live();
    CHECK(live.dx == 0.0);
    CHECK(live.dy == 0.0);
    CHECK(live.dyaw == 0.0);
}
