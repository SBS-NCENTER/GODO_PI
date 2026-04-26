#pragma once

// Test fake — duck-typed twin of GpioSourceLibgpiod (CODEBASE.md
// invariant (a) extends to GPIO/UDS source twins; no shared base class).
//
// `simulate_press(line, monotonic_ns)` exercises the same debounce filter
// the production driver uses, then dispatches the matching callback.
// Time argument is on CLOCK_MONOTONIC (matches production's clock pin per
// amendment M2).

#include <array>
#include <climits>
#include <cstdint>
#include <utility>

#include "gpio/gpio_source.hpp"

namespace godo::gpio::test {

class GpioSourceFake {
public:
    GpioSourceFake(std::int64_t  debounce_ns,
                   GpioCallbacks callbacks)
        : debounce_ns_(debounce_ns),
          callbacks_(std::move(callbacks)),
          // Sentinel: the first press on each line is always accepted.
          // Using a large negative value keeps `(t - last) >= debounce_ns`
          // true for any non-negative t (matches production semantics —
          // see gpio_source_libgpiod.cpp's last_event_ns_ comment).
          last_event_ns_{INT64_MIN, INT64_MIN} {}

    // Drive the debounce + dispatch path. Returns true if the press was
    // accepted (callback invoked); false if it was filtered out.
    bool simulate_press(LineIndex idx, std::int64_t monotonic_ns) {
        const auto i = static_cast<std::size_t>(idx);
        // Use signed subtraction safely: convert to int64_t arithmetic
        // and reject if the gap is shorter than debounce_ns_.
        if (last_event_ns_[i] != INT64_MIN &&
            monotonic_ns - last_event_ns_[i] < debounce_ns_) {
            // Last-accepted semantics: do NOT advance the window on
            // rejected events (matches production GpioSourceLibgpiod).
            return false;
        }
        last_event_ns_[i] = monotonic_ns;
        if (idx == LineIndex::Calibrate) {
            if (callbacks_.on_calibrate_press) callbacks_.on_calibrate_press();
        } else {
            if (callbacks_.on_live_toggle_press) callbacks_.on_live_toggle_press();
        }
        return true;
    }

    // Inspector — for white-box tests verifying the last-accepted
    // semantics (rejected event must not have updated the timestamp).
    std::int64_t last_event_ns(LineIndex idx) const noexcept {
        return last_event_ns_[static_cast<std::size_t>(idx)];
    }

private:
    std::int64_t                  debounce_ns_;
    GpioCallbacks                 callbacks_;
    std::array<std::int64_t, 2>   last_event_ns_;
};

}  // namespace godo::gpio::test
