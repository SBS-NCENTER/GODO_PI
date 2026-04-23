#pragma once

// Session log writer — mirrors the schema of
// prototype/Python/src/godo_lidar/io/session_log.py.
//
// The Python prototype's session log is the ground truth for field names
// and ordering. Byte-identity of the log file is NOT enforced (see
// CODEBASE.md invariant (d) — scope-out); only the CSV is byte-identical
// across the two implementations.

#include <cstdint>
#include <filesystem>
#include <string>

namespace godo::smoke {

struct CaptureParams {
    std::string backend;           // "rplidar-sdk" | "fake"
    std::string port;              // "/dev/ttyUSB0" etc.
    int         baud{};
    int         frames_requested{};
    std::string tag;
    std::string notes;
};

struct RunStats {
    std::int64_t frames_captured{};
    std::int64_t samples_total{};
    double       duration_s{};
    double       mean_quality{};
    double       median_quality{};
    std::int64_t dropped_frames{};
};

// Returns (hex-sha256, byte-count) for the file at `path`.
// Uses OpenSSL EVP_DigestUpdate in 64 KiB chunks — streaming, not
// one-shot — to handle multi-MB captures. Throws std::runtime_error on
// any I/O or OpenSSL failure.
struct FileDigest {
    std::string  sha256_hex;
    std::int64_t byte_count{};
};

FileDigest sha256_file(const std::filesystem::path& path);

// Write the plain-text session log to `path`. Creates parent directories.
// `csv_path` must already exist — its bytes are hashed for the integrity
// section.
void write_session_log(const std::filesystem::path& path,
                       const CaptureParams&         params,
                       const RunStats&              stats,
                       const std::filesystem::path& csv_path);

}  // namespace godo::smoke
