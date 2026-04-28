#include "atomic_toml_writer.hpp"

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace godo::config {

namespace {

// write_loop — handle EINTR + partial writes. Returns true on success.
bool write_loop(int fd, const char* data, std::size_t len) noexcept {
    std::size_t off = 0;
    while (off < len) {
        const ssize_t n = ::write(fd, data + off, len - off);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (n == 0) {  // unusual on regular file but defensively treat as EIO.
            errno = EIO;
            return false;
        }
        off += static_cast<std::size_t>(n);
    }
    return true;
}

}  // namespace

WriteResult write_atomic(const std::filesystem::path& target_path,
                         std::string_view             contents) noexcept {
    WriteResult r;

    const std::filesystem::path parent = target_path.parent_path();

    // Step 1 — Mode-A S1: early-detect read-only / missing parent.
    if (::access(parent.c_str(), W_OK) != 0) {
        r.outcome       = WriteOutcome::ParentNotWritable;
        r.errno_capture = errno;
        return r;
    }

    // Step 2 — mkstemp template MUST be mutable (it is rewritten in
    // place). Compose under parent so rename(2) is atomic on same fs.
    std::string tmpl = (parent / ".tracker.toml.XXXXXX").string();
    std::vector<char> buf(tmpl.begin(), tmpl.end());
    buf.push_back('\0');

    const int fd = ::mkstemp(buf.data());
    if (fd < 0) {
        r.outcome       = WriteOutcome::MkstempFailed;
        r.errno_capture = errno;
        return r;
    }
    const std::filesystem::path tmp_path(buf.data());

    // Step 3 — operator-readable. Best-effort; log-only if it fails so
    // we still produce a valid file (worst case: 0600 stays).
    if (::fchmod(fd, 0644) != 0) {
        std::fprintf(stderr,
            "atomic_toml_writer: fchmod 0644 warning on '%s': %s\n",
            tmp_path.c_str(), std::strerror(errno));
    }

    // Step 4 — write_loop.
    if (!write_loop(fd, contents.data(), contents.size())) {
        r.outcome       = WriteOutcome::WriteFailed;
        r.errno_capture = errno;
        ::close(fd);
        ::unlink(tmp_path.c_str());
        return r;
    }

    // Step 5 — fsync.
    if (::fsync(fd) != 0) {
        r.outcome       = WriteOutcome::FsyncFailed;
        r.errno_capture = errno;
        ::close(fd);
        ::unlink(tmp_path.c_str());
        return r;
    }

    if (::close(fd) != 0) {
        // Close failure post-fsync is unusual; treat conservatively as
        // a write error so the operator retries.
        r.outcome       = WriteOutcome::WriteFailed;
        r.errno_capture = errno;
        ::unlink(tmp_path.c_str());
        return r;
    }

    // Step 7 — atomic publish. On failure unlink the tmp.
    if (::rename(tmp_path.c_str(), target_path.c_str()) != 0) {
        r.outcome       = WriteOutcome::RenameFailed;
        r.errno_capture = errno;
        ::unlink(tmp_path.c_str());
        return r;
    }

    r.outcome = WriteOutcome::Ok;
    return r;
}

}  // namespace godo::config
