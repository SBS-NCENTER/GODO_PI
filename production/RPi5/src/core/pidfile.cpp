#include "pidfile.hpp"

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace godo::core {

namespace {

// Best-effort PID read from the file. Diagnostic only — the lock
// decision has already been made by fcntl. Returns -1 on any error.
int read_holder_pid_or_minus_one(const std::string& path) {
    int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    char buf[64] = {0};
    const ssize_t n = ::read(fd, buf, sizeof(buf) - 1);
    ::close(fd);
    if (n <= 0) return -1;
    char*       endp = nullptr;
    const long  v    = std::strtol(buf, &endp, 10);
    if (endp == buf) return -1;
    if (v <= 0 || v > INT32_MAX) return -1;
    return static_cast<int>(v);
}

}  // namespace

PidFileLockHeld::PidFileLockHeld(const std::string& path, int holder_pid)
    : std::runtime_error(
          std::string("godo_tracker_rt: pidfile held by PID ") +
          std::to_string(holder_pid) + " — refusing to start (lock=" +
          path + ")"),
      holder_pid_(holder_pid) {}

PidFileLock::PidFileLock(std::string path) : path_(std::move(path)), fd_(-1) {
    // Open + create. O_RDWR so we can write our PID.
    int fd = ::open(path_.c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0644);
    if (fd < 0) {
        const int e = errno;
        throw PidFileLockSetupError(
            std::string("pidfile open('") + path_ + "'): " +
            std::strerror(e));
    }

    // POSIX advisory lock — auto-released by the kernel on FD close.
    // Use F_SETLK (non-blocking) so a held lock surfaces as EAGAIN /
    // EACCES immediately rather than blocking the boot path.
    struct flock fl{};
    fl.l_type   = F_WRLCK;
    fl.l_whence = SEEK_SET;
    fl.l_start  = 0;
    fl.l_len    = 0;  // whole file

    if (::fcntl(fd, F_SETLK, &fl) < 0) {
        const int e = errno;
        if (e == EAGAIN || e == EACCES) {
            const int holder = read_holder_pid_or_minus_one(path_);
            ::close(fd);
            throw PidFileLockHeld(path_, holder);
        }
        ::close(fd);
        throw PidFileLockSetupError(
            std::string("pidfile fcntl(F_SETLK) on '") + path_ +
            "': " + std::strerror(e));
    }

    // Lock acquired — write our PID. Truncate-then-write so a stale
    // decimal from a prior dead holder is overwritten cleanly.
    if (::ftruncate(fd, 0) < 0) {
        const int e = errno;
        ::close(fd);
        throw PidFileLockSetupError(
            std::string("pidfile ftruncate('") + path_ + "'): " +
            std::strerror(e));
    }
    char        buf[32];
    const int   n = std::snprintf(buf, sizeof(buf), "%d\n",
                                  static_cast<int>(::getpid()));
    if (n <= 0 || n >= static_cast<int>(sizeof(buf))) {
        ::close(fd);
        throw PidFileLockSetupError(
            "pidfile snprintf failed (PID render)");
    }
    ssize_t off = 0;
    while (off < n) {
        const ssize_t w = ::write(fd, buf + off, static_cast<size_t>(n - off));
        if (w < 0) {
            const int e = errno;
            if (e == EINTR) continue;
            ::close(fd);
            throw PidFileLockSetupError(
                std::string("pidfile write('") + path_ + "'): " +
                std::strerror(e));
        }
        off += w;
    }
    if (::fsync(fd) < 0) {
        // fsync failure is rare but worth surfacing for durability —
        // the operator should know why their pidfile is unreliable.
        const int e = errno;
        ::close(fd);
        throw PidFileLockSetupError(
            std::string("pidfile fsync('") + path_ + "'): " +
            std::strerror(e));
    }

    fd_ = fd;
}

PidFileLock::~PidFileLock() {
    // Mode-A M6: unlink BEFORE close.
    //
    // The kernel ties the lock state to the FD, NOT the path. Once we
    // close the FD the lock is released regardless of whether the
    // path still exists. By unlinking first we guarantee that a third
    // process which races our shutdown sees ENOENT during its open()
    // attempt — it then creates a fresh inode and takes the lock
    // cleanly. Without unlink-first, a tight retry loop in the third
    // process could observe our path during the gap between
    // close(fd_) and the next open(), get a stale FD pointing at our
    // already-released inode, and momentarily believe the lock is
    // free even before our process exits.
    if (fd_ < 0) return;
    if (::unlink(path_.c_str()) < 0 && errno != ENOENT) {
        std::fprintf(
            stderr,
            "godo_tracker_rt: pidfile unlink('%s') failed: %s\n",
            path_.c_str(), std::strerror(errno));
    }
    ::close(fd_);
    fd_ = -1;
}

}  // namespace godo::core
