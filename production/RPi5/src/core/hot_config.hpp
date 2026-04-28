#pragma once

// HotConfig — the precise field set the cold writer reads on every
// iteration. Track B-CONFIG (PR-CONFIG-α) introduces this struct as the
// SSOT for hot-reloadable Tier-2 values. The UDS handler thread
// publishes via Seqlock<HotConfig>; the cold writer reads (lock-free).
//
// Only `hot`-class fields from the schema (config_schema.hpp) belong
// here. Specifically:
//   - smoother.deadband_mm + smoother.deadband_deg (cold writer reads
//     each iteration in the deadband filter at the publish seam),
//   - amcl.yaw_tripwire_deg (compared against AMCL pose every iteration).
//
// Mode-A M1 fold dropped `divergence_mm` / `divergence_deg` — they were
// never consumed in cold_writer.cpp and reclassifying them as `restart`
// keeps the schema honest without bloating HotConfig.

#include <cstdint>
#include <type_traits>

namespace godo::core {

struct HotConfig {
    double        deadband_mm;
    double        deadband_deg;
    double        amcl_yaw_tripwire_deg;
    std::uint64_t published_mono_ns;     // monotonic_ns() at publish time.
    std::uint8_t  valid;                 // 0 = pre-publish sentinel, 1 = ready.
    std::uint8_t  _pad[7];               // pad trailing struct to 40 B.
};

// Layout pin (Mode-A M1 fold): 3×8 (doubles) + 8 (uint64) + 1 (valid)
// + 7 (pad) = 40 B exact. 8-aligned for Seqlock<T>::payload_ safety.
static_assert(sizeof(HotConfig) == 40, "HotConfig layout is ABI-visible");
static_assert(alignof(HotConfig) == 8,  "HotConfig must be 8-aligned");
static_assert(std::is_trivially_copyable_v<HotConfig>,
              "HotConfig must be trivially copyable for Seqlock payload");

// Forward declaration; defined alongside Config to avoid circular include.
struct Config;

// Snapshot the hot-reloadable fields out of a fully-loaded Config.
// `published_mono_ns` is filled by the caller (apply.cpp) immediately
// before the seqlock store so the timestamp reflects publish, not read.
HotConfig snapshot_hot(const Config& cfg) noexcept;

}  // namespace godo::core
