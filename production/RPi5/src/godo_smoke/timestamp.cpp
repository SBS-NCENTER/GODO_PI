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

std::tm kst_now_tm() {
    using namespace std::chrono;
    const auto tt = system_clock::to_time_t(system_clock::now());
    std::tm out{};
    // localtime_r reads `TZ` env / `/etc/localtime`; the production
    // host is fixed to KST so the result is always KST. Project
    // convention — see
    // `.claude/memory/feedback_timestamp_kst_convention.md`.
    localtime_r(&tt, &out);
    return out;
}

}  // namespace

std::string utc_timestamp_compact() {
    // Function name retained for ABI stability; the body now emits KST
    // (compact form drops the offset suffix per project convention).
    const std::tm t = kst_now_tm();
    std::array<char, 32> buf{};
    const std::size_t n =
        std::strftime(buf.data(), buf.size(), "%Y%m%dT%H%M%S", &t);
    return std::string(buf.data(), n);
}

std::string utc_timestamp_iso() {
    // Function name retained for ABI stability; the body now emits ISO
    // 8601 with explicit KST offset (`+09:00`).
    const std::tm t = kst_now_tm();
    std::array<char, 32> buf{};
    const std::size_t n =
        std::strftime(buf.data(), buf.size(), "%Y-%m-%dT%H:%M:%S+09:00", &t);
    return std::string(buf.data(), n);
}

}  // namespace godo::smoke
