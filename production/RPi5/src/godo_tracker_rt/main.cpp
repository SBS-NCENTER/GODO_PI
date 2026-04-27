// godo_tracker_rt — Phase 4-1 RT hot path + Phase 4-2 B AMCL cold writer +
// Phase 4-2 D Wave B operator input surfaces (GPIO + UDS).
//
// Lifecycle (per SYSTEM_DESIGN.md §6.2):
//   main(): setlocale C → block signals → mlockall → load Config
//     → spawn Thread A (FreeD serial reader)
//     → spawn cold writer (AMCL OneShot state machine; src/localization/)
//     → spawn GPIO thread     (button → g_amcl_mode; src/gpio/)
//     → spawn UDS thread      (UDS JSON-lines → g_amcl_mode; src/uds/)
//     → spawn Thread D (UDP sender @ 59.94 Hz, SCHED_FIFO + pinned)
//     → spawn signal thread (waits for SIGTERM/SIGINT → g_running=false)
//     → join D, cold writer, GPIO, UDS, A, signal thread.
//
// Shutdown signalling (per plan §M1 amendment):
//   - cold writer: pthread_kill(SIGTERM) before join — its blocking
//     scan_frames(1) does not observe g_running on its own (M8).
//   - GPIO + UDS threads: NO pthread_kill. Both poll with
//     constants::SHUTDOWN_POLL_TIMEOUT_MS and self-exit on the next
//     wake-up after `g_running.store(false)`. Worst-case latency is
//     2 × SHUTDOWN_POLL_TIMEOUT_MS = 200 ms.

#include <atomic>
#include <cerrno>
#include <clocale>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <exception>
#include <memory>
#include <string>
#include <thread>

#include <pthread.h>
#include <signal.h>
#include <sys/types.h>
#include <unistd.h>

#include "core/config.hpp"
#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "core/rt_types.hpp"
#include "core/seqlock.hpp"
#include "core/time.hpp"
#include "freed/serial_reader.hpp"
#include "gpio/gpio_source.hpp"
#include "gpio/gpio_source_libgpiod.hpp"
#include "lidar/lidar_source_rplidar.hpp"
#include "localization/cold_writer.hpp"
#include "rt/rt_setup.hpp"
#include "smoother/offset_smoother.hpp"
#include "udp/sender.hpp"
#include "uds/uds_server.hpp"

using godo::rt::FreedPacket;
using godo::rt::LastPose;
using godo::rt::Offset;
using godo::rt::Seqlock;

namespace {

void advance_ns(timespec& ts, std::int64_t period_ns) noexcept {
    ts.tv_nsec += period_ns;
    while (ts.tv_nsec >= 1'000'000'000) {
        ts.tv_nsec -= 1'000'000'000;
        ts.tv_sec  += 1;
    }
}

void thread_a_serial(const godo::core::Config& cfg,
                     Seqlock<FreedPacket>&     out) {
    try {
        godo::freed::SerialReader reader(cfg.freed_port, cfg.freed_baud);
        reader.run(out);
    } catch (const std::exception& e) {
        std::fprintf(stderr,
            "godo_tracker_rt: thread_a_serial fatal: %s\n", e.what());
        godo::rt::g_running.store(false, std::memory_order_release);
    }
}

void thread_d_rt(const godo::core::Config& cfg,
                 Seqlock<FreedPacket>&     latest_freed,
                 Seqlock<Offset>&          target_offset) {
    // Thread-local lifecycle stanza.
    godo::rt::setup::pin_current_thread_to_cpu(cfg.rt_cpu);
    godo::rt::setup::set_current_thread_fifo(cfg.rt_priority);

    godo::udp::UdpSender        udp(cfg.ue_host, cfg.ue_port);
    godo::smoother::OffsetSmoother smoother(cfg.t_ramp_ns);

    timespec next{};
    clock_gettime(CLOCK_MONOTONIC, &next);

    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        const std::int64_t now_ns = godo::rt::monotonic_ns();

        const FreedPacket  p   = latest_freed.load();
        const std::uint64_t gen = target_offset.generation();
        const Offset       t   = target_offset.load();

        smoother.tick(t, gen, now_ns);
        const Offset live = smoother.live();

        FreedPacket out = p;
        godo::udp::apply_offset_inplace(out, live);
        udp.send(out);

        advance_ns(next, godo::constants::FRAME_PERIOD_NS);
        int rc;
        do {
            rc = ::clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next,
                                   nullptr);
        } while (rc == EINTR);
        if (rc != 0) {
            std::fprintf(stderr,
                "godo_tracker_rt: clock_nanosleep failed: %s — exiting.\n",
                std::strerror(rc));
            godo::rt::g_running.store(false, std::memory_order_release);
            break;
        }
    }
}

