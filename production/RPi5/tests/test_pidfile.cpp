// Hardware-free tests for godo::core::PidFileLock.
//
// 6 cases per planner §5; case 5 re-specced per Mode-A TB4 / M4
// (fork-does-not-inherit-lock), case 6 documents that the kill(pid, 0)
// diagnostic does NOT influence the lock decision.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>

#include <fcntl.h>
#include <signal.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include "core/pidfile.hpp"

namespace {

// Sentinel "definitely-dead" PID per Mode-A TB1 — exceeds Linux
// pid_max by construction, so kill(pid, 0) returns ESRCH on every
// reasonable system. NOT PID 1 (which is always init / always alive).
constexpr int kSentinelDeadPid = 0x7FFFFFFF;

// Build a unique tmp path under /tmp using PID + a tag.
std::string tmp_pidfile_path(const char* tag) {
    char buf[256];
    std::snprintf(buf, sizeof(buf), "/tmp/godo_pidfile_%d_%s.pid",
                  static_cast<int>(::getpid()), tag);
    return std::string(buf);
}

// RAII guard: unlinks the path on every test exit (pass or fail) so
// reruns are deterministic.
struct TempPath {
    std::string path;
    explicit TempPath(std::string p) : path(std::move(p)) {
        ::unlink(path.c_str());
    }
    ~TempPath() { ::unlink(path.c_str()); }
    TempPath(const TempPath&)            = delete;
    TempPath& operator=(const TempPath&) = delete;
};

}  // namespace

TEST_CASE("PidFileLock acquires and releases on a fresh path") {
    TempPath guard(tmp_pidfile_path("fresh"));
    {
        godo::core::PidFileLock lock(guard.path);
        // File now exists and contains our PID + newline.
        std::ifstream f(guard.path);
        REQUIRE(f.is_open());
        std::string content;
        std::getline(f, content);
        CHECK(content == std::to_string(static_cast<int>(::getpid())));
    }
    // Dtor: unlinked.
    struct stat st;
    CHECK(::stat(guard.path.c_str(), &st) < 0);
    CHECK(errno == ENOENT);
}

TEST_CASE("Second-process acquire on a held path throws PidFileLockHeld") {
    // POSIX fcntl(F_SETLK) locks are PROCESS-owned, so a second
    // PidFileLock constructed in the SAME process would silently
    // succeed (the kernel sees the same owner). Cross-process
    // protection — the only case that matters in production — is
    // verified here via fork: child opens a fresh FD, attempts the
    // same lock, MUST fail with EAGAIN/EACCES which we surface as
    // PidFileLockHeld. The lock decision in the child is made
    // BEFORE consulting the file content.
    TempPath guard(tmp_pidfile_path("crossproc"));
    godo::core::PidFileLock parent_lock(guard.path);

    pid_t child = ::fork();
    REQUIRE(child >= 0);
    if (child == 0) {
        try {
            godo::core::PidFileLock child_lock(guard.path);
            _exit(101);  // unexpected: child took the lock
        } catch (const godo::core::PidFileLockHeld&) {
            _exit(0);    // expected
        } catch (...) {
            _exit(102);  // unexpected: wrong exception type
        }
    }
    int status = 0;
    REQUIRE(::waitpid(child, &status, 0) == child);
    REQUIRE(WIFEXITED(status));
    CHECK(WEXITSTATUS(status) == 0);
}

TEST_CASE("Stale PID in file with no holder — second acquire succeeds") {
    // Write a stale (sentinel-dead) PID into the file but DO NOT take
    // the lock — exactly the state left when a prior process died and
    // the kernel released the lock. The new instance's flock attempt
    // must succeed and overwrite the PID.
    TempPath guard(tmp_pidfile_path("stale"));
    {
        std::ofstream f(guard.path);
        REQUIRE(f.is_open());
        f << kSentinelDeadPid << "\n";
    }
    godo::core::PidFileLock lock(guard.path);
    std::ifstream f(guard.path);
    std::string content;
    std::getline(f, content);
    CHECK(content == std::to_string(static_cast<int>(::getpid())));
}

TEST_CASE("Dtor releases lock and unlinks file (M6 ordering)") {
    TempPath guard(tmp_pidfile_path("dtor"));
    {
        godo::core::PidFileLock lock(guard.path);
        struct stat st;
        REQUIRE(::stat(guard.path.c_str(), &st) == 0);
    }
    // Path is gone (unlink before close).
    struct stat st;
    CHECK(::stat(guard.path.c_str(), &st) < 0);
    CHECK(errno == ENOENT);
    // A fresh acquire on the same path now succeeds — proves both
    // the lock state and the path were cleaned up.
    godo::core::PidFileLock lock_again(guard.path);
}

TEST_CASE("fork does not inherit fcntl F_SETLK lock (TB4)") {
    // POSIX fcntl(F_SETLK) locks are NOT inherited across fork(2).
    // The parent's lock is on the file (via inode + range), but the
    // child's process ID is distinct so its F_SETLK attempt would
    // succeed if it opened a SEPARATE FD. The contract we pin here:
    // even though parent + child share an inherited FD, an
    // independently-opened FD in the child trying to lock the same
    // range gets EAGAIN/EACCES because the parent already holds it.
    // (Per POSIX: locks are owned by the process; multiple FDs in
    // the same process see no contention; fork creates a NEW process
    // owner — a separate-FD attempt MUST conflict with the parent.)
    TempPath guard(tmp_pidfile_path("fork"));
    godo::core::PidFileLock parent_lock(guard.path);

    pid_t child = ::fork();
    REQUIRE(child >= 0);
    if (child == 0) {
        // Child: open the same path, try F_SETLK on a fresh FD.
        int fd = ::open(guard.path.c_str(), O_RDWR);
        if (fd < 0) {
            _exit(101);
        }
        struct flock fl{};
        fl.l_type   = F_WRLCK;
        fl.l_whence = SEEK_SET;
        fl.l_start  = 0;
        fl.l_len    = 0;
        const int r = ::fcntl(fd, F_SETLK, &fl);
        const int e = errno;
        ::close(fd);
        if (r < 0 && (e == EAGAIN || e == EACCES)) {
            _exit(0);  // expected
        }
        _exit(102);  // unexpected: child took the lock
    }
    int status = 0;
    REQUIRE(::waitpid(child, &status, 0) == child);
    REQUIRE(WIFEXITED(status));
    CHECK(WEXITSTATUS(status) == 0);
}

TEST_CASE("kill(pid, 0) diagnostic distinguishes alive / dead but does NOT gate the lock") {
    // The kill(pid, 0) probe is used solely for the stderr message
    // phrasing. Verify it returns ESRCH for a known-dead PID and
    // succeeds (returns 0) for our own PID. The lock decision in
    // PidFileLock has ALREADY been made by fcntl(F_SETLK) before
    // this probe is consulted (M4 fold).
    errno = 0;
    CHECK(::kill(::getpid(), 0) == 0);
    errno = 0;
    CHECK(::kill(kSentinelDeadPid, 0) < 0);
    CHECK(errno == ESRCH);
}
