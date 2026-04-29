#pragma once

// Single-instance pidfile lock for godo_tracker_rt.
//
// Acquired by main() IMMEDIATELY after Config::load and BEFORE any
// thread spawn / Seqlock allocation / device open. Mechanism: POSIX
// fcntl(F_SETLK, F_WRLCK) on a file in /run/godo. The lock is
// auto-released by the kernel when the holding FD closes (process
// death, SIGKILL included), so a stale pidfile from a crashed prior
// run does NOT block startup.
//
// CLAUDE.md §6 "Single-instance discipline" + RPi5 production
// CODEBASE invariant (l) tracker-pidfile-discipline.

#include <stdexcept>
#include <string>

namespace godo::core {

// Thrown by PidFileLock::PidFileLock when another process holds the
// lock; ``holder_pid`` is the PID read from the file (or -1 if
// unreadable). The lock decision does NOT depend on this PID — it is
// diagnostic only.
class PidFileLockHeld : public std::runtime_error {
   public:
    PidFileLockHeld(const std::string& path, int holder_pid);

    int holder_pid() const noexcept { return holder_pid_; }

   private:
    int holder_pid_;
};

// Thrown by the constructor for parent-dir / open / generic IO
// failures. Distinct from "another instance is running" so main() can
// emit the right operator message.
class PidFileLockSetupError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

// RAII guard. Stack-allocate in main() (Mode-A M6); the dtor unlinks
// the path BEFORE closing the FD so a third process trying open-then-
// lock sees ENOENT promptly. Move-only — never copy a lock.
class PidFileLock {
   public:
    explicit PidFileLock(std::string path);
    ~PidFileLock();

    PidFileLock(const PidFileLock&)            = delete;
    PidFileLock& operator=(const PidFileLock&) = delete;
    PidFileLock(PidFileLock&&)                 = delete;
    PidFileLock& operator=(PidFileLock&&)      = delete;

    const std::string& path() const noexcept { return path_; }

   private:
    std::string path_;
    int         fd_;  // -1 if not held (e.g. after release).
};

}  // namespace godo::core
