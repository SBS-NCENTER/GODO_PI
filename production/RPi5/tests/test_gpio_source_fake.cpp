// Hardware-free tests for GpioSourceFake — exercises the same debounce +
// dispatch path GpioSourceLibgpiod uses (the fake's body is the spec for
// the production behaviour).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <atomic>
#include <cstdint>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "gpio/gpio_source.hpp"

#include "gpio_source_fake.hpp"

using godo::gpio::GpioCallbacks;
using godo::gpio::LineIndex;
using godo::gpio::test::GpioSourceFake;
using godo::rt::AmclMode;

namespace {

// Build callbacks that drive a *test-local* atomic — never the global
// g_amcl_mode — so parallel test executables cannot interfere with each
// other. The production driver uses identical logic; only the target
// atomic differs.
GpioCallbacks make_cbs(std::atomic<AmclMode>& mode_target) {
    GpioCallbacks cbs;
    cbs.on_calibrate_press = [&mode_target]() {
        mode_target.store(AmclMode::OneShot, std::memory_order_release);
    };
    cbs.on_live_toggle_press = [&mode_target]() {
        auto cur = mode_target.load(std::memory_order_acquire);
        for (;;) {
            AmclMode next = AmclMode::Idle;
            switch (cur) {
                case AmclMode::Idle: next = AmclMode::Live; break;
                case AmclMode::Live: next = AmclMode::Idle; break;
                case AmclMode::OneShot: return;  // drop, do not queue (S5)
            }
            if (mode_target.compare_exchange_weak(
                    cur, next,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                return;
            }
        }
    };
    return cbs;
}

constexpr std::int64_t MS = 1'000'000LL;
constexpr std::int64_t DEBOUNCE_NS = godo::constants::GPIO_DEBOUNCE_NS;  // 50 ms

}  // namespace

TEST_CASE("Calibrate press stores OneShot") {
    std::atomic<AmclMode> mode{AmclMode::Idle};
    GpioSourceFake src(DEBOUNCE_NS, make_cbs(mode));

    REQUIRE(src.simulate_press(LineIndex::Calibrate, 0));
    CHECK(mode.load() == AmclMode::OneShot);
}

TEST_CASE("Live-toggle press toggles Idle ↔ Live") {
    std::atomic<AmclMode> mode{AmclMode::Idle};
    GpioSourceFake src(DEBOUNCE_NS, make_cbs(mode));

    REQUIRE(src.simulate_press(LineIndex::LiveToggle, 0));
    CHECK(mode.load() == AmclMode::Live);

    // Use a press time outside the debounce window so it is accepted.
    REQUIRE(src.simulate_press(LineIndex::LiveToggle, 100 * MS));
    CHECK(mode.load() == AmclMode::Idle);
}

TEST_CASE("Debounce — 30 ms gap is rejected, 80 ms gap accepted") {
    int calibrate_count = 0;
    GpioCallbacks cbs;
    cbs.on_calibrate_press = [&]() { ++calibrate_count; };
    GpioSourceFake src(DEBOUNCE_NS, cbs);

    REQUIRE(src.simulate_press(LineIndex::Calibrate, 10 * MS));
    CHECK(calibrate_count == 1);

    // 30 ms gap → inside 50 ms window → rejected.
    CHECK_FALSE(src.simulate_press(LineIndex::Calibrate, 40 * MS));
    CHECK(calibrate_count == 1);

    // 80 ms gap from the LAST ACCEPTED (10 ms) → 70 ms apart → accepted.
    REQUIRE(src.simulate_press(LineIndex::Calibrate, 80 * MS));
    CHECK(calibrate_count == 2);
}

TEST_CASE("Last-accepted semantics — bounce-burst cannot extend the window") {
    // Per amendment M2: a rejected event does NOT advance last_event_ns.
    // Construct a long bounce burst where each event is < 50 ms after the
    // previous BUT the cumulative span exceeds 50 ms. Without
    // last-accepted semantics, the window would slide forward and a
    // spurious press at the end could land outside the original 50 ms;
    // with last-accepted semantics, every event in the burst is rejected.
    int calibrate_count = 0;
    GpioCallbacks cbs;
    cbs.on_calibrate_press = [&]() { ++calibrate_count; };
    GpioSourceFake src(DEBOUNCE_NS, cbs);

    REQUIRE(src.simulate_press(LineIndex::Calibrate, 0));
    CHECK(calibrate_count == 1);
    const auto first_accept_ns = src.last_event_ns(LineIndex::Calibrate);

    // Burst: events at 10, 20, 30, 40, 49 ms — all < 50 ms after 0.
    for (std::int64_t t : {10 * MS, 20 * MS, 30 * MS, 40 * MS, 49 * MS}) {
        CHECK_FALSE(src.simulate_press(LineIndex::Calibrate, t));
    }
    CHECK(calibrate_count == 1);
    // Critical: last_event_ns must still equal first_accept_ns.
    CHECK(src.last_event_ns(LineIndex::Calibrate) == first_accept_ns);

    // Now an event at exactly 50 ms after first accept is accepted (the
    // strict-less condition < is the rejection guard, so == passes).
    REQUIRE(src.simulate_press(LineIndex::Calibrate, 50 * MS));
    CHECK(calibrate_count == 2);
}

TEST_CASE("Live-toggle press during OneShot is dropped (S5)") {
    std::atomic<AmclMode> mode{AmclMode::OneShot};
    GpioSourceFake src(DEBOUNCE_NS, make_cbs(mode));

    // Press while in OneShot — callback runs, but CAS detects OneShot and
    // returns without storing.
    REQUIRE(src.simulate_press(LineIndex::LiveToggle, 0));
    CHECK(mode.load() == AmclMode::OneShot);

    // After OneShot completes (cold writer would store Idle; we simulate),
    // the next press toggles to Live as usual.
    mode.store(AmclMode::Idle);
    REQUIRE(src.simulate_press(LineIndex::LiveToggle, 100 * MS));
    CHECK(mode.load() == AmclMode::Live);
}

TEST_CASE("Per-line debounce is independent") {
    // Calibrate and live-toggle have separate debounce windows; pressing
    // one immediately after the other must not silence the second.
    int calibrate_count = 0, live_toggle_count = 0;
    GpioCallbacks cbs;
    cbs.on_calibrate_press   = [&]() { ++calibrate_count; };
    cbs.on_live_toggle_press = [&]() { ++live_toggle_count; };
    GpioSourceFake src(DEBOUNCE_NS, cbs);

    REQUIRE(src.simulate_press(LineIndex::Calibrate, 0));
    REQUIRE(src.simulate_press(LineIndex::LiveToggle, 5 * MS));  // 5 ms later
    CHECK(calibrate_count == 1);
    CHECK(live_toggle_count == 1);
}