// GPIO-thread body. Wires the two button presses to g_amcl_mode:
//   - calibrate press → store(OneShot)
//   - live-toggle press → toggle Idle ↔ Live (drop if currently OneShot
//     so a running calibrate cannot be interrupted; press is dropped, NOT
//     queued — see doc/gpio_wiring.md UX notes / amendment S5)
// On open() failure (no chip / permission denied / pin already requested
// elsewhere) the thread logs and exits cleanly without affecting g_running;
// the rest of the system stays up so HTTP / UDS triggers still work.
void thread_gpio(const godo::core::Config& cfg) {
    godo::gpio::GpioCallbacks cbs;
    cbs.on_calibrate_press = []() {
        godo::rt::g_amcl_mode.store(godo::rt::AmclMode::OneShot,
                                    std::memory_order_release);
    };
    cbs.on_live_toggle_press = []() {
        // Compare-and-swap so we never overwrite an in-flight OneShot.
        // If the current mode is OneShot we drop the press (S5).
        auto cur = godo::rt::g_amcl_mode.load(std::memory_order_acquire);
        for (;;) {
            godo::rt::AmclMode next = godo::rt::AmclMode::Idle;
            switch (cur) {
                case godo::rt::AmclMode::Idle: next = godo::rt::AmclMode::Live; break;
                case godo::rt::AmclMode::Live: next = godo::rt::AmclMode::Idle; break;
                case godo::rt::AmclMode::OneShot: return;  // drop, do not queue
            }
            if (godo::rt::g_amcl_mode.compare_exchange_weak(
                    cur, next,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                return;
            }
        }
    };

    godo::gpio::GpioSourceLibgpiod src(
        "/dev/gpiochip0",
        cfg.gpio_calibrate_pin,
        cfg.gpio_live_toggle_pin,
        godo::constants::GPIO_DEBOUNCE_NS,
        std::move(cbs));
    try {
        src.open();
    } catch (const std::exception& e) {
        std::fprintf(stderr,
            "godo_tracker_rt: thread_gpio: open failed: %s — GPIO "
            "triggers disabled, UDS / future HTTP triggers still work.\n",
            e.what());
        return;
    }
    src.run();
    // RAII close on scope exit.
}

// UDS-thread body. Wires set_mode → g_amcl_mode store and get_mode →
// g_amcl_mode load. Same callback shape as the GPIO live-toggle path:
// a set_mode("Live") during a OneShot is honoured (overrides) — the UDS
// is the operator's escape hatch, distinct from the GPIO's safety guard.
//
// Track B: also wires `get_last_pose` to the cold-writer's Seqlock<LastPose>
// load so the repeatability harness + pose_watch can read the last AMCL
// pose without a tracker-side restart.
void thread_uds(const godo::core::Config& cfg,
                Seqlock<LastPose>&        last_pose_seq) {
    godo::uds::UdsServer server(
        cfg.uds_socket,
        []() { return godo::rt::g_amcl_mode.load(std::memory_order_acquire); },
        [](godo::rt::AmclMode m) {
            godo::rt::g_amcl_mode.store(m, std::memory_order_release);
        },
        [&last_pose_seq]() { return last_pose_seq.load(); });
    try {
        server.open();
    } catch (const std::exception& e) {
        std::fprintf(stderr,
            "godo_tracker_rt: thread_uds: open failed: %s — UDS "
            "triggers disabled.\n", e.what());
        return;
    }
    server.run();
}

void thread_signal_handler() {
    sigset_t mask;
    sigemptyset(&mask);
    sigaddset(&mask, SIGTERM);
    sigaddset(&mask, SIGINT);
    // Unblock only these two in this thread so sigwait can receive them;
    // other signals remain blocked per main()'s full-mask block.
    ::pthread_sigmask(SIG_UNBLOCK, &mask, nullptr);

    int signo = 0;
    const int rc = ::sigwait(&mask, &signo);
    if (rc == 0) {
        std::fprintf(stderr,
            "godo_tracker_rt: caught signal %d — shutting down\n", signo);
    } else {
        std::fprintf(stderr,
            "godo_tracker_rt: sigwait failed: %s\n", std::strerror(rc));
    }
    godo::rt::g_running.store(false, std::memory_order_release);
}

}  // namespace

