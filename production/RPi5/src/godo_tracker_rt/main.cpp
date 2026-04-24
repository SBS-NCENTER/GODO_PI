// godo_tracker_rt — Phase 4-1 RT hot-path binary.
//
// Lifecycle (per SYSTEM_DESIGN.md §6.2):
//   main(): setlocale C → block signals → mlockall → load Config
//     → spawn Thread A (FreeD serial reader)
//     → spawn stub cold writer (Phase 4-2: replaced by AMCL thread)
//     → spawn Thread D (UDP sender @ 59.94 Hz, SCHED_FIFO + pinned)
//     → spawn signal thread (waits for SIGTERM/SIGINT → g_running=false)
//     → join D, A, stub-writer, signal thread in order.

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

// TODO(phase-4-2): replace with AMCL writer thread from src/localization/.
// This stub emits a canned offset sequence at 1 Hz so the hot path can be
// integration-tested without LiDAR + map + AMCL.
void thread_stub_cold_writer(Seqlock<Offset>& out) {
    const Offset steps[] = {
        {0.0, 0.0, 0.0},
        {0.1, 0.0, 0.0},
        {0.1, 0.1, 1.0},
        {0.2, 0.1, 2.0},
        {0.0, 0.0, 0.0},
    };
    std::size_t idx = 0;
    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        out.store(steps[idx % (sizeof(steps) / sizeof(steps[0]))]);
        ++idx;
        // Sleep 1 s in 100 ms slices so SIGTERM exit is responsive.
        for (int i = 0; i < 10; ++i) {
            if (!godo::rt::g_running.load(std::memory_order_acquire)) return;
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
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

    std::thread t_signal, t_a, t_stub, t_d;
    try {
        t_signal = std::thread(thread_signal_handler);
        t_a     = std::thread(thread_a_serial, std::cref(cfg), std::ref(latest_freed));
        t_stub  = std::thread(thread_stub_cold_writer, std::ref(target_offset));
        t_d     = std::thread(thread_d_rt, std::cref(cfg),
                              std::ref(latest_freed), std::ref(target_offset));
    } catch (const std::exception& e) {
        std::fprintf(stderr,
            "godo_tracker_rt: thread spawn failed: %s\n", e.what());
        godo::rt::g_running.store(false, std::memory_order_release);
        if (t_d.joinable())    t_d.join();
        if (t_stub.joinable()) t_stub.join();
        if (t_a.joinable())    t_a.join();
        if (t_signal.joinable()) { ::kill(::getpid(), SIGTERM); t_signal.join(); }
        return 1;
    }

    // Join order: RT first (fastest exit), then workers, then signal thread.
    t_d.join();
    t_stub.join();
    t_a.join();

    // Kick the signal thread if no external signal arrived — raising
    // SIGTERM on ourselves so sigwait unblocks cleanly.
    if (t_signal.joinable()) {
        ::kill(::getpid(), SIGTERM);
        t_signal.join();
    }

    return 0;
}
