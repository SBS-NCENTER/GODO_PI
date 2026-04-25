// Hardware-in-the-loop smoke test for LidarSourceRplidar.
//
// Label: hardware-required. Not exercised by default `ctest`; run
// explicitly when the C1 is plugged in:
//   ctest --test-dir build -L hardware-required --output-on-failure
//
// The test opens the default port, captures one frame, and asserts the
// invariants documented in sample.hpp.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdlib>
#include <string>

#include "lidar/lidar_source_rplidar.hpp"
#include "lidar/sample.hpp"

using godo::lidar::Frame;
using godo::lidar::LidarSourceRplidar;
using godo::lidar::validate;

TEST_CASE("RPLIDAR C1 delivers a valid frame on the default port") {
    const char* port_env = std::getenv("GODO_SMOKE_PORT");
    const std::string port = port_env ? port_env : "/dev/ttyUSB0";

    LidarSourceRplidar lidar(port, 460'800);
    lidar.open();
    bool called = false;
    lidar.scan_frames(1, [&](int idx, const Frame& frame) {
        called = true;
        CHECK(idx == 0);
        REQUIRE(!frame.samples.empty());
        for (const auto& s : frame.samples) {
            CHECK_NOTHROW(validate(s));
        }
    });
    lidar.close();
    CHECK(called);
}
