// Phase 4-2 C — cold-path deadband filter (SYSTEM_DESIGN.md §6.4.1).
//
// Two layers:
//   1. `within_deadband` — the pure predicate. Per-axis check on dx, dy
//      (metres) and dyaw (shortest signed arc, degrees). Strict `<`
//      boundary per the spec.
//   2. `apply_deadband_publish` — the publish-seam composition the cold
//      writer calls. Drives a real `Seqlock<Offset>` and `last_written`
//      reference and asserts seqlock generation behaviour:
//        - sub-deadband + forced=false → no publish, gen unchanged
//        - supra-deadband + forced=false → publish, gen advances
//        - sub-deadband + forced=true   → publish anyway (OneShot bypass)
//        - repeated sub-deadband does NOT slow-drift `last_written` past
//          the threshold (the filter compares against last WRITTEN, not
//          last seen)

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include "core/config_defaults.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "localization/deadband.hpp"

using godo::config::defaults::DEADBAND_DEG;
using godo::config::defaults::DEADBAND_MM;
using godo::localization::apply_deadband_publish;
using godo::localization::deadband_shortest_arc_deg;
using godo::localization::within_deadband;
using godo::rt::Offset;
using godo::rt::Seqlock;

namespace {

// Defaults match cfg_defaults: 10 mm / 0.1°. Cold writer divides mm by 1000
// before calling the predicate; mirror that here.
constexpr double kDeadbandXyM  = DEADBAND_MM / 1000.0;  // 0.010 m
constexpr double kDeadbandDeg  = DEADBAND_DEG;          // 0.1°

// Origin shorthand.
constexpr Offset kZero{0.0, 0.0, 0.0};

}  // namespace

// =============================================================================
// 1. within_deadband — pure predicate
// =============================================================================

TEST_CASE("within_deadband: sub-deadband Δ on all axes returns true") {
    const Offset a = kZero;
    const Offset b{0.005, 0.0, 0.05};   // 5 mm dx, 0 dy, 0.05° dyaw
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == true);
}

TEST_CASE("within_deadband: supra-deadband Δ on dx alone returns false") {
    const Offset a = kZero;
    const Offset b{0.011, 0.0, 0.0};    // 11 mm dx
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == false);
}

TEST_CASE("within_deadband: supra-deadband Δ on dy alone returns false") {
    const Offset a = kZero;
    const Offset b{0.0, 0.011, 0.0};    // 11 mm dy
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == false);
}

TEST_CASE("within_deadband: supra-deadband Δ on dyaw alone returns false") {
    const Offset a = kZero;
    const Offset b{0.0, 0.0, 0.15};     // 0.15° dyaw
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == false);
}

TEST_CASE("within_deadband: yaw wrap forward (359.95° → 0.02°) is short arc") {
    // Naive Δ would be -359.93°; shortest arc is +0.07°, well inside the
    // 0.1° deadband. Pins the wrap behaviour at the seam.
    const Offset a{0.0, 0.0, 359.95};
    const Offset b{0.0, 0.0, 0.02};
    CHECK(deadband_shortest_arc_deg(a.dyaw, b.dyaw) == doctest::Approx(0.07));
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == true);
}

TEST_CASE("within_deadband: yaw wrap backward (0.02° → 359.95°) is short arc") {
    // Naive Δ would be +359.93°; shortest arc is -0.07°. Symmetry pin.
    const Offset a{0.0, 0.0, 0.02};
    const Offset b{0.0, 0.0, 359.95};
    CHECK(deadband_shortest_arc_deg(a.dyaw, b.dyaw) == doctest::Approx(-0.07));
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == true);
}

TEST_CASE("within_deadband: exactly at the deadband (10 mm) is supra (strict <)") {
    // Spec uses strict `<`, so equality is supra-deadband (publish).
    const Offset a = kZero;
    const Offset b{0.010, 0.0, 0.0};    // exactly 10 mm
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == false);
}

TEST_CASE("within_deadband: exactly at the dyaw deadband (0.1°) is supra") {
    const Offset a = kZero;
    const Offset b{0.0, 0.0, 0.1};      // exactly 0.1°
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == false);
}

TEST_CASE("within_deadband: per-axis (NOT Euclidean) — diagonal under hypot") {
    // dx = dy = 8 mm. Euclidean magnitude is 11.31 mm, which would reject
    // under a hypot deadband; the spec is per-axis so this is sub-deadband.
    const Offset a = kZero;
    const Offset b{0.008, 0.008, 0.0};
    CHECK(within_deadband(a, b, kDeadbandXyM, kDeadbandDeg) == true);
}

// =============================================================================
// 2. apply_deadband_publish — publish-seam composition
// =============================================================================

