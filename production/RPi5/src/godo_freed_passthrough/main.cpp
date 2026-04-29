// godo_freed_passthrough — minimal FreeD serial → UDP forwarder.
//
// Bring-up tool. Validates that bytes flow from the YL-128 (PL011 UART0)
// into the Pi and back out as UDP to Unreal Engine, before bringing up
// the full RT tracker (which adds offset, smoothing, SCHED_FIFO, etc.).
//
// What it does:
//   - Spawn one worker thread that runs freed::SerialReader (reuses the
//     production termios 8O1 setup + memmove re-sync framing).
//   - Two send modes:
//       --rate-hz 0    (default): forward each new packet as it arrives
//                                 (1 ms poll, lowest latency, jitter
//                                 inherited from serial + scheduler).
//       --rate-hz 59.94          : paced send via
//                                 clock_nanosleep(TIMER_ABSTIME). At
//                                 each tick send the latest available
//                                 packet (re-send previous if no new
//                                 arrived). Cadence determined by us,
//                                 not by the source.
//   - Per-second stats line on stderr.
//   - SIGINT/SIGTERM → exit cleanly within ~100 ms.
//
// What it does NOT do:
//   - Apply any (dx, dy, dyaw) offset (the tracker does that).
//   - mlockall / SCHED_FIFO / CPU pinning / cap_sys_nice (the tracker does).
//
// Defaults match the production wiring (production/RPi5/doc/freed_wiring.md):
//   --port /dev/ttyAMA0  --baud 38400  --host 10.10.204.184  --udp-port 50003
// NOTE: 50002 is reserved on the UE host for an existing listener; sending
// to 50002 would collide. The default landed at 50002 in 22b4097 and
// regressed back; this default must stay at 50003 unless the UE host's
// listener inventory changes.

#include <cerrno>
#include <climits>
#include <clocale>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <memory>
#include <string>
#include <thread>

#include <pthread.h>
#include <time.h>

#include "core/rt_flags.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "core/time.hpp"
#include "freed/d1_parser.hpp"
#include "freed/serial_reader.hpp"
#include "udp/sender.hpp"

