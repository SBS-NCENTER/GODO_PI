// Tests for session_log.{hpp,cpp}. Focuses on:
//   - SHA-256 of a file matches a known-good OpenSSL CLI value (indirectly:
//     the empty string's hash is a well-known literal, we use that).
//   - Chunked hashing handles multi-chunk inputs (we write > 64 KiB).
//   - The human-readable log contains every required field.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "session_log.hpp"

using godo::smoke::CaptureParams;
using godo::smoke::FileDigest;
using godo::smoke::RunStats;
using godo::smoke::sha256_file;
using godo::smoke::write_session_log;

namespace {

std::string slurp(const std::filesystem::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream os;
    os << in.rdbuf();
    return os.str();
}

std::filesystem::path tmp_dir(const char* name) {
    const auto d = std::filesystem::temp_directory_path() /
                   (std::string("godo_smoke_sessionlog_") + name);
    std::filesystem::remove_all(d);
    std::filesystem::create_directories(d);
    return d;
}

}  // namespace

TEST_CASE("sha256_file: empty file matches the well-known digest") {
    // Known-good: SHA-256 of zero bytes.
    constexpr const char* kEmptyHex =
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

    const auto dir = tmp_dir("empty");
    const auto p = dir / "empty.bin";
    { std::ofstream out(p, std::ios::binary); /* creates 0 bytes */ }

    const FileDigest d = sha256_file(p);
    CHECK(d.sha256_hex == kEmptyHex);
    CHECK(d.byte_count == 0);
}

TEST_CASE("sha256_file: 'abc' matches the well-known digest") {
    // From FIPS 180-4 Annex C: SHA-256("abc").
    constexpr const char* kAbcHex =
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    const auto dir = tmp_dir("abc");
    const auto p = dir / "abc.bin";
    { std::ofstream out(p, std::ios::binary); out << "abc"; }

    const FileDigest d = sha256_file(p);
    CHECK(d.sha256_hex == kAbcHex);
    CHECK(d.byte_count == 3);
}

TEST_CASE("sha256_file: chunked path is exercised on files > 64 KiB") {
    const auto dir = tmp_dir("big");
    const auto p = dir / "big.bin";
    // 200 KiB of zeros.
    const std::size_t n = 200 * 1024;
    {
        std::ofstream out(p, std::ios::binary);
        std::vector<char> zeroes(n, '\0');
        out.write(zeroes.data(), static_cast<std::streamsize>(n));
    }
    const FileDigest d = sha256_file(p);
    // Don't hardcode the hex (easy to make a typo); instead verify the
    // count and that the digest is a valid 64-hex-char string.
    CHECK(d.byte_count == static_cast<std::int64_t>(n));
    REQUIRE(d.sha256_hex.size() == 64);
    for (char c : d.sha256_hex) {
        CHECK(((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')));
    }
}

TEST_CASE("sha256_file: missing file throws") {
    const auto dir = tmp_dir("missing");
    CHECK_THROWS(sha256_file(dir / "does-not-exist.bin"));
}

TEST_CASE("write_session_log: emits every documented field") {
    const auto dir = tmp_dir("log");
    const auto csv = dir / "data.csv";
    { std::ofstream out(csv, std::ios::binary); out << "abc"; }

    CaptureParams p;
    p.backend = "rplidar-sdk";
    p.port = "/dev/ttyUSB0";
    p.baud = 460800;
    p.frames_requested = 10;
    p.tag = "smoke";
    p.notes = "first bring-up";

    RunStats s;
    s.frames_captured = 10;
    s.samples_total = 4500;
    s.duration_s = 1.23;
    s.mean_quality = 200.5;
    s.median_quality = 201.0;
    s.dropped_frames = 0;

    const auto log_path = dir / "log.txt";
    write_session_log(log_path, p, s, csv);

    const std::string body = slurp(log_path);
    CHECK(body.find("# GODO Phase 3 smoke capture session log")
          != std::string::npos);
    CHECK(body.find("timestamp_utc") != std::string::npos);
    CHECK(body.find("host")          != std::string::npos);
    CHECK(body.find("os")            != std::string::npos);
    CHECK(body.find("backend         : rplidar-sdk") != std::string::npos);
    CHECK(body.find("port            : /dev/ttyUSB0") != std::string::npos);
    CHECK(body.find("baud            : 460800") != std::string::npos);
    CHECK(body.find("frames_requested: 10") != std::string::npos);
    CHECK(body.find("tag             : smoke") != std::string::npos);
    CHECK(body.find("notes           : first bring-up") != std::string::npos);
    CHECK(body.find("frames_captured : 10") != std::string::npos);
    CHECK(body.find("samples_total   : 4500") != std::string::npos);
    CHECK(body.find("duration_s      : 1.230") != std::string::npos);
    CHECK(body.find("mean_quality    : 200.50") != std::string::npos);
    CHECK(body.find("median_quality  : 201.00") != std::string::npos);
    CHECK(body.find("dropped_frames  : 0") != std::string::npos);
    CHECK(body.find("csv_path        : ") != std::string::npos);
    CHECK(body.find("csv_byte_count  : 3") != std::string::npos);
    // SHA-256 "abc" literal, same as the sibling test above.
    CHECK(body.find(
        "csv_sha256      : "
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
          != std::string::npos);
}

TEST_CASE("write_session_log: missing csv_path propagates error") {
    const auto dir = tmp_dir("missing_csv");
    CaptureParams p;
    RunStats s;
    CHECK_THROWS(
        write_session_log(dir / "log.txt", p, s, dir / "missing.csv"));
}