TEST_CASE("apply_deadband_publish: sub-deadband + forced=false → no publish") {
    Seqlock<Offset> sl;
    Offset last_written = kZero;
    const std::uint64_t gen0 = sl.generation();

    const Offset noise{0.005, 0.003, 0.05};   // all sub-deadband
    const bool wrote = apply_deadband_publish(
        noise, /*forced=*/false, kDeadbandXyM, kDeadbandDeg,
        last_written, sl);

    CHECK(wrote == false);
    CHECK(sl.generation() == gen0);            // gen DID NOT advance
    CHECK(last_written.dx   == kZero.dx);      // last_written UNCHANGED
    CHECK(last_written.dy   == kZero.dy);
    CHECK(last_written.dyaw == kZero.dyaw);
}

TEST_CASE("apply_deadband_publish: supra-deadband + forced=false → publishes") {
    Seqlock<Offset> sl;
    Offset last_written = kZero;
    const std::uint64_t gen0 = sl.generation();

    const Offset jump{0.05, 0.0, 0.0};        // 5 cm — clearly supra
    const bool wrote = apply_deadband_publish(
        jump, /*forced=*/false, kDeadbandXyM, kDeadbandDeg,
        last_written, sl);

    CHECK(wrote == true);
    CHECK(sl.generation() > gen0);             // gen advanced
    const Offset published = sl.load();
    CHECK(published.dx   == jump.dx);
    CHECK(published.dy   == jump.dy);
    CHECK(published.dyaw == jump.dyaw);
    CHECK(last_written.dx   == jump.dx);       // last_written tracks publish
    CHECK(last_written.dy   == jump.dy);
    CHECK(last_written.dyaw == jump.dyaw);
}

TEST_CASE("apply_deadband_publish: sub-deadband + forced=true → publishes anyway") {
    // OneShot bypass — the operator explicitly asked for a fresh fix, so
    // even sub-deadband output must reach the seqlock and update
    // last_written.
    Seqlock<Offset> sl;
    Offset last_written = kZero;
    const std::uint64_t gen0 = sl.generation();

    const Offset tiny{0.002, 0.001, 0.03};    // all sub-deadband
    const bool wrote = apply_deadband_publish(
        tiny, /*forced=*/true, kDeadbandXyM, kDeadbandDeg,
        last_written, sl);

    CHECK(wrote == true);
    CHECK(sl.generation() > gen0);
    CHECK(last_written.dx   == tiny.dx);
    CHECK(last_written.dy   == tiny.dy);
    CHECK(last_written.dyaw == tiny.dyaw);
}

TEST_CASE("apply_deadband_publish: 100 sub-deadband calls do NOT slow-drift") {
    // Pin: the filter compares each new candidate against the LAST WRITTEN
    // value (kept fixed across rejected calls), NOT against the previous
    // candidate. So 100 candidates each ~5 mm from zero are individually
    // sub-deadband and must all be rejected — even though their cumulative
    // travel (had we used "last seen") would be 0.5 m.
    Seqlock<Offset> sl;
    Offset last_written = kZero;
    const std::uint64_t gen0 = sl.generation();

    for (int i = 0; i < 100; ++i) {
        const Offset noise{0.005, 0.0, 0.0};   // 5 mm — sub-deadband
        const bool wrote = apply_deadband_publish(
            noise, /*forced=*/false, kDeadbandXyM, kDeadbandDeg,
            last_written, sl);
        CHECK(wrote == false);
    }

    CHECK(sl.generation() == gen0);            // no writes at all
    CHECK(last_written.dx   == kZero.dx);
    CHECK(last_written.dy   == kZero.dy);
    CHECK(last_written.dyaw == kZero.dyaw);
}

TEST_CASE("apply_deadband_publish: alternating accept/reject advances correctly") {
    // After a published 5 cm jump, sub-5 mm noise around the new last_written
    // is rejected; another 5 cm jump from there is accepted again.
    Seqlock<Offset> sl;
    Offset last_written = kZero;

    const Offset jump1{0.05, 0.0, 0.0};
    CHECK(apply_deadband_publish(jump1, false, kDeadbandXyM, kDeadbandDeg,
                                 last_written, sl) == true);
    const std::uint64_t gen_after_1 = sl.generation();

    // Noise around jump1 — sub-deadband against last_written = jump1.
    const Offset noise{0.052, 0.003, 0.05};
    CHECK(apply_deadband_publish(noise, false, kDeadbandXyM, kDeadbandDeg,
                                 last_written, sl) == false);
    CHECK(sl.generation() == gen_after_1);

    // Another jump — supra-deadband against jump1.
    const Offset jump2{0.10, 0.0, 0.0};
    CHECK(apply_deadband_publish(jump2, false, kDeadbandXyM, kDeadbandDeg,
                                 last_written, sl) == true);
    CHECK(sl.generation() > gen_after_1);
    const Offset published = sl.load();
    CHECK(published.dx == jump2.dx);
    CHECK(last_written.dx == jump2.dx);
}
