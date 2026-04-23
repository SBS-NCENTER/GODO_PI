#pragma once

// Value types for the capture → dump pipeline.
//
// Mirror of prototype/Python/src/godo_lidar/frame.py (Sample / Frame).
// Invariants are enforced by `Sample::validate()` (explicit, not in a
// constructor — we want plain aggregate init for tests).

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace godo::smoke {

struct Sample {
    double   angle_deg;     // [0, 360)
    double   distance_mm;   // >= 0; 0 means "invalid range" per SLAMTEC PDF Fig 4-5
    std::uint8_t quality;   // [0, 255]
    std::uint8_t flag;      // bit 0 = S (start-of-frame)
    std::int64_t timestamp_ns;  // >= 0; monotonic capture clock
};

struct Frame {
    int                 index;
    std::vector<Sample> samples;
};

// Validate a single sample against the invariants documented above.
// Throws std::invalid_argument with a short reason. Used by the RPLIDAR
// source path when converting raw SDK measurements; keeps the policy in
// one place so fake sources can reuse it in tests.
inline void validate(const Sample& s) {
    if (!(s.angle_deg >= 0.0 && s.angle_deg < 360.0)) {
        throw std::invalid_argument("angle_deg must be in [0, 360)");
    }
    if (s.distance_mm < 0.0) {
        throw std::invalid_argument("distance_mm must be >= 0");
    }
    if (s.timestamp_ns < 0) {
        throw std::invalid_argument("timestamp_ns must be >= 0");
    }
    // quality and flag are uint8_t; their invariants are type-enforced.
}

}  // namespace godo::smoke
