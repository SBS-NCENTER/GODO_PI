#pragma once

// Deterministic fake LiDAR source for hardware-free tests.
//
// Duck-typed twin of godo::lidar::LidarSourceRplidar; NOT a subclass. The
// class name is deliberately different so tests that use `LidarSourceFake`
// directly cannot accidentally compile against the real type. See
// CODEBASE.md invariant (a).

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "lidar/sample.hpp"

namespace godo::lidar::test {

class LidarSourceFake {
public:
    // `samples_per_frame` must be >= 1. The fake emits deterministic,
    // strictly-sorted angles in [0, 360), distances starting at 1000 mm and
    // incrementing by 1 mm per sample, and quality = 50 + sample_idx (mod
    // 200). The start-of-frame bit is set on sample 0 of each frame.
    LidarSourceFake(std::string port, int baud, int samples_per_frame);

    void open();
    void close();

    using FrameCallback = std::function<void(int frame_index, const Frame&)>;
    void scan_frames(int n_frames, const FrameCallback& on_frame);

    [[nodiscard]] bool is_open() const { return opened_; }
    [[nodiscard]] const std::string& port() const { return port_; }
    [[nodiscard]] int baud() const { return baud_; }

private:
    std::string port_;
    int         baud_;
    int         samples_per_frame_;
    bool        opened_{false};
};

}  // namespace godo::lidar::test
