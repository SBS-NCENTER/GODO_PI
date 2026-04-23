// Unit tests for the Sample invariants declared in sample.hpp and for the
// LidarSourceFake duck-typed twin (which exercises the same contract path
// godo_smoke's main loop drives).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

#include "lidar_source_fake.hpp"
#include "sample.hpp"

using godo::smoke::Frame;
using godo::smoke::Sample;
using godo::smoke::validate;
using godo::smoke::test::LidarSourceFake;

TEST_CASE("validate: angle boundaries") {
    Sample s{0.0, 0.0, 0, 0, 0};
    CHECK_NOTHROW(validate(s));
    s.angle_deg = 359.999;
    CHECK_NOTHROW(validate(s));
    // 360.0 is rejected (Python parity: must wrap upstream).
    s.angle_deg = 360.0;
    CHECK_THROWS(validate(s));
    s.angle_deg = -0.0001;
    CHECK_THROWS(validate(s));
}

TEST_CASE("validate: distance >= 0") {
    Sample s{0.0, 0.0, 0, 0, 0};
    CHECK_NOTHROW(validate(s));
    s.distance_mm = -0.0001;
    CHECK_THROWS(validate(s));
}

TEST_CASE("validate: timestamp >= 0") {
    Sample s{0.0, 0.0, 0, 0, 0};
    CHECK_NOTHROW(validate(s));
    s.timestamp_ns = -1;
    CHECK_THROWS(validate(s));
    s.timestamp_ns = std::numeric_limits<std::int64_t>::max();
    CHECK_NOTHROW(validate(s));
}

TEST_CASE("LidarSourceFake: constructor rejects bad samples_per_frame") {
    CHECK_THROWS(LidarSourceFake("fake", 460800, 0));
    CHECK_THROWS(LidarSourceFake("fake", 460800, -1));
}

TEST_CASE("LidarSourceFake: scan_frames before open throws") {
    LidarSourceFake f("fake", 460800, 5);
    CHECK_THROWS(f.scan_frames(1, [](int, const Frame&) {}));
}

TEST_CASE("LidarSourceFake: scan_frames rejects n_frames < 1") {
    LidarSourceFake f("fake", 460800, 5);
    f.open();
    CHECK_THROWS(f.scan_frames(0, [](int, const Frame&) {}));
    CHECK_THROWS(f.scan_frames(-1, [](int, const Frame&) {}));
}

TEST_CASE("LidarSourceFake: emits requested frame count and shape") {
    LidarSourceFake f("fake", 460800, 7);
    f.open();
    std::vector<int> indices;
    std::size_t total_samples = 0;
    f.scan_frames(3, [&](int idx, const Frame& frame) {
        indices.push_back(idx);
        // All emitted samples must satisfy the invariants.
        for (const auto& s : frame.samples) {
            CHECK_NOTHROW(validate(s));
        }
        // First sample of each frame carries the start-of-frame bit.
        REQUIRE(!frame.samples.empty());
        CHECK((frame.samples.front().flag & 0x01) == 0x01);
        for (std::size_t i = 1; i < frame.samples.size(); ++i) {
            CHECK((frame.samples[i].flag & 0x01) == 0x00);
        }
        total_samples += frame.samples.size();
    });
    CHECK(indices == std::vector<int>{0, 1, 2});
    CHECK(total_samples == 21);  // 3 frames × 7 samples
    f.close();
    CHECK(f.is_open() == false);
}
