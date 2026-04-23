#include "lidar_source_rplidar.hpp"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <thread>

#include "sl_lidar.h"
#include "sl_lidar_driver.h"

#include "timestamp.hpp"

namespace godo::smoke {

namespace {

constexpr std::size_t kMaxScanNodes = 8192;

}  // namespace

struct LidarSourceRplidar::Impl {
    std::string          port;
    int                  baud{};
    sl::ILidarDriver*    drv{nullptr};
    sl::IChannel*        channel{nullptr};
    bool                 scanning{false};

    Impl(std::string p, int b) : port(std::move(p)), baud(b) {}

    void connect() {
        drv = *sl::createLidarDriver();
        if (drv == nullptr) {
            throw std::runtime_error(
                "rplidar: createLidarDriver returned null");
        }
        channel = *sl::createSerialPortChannel(port.c_str(),
                                               static_cast<sl_u32>(baud));
        if (channel == nullptr) {
            throw std::runtime_error(
                "rplidar: createSerialPortChannel returned null");
        }
        const sl_result rc = drv->connect(channel);
        if (!SL_IS_OK(rc)) {
            throw std::runtime_error(
                "rplidar: driver connect failed on '" + port + "'");
        }

        sl_lidar_response_device_info_t devinfo{};
        if (!SL_IS_OK(drv->getDeviceInfo(devinfo))) {
            throw std::runtime_error("rplidar: getDeviceInfo failed");
        }

        sl_lidar_response_device_health_t health{};
        if (!SL_IS_OK(drv->getHealth(health))) {
            throw std::runtime_error("rplidar: getHealth failed");
        }
        if (health.status == SL_LIDAR_STATUS_ERROR) {
            throw std::runtime_error(
                "rplidar: device reports SL_LIDAR_STATUS_ERROR; reboot the "
                "unit and retry");
        }
    }

    void start() {
        // Default motor speed (C1 cmd 0xA8 with the firmware's preferred RPM).
        drv->setMotorSpeed();
        // startScan(force=0, useTypicalScan=1): standard scan mode.
        const sl_result rc = drv->startScan(0, 1);
        if (!SL_IS_OK(rc)) {
            throw std::runtime_error("rplidar: startScan failed");
        }
        scanning = true;
    }

    void stop_and_disconnect() {
        if (drv != nullptr) {
            if (scanning) {
                drv->stop();
                std::this_thread::sleep_for(std::chrono::milliseconds(200));
                drv->setMotorSpeed(0);
                scanning = false;
            }
            delete drv;
            drv = nullptr;
        }
        // Channel is owned by the driver after connect(); no explicit delete.
        channel = nullptr;
    }

    ~Impl() {
        try {
            stop_and_disconnect();
        } catch (...) {
            // Destructors must not throw.
        }
    }
};

LidarSourceRplidar::LidarSourceRplidar(std::string port, int baud)
    : impl_(std::make_unique<Impl>(std::move(port), baud)) {}

LidarSourceRplidar::~LidarSourceRplidar() = default;

void LidarSourceRplidar::open() {
    impl_->connect();
    impl_->start();
}

void LidarSourceRplidar::close() { impl_->stop_and_disconnect(); }

void LidarSourceRplidar::scan_frames(int n_frames,
                                     const FrameCallback& on_frame) {
    if (n_frames < 1) {
        throw std::invalid_argument("scan_frames: n_frames must be >= 1");
    }
    if (!impl_->scanning) {
        throw std::runtime_error("scan_frames: open() must be called first");
    }

    // grabScanDataHq returns one complete sorted 360-degree scan per call.
    std::array<sl_lidar_response_measurement_node_hq_t, kMaxScanNodes> nodes{};
    int delivered = 0;
    while (delivered < n_frames) {
        size_t count = nodes.size();
        const sl_result rc = impl_->drv->grabScanDataHq(nodes.data(), count);
        if (!SL_IS_OK(rc)) {
            throw std::runtime_error(
                "rplidar: grabScanDataHq failed mid-stream");
        }
        impl_->drv->ascendScanData(nodes.data(), count);

        Frame frame;
        frame.index = delivered;
        frame.samples.reserve(count);
        const std::int64_t t_ns = monotonic_ns();
        for (std::size_t i = 0; i < count; ++i) {
            const auto& n = nodes[i];
            const double angle_deg =
                (static_cast<double>(n.angle_z_q14) * 90.0) / 16384.0;
            const double distance_mm = static_cast<double>(n.dist_mm_q2) / 4.0;
            const std::uint8_t quality = static_cast<std::uint8_t>(
                n.quality >> SL_LIDAR_RESP_MEASUREMENT_QUALITY_SHIFT);
            const std::uint8_t flag = static_cast<std::uint8_t>(n.flag & 0xFF);

            Sample s{};
            // Wrap per the frame.py invariant: angle must be strictly < 360.
            double wrapped = std::fmod(angle_deg, 360.0);
            if (wrapped < 0.0) wrapped += 360.0;
            if (wrapped >= 360.0) wrapped = 0.0;
            s.angle_deg   = wrapped;
            s.distance_mm = distance_mm;
            s.quality     = quality;
            s.flag        = flag;
            s.timestamp_ns = t_ns;
            try {
                validate(s);
            } catch (const std::invalid_argument&) {
                // Drop malformed samples rather than abort the capture; the
                // smoke binary privileges "some data on disk" over strict
                // invariant enforcement. Consistent with the Python
                // SdkBackend's drop-on-validation-failure behaviour.
                continue;
            }
            frame.samples.push_back(s);
        }

        if (!frame.samples.empty()) {
            on_frame(frame.index, frame);
            ++delivered;
        }
    }
}

}  // namespace godo::smoke
