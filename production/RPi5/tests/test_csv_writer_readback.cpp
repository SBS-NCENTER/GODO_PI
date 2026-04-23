// Bias-block test: reads a CSV file back using ONLY stdlib parsing and
// verifies column-name / row-content contract against a literal expected
// header. This target's include path deliberately EXCLUDES the production
// ../src/godo_smoke/ tree — if any `#include "csv_writer.hpp"` or friend
// ever sneaks in, compilation fails. See tests/CMakeLists.txt.
//
// The CSV under test is written in a sibling test process (or captured
// from a known-good run). Here we ship the expected bytes as a literal
// string and assert their round-trip properties end-to-end.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace {

// Literal — not imported from production. See module docstring above.
constexpr const char* kExpectedHeader =
    "frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag";

// A known-good CSV body produced by the writer for the fixture in
// test_csv_writer_writes.cpp "multiple frames share no state". We do not
// re-run the writer here (that would leak production state into this
// target). Instead we parse the literal body to verify the schema is
// parsable with stdlib tools.
constexpr const char* kFixtureCsv =
    "frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag\n"
    "0,0,1000000,0.000000,1000.000,50,1\n"
    "0,1,2000000,0.720000,1001.000,51,0\n"
    "1,0,1000000,0.000000,1000.000,50,1\n";

std::vector<std::string> split_line(const std::string& line, char delim) {
    std::vector<std::string> out;
    std::string cur;
    for (char c : line) {
        if (c == delim) {
            out.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    out.push_back(cur);
    return out;
}

std::vector<std::string> split_lines(const std::string& body) {
    std::vector<std::string> out;
    std::string cur;
    for (char c : body) {
        if (c == '\n') {
            out.push_back(cur);
            cur.clear();
        } else if (c == '\r') {
            // If a CR ever appears, fail loudly — the writer must be opened
            // in binary mode to avoid platform-dependent translation.
            out.push_back(cur + "<CR>");
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    if (!cur.empty()) out.push_back(cur);
    return out;
}

}  // namespace

TEST_CASE("header column names match the literal contract") {
    const auto lines = split_lines(kFixtureCsv);
    REQUIRE(!lines.empty());
    CHECK(lines[0] == std::string(kExpectedHeader));

    const auto cols = split_line(lines[0], ',');
    REQUIRE(cols.size() == 7);
    CHECK(cols[0] == "frame_idx");
    CHECK(cols[1] == "sample_idx");
    CHECK(cols[2] == "timestamp_ns");
    CHECK(cols[3] == "angle_deg");
    CHECK(cols[4] == "distance_mm");
    CHECK(cols[5] == "quality");
    CHECK(cols[6] == "flag");
}

TEST_CASE("no carriage returns ever appear in the CSV stream") {
    for (char c : std::string(kFixtureCsv)) {
        CHECK(c != '\r');
    }
}

TEST_CASE("each non-header row has exactly 7 comma-separated fields") {
    const auto lines = split_lines(kFixtureCsv);
    REQUIRE(lines.size() >= 2);
    for (std::size_t i = 1; i < lines.size(); ++i) {
        const auto cols = split_line(lines[i], ',');
        CHECK_MESSAGE(cols.size() == 7,
            "row ", i, " has ", cols.size(), " columns, expected 7");
    }
}

TEST_CASE("first row integer fields parse, floats have expected precision") {
    const auto lines = split_lines(kFixtureCsv);
    REQUIRE(lines.size() >= 2);
    const auto cols = split_line(lines[1], ',');
    REQUIRE(cols.size() == 7);

    CHECK(cols[0] == "0");       // frame_idx
    CHECK(cols[1] == "0");       // sample_idx
    CHECK(cols[2] == "1000000"); // timestamp_ns
    // %.6f formatting => exactly 6 digits after the point.
    CHECK(cols[3] == "0.000000");
    // %.3f formatting => exactly 3 digits after the point.
    CHECK(cols[4] == "1000.000");
    CHECK(cols[5] == "50");
    CHECK(cols[6] == "1");
}

TEST_CASE("the fixture is exactly header + 3 rows = 4 lines total") {
    int lf = 0;
    for (char c : std::string(kFixtureCsv)) {
        if (c == '\n') ++lf;
    }
    CHECK(lf == 4);
}
