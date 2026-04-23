#include "timestamp.hpp"

#include <array>
#include <chrono>
#include <ctime>
#include <cstdio>

namespace godo::smoke {

std::int64_t monotonic_ns() {
    using namespace std::chrono;
    return duration_cast<nanoseconds>(
               steady_clock::now().time_since_epoch())
        .count();
}

namespace {

std::tm utc_now_tm() {
    using namespace std::chrono;
    const auto tt = system_clock::to_time_t(system_clock::now());
    std::tm out{};
    // gmtime_r is POSIX; the target is RPi 5 / Debian 13.
    gmtime_r(&tt, &out);
    return out;
}

}  // namespace

std::string utc_timestamp_compact() {
    const std::tm t = utc_now_tm();
    std::array<char, 32> buf{};
    // Matches prototype/Python/scripts/capture.py strftime("%Y%m%dT%H%M%SZ").
    const std::size_t n =
        std::strftime(buf.data(), buf.size(), "%Y%m%dT%H%M%SZ", &t);
    return std::string(buf.data(), n);
}

std::string utc_timestamp_iso() {
    const std::tm t = utc_now_tm();
    std::array<char, 32> buf{};
    const std::size_t n =
        std::strftime(buf.data(), buf.size(), "%Y-%m-%dT%H:%M:%S+00:00", &t);
    return std::string(buf.data(), n);
}

}  // namespace godo::smoke
