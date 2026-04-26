// godo_tracker_rt — Phase 4-1 RT hot path + Phase 4-2 B AMCL cold writer.
//
// Lifecycle (per SYSTEM_DESIGN.md §6.2):
//   main(): setlocale C → block signals → mlockall → load Config
//     → spawn Thread A (FreeD serial reader)
//     → spawn cold writer (AMCL OneShot state machine; src/localization/)
//     → spawn Thread D (UDP sender @ 59.94 Hz, SCHED_FIFO + pinned)
//     → spawn signal thread (waits for SIGTERM/SIGINT → g_running=false)
//     → join D, A, cold writer, signal thread in order. The cold writer
//       can be blocked inside scan_frames(1); main pthread_kill's SIGTERM
//       to its native_handle before joining (M8 SIGTERM watchdog).

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
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
#include "lidar/lidar_source_rplidar.hpp"
#include "localization/cold_writer.hpp"
#include "rt/rt_setup.hpp"
#include "smoother/offset_smoother.hpp"
#include "udp/sender.hpp"

using godo::rt::FreedPacket;
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

    std::thread t_signal, t_a, t_cold, t_d;
    pthread_t   cold_native = 0;
    try {
        t_signal = std::thread(thread_signal_handler);
        t_a      = std::thread(thread_a_serial, std::cref(cfg),
                               std::ref(latest_freed));
        t_cold   = std::thread(godo::localization::run_cold_writer,
                               std::cref(cfg),
                               std::ref(target_offset),
                               lidar_factory);
        cold_native = t_cold.native_handle();
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
        if (t_a.joinable())    t_a.join();
        if (t_signal.joinable()) { ::kill(::getpid(), SIGTERM); t_signal.join(); }
        return 1;
    }

    // Join order: RT first (fastest exit), then cold writer (may need a
    // SIGTERM kick to interrupt scan_frames), then Thread A, then signal.
    t_d.join();

    // M8: kick the cold writer in case it's blocked in scan_frames(1)
    // waiting for the SDK to deliver a frame. After SIGTERM the LiDAR
    // source's read returns EINTR; the cold writer treats that as clean
    // cancellation and returns at the top of the loop on g_running=false.
    if (cold_native != 0) {
        ::pthread_kill(cold_native, SIGTERM);
    }
    t_cold.join();
    t_a.join();

    // Kick the signal thread if no external signal arrived — raising
    // SIGTERM on ourselves so sigwait unblocks cleanly.
    if (t_signal.joinable()) {
        ::kill(::getpid(), SIGTERM);
        t_signal.join();
    }

    return 0;
}
