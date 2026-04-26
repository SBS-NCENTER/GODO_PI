// Hardware-required test for GpioSourceLibgpiod — verifies the libgpiod
// bring-up sequence on a real /dev/gpiochip0. ctest LABEL =
// "hardware-required-gpio". Not run by default; invoke with:
//
//   ctest -L hardware-required-gpio
//
// Asserts:
//   - chip path exists,
//   - construction does not throw,
//   - open() succeeds (chip is openable, line request succeeds with the
//     configured BCM offsets and PULL_UP / FALLING / MONOTONIC settings),
//   - close() is idempotent,
//   - destruction is clean.
//
// Does NOT actually press a button — that requires a hardware harness.
// The press path is exercised by test_gpio_source_fake (hardware-free).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <filesystem>

#include "core/constants.hpp"
#include "gpio/gpio_source.hpp"
#include "gpio/gpio_source_libgpiod.hpp"

namespace {

constexpr const char* CHIP_PATH = "/dev/gpiochip0";

// Use the same defaults the production Config exposes.
constexpr int CALIBRATE_PIN  = 16;
constexpr int LIVE_TOGGLE_PIN = 20;

}  // namespace

TEST_CASE("GpioSourceLibgpiod opens /dev/gpiochip0 and requests two lines") {
    if (!std::filesystem::exists(CHIP_PATH)) {
        MESSAGE("Skipping: " << CHIP_PATH << " not present on this host.");
        return;
    }

    godo::gpio::GpioCallbacks cbs;
    cbs.on_calibrate_press   = []() {};
    cbs.on_live_toggle_press = []() {};

    godo::gpio::GpioSourceLibgpiod src(
        CHIP_PATH,
        CALIBRATE_PIN,
        LIVE_TOGGLE_PIN,
        godo::constants::GPIO_DEBOUNCE_NS,
        std::move(cbs));

    // open() may throw if the user does not have permission (gpio group
    // membership) or if the lines are already requested elsewhere; both
    // are operator-environment problems, NOT code defects, so we surface
    // them as test failures with a clear message.
    REQUIRE_NOTHROW(src.open());

    // Idempotent close.
    REQUIRE_NOTHROW(src.close());
    REQUIRE_NOTHROW(src.close());
}

TEST_CASE("GpioSourceLibgpiod open then immediate destruction is clean") {
    if (!std::filesystem::exists(CHIP_PATH)) {
        MESSAGE("Skipping: " << CHIP_PATH << " not present on this host.");
        return;
    }

    godo::gpio::GpioCallbacks cbs;
    cbs.on_calibrate_press   = []() {};
    cbs.on_live_toggle_press = []() {};

    {
        godo::gpio::GpioSourceLibgpiod src(
            CHIP_PATH,
            CALIBRATE_PIN,
            LIVE_TOGGLE_PIN,
            godo::constants::GPIO_DEBOUNCE_NS,
            std::move(cbs));
        REQUIRE_NOTHROW(src.open());
        // Destructor call here.
    }
}
