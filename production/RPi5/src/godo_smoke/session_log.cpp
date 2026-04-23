#include "session_log.hpp"

#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <sys/utsname.h>
#include <unistd.h>

#include <openssl/evp.h>

#include "timestamp.hpp"

namespace godo::smoke {

namespace {

std::string hostname_or_unknown() {
    std::array<char, 256> buf{};
    if (gethostname(buf.data(), buf.size()) != 0) {
        return "unknown";
    }
    buf.back() = '\0';  // defensive
    return std::string(buf.data());
}

std::string os_or_unknown() {
    utsname u{};
    if (uname(&u) != 0) {
        return "unknown";
    }
    std::ostringstream os;
    os << u.sysname << "-" << u.release << "-" << u.machine;
    return os.str();
}

std::string hex_of(const unsigned char* md, unsigned int len) {
    static constexpr char kHex[] = "0123456789abcdef";
    std::string out;
    out.resize(static_cast<std::size_t>(len) * 2);
    for (unsigned int i = 0; i < len; ++i) {
        out[i * 2]     = kHex[(md[i] >> 4) & 0x0F];
        out[i * 2 + 1] = kHex[md[i] & 0x0F];
    }
    return out;
}

double safe_rate(std::int64_t n, double s) {
    return (s > 0.0) ? (static_cast<double>(n) / s) : 0.0;
}

// RAII wrapper for EVP_MD_CTX. Keeps the cleanup on every return path.
struct EvpCtx {
    EVP_MD_CTX* p;
    EvpCtx() : p(EVP_MD_CTX_new()) {
        if (p == nullptr) {
            throw std::runtime_error("EVP_MD_CTX_new failed");
        }
    }
    ~EvpCtx() {
        if (p != nullptr) EVP_MD_CTX_free(p);
    }
    EvpCtx(const EvpCtx&)            = delete;
    EvpCtx& operator=(const EvpCtx&) = delete;
};

}  // namespace

FileDigest sha256_file(const std::filesystem::path& path) {
    std::FILE* fh = std::fopen(path.c_str(), "rb");
    if (fh == nullptr) {
        throw std::runtime_error(
            "sha256_file: fopen failed for '" + path.string() +
            "': " + std::strerror(errno));
    }
    // RAII for the file handle too — fclose in every exit path.
    struct FileGuard {
        std::FILE* f;
        ~FileGuard() { if (f) std::fclose(f); }
    } guard{fh};

    EvpCtx ctx;
    if (EVP_DigestInit_ex(ctx.p, EVP_sha256(), nullptr) != 1) {
        throw std::runtime_error("EVP_DigestInit_ex(SHA-256) failed");
    }

    std::array<unsigned char, 64 * 1024> buf{};
    std::int64_t total = 0;
    while (true) {
        const std::size_t got = std::fread(buf.data(), 1, buf.size(), fh);
        if (got > 0) {
            if (EVP_DigestUpdate(ctx.p, buf.data(), got) != 1) {
                throw std::runtime_error("EVP_DigestUpdate failed");
            }
            total += static_cast<std::int64_t>(got);
        }
        if (got < buf.size()) {
            if (std::ferror(fh)) {
                throw std::runtime_error(
                    "sha256_file: read error on '" + path.string() + "'");
            }
            break;  // EOF
        }
    }

    std::array<unsigned char, EVP_MAX_MD_SIZE> md{};
    unsigned int mdlen = 0;
    if (EVP_DigestFinal_ex(ctx.p, md.data(), &mdlen) != 1) {
        throw std::runtime_error("EVP_DigestFinal_ex failed");
    }

    return FileDigest{hex_of(md.data(), mdlen), total};
}

void write_session_log(const std::filesystem::path& path,
                       const CaptureParams&         params,
                       const RunStats&              stats,
                       const std::filesystem::path& csv_path) {
    const auto parent = path.parent_path();
    if (!parent.empty()) {
        std::error_code ec;
        std::filesystem::create_directories(parent, ec);
        if (ec) {
            throw std::runtime_error(
                "write_session_log: create_directories('" + parent.string() +
                "') failed: " + ec.message());
        }
    }

    const FileDigest digest = sha256_file(csv_path);

    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error(
            "write_session_log: failed to open '" + path.string() + "'");
    }

    const double samples_per_sec = safe_rate(stats.samples_total,
                                             stats.duration_s);

    // Field ordering mirrors the Python SessionLogWriter.write().
    out << "# GODO Phase 3 smoke capture session log\n"
        << "timestamp_utc   : " << utc_timestamp_iso() << "\n"
        << "host            : " << hostname_or_unknown() << "\n"
        << "os              : " << os_or_unknown() << "\n"
        << "binary          : godo_smoke\n"
        << "\n"
        << "## Capture parameters\n"
        << "backend         : " << params.backend          << "\n"
        << "port            : " << params.port             << "\n"
        << "baud            : " << params.baud             << "\n"
        << "frames_requested: " << params.frames_requested << "\n"
        << "tag             : " << params.tag              << "\n"
        << "notes           : " << params.notes            << "\n"
        << "\n"
        << "## Run stats\n"
        << "frames_captured : " << stats.frames_captured   << "\n"
        << "samples_total   : " << stats.samples_total     << "\n";

    // Fixed precision for the floating-point lines, matching Python's
    // f-string formatters in session_log.py.
    char fbuf[64];
    std::snprintf(fbuf, sizeof(fbuf), "%.3f", stats.duration_s);
    out << "duration_s      : " << fbuf << "\n";
    std::snprintf(fbuf, sizeof(fbuf), "%.1f", samples_per_sec);
    out << "samples_per_sec : " << fbuf << "\n";
    std::snprintf(fbuf, sizeof(fbuf), "%.2f", stats.mean_quality);
    out << "mean_quality    : " << fbuf << "\n";
    std::snprintf(fbuf, sizeof(fbuf), "%.2f", stats.median_quality);
    out << "median_quality  : " << fbuf << "\n";
    out << "dropped_frames  : " << stats.dropped_frames << "\n"
        << "\n"
        << "## Artifact integrity\n"
        << "csv_path        : " << csv_path.string()   << "\n"
        << "csv_byte_count  : " << digest.byte_count   << "\n"
        << "csv_sha256      : " << digest.sha256_hex   << "\n";

    if (!out) {
        throw std::runtime_error(
            "write_session_log: I/O error while writing '" + path.string() +
            "'");
    }
}

}  // namespace godo::smoke
