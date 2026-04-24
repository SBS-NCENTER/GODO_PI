// godo_jitter — measure the actual p99 jitter that Thread D's
// clock_nanosleep(TIMER_ABSTIME) delivers on this host.
//
// Lifecycle mirrors godo_tracker_rt exactly (setlocale C, block signals,
// mlockall, pin, SCHED_FIFO) so the measured numbers reflect the RT
// environment of the real tracker.
//
// Output: mean/p50/p95/p99/max in human-readable text AND a one-line JSON
// blob (so a CI / PROGRESS.md script can parse).

#include <algorithm>
#include <cerrno>
#include <clocale>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <stdexcept>
#include <string>
#include <vector>

#include "core/constants.hpp"
#include "core/time.hpp"
#include "rt/rt_setup.hpp"

namespace {

struct Args {
    double duration_sec = 60.0;
    int    cpu          = 3;
    int    prio         = 50;
};

int parse_int(const char* s, const char* flag) {
    char* end = nullptr;
    const long v = std::strtol(s, &end, 10);
    if (end == s || *end != '\0') {
        std::fprintf(stderr, "godo_jitter: bad int for %s: '%s'\n", flag, s);
        std::exit(2);
    }
    return static_cast<int>(v);
}

double parse_double(const char* s, const char* flag) {
    char* end = nullptr;
    const double v = std::strtod(s, &end);
    if (end == s || *end != '\0') {
        std::fprintf(stderr, "godo_jitter: bad double for %s: '%s'\n", flag, s);
        std::exit(2);
    }
    return v;
}

Args parse_args(int argc, char** argv) {
    Args a;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto need_value = [&]() -> const char* {
            if (i + 1 >= argc) {
                std::fprintf(stderr,
                    "godo_jitter: %s requires a value\n", arg.c_str());
                std::exit(2);
            }
            return argv[++i];
        };
        if      (arg == "--duration-sec") a.duration_sec = parse_double(need_value(), "--duration-sec");
        else if (arg == "--cpu")          a.cpu          = parse_int(need_value(),    "--cpu");
        else if (arg == "--prio")         a.prio         = parse_int(need_value(),    "--prio");
        else if (arg == "--help" || arg == "-h") {
            std::printf(
                "Usage: godo_jitter [--duration-sec SECONDS] [--cpu N] [--prio N]\n"
                "  default: --duration-sec 60 --cpu 3 --prio 50\n");
            std::exit(0);
        } else {
            std::fprintf(stderr, "godo_jitter: unknown flag '%s'\n", arg.c_str());
            std::exit(2);
        }
    }
    return a;
}

void advance_ns(timespec& ts, std::int64_t period_ns) noexcept {
    ts.tv_nsec += period_ns;
    while (ts.tv_nsec >= 1'000'000'000) {
        ts.tv_nsec -= 1'000'000'000;
        ts.tv_sec  += 1;
    }
}

double percentile(const std::vector<std::int64_t>& sorted, double p) {
    if (sorted.empty()) return 0.0;
    const double idx = p * (static_cast<double>(sorted.size()) - 1.0);
    const std::size_t i = static_cast<std::size_t>(idx);
    return static_cast<double>(sorted[i]);
}

}  // namespace

int main(int argc, char** argv) {
    std::setlocale(LC_ALL, "C");

    const Args a = parse_args(argc, argv);

    godo::rt::setup::block_all_signals_process();
    godo::rt::setup::lock_all_memory();        // best-effort; logged on fail
    godo::rt::setup::pin_current_thread_to_cpu(a.cpu);
    godo::rt::setup::set_current_thread_fifo(a.prio);

    const std::int64_t period_ns = godo::constants::FRAME_PERIOD_NS;
    const double       hz        = godo::constants::FRAME_RATE_HZ;
    const std::size_t  ticks = static_cast<std::size_t>(a.duration_sec * hz);

    std::vector<std::int64_t> deltas;
    deltas.reserve(ticks);

    timespec next{};
    clock_gettime(CLOCK_MONOTONIC, &next);
    advance_ns(next, period_ns);               // first deadline

    std::fprintf(stderr,
        "godo_jitter: %zu ticks over %.3f s (%.3f Hz period %ld ns)\n",
        ticks, a.duration_sec, hz, static_cast<long>(period_ns));

    for (std::size_t i = 0; i < ticks; ++i) {
        int rc;
        do {
            rc = ::clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next,
                                   nullptr);
        } while (rc == EINTR);
        if (rc != 0) {
            std::fprintf(stderr,
                "godo_jitter: clock_nanosleep failed at tick %zu: %s\n",
                i, std::strerror(rc));
            return 1;
        }

        const std::int64_t now = godo::rt::monotonic_ns();
        const std::int64_t scheduled =
            static_cast<std::int64_t>(next.tv_sec) * 1'000'000'000LL +
            static_cast<std::int64_t>(next.tv_nsec);
        // Actual-minus-scheduled delta; positive = slept past the deadline.
        deltas.push_back(now - scheduled);

        advance_ns(next, period_ns);
    }

    std::sort(deltas.begin(), deltas.end());
    double mean = 0.0;
    for (std::int64_t d : deltas) mean += static_cast<double>(d);
    mean = deltas.empty() ? 0.0 : mean / static_cast<double>(deltas.size());

    const double p50 = percentile(deltas, 0.50);
    const double p95 = percentile(deltas, 0.95);
    const double p99 = percentile(deltas, 0.99);
    const double mx  = deltas.empty() ? 0.0 : static_cast<double>(deltas.back());

    std::printf(
        "godo_jitter: ticks=%zu period_ns=%ld\n"
        "  mean = %12.1f ns\n"
        "  p50  = %12.1f ns\n"
        "  p95  = %12.1f ns\n"
        "  p99  = %12.1f ns\n"
        "  max  = %12.1f ns\n",
        deltas.size(), static_cast<long>(period_ns),
        mean, p50, p95, p99, mx);

    // Machine-readable line for log scraping.
    std::printf(
        "{\"ticks\":%zu,\"period_ns\":%ld,\"mean_ns\":%.1f,"
        "\"p50_ns\":%.1f,\"p95_ns\":%.1f,\"p99_ns\":%.1f,\"max_ns\":%.1f}\n",
        deltas.size(), static_cast<long>(period_ns),
        mean, p50, p95, p99, mx);

    return 0;
}
