#pragma once

// GPIO source — libgpiod v2 production implementation.
//
// Opens /dev/gpiochip0, requests the calibrate + live-toggle lines as
// FALLING-edge inputs with PULL_UP bias and CLOCK_MONOTONIC event
// timestamps. The event loop blocks in `wait_edge_events` with a 100 ms
// timeout (constants::SHUTDOWN_POLL_TIMEOUT_MS) so SIGTERM / g_running
// shutdown is observed within one poll cycle.
//
// Software debounce uses last-accepted semantics (rejected events do NOT
// advance `last_event_ns_[]`) and CLOCK_MONOTONIC. Burst-bouncing within
// the GPIO_DEBOUNCE_NS window (50 ms) cannot let a spurious press through;
// only a 50 ms quiet period re-arms the line.
//
// Construction is open-deferred: the constructor only stores parameters.
// `open()` builds the libgpiod request (may throw). `run()` enters the
// event loop. `close()` releases the request (idempotent, noexcept). The
// destructor calls `close()`.

#include <array>
#include <climits>
#include <cstdint>
#include <memory>
#include <string>

#include "gpio_source.hpp"

// Forward-declare gpiod types so this header does not pull libgpiod into
// every translation unit that includes it. The implementation TU
// (gpio_source_libgpiod.cpp) includes <gpiod.hpp> directly.
namespace gpiod {
class chip;
class line_request;
}  // namespace gpiod

namespace godo::gpio {

class GpioSourceLibgpiod {
public:
    // chip_path defaults to "/dev/gpiochip0" — Pi 5's main GPIO controller.
    // calibrate_pin / live_toggle_pin are BCM offsets (validated by Config
    // against constants::GPIO_MAX_BCM_PIN).
    GpioSourceLibgpiod(std::string    chip_path,
                       int            calibrate_pin,
                       int            live_toggle_pin,
                       std::int64_t   debounce_ns,
                       GpioCallbacks  callbacks);

    GpioSourceLibgpiod(const GpioSourceLibgpiod&)            = delete;
    GpioSourceLibgpiod& operator=(const GpioSourceLibgpiod&) = delete;

    ~GpioSourceLibgpiod();

    // Open the chip and request both lines. Throws std::runtime_error on
    // chip-open failure or line-request failure.
    void open();

    // Event loop. Returns when godo::rt::g_running is false. Re-enterable
    // is NOT required (the cold writer / tracker_rt main spawns one
    // instance per process).
    void run();

    // Idempotent. Releases the line request and closes the chip handle.
    void close() noexcept;

private:
    // Returns true if the event passes the debounce filter (i.e. should be
    // dispatched). Updates last_event_ns_[] only on accept.
    bool accept_event(LineIndex            idx,
                      std::int64_t         monotonic_ns) noexcept;

    std::string  chip_path_;
    int          calibrate_pin_;
    int          live_toggle_pin_;
    std::int64_t debounce_ns_;
    GpioCallbacks callbacks_;

    // libgpiod handles owned via unique_ptr so the forward declaration in
    // the header is sufficient. Both reset to nullptr in close().
    std::unique_ptr<gpiod::chip>         chip_handle_;
    std::unique_ptr<gpiod::line_request> request_;

    // Per-line last-accepted timestamp; index 0 = calibrate, 1 = live-toggle.
    // Initialised to INT64_MIN so the first press on each line is always
    // accepted regardless of the boot-uptime monotonic clock value (the
    // kernel timestamp can be very large at long uptimes).
    std::array<std::int64_t, 2> last_event_ns_{INT64_MIN, INT64_MIN};
};

}  // namespace godo::gpio
