#include "lidar_source_fake.hpp"

#include <stdexcept>

namespace godo::lidar::test {

LidarSourceFake::LidarSourceFake(std::string port, int baud,
                                 int samples_per_frame)
    : port_(std::move(port)), baud_(baud),
      samples_per_frame_(samples_per_frame) {
    if (samples_per_frame_ < 1) {
        throw std::invalid_argument(
            "LidarSourceFake: samples_per_frame must be >= 1");
    }
}

void LidarSourceFake::open() { opened_ = true; }
void LidarSourceFake::close() { opened_ = false; }

void LidarSourceFake::scan_frames(int n_frames, const FrameCallback& on_frame) {
    if (!opened_) {
        throw std::runtime_error("LidarSourceFake: open() must be called first");
    }
    if (n_frames < 1) {
        throw std::invalid_argument(
            "LidarSourceFake::scan_frames: n_frames must be >= 1");
    }

    std::int64_t fake_ts = 1'000'000;  // 1 ms; monotonically increasing
    for (int f = 0; f < n_frames; ++f) {
        Frame frame;
        frame.index = f;
        frame.samples.reserve(static_cast<std::size_t>(samples_per_frame_));
        for (int i = 0; i < samples_per_frame_; ++i) {
            Sample s;
            // Angles strictly in [0, 360). 0.72 deg step × up to 500 samples
            // keeps well under 360 for typical tests.
            const double angle = (static_cast<double>(i) * 0.72);
            // Wrap defensively.
            double wrapped = angle;
            while (wrapped >= 360.0) wrapped -= 360.0;
            s.angle_deg   = wrapped;
            s.distance_mm = 1000.0 + static_cast<double>(i);
            s.quality     = static_cast<std::uint8_t>(50 + (i % 200));
            s.flag        = (i == 0) ? 0x01 : 0x00;
            s.timestamp_ns = fake_ts;
            fake_ts += 100'000;  // 0.1 ms
            frame.samples.push_back(s);
        }
        on_frame(frame.index, frame);
    }
}

}  // namespace godo::lidar::test
