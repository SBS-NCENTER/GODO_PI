#pragma once

// GPIO source — public API contract.
//
// Two physical buttons translate into godo::rt::AmclMode transitions:
//   - calibrate-line falling edge → store(OneShot)
//   - live-toggle-line falling edge → toggle Idle ↔ Live (drop if currently
//     OneShot — running calibrate cannot be interrupted by a Live press;
//     the press is dropped, NOT queued, see doc/gpio_wiring.md UX notes)
//
// Production class: src/gpio/gpio_source_libgpiod.hpp.
// Test fake:        tests/gpio_source_fake.hpp.
//
// Per CODEBASE.md invariant (a), the two are duck-typed twins (same shape,
// distinct class names, no shared base class). This header only defines the
// types both share — `GpioCallbacks` and the conventional indices for the
// two lines as accepted by the test fake's `simulate_press`.

#include <functional>

namespace godo::gpio {

// Callbacks invoked when a debounced press is accepted on the corresponding
// line. Both callbacks are invoked from the GPIO event thread (not the RT
// thread); they must not block. Production wires them to `g_amcl_mode`
// transitions; tests may inject any callable.
struct GpioCallbacks {
    std::function<void()> on_calibrate_press;
    std::function<void()> on_live_toggle_press;
};

// Conventional line index used by the fake's `simulate_press` and by the
// production driver's internal `last_event_ns[2]` debounce table. The
// libgpiod implementation looks the actual BCM offset up via the line's
// `offset()` and maps it to one of these indices.
enum class LineIndex : int {
    Calibrate  = 0,
    LiveToggle = 1,
};

}  // namespace godo::gpio
