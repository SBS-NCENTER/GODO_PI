// RT setup helpers — failure-path assertions.
//
// We cannot guarantee the test host has CAP_SYS_NICE. The contract we CAN
// assert is: the helpers log actionable stderr messages when they fail,
// and they never throw.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdio>
#include <functional>
#include <pthread.h>
#include <sched.h>
#include <string>
#include <unistd.h>

#include "rt/rt_setup.hpp"

namespace {

// Redirect stderr to a pipe so we can inspect the message. Returns the
// captured bytes. The subject must be invoked INSIDE `run` so we capture
// only its output.
std::string capture_stderr(std::function<void()>&& run) {
    std::fflush(stderr);
    int pipefd[2] = {-1, -1};
    REQUIRE(::pipe(pipefd) == 0);
    const int saved = ::dup(fileno(stderr));
    REQUIRE(saved >= 0);
    REQUIRE(::dup2(pipefd[1], fileno(stderr)) >= 0);
    ::close(pipefd[1]);

    run();

    std::fflush(stderr);
    ::dup2(saved, fileno(stderr));
    ::close(saved);

    std::string out;
    char buf[1024];
    ssize_t n;
    while ((n = ::read(pipefd[0], buf, sizeof(buf))) > 0) {
        out.append(buf, static_cast<std::size_t>(n));
    }
    ::close(pipefd[0]);
    return out;
}

}  // namespace

TEST_CASE("block_all_signals_process succeeds and returns true") {
    CHECK(godo::rt::setup::block_all_signals_process() == true);
}

TEST_CASE("pin_current_thread_to_cpu: invalid CPU returns false, logs actionable msg") {
    std::string stderr_out;
    bool ok = true;
    stderr_out = capture_stderr([&]() {
        ok = godo::rt::setup::pin_current_thread_to_cpu(9999);
    });
    CHECK(ok == false);
    CHECK(stderr_out.find("pthread_setaffinity_np") != std::string::npos);
}

TEST_CASE("set_current_thread_fifo without privilege returns false, logs setup pointer") {
    // On most dev hosts this will fail with EPERM. If the host happens to
    // grant the cap, we allow the success path too — but we still require
    // that a failure produces the actionable message.
    std::string stderr_out;
    bool ok = false;
    stderr_out = capture_stderr([&]() {
        ok = godo::rt::setup::set_current_thread_fifo(50);
    });
    if (!ok) {
        CHECK(stderr_out.find("setup-pi5-rt.sh") != std::string::npos);
    }
    // Reset scheduling policy back to SCHED_OTHER if we managed to change it,
    // to avoid affecting the rest of the test run.
    if (ok) {
        sched_param sp{};
        sp.sched_priority = 0;
        ::pthread_setschedparam(::pthread_self(), SCHED_OTHER, &sp);
    }
}

TEST_CASE("lock_all_memory: on success returns true; on failure logs actionable msg") {
    std::string stderr_out;
    bool ok = false;
    stderr_out = capture_stderr([&]() {
        ok = godo::rt::setup::lock_all_memory();
    });
    if (!ok) {
        CHECK(stderr_out.find("mlockall") != std::string::npos);
        CHECK(stderr_out.find("setup-pi5-rt.sh") != std::string::npos);
    }
}