int main(int argc, char** argv, char** envp) {
    // Order matches SYSTEM_DESIGN.md §6.2: memory lock before any thread
    // spawn, then process-wide signal mask, then locale. All three MUST
    // precede std::thread/pthread_create calls.
    godo::rt::setup::lock_all_memory();
    godo::rt::setup::block_all_signals_process();
    std::setlocale(LC_ALL, "C");

    godo::core::Config cfg;
    try {
        cfg = godo::core::Config::load(argc, argv, envp);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "godo_tracker_rt: %s\n", e.what());
        return 2;
    }

    std::fprintf(stderr,
        "godo_tracker_rt: ue=%s:%d freed=%s@%d rt_cpu=%d rt_prio=%d "
        "t_ramp_ns=%ld\n",
        cfg.ue_host.c_str(), cfg.ue_port,
        cfg.freed_port.c_str(), cfg.freed_baud,
        cfg.rt_cpu, cfg.rt_priority,
        static_cast<long>(cfg.t_ramp_ns));

    Seqlock<FreedPacket> latest_freed;
    Seqlock<Offset>      target_offset;
    // Track B — last AMCL pose published by the cold writer; consumed by
    // the UDS `get_last_pose` handler (uds_protocol.md §C.4). Defaults to
    // valid=0 / iterations=-1 ("no pose ever published") via the
    // value-initialised payload.
    Seqlock<LastPose>    last_pose_seq;
    // Seed `iterations = -1` so the first `get_last_pose` call before any
    // AMCL run returns a sentinel iteration count instead of zero (which
    // would be ambiguous with "ran 0 iterations").
    {
        LastPose init{};
        init.iterations = -1;
        last_pose_seq.store(init);
    }

    // Cold-writer LiDAR factory: lazily build a LidarSourceRplidar bound
    // to the configured port/baud. The factory is invoked once inside
    // run_cold_writer at startup.
    godo::localization::LidarFactory lidar_factory =
        [&cfg]() -> std::unique_ptr<godo::lidar::LidarSourceRplidar> {
            auto src = std::make_unique<godo::lidar::LidarSourceRplidar>(
                cfg.lidar_port, cfg.lidar_baud);
            src->open();
            return src;
        };

    std::thread t_signal, t_a, t_cold, t_gpio, t_uds, t_d;
    pthread_t   cold_native = 0;
    try {
        t_signal = std::thread(thread_signal_handler);
        t_a      = std::thread(thread_a_serial, std::cref(cfg),
                               std::ref(latest_freed));
        t_cold   = std::thread(godo::localization::run_cold_writer,
                               std::cref(cfg),
                               std::ref(target_offset),
                               std::ref(last_pose_seq),
                               lidar_factory);
        cold_native = t_cold.native_handle();
        t_gpio   = std::thread(thread_gpio, std::cref(cfg));
        t_uds    = std::thread(thread_uds,  std::cref(cfg),
                               std::ref(last_pose_seq));
        t_d      = std::thread(thread_d_rt, std::cref(cfg),
                               std::ref(latest_freed), std::ref(target_offset));
    } catch (const std::exception& e) {
        std::fprintf(stderr,
            "godo_tracker_rt: thread spawn failed: %s\n", e.what());
        godo::rt::g_running.store(false, std::memory_order_release);
        if (t_d.joinable())    t_d.join();
        if (t_cold.joinable()) {
            if (cold_native != 0) ::pthread_kill(cold_native, SIGTERM);
            t_cold.join();
        }
        if (t_gpio.joinable()) t_gpio.join();
        if (t_uds.joinable())  t_uds.join();
        if (t_a.joinable())    t_a.join();
        if (t_signal.joinable()) { ::kill(::getpid(), SIGTERM); t_signal.join(); }
        return 1;
    }

    // Join order: RT first (fastest exit), then cold writer (may need a
    // SIGTERM kick to interrupt scan_frames), then GPIO + UDS (poll-based
    // self-exit on g_running=false; M1 amendment forbids pthread_kill
    // here), then Thread A, then signal.
    t_d.join();

    // M8: kick the cold writer in case it's blocked in scan_frames(1)
    // waiting for the SDK to deliver a frame. After SIGTERM the LiDAR
    // source's read returns EINTR; the cold writer treats that as clean
    // cancellation and returns at the top of the loop on g_running=false.
    if (cold_native != 0) {
        ::pthread_kill(cold_native, SIGTERM);
    }
    t_cold.join();

    // GPIO + UDS: NO pthread_kill (M1). Both poll with
    // SHUTDOWN_POLL_TIMEOUT_MS and observe g_running on every wake-up;
    // worst-case shutdown latency is one poll period each.
    t_gpio.join();
    t_uds.join();

    t_a.join();

    // Kick the signal thread if no external signal arrived — raising
    // SIGTERM on ourselves so sigwait unblocks cleanly.
    if (t_signal.joinable()) {
        ::kill(::getpid(), SIGTERM);
        t_signal.join();
    }

    return 0;
}
