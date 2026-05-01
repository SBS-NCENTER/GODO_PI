#pragma once

// Atomic POSIX-rename writer for /var/lib/godo/tracker.toml. Track B-CONFIG
// (PR-CONFIG-α) — sole owner of writes against the TOML file. Build
// grep `[atomic-toml-write-grep]` enforces this exclusivity.
//
// Sequence (Mode-A S1 fold — early-detect read-only parents):
//   1. ::access(parent_path, W_OK)         — surface ParentNotWritable
//   2. ::mkstemp(parent_path/.tracker.toml.XXXXXX) → fd, mode 0600
//   3. ::fchmod(fd, 0644)                  — operator-readable
//   4. write_loop(fd, contents)            — handles EINTR + partial
//   5. ::fsync(fd)                         — durability before rename
//   6. ::close(fd)
//   7. ::rename(tmp_path, target_path)     — atomic on POSIX same-fs
//   8. on any failure after step 2 → ::unlink(tmp_path)
//
// Same-filesystem precondition: `tmp_path.parent_path() ==
// target_path.parent_path()`, so `rename(2)` cannot trip EXDEV.

#include <filesystem>
#include <string_view>

namespace godo::config {

enum class WriteOutcome : std::uint8_t {
    Ok,
    ParentNotWritable,    // access(parent, W_OK) failed (Mode-A S1).
    MkstempFailed,
    WriteFailed,
    FsyncFailed,
    RenameFailed,
};

struct WriteResult {
    WriteOutcome outcome = WriteOutcome::Ok;
    int          errno_capture = 0;  // captured from the failing syscall.
};

// Write `contents` atomically to `target_path`. Empty `contents` is
// allowed (the resulting file is zero-length).
WriteResult write_atomic(const std::filesystem::path& target_path,
                         std::string_view             contents) noexcept;

inline std::string_view outcome_to_string(WriteOutcome o) noexcept {
    switch (o) {
        case WriteOutcome::Ok:                return "ok";
        case WriteOutcome::ParentNotWritable: return "parent_not_writable";
        case WriteOutcome::MkstempFailed:     return "mkstemp_failed";
        case WriteOutcome::WriteFailed:       return "write_failed";
        case WriteOutcome::FsyncFailed:       return "fsync_failed";
        case WriteOutcome::RenameFailed:      return "rename_failed";
    }
    return "unknown";
}

}  // namespace godo::config
