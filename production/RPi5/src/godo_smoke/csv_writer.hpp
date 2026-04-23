#pragma once

// Byte-identical CSV writer to prototype/Python/src/godo_lidar/io/csv_dump.py.
//
// Row format (see Plan B v2 §CSV row format):
//     frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag\n
//
// - angle_deg printed with %.6f, distance_mm with %.3f
// - Integer columns printed with %d / %lld (timestamp_ns is signed 64-bit)
// - Single comma delimiter, no quoting, no BOM, LF line terminator
// - Files are opened with "wb" to prevent CRLF translation on non-POSIX
//   platforms (see CODEBASE.md invariant (c)).
//
// Hot-path note: the writer MAY allocate (snprintf into a reused string
// buffer). See CODEBASE.md invariant (c) — this writer is a smoke-scoped
// convenience, NOT the pattern for the godo-tracker Thread D in Phase 4.

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <string>

#include "sample.hpp"

namespace godo::smoke {

class CsvWriter {
public:
    explicit CsvWriter(std::filesystem::path path);
    CsvWriter(const CsvWriter&)            = delete;
    CsvWriter& operator=(const CsvWriter&) = delete;
    CsvWriter(CsvWriter&&)                 = delete;
    CsvWriter& operator=(CsvWriter&&)      = delete;
    ~CsvWriter();

    // Open the file and write the header row. Creates parent directories.
    // Safe to call once; subsequent calls are a no-op.
    void open();

    // Flush and close the file. Called by the destructor if still open.
    void close();

    // Append one Frame as N rows. Requires open() has been called.
    void write_frame(const Frame& frame);

    [[nodiscard]] const std::filesystem::path& path() const { return path_; }
    [[nodiscard]] std::int64_t frames_written() const { return frames_; }
    [[nodiscard]] std::int64_t samples_written() const { return samples_; }

private:
    std::filesystem::path path_;
    std::FILE*            fh_{nullptr};
    std::int64_t          frames_{0};
    std::int64_t          samples_{0};
};

}  // namespace godo::smoke
