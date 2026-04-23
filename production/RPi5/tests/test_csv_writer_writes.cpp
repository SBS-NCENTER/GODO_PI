// Test "writing side" of CsvWriter — exercises the production code path.
// This file DOES include csv_writer.hpp (by design; it is the driver).
//
// The read-back test lives in a separate target (test_read_back) with
// include path restricted so it CANNOT include csv_writer.hpp. See
// CODEBASE.md invariant (b) for the bias-blocking rationale.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "csv_writer.hpp"
#include "sample.hpp"

using godo::smoke::CsvWriter;
using godo::smoke::Frame;
using godo::smoke::Sample;

namespace {

// Literal header — duplicated on purpose. If a reorder in csv_writer.cpp
// changes it, this test fails. NEVER replace with `#include` of a constant.
constexpr const char* kExpectedHeader =
    "frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag\n";

Frame make_frame(int idx, int n) {
    Frame f;
    f.index = idx;
    f.samples.reserve(static_cast<std::size_t>(n));
    for (int i = 0; i < n; ++i) {
        Sample s;
        s.angle_deg    = (static_cast<double>(i) * 0.72);
        if (s.angle_deg >= 360.0) s.angle_deg -= 360.0;
        s.distance_mm  = 1000.0 + static_cast<double>(i);
        s.quality      = static_cast<std::uint8_t>(50 + i);
        s.flag         = static_cast<std::uint8_t>(i == 0 ? 1 : 0);
        s.timestamp_ns = 1'000'000 * static_cast<std::int64_t>(i + 1);
        f.samples.push_back(s);
    }
    return f;
}

std::string read_all(const std::filesystem::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream os;
    os << in.rdbuf();
    return os.str();
}

}  // namespace

TEST_CASE("header is written on open and counters start at zero") {
    const auto dir = std::filesystem::temp_directory_path() /
                     "godo_smoke_test_csv_header";
    std::filesystem::remove_all(dir);
    const auto p = dir / "a.csv";

    {
        CsvWriter w(p);
        w.open();
        CHECK(w.frames_written() == 0);
        CHECK(w.samples_written() == 0);
    }
    const auto body = read_all(p);
    CHECK(body == std::string(kExpectedHeader));
}

TEST_CASE("write_frame emits one row per sample with exact formatting") {
    const auto dir = std::filesystem::temp_directory_path() /
                     "godo_smoke_test_csv_rows";
    std::filesystem::remove_all(dir);
    const auto p = dir / "b.csv";

    Frame f = make_frame(7, 3);
    {
        CsvWriter w(p);
        w.open();
        w.write_frame(f);
        CHECK(w.frames_written() == 1);
        CHECK(w.samples_written() == 3);
    }

    const auto body = read_all(p);
    // Header + 3 rows; exact byte match so any format drift is caught.
    const std::string expected =
        std::string(kExpectedHeader) +
        "7,0,1000000,0.000000,1000.000,50,1\n"
        "7,1,2000000,0.720000,1001.000,51,0\n"
        "7,2,3000000,1.440000,1002.000,52,0\n";
    CHECK(body == expected);
}

TEST_CASE("write_frame before open() throws") {
    CsvWriter w(std::filesystem::temp_directory_path() /
                "godo_smoke_test_csv_nopen.csv");
    Frame f = make_frame(0, 1);
    CHECK_THROWS(w.write_frame(f));
}

TEST_CASE("empty frame leaves only the header") {
    const auto dir = std::filesystem::temp_directory_path() /
                     "godo_smoke_test_csv_empty";
    std::filesystem::remove_all(dir);
    const auto p = dir / "c.csv";

    {
        CsvWriter w(p);
        w.open();
        Frame empty;
        empty.index = 0;
        w.write_frame(empty);
        CHECK(w.frames_written() == 1);
        CHECK(w.samples_written() == 0);
    }
    const auto body = read_all(p);
    CHECK(body == std::string(kExpectedHeader));
}

TEST_CASE("angle_deg uses 6 decimals and distance_mm uses 3 decimals") {
    // Boundary: max allowed angle just under 360, very small distance.
    const auto dir = std::filesystem::temp_directory_path() /
                     "godo_smoke_test_csv_precision";
    std::filesystem::remove_all(dir);
    const auto p = dir / "d.csv";

    Frame f;
    f.index = 0;
    Sample s;
    s.angle_deg    = 359.999999;
    s.distance_mm  = 0.125;
    s.quality      = 0;
    s.flag         = 1;
    s.timestamp_ns = 0;
    f.samples.push_back(s);

    {
        CsvWriter w(p);
        w.open();
        w.write_frame(f);
    }

    const auto body = read_all(p);
    const std::string expected =
        std::string(kExpectedHeader) +
        "0,0,0,359.999999,0.125,0,1\n";
    CHECK(body == expected);
}

TEST_CASE("multiple frames share no state between them") {
    const auto dir = std::filesystem::temp_directory_path() /
                     "godo_smoke_test_csv_multiframe";
    std::filesystem::remove_all(dir);
    const auto p = dir / "e.csv";

    {
        CsvWriter w(p);
        w.open();
        w.write_frame(make_frame(0, 2));
        w.write_frame(make_frame(1, 1));
        CHECK(w.frames_written() == 2);
        CHECK(w.samples_written() == 3);
    }

    const auto body = read_all(p);
    const std::string expected =
        std::string(kExpectedHeader) +
        "0,0,1000000,0.000000,1000.000,50,1\n"
        "0,1,2000000,0.720000,1001.000,51,0\n"
        "1,0,1000000,0.000000,1000.000,50,1\n";
    CHECK(body == expected);
}
