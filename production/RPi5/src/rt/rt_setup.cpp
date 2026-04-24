#include "rt_setup.hpp"

#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/resource.h>

#include <cerrno>
#include <cstdio>
#include <cstring>

namespace godo::rt::setup {

bool lock_all_memory() noexcept {
    // Gate mlockall on RLIMIT_MEMLOCK because MCL_FUTURE silently causes
    // subsequent mmap() calls (thread stacks, among others) to fail with
    // EAGAIN once the locked-pages rlimit is hit. On a host that has not
    // run setup-pi5-rt.sh the default is ~64 KiB / 8 MiB, well below the
    // 8 MiB per thread stack the tracker needs.
    rlimit rl{};
    if (::getrlimit(RLIMIT_MEMLOCK, &rl) != 0) {
        std::fprintf(stderr,
            "rt::lock_all_memory: getrlimit(RLIMIT_MEMLOCK) failed (%s)\n",
            std::strerror(errno));
        return false;
    }
    // Demand at least 128 MiB of headroom: enough for the tracker's four
    // threads + cold-path working set. Hosts with 'unlimited' report
    // RLIM_INFINITY which compares > any finite value.
    constexpr rlim_t kRequiredBytes = 128ULL * 1024ULL * 1024ULL;
    if (rl.rlim_cur != RLIM_INFINITY && rl.rlim_cur < kRequiredBytes) {
        std::fprintf(stderr,
            "rt::lock_all_memory: skipped — RLIMIT_MEMLOCK is %lu bytes, "
            "need at least %lu. Run 'scripts/setup-pi5-rt.sh' as root to "
            "raise the memlock rlimit and grant cap_ipc_lock before the "
            "tracker can mlockall.\n",
            static_cast<unsigned long>(rl.rlim_cur),
            static_cast<unsigned long>(kRequiredBytes));
        return false;
    }

    if (::mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        std::fprintf(stderr,
            "rt::lock_all_memory: mlockall failed (%s). Run "
            "'scripts/setup-pi5-rt.sh' once as root to grant "
            "cap_ipc_lock.\n",
            std::strerror(errno));
        return false;
    }
    return true;
}

bool pin_current_thread_to_cpu(int cpu) noexcept {
    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cpu, &mask);
    const int rc =
        ::pthread_setaffinity_np(::pthread_self(), sizeof(mask), &mask);
    if (rc != 0) {
        std::fprintf(stderr,
            "rt::pin_current_thread_to_cpu(%d): pthread_setaffinity_np "
            "failed (%s)\n",
            cpu, std::strerror(rc));
        return false;
    }
    return true;
}

bool set_current_thread_fifo(int prio) noexcept {
    sched_param sp{};
    sp.sched_priority = prio;
    const int rc =
        ::pthread_setschedparam(::pthread_self(), SCHED_FIFO, &sp);
    if (rc != 0) {
        std::fprintf(stderr,
            "rt::set_current_thread_fifo(%d): pthread_setschedparam "
            "failed (%s). Run 'scripts/setup-pi5-rt.sh' once as root to "
            "grant cap_sys_nice and raise the rtprio rlimit.\n",
            prio, std::strerror(rc));
        return false;
    }
    return true;
}

bool block_all_signals_process() noexcept {
    sigset_t mask;
    sigfillset(&mask);
    const int rc = ::pthread_sigmask(SIG_BLOCK, &mask, nullptr);
    if (rc != 0) {
        std::fprintf(stderr,
            "rt::block_all_signals_process: pthread_sigmask failed (%s)\n",
            std::strerror(rc));
        return false;
    }
    return true;
}

}  // namespace godo::rt::setup
