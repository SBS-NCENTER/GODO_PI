// Byte-identity parity: C++ CsvWriter MUST produce the same CSV as the
// Python CsvDumpWriter for the same sample input.
//
// Strategy:
//   1. Build a fixed Frame in C++ and write it out.
//   2. Shell out to `uv run python -c "<script>"` to drive the Python
//      CsvDumpWriter against the same data.
//   3. cmp -s the two files.
//
// Test is conditionally compiled: tests/CMakeLists.txt skips it when uv
// or the project's uv.lock is unavailable (labels include python-required).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <array>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

#include "csv_writer.hpp"
#include "lidar/sample.hpp"

namespace {

// Absolute path of the Python prototype. Injected by CMake via a compile
// definition so this string stays authoritative from the build tree's POV.
#ifndef GODO_PYTHON_PROJECT_DIR
#error "GODO_PYTHON_PROJECT_DIR must be defined by the build system"
#endif

std::string run_capture_output(const std::string& cmd) {
    std::string out;
    std::array<char, 4096> buf{};
    FILE* p = popen(cmd.c_str(), "r");
    REQUIRE(p != nullptr);
    while (std::fgets(buf.data(), static_cast<int>(buf.size()), p) != nullptr) {
        out += buf.data();
    }
    const int rc = pclose(p);
    REQUIRE(rc == 0);
    return out;
}

}  // namespace

TEST_CASE("C++ and Python CSV writers produce byte-identical output") {
    using godo::smoke::CsvWriter;
    using godo::lidar::Frame;
    using godo::lidar::Sample;

    const auto tmp = std::filesystem::temp_directory_path() /
                     "godo_smoke_parity";
    std::filesystem::remove_all(tmp);
    std::filesystem::create_directories(tmp);

    const auto cpp_path = tmp / "cpp.csv";
    const auto py_path  = tmp / "py.csv";

    // Build the same Frame in both languages.
    Frame f;
    f.index = 3;
    for (int i = 0; i < 5; ++i) {
        Sample s;
        s.angle_deg    = (static_cast<double>(i) * 0.72);
        s.distance_mm  = 1000.0 + static_cast<double>(i);
        s.quality      = static_cast<std::uint8_t>(50 + i);
        s.flag         = static_cast<std::uint8_t>(i == 0 ? 1 : 0);
        s.timestamp_ns = 1'000'000 * static_cast<std::int64_t>(i + 1);
        f.samples.push_back(s);
    }

    {
        CsvWriter w(cpp_path);
        w.open();
        w.write_frame(f);
    }

    // Drive the Python writer through uv. The Python input is the exact
    // same numbers — no shared data file between the two paths, so the
    // comparison stays honest (different serializers, same input data).
    std::ostringstream py;
    py << "uv run --project '" << GODO_PYTHON_PROJECT_DIR << "' python -c \""
       << "from godo_lidar.frame import Frame, Sample;"
       << "from godo_lidar.io.csv_dump import CsvDumpWriter;"
       << "from pathlib import Path;"
       << "samples = [Sample("
            << "angle_deg=i*0.72,"
            << "distance_mm=1000.0+i,"
            << "quality=50+i,"
            << "flag=1 if i==0 else 0,"
            << "timestamp_ns=1_000_000*(i+1)) for i in range(5)];"
       << "f = Frame(index=3, samples=samples);"
       << "w = CsvDumpWriter(Path(r'" << py_path.string() << "'));"
       << "w.open(); w.write_frame(f); w.close();"
       << "\"";

    (void)run_capture_output(py.str());

    // Read both files as raw bytes and compare.
    auto slurp = [](const std::filesystem::path& p) {
        std::ifstream in(p, std::ios::binary);
        std::ostringstream os;
        os << in.rdbuf();
        return os.str();
    };
    const std::string cpp_bytes = slurp(cpp_path);
    const std::string py_bytes  = slurp(py_path);
    CHECK(cpp_bytes == py_bytes);

    // Helpful diagnostic when the bytes differ.
    if (cpp_bytes != py_bytes) {
        MESSAGE("cpp_path = ", cpp_path.string());
        MESSAGE("py_path  = ", py_path.string());
    }
}