namespace {

struct Args {
    std::string port      = "/dev/ttyAMA0";
    int         baud      = 38400;
    std::string host      = "10.10.204.184";
    int         udp_port  = 50003;  // 50002 collides with UE host listener
    int         stats_sec = 1;
    bool        quiet     = false;
    double      rate_hz   = 0.0;   // 0 = as-arrives; >0 = paced
};

void print_help() {
    std::fprintf(stderr,
        "godo_freed_passthrough — minimal FreeD serial → UDP forwarder\n"
        "\n"
        "Usage: godo_freed_passthrough [options]\n"
        "  --port <dev>       serial device     (default: /dev/ttyAMA0)\n"
        "  --baud <n>         serial baud rate  (default: 38400)\n"
        "  --host <ip>        UDP target host   (default: 10.10.204.184)\n"
        "  --udp-port <n>     UDP target port   (default: 50003)\n"
        "  --rate-hz <f>      paced send rate; 0 = as-arrives (default: 0)\n"
        "                     example: --rate-hz 59.94 for steady FreeD cadence\n"
        "  --stats-sec <n>    stats interval seconds, 0 disables (default: 1)\n"
        "  --quiet            suppress per-second stats lines\n"
        "  --help             show this message and exit\n"
        "\n"
        "On a Pi 5 with the default Trixie image the PL011 UART can appear\n"
        "as /dev/ttyAMA10 (or /dev/serial0). Apply the boot config in\n"
        "production/RPi5/doc/freed_wiring.md §B to rename it to /dev/ttyAMA0,\n"
        "or pass --port /dev/serial0 to use the canonical symlink.\n"
        "\n"
        "Paced mode uses clock_nanosleep(TIMER_ABSTIME) — independent of\n"
        "serial arrival jitter. Without RT capabilities (cap_sys_nice +\n"
        "cap_ipc_lock from scripts/setup-pi5-rt.sh) the cadence is still\n"
        "much steadier than as-arrives but may show occasional outliers\n"
        "from CFS preemption. For the production p99 < 200 µs target use\n"
        "scripts/run-pi5-tracker-rt.sh instead.\n"
        "\n"
        "Exits cleanly on SIGINT/SIGTERM.\n");
}

bool parse_int(const char* s, int& out) {
    char* end = nullptr;
    const long v = std::strtol(s, &end, 10);
    if (end == s || *end != '\0') return false;
    if (v < INT_MIN || v > INT_MAX) return false;
    out = static_cast<int>(v);
    return true;
}

bool parse_double(const char* s, double& out) {
    char* end = nullptr;
    const double v = std::strtod(s, &end);
    if (end == s || *end != '\0') return false;
    out = v;
    return true;
}

// Returns 0 on success, 1 on --help, 2 on parse error.
int parse_args(int argc, char** argv, Args& a) {
    auto need_value = [&](int& i, const char* name) -> const char* {
        if (i + 1 >= argc) {
            std::fprintf(stderr,
                "godo_freed_passthrough: %s requires a value\n", name);
            return nullptr;
        }
        return argv[++i];
    };

    for (int i = 1; i < argc; ++i) {
        const std::string opt = argv[i];
        if (opt == "--help" || opt == "-h") {
            print_help();
            return 1;
        } else if (opt == "--port") {
            const char* v = need_value(i, "--port");
            if (!v) return 2;
            a.port = v;
        } else if (opt == "--baud") {
            const char* v = need_value(i, "--baud");
            if (!v || !parse_int(v, a.baud)) {
                std::fprintf(stderr,
                    "godo_freed_passthrough: bad --baud value\n");
                return 2;
            }
        } else if (opt == "--host") {
            const char* v = need_value(i, "--host");
            if (!v) return 2;
            a.host = v;
        } else if (opt == "--udp-port") {
            const char* v = need_value(i, "--udp-port");
            if (!v || !parse_int(v, a.udp_port)) {
                std::fprintf(stderr,
                    "godo_freed_passthrough: bad --udp-port value\n");
                return 2;
            }
        } else if (opt == "--rate-hz") {
            const char* v = need_value(i, "--rate-hz");
            if (!v || !parse_double(v, a.rate_hz) || a.rate_hz < 0.0) {
                std::fprintf(stderr,
                    "godo_freed_passthrough: bad --rate-hz value (must be >= 0)\n");
                return 2;
            }
        } else if (opt == "--stats-sec") {
            const char* v = need_value(i, "--stats-sec");
            if (!v || !parse_int(v, a.stats_sec) || a.stats_sec < 0) {
                std::fprintf(stderr,
                    "godo_freed_passthrough: bad --stats-sec value (must be >= 0)\n");
                return 2;
            }
        } else if (opt == "--quiet") {
            a.quiet = true;
        } else {
            std::fprintf(stderr,
                "godo_freed_passthrough: unknown option '%s' (try --help)\n",
                opt.c_str());
            return 2;
        }
    }
    return 0;
}

// Signal handler — touches only an atomic flag, async-signal-safe.
extern "C" void signal_handler(int) noexcept {
    godo::rt::g_running.store(false, std::memory_order_release);
}

void install_signals() noexcept {
    struct sigaction sa{};
    sa.sa_handler = signal_handler;
    sigemptyset(&sa.sa_mask);
    // No SA_RESTART: we WANT blocking read()/nanosleep to return EINTR
    // so g_running gets observed promptly on Ctrl-C.
    sa.sa_flags = 0;
    ::sigaction(SIGINT,  &sa, nullptr);
    ::sigaction(SIGTERM, &sa, nullptr);
}

void advance_ns(timespec& ts, std::int64_t period_ns) noexcept {
    ts.tv_nsec += period_ns;
    while (ts.tv_nsec >= 1'000'000'000) {
        ts.tv_nsec -= 1'000'000'000;
        ts.tv_sec  += 1;
    }
}

// Counters. Both modes use the same fields — repeat/skip stay 0 in
// as-arrives mode since each loop iteration only acts on a new gen.
struct Stats {
    std::uint64_t pps      = 0;   // UDP sends in the current period
    std::uint64_t total    = 0;
    std::uint64_t send_fail = 0;
    std::uint64_t repeat   = 0;   // paced ticks where we re-sent prev pkt
    std::uint64_t skip     = 0;   // paced ticks where >1 src gen elapsed
    std::int64_t  last_emit_ns = 0;
};

void maybe_emit_stats(Stats& s, const Args& a, std::int64_t now_ns) {
    if (a.quiet || a.stats_sec <= 0) return;
    const std::int64_t period_ns =
        static_cast<std::int64_t>(a.stats_sec) * 1'000'000'000LL;
    if (now_ns - s.last_emit_ns < period_ns) return;
    std::fprintf(stderr,
        "[stat] pps=%llu total=%llu repeat=%llu skip=%llu send_fail=%llu unknown_type=%llu\n",
        static_cast<unsigned long long>(s.pps),
        static_cast<unsigned long long>(s.total),
        static_cast<unsigned long long>(s.repeat),
        static_cast<unsigned long long>(s.skip),
        static_cast<unsigned long long>(s.send_fail),
        static_cast<unsigned long long>(godo::freed::unknown_type_count()));
    s.pps = 0;
    s.repeat = 0;
    s.skip = 0;
    s.last_emit_ns = now_ns;
}

void run_as_arrives(godo::rt::Seqlock<godo::rt::FreedPacket>& latest,
                    godo::udp::UdpSender& udp,
                    const Args& a,
                    Stats& s) {
    std::uint64_t last_gen = latest.generation();
    s.last_emit_ns = godo::rt::monotonic_ns();

    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        const std::uint64_t gen = latest.generation();
        if (gen != last_gen) {
            const auto pkt = latest.load();
            if (!udp.send(pkt)) ++s.send_fail;
            last_gen = gen;
            ++s.pps;
            ++s.total;
        }
        maybe_emit_stats(s, a, godo::rt::monotonic_ns());

        // 1 ms poll. EINTR from a signal returns immediately; SIGINT
        // exit is bounded by the SerialReader's VTIME=1 (≤ 100 ms).
        timespec ts{0, 1'000'000};
        ::nanosleep(&ts, nullptr);
    }
}

