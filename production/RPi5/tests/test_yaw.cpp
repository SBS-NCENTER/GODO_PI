// Pinned tests for yaw/yaw.hpp, per SYSTEM_DESIGN.md §6.5.
// All comparisons are byte-identical (no doctest Approx).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdint>

#include "yaw/yaw.hpp"

using godo::yaw::lerp_angle;
using godo::yaw::wrap_signed24;

TEST_CASE("lerp_angle: fixed-point identity at 0, 90, 180, 270") {
    for (double a : {0.0, 90.0, 180.0, 270.0}) {
        CHECK(lerp_angle(a, a, 0.0)  == a);
        CHECK(lerp_angle(a, a, 0.5)  == a);
        CHECK(lerp_angle(a, a, 1.0)  == a);
    }
}

TEST_CASE("lerp_angle: endpoint at frac=0 (359 -> 1)") {
    CHECK(lerp_angle(359.0, 1.0, 0.0) == 359.0);
}

TEST_CASE("lerp_angle: endpoint at frac=1 (359 -> 1)") {
    CHECK(lerp_angle(359.0, 1.0, 1.0) == 1.0);
}

TEST_CASE("lerp_angle: short arc across zero (359 -> 1 @ 0.5 = 0)") {
    CHECK(lerp_angle(359.0, 1.0, 0.5) == 0.0);
}

TEST_CASE("lerp_angle: short arc on the other side (10 -> 350 @ 0.5 = 0)") {
    CHECK(lerp_angle(10.0, 350.0, 0.5) == 0.0);
}

TEST_CASE("lerp_angle: aliased endpoints (0 -> 360 @ 0.5 = 0)") {
    CHECK(lerp_angle(0.0, 360.0, 0.5) == 0.0);
}

TEST_CASE("lerp_angle: 720 delta collapses to shortest arc (0 -> 720 @ 0.5 = 0)") {
    CHECK(lerp_angle(0.0, 720.0, 0.5) == 0.0);
}

TEST_CASE("wrap_signed24: identity inside the canonical range") {
    constexpr std::int64_t H = std::int64_t{1} << 23;
    CHECK(wrap_signed24(-H)        == -H);
    CHECK(wrap_signed24(-1)        == -1);
    CHECK(wrap_signed24(0)         == 0);
    CHECK(wrap_signed24(1)         == 1);
    CHECK(wrap_signed24(H - 1)     == H - 1);
}

TEST_CASE("wrap_signed24: upper edge folds to -H") {
    constexpr std::int64_t H = std::int64_t{1} << 23;
    CHECK(wrap_signed24(H) == -H);
}

TEST_CASE("wrap_signed24: rollover just past upper edge") {
    constexpr std::int64_t H = std::int64_t{1} << 23;
    CHECK(wrap_signed24(H + 1) == -H + 1);
}

TEST_CASE("wrap_signed24: negative rollover just past lower edge") {
    constexpr std::int64_t H = std::int64_t{1} << 23;
    CHECK(wrap_signed24(-H - 1) == H - 1);
}

TEST_CASE("wrap_signed24: idempotence on a dense range") {
    // Sample boundaries + a wide range; idempotence must hold for all.
    for (std::int64_t v : {
             -(std::int64_t{1} << 30),
             -(std::int64_t{1} << 24),
             -((std::int64_t{1} << 23) + 7),
             std::int64_t{-5},
             std::int64_t{0},
             std::int64_t{5},
             (std::int64_t{1} << 23) - 3,
             (std::int64_t{1} << 23),
             (std::int64_t{1} << 23) + 5,
             std::int64_t{1} << 24,
             (std::int64_t{1} << 30) - 1,
         }) {
        const std::int32_t once = wrap_signed24(v);
        const std::int32_t twice = wrap_signed24(once);
        CHECK(once == twice);
    }
}
