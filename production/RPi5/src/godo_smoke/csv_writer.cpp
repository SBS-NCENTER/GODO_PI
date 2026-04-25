#include "csv_writer.hpp"

#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <system_error>

// static_asserts pin the printf width matching assumptions made by this
// writer. `long long` must be at least 64 bits so `%lld` renders the full
// timestamp_ns; `int` must be at least 32 bits to hold the signed frame/
// sample indices we use.
static_assert(sizeof(long long) >= 8,
              "timestamp_ns formatting assumes long long >= 64 bits");
static_assert(sizeof(int) >= 4,
              "frame_idx / sample_idx formatting assumes int >= 32 bits");

namespace godo::smoke {

using godo::lidar::Frame;
using godo::lidar::Sample;

namespace {

constexpr const char* kHeader =
    "frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag\n";

// Upper bound for one formatted row. Conservative: angle %.6f and distance
// %.3f with leading digits, plus six integer fields with commas and LF.
constexpr std::size_t kRowMaxBytes = 160;

}  // namespace

CsvWriter::CsvWriter(std::filesystem::path path) : path_(std::move(path)) {}

CsvWriter::~CsvWriter() { close(); }

void CsvWriter::open() {
    if (fh_ != nullptr) return;

    const auto parent = path_.parent_path();
    if (!parent.empty()) {
        std::error_code ec;
        std::filesystem::create_directories(parent, ec);
        if (ec) {
            throw std::runtime_error(
                "CsvWriter: failed to create parent directory '" +
                parent.string() + "': " + ec.message());
        }
    }

    // "wb" keeps byte output identical on any host (no CRLF translation).
    fh_ = std::fopen(path_.c_str(), "wb");
    if (fh_ == nullptr) {
        throw std::runtime_error(
            "CsvWriter: fopen failed for '" + path_.string() +
            "': " + std::strerror(errno));
    }
    // Full buffering keeps the tight write loop fast; close() flushes.
    std::setvbuf(fh_, nullptr, _IOFBF, 64 * 1024);

    if (std::fputs(kHeader, fh_) == EOF) {
        throw std::runtime_error(
            "CsvWriter: failed to write header to '" + path_.string() + "'");
    }
}

void CsvWriter::close() {
    if (fh_ == nullptr) return;
    std::fflush(fh_);
    std::fclose(fh_);
    fh_ = nullptr;
}

void CsvWriter::write_frame(const Frame& frame) {
    if (fh_ == nullptr) {
        throw std::runtime_error("CsvWriter::write_frame called before open()");
    }

    std::array<char, kRowMaxBytes> buf{};
    const int frame_idx = frame.index;
    for (std::size_t i = 0; i < frame.samples.size(); ++i) {
        const Sample& s = frame.samples[i];
        const int sample_idx = static_cast<int>(i);
        const long long ts_ll = static_cast<long long>(s.timestamp_ns);
        // Column order is pinned by the Python ground-truth writer.
        const int n = std::snprintf(
            buf.data(), buf.size(),
            "%d,%d,%lld,%.6f,%.3f,%d,%d\n",
            frame_idx,
            sample_idx,
            ts_ll,
            s.angle_deg,
            s.distance_mm,
            static_cast<int>(s.quality),
            static_cast<int>(s.flag));
        if (n < 0 || static_cast<std::size_t>(n) >= buf.size()) {
            throw std::runtime_error(
                "CsvWriter: snprintf truncation on a row (should never "
                "happen given the 160-byte scratch)");
        }
        if (std::fwrite(buf.data(), 1, static_cast<std::size_t>(n), fh_) !=
            static_cast<std::size_t>(n)) {
            throw std::runtime_error("CsvWriter: fwrite failure");
        }
    }
    ++frames_;
    samples_ += static_cast<std::int64_t>(frame.samples.size());
}

}  // namespace godo::smoke
