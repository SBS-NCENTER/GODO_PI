#pragma once

// RPLIDAR-backed LiDAR source.
//
// Intentionally CONCRETE — no `virtual`, no ABC. Duck-typed twin for tests
// lives in tests/lidar_source_fake.hpp under a different class name. The
// production target compiles this file; the test targets compile the fake.
// See production/RPi5/CODEBASE.md invariant (a) — matches the Python
// prototype's capture/sdk.py vs capture/raw.py precedent.
//
// Promoted from src/godo_smoke/lidar_source_rplidar.hpp (Phase 4-2
// LiDAR component-isation, 2026-04-25). Phase 4-2 AMCL writer thread
// will hold an instance via `godo::lidar::LidarSourceRplidar`.

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

#include "lidar/sample.hpp"

namespace godo::lidar {

class LidarSourceRplidar {
public:
    LidarSourceRplidar(std::string port, int baud);
    ~LidarSourceRplidar();
    LidarSourceRplidar(const LidarSourceRplidar&)            = delete;
    LidarSourceRplidar& operator=(const LidarSourceRplidar&) = delete;
    LidarSourceRplidar(LidarSourceRplidar&&)                 = delete;
    LidarSourceRplidar& operator=(LidarSourceRplidar&&)      = delete;

    // Connect, spin the motor, start scanning. Throws on failure.
    void open();

    // Stop the scan, park the motor, disconnect. Idempotent.
    void close();

    // Stream `n_frames` complete 360-degree frames. The callback is invoked
    // once per frame with (frame_index, frame). The method returns when the
    // requested number of frames has been delivered or the SDK reports a
    // fatal error.
    using FrameCallback = std::function<void(int frame_index, const Frame&)>;
    void scan_frames(int n_frames, const FrameCallback& on_frame);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace godo::lidar
