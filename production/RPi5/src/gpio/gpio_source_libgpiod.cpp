#include "gpio_source_libgpiod.hpp"

#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <stdexcept>
#include <string>
#include <utility>

#include <gpiod.hpp>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"

namespace godo::gpio {

namespace {

// CLOCK_MONOTONIC reading; matches the test fake's time domain (M2).
std::int64_t now_monotonic_ns() noexcept {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<std::int64_t>(ts.tv_sec) * 1'000'000'000LL +
           static_cast<std::int64_t>(ts.tv_nsec);
}

}  // namespace

GpioSourceLibgpiod::GpioSourceLibgpiod(std::string    chip_path,
                                       int            calibrate_pin,
                                       int            live_toggle_pin,
                                       std::int64_t   debounce_ns,
                                       GpioCallbacks  callbacks)
    : chip_path_(std::move(chip_path)),
      calibrate_pin_(calibrate_pin),
      live_toggle_pin_(live_toggle_pin),
      debounce_ns_(debounce_ns),
      callbacks_(std::move(callbacks)) {}

GpioSourceLibgpiod::~GpioSourceLibgpiod() {
    close();
}

void GpioSourceLibgpiod::open() {
    try {
        chip_handle_ = std::make_unique<gpiod::chip>(chip_path_);

        gpiod::line_settings settings;
        settings.set_direction(gpiod::line::direction::INPUT)
                .set_edge_detection(gpiod::line::edge::FALLING)
                .set_bias(gpiod::line::bias::PULL_UP)
                .set_event_clock(gpiod::line::clock::MONOTONIC);

        gpiod::line::offsets offsets{
            static_cast<unsigned int>(calibrate_pin_),
            static_cast<unsigned int>(live_toggle_pin_)
        };

        auto request = chip_handle_->prepare_request()
            .set_consumer("godo_tracker_rt")
            .add_line_settings(offsets, settings)
            .do_request();

        request_ = std::make_unique<gpiod::line_request>(std::move(request));
    } catch (const std::exception& e) {
        // Re-throw as std::runtime_error with a context-rich message; the
        // tracker_rt main treats this as a non-fatal degradation (logs and
        // continues, GPIO triggers will not fire).
        throw std::runtime_error(
            std::string("GpioSourceLibgpiod::open: ") + e.what() +
            " (chip='" + chip_path_ + "', calibrate_pin=" +
            std::to_string(calibrate_pin_) + ", live_toggle_pin=" +
            std::to_string(live_toggle_pin_) + ")");
    }
}

bool GpioSourceLibgpiod::accept_event(LineIndex idx,
                                       std::int64_t monotonic_ns) noexcept {
    const auto i = static_cast<std::size_t>(idx);
    if (last_event_ns_[i] != INT64_MIN &&
        monotonic_ns - last_event_ns_[i] < debounce_ns_) {
        // Last-accepted semantics (M2): a rejected event does NOT advance
        // the window. The next press still has to wait `debounce_ns_`
        // after the LAST ACCEPTED press, not after the bouncing tail.
        return false;
    }
    last_event_ns_[i] = monotonic_ns;
    return true;
}

void GpioSourceLibgpiod::run() {
    if (!request_) {
        std::fprintf(stderr,
            "GpioSourceLibgpiod::run: open() not called or failed; "
            "exiting event loop without dispatching events.\n");
        return;
    }

    // Buffer capacity is small — bursty bounce events should be at most
    // a handful per real press; debounce drops them.
    gpiod::edge_event_buffer buffer(16);

    const auto poll_timeout = std::chrono::milliseconds(
        godo::constants::SHUTDOWN_POLL_TIMEOUT_MS);

    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        bool ready = false;
        try {
            ready = request_->wait_edge_events(poll_timeout);
        } catch (const std::exception& e) {
            std::fprintf(stderr,
                "GpioSourceLibgpiod::run: wait_edge_events: %s — exiting "
                "event loop.\n", e.what());
            return;
        }
        if (!ready) {
            // Timeout — re-check g_running and continue.
            continue;
        }
        std::size_t count = 0;
        try {
            count = request_->read_edge_events(buffer);
        } catch (const std::exception& e) {
            std::fprintf(stderr,
                "GpioSourceLibgpiod::run: read_edge_events: %s — "
                "continuing.\n", e.what());
            continue;
        }
        for (std::size_t i = 0; i < count; ++i) {
            const auto& ev = buffer.get_event(static_cast<unsigned int>(i));
            const auto offset = static_cast<unsigned int>(ev.line_offset());

            // The kernel-supplied timestamp is on CLOCK_MONOTONIC because
            // we set event_clock(MONOTONIC) above; equivalent to a
            // userspace clock_gettime here. Use the userspace reading for
            // consistency with the fake's `simulate_press(now_ns)` time
            // domain — both pass through `accept_event` identically.
            const std::int64_t now_ns = now_monotonic_ns();

            if (offset == static_cast<unsigned int>(calibrate_pin_)) {
                if (accept_event(LineIndex::Calibrate, now_ns)) {
                    if (callbacks_.on_calibrate_press) {
                        callbacks_.on_calibrate_press();
                    }
                }
            } else if (offset == static_cast<unsigned int>(live_toggle_pin_)) {
                if (accept_event(LineIndex::LiveToggle, now_ns)) {
                    if (callbacks_.on_live_toggle_press) {
                        callbacks_.on_live_toggle_press();
                    }
                }
            } else {
                std::fprintf(stderr,
                    "GpioSourceLibgpiod::run: unexpected line offset %u "
                    "(expected %d or %d); ignoring.\n",
                    offset, calibrate_pin_, live_toggle_pin_);
            }
        }
    }
}

void GpioSourceLibgpiod::close() noexcept {
    // unique_ptr resets are no-throw on libgpiod handles (their destructors
    // call release/close internally and swallow errors).
    request_.reset();
    chip_handle_.reset();
}

}  // namespace godo::gpio