void run_paced(godo::rt::Seqlock<godo::rt::FreedPacket>& latest,
               godo::udp::UdpSender& udp,
               const Args& a,
               Stats& s) {
    const std::int64_t period_ns =
        static_cast<std::int64_t>(1.0e9 / a.rate_hz);
    std::fprintf(stderr,
        "godo_freed_passthrough: paced mode period_ns=%lld (rate=%.3f Hz)\n",
        static_cast<long long>(period_ns), a.rate_hz);

    std::uint64_t last_gen = latest.generation();
    s.last_emit_ns = godo::rt::monotonic_ns();

    timespec next{};
    clock_gettime(CLOCK_MONOTONIC, &next);
    advance_ns(next, period_ns);   // first deadline = now + 1 period

    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        int rc;
        do {
            rc = ::clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next,
                                   nullptr);
        } while (rc == EINTR &&
                 godo::rt::g_running.load(std::memory_order_acquire));
        if (!godo::rt::g_running.load(std::memory_order_acquire)) break;
        if (rc != 0 && rc != EINTR) {
            std::fprintf(stderr,
                "godo_freed_passthrough: clock_nanosleep failed: %s — exiting\n",
                std::strerror(rc));
            godo::rt::g_running.store(false, std::memory_order_release);
            break;
        }

        const std::uint64_t gen = latest.generation();
        if (gen == 0) {
            // No packet ever arrived from serial yet. Skip this tick;
            // do not transmit garbage. Stats still tick the deadline.
        } else {
            const auto pkt = latest.load();
            if (!udp.send(pkt)) ++s.send_fail;
            ++s.pps;
            ++s.total;
            if (gen == last_gen) {
                ++s.repeat;
            } else {
                // Detect skipped source packets. Each Seqlock store
                // bumps the sequence by 2, so gen advances by 2 per
                // new packet. Therefore (gen - last_gen) / 2 = number
                // of new source packets since our last send; skip count
                // is anything beyond the one we forward this tick.
                const std::uint64_t advanced = (gen - last_gen) / 2U;
                if (advanced > 1U) s.skip += advanced - 1U;
                last_gen = gen;
            }
        }

        maybe_emit_stats(s, a, godo::rt::monotonic_ns());
        advance_ns(next, period_ns);
    }
}

}  // namespace

int main(int argc, char** argv) {
    std::setlocale(LC_ALL, "C");

    Args a;
    const int prc = parse_args(argc, argv, a);
    if (prc == 1) return 0;
    if (prc != 0) return 2;

    install_signals();

    std::fprintf(stderr,
        "godo_freed_passthrough: serial=%s@%d → udp %s:%d "
        "(rate=%.3f Hz, stats=%ds%s)\n",
        a.port.c_str(), a.baud, a.host.c_str(), a.udp_port,
        a.rate_hz, a.stats_sec, a.quiet ? ", quiet" : "");

    std::unique_ptr<godo::udp::UdpSender> udp;
    try {
        udp = std::make_unique<godo::udp::UdpSender>(a.host, a.udp_port);
    } catch (const std::exception& e) {
        std::fprintf(stderr,
            "godo_freed_passthrough: UDP init failed: %s\n", e.what());
        return 1;
    }

    godo::rt::Seqlock<godo::rt::FreedPacket> latest;

    std::thread t_serial([&]() {
        try {
            godo::freed::SerialReader r(a.port, a.baud);
            r.run(latest);
        } catch (const std::exception& e) {
            std::fprintf(stderr,
                "godo_freed_passthrough: serial thread fatal: %s\n", e.what());
            godo::rt::g_running.store(false, std::memory_order_release);
        }
    });

    Stats stats;
    if (a.rate_hz > 0.0) {
        run_paced(latest, *udp, a, stats);
    } else {
        run_as_arrives(latest, *udp, a, stats);
    }

    // The serial worker may be blocked inside read() waiting for the
    // first byte (VMIN=1, VTIME=1 only arms the inter-byte timer AFTER
    // the first byte arrives — with no FreeD source connected, read()
    // blocks indefinitely). Send SIGTERM directly to the worker to
    // force EINTR; the handler is a no-op on the already-set flag and
    // the worker exits at the top of its loop.
    if (t_serial.joinable()) {
        ::pthread_kill(t_serial.native_handle(), SIGTERM);
        t_serial.join();
    }
    std::fprintf(stderr,
        "godo_freed_passthrough: shutdown — total=%llu repeat=%llu skip=%llu "
        "send_fail=%llu unknown_type=%llu\n",
        static_cast<unsigned long long>(stats.total),
        static_cast<unsigned long long>(stats.repeat),
        static_cast<unsigned long long>(stats.skip),
        static_cast<unsigned long long>(stats.send_fail),
        static_cast<unsigned long long>(godo::freed::unknown_type_count()));
    return 0;
}
