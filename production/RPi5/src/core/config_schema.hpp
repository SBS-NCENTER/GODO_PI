#pragma once

// Tier-2 config schema — the canonical declaration of every operator-
// tunable Config field. Track B-CONFIG (PR-CONFIG-α) consumes this
// table to validate `set_config` payloads, render `get_config_schema`
// JSON, and drive the SPA's per-row reload-class indicator.
//
// SSOT contract (CODEBASE.md invariant (l)):
//   - C++ canonical: this file's CONFIG_SCHEMA[] array.
//   - Python mirror (next session, PR-CONFIG-β):
//       godo-webctl/src/godo_webctl/config_schema.py — regex-extracts
//       this file at startup and asserts row count + per-key parity.
//   - TS mirror (PR-CONFIG-β): runtime fetch from /api/config/schema.
//
// Adding / removing a row requires:
//   - update CONFIG_SCHEMA[] entries below (alphabetical by `name`),
//   - update the static_assert(N == ...) count,
//   - update godo-webctl/tests/test_config_schema_parity.py (β),
//   - update apply_set / apply_get to reach the corresponding Config field.
//
// One row per line is intentional — `// clang-format off` keeps the
// table reflow-free so the Python regex parser sees a stable shape.

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>

namespace godo::core::config_schema {

enum class ValueType : std::uint8_t {
    Int,
    Double,
    String,
};

enum class ReloadClass : std::uint8_t {
    Hot,          // mid-run swap via Seqlock<HotConfig>; cold writer reads.
    Restart,      // takes effect on next godo-tracker boot.
    Recalibrate,  // invalidates particle cloud; operator must re-OneShot.
};

struct ConfigSchemaRow {
    std::string_view name;          // dotted path, alphabetical-sortable.
    ValueType        type;
    double           min_d;         // numeric range; ignored for String.
    double           max_d;
    std::string_view default_repr;  // operator-readable default (string form).
    ReloadClass      reload_class;
    std::string_view description;
};

// 37 rows — Mode-A M2 fold. Adding 2 missing seed-σ rows brought the
// count from 35 to 37 (`amcl.sigma_seed_xy_m`, `amcl.sigma_seed_yaw_deg`).
//
// Ordering: alphabetical by `name`. Section grouping (network, serial,
// smoother, rt, ipc, amcl, gpio) emerges naturally from the alphabet.
//
// NOTE: `t_ramp_ms` reload_class is `restart` (Mode-A M2 fold) — mid-
// run ramp duration changes would race the smoother's state machine.

// clang-format off
inline constexpr std::array<ConfigSchemaRow, 37> CONFIG_SCHEMA = {{
    {"amcl.converge_xy_std_m",          ValueType::Double, 0.001,    1.0,      "0.015",                          ReloadClass::Recalibrate, "AMCL converge() xy_std exit threshold (m)."},
    {"amcl.converge_yaw_std_deg",       ValueType::Double, 0.01,     30.0,     "0.3",                            ReloadClass::Recalibrate, "AMCL converge() yaw_std exit threshold (deg)."},
    {"amcl.downsample_stride",          ValueType::Int,    1.0,      16.0,     "2",                              ReloadClass::Recalibrate, "LiDAR beam decimation stride."},
    {"amcl.map_path",                   ValueType::String, 0.0,      0.0,      "/etc/godo/maps/studio_v1.pgm",   ReloadClass::Recalibrate, "PGM map path; load_map runs at OneShot start."},
    {"amcl.max_iters",                  ValueType::Int,    1.0,      200.0,    "25",                             ReloadClass::Recalibrate, "AMCL converge() upper-bound iteration count."},
    {"amcl.origin_x_m",                 ValueType::Double, -1000.0,  1000.0,   "0.0",                            ReloadClass::Recalibrate, "Calibration origin X (m); affects offset arithmetic."},
    {"amcl.origin_y_m",                 ValueType::Double, -1000.0,  1000.0,   "0.0",                            ReloadClass::Recalibrate, "Calibration origin Y (m)."},
    {"amcl.origin_yaw_deg",             ValueType::Double, -180.0,   180.0,    "0.0",                            ReloadClass::Recalibrate, "Calibration origin yaw (deg)."},
    {"amcl.particles_global_n",         ValueType::Int,    100.0,    10000.0,  "5000",                           ReloadClass::Recalibrate, "Global localization particle count."},
    {"amcl.particles_local_n",          ValueType::Int,    50.0,     2000.0,   "500",                            ReloadClass::Recalibrate, "Local-mode particle count."},
    {"amcl.range_max_m",                ValueType::Double, 1.0,      50.0,     "12.0",                           ReloadClass::Recalibrate, "Max beam range (m)."},
    {"amcl.range_min_m",                ValueType::Double, 0.0,      2.0,      "0.15",                           ReloadClass::Recalibrate, "Min beam range (m); discards LiDAR housing returns."},
    {"amcl.sigma_hit_m",                ValueType::Double, 0.005,    1.0,      "0.05",                           ReloadClass::Recalibrate, "Beam likelihood sigma (m)."},
    {"amcl.sigma_seed_xy_m",            ValueType::Double, 0.05,     5.0,      "0.1",                            ReloadClass::Recalibrate, "Particle filter seed cloud XY std (m)."},
    {"amcl.sigma_seed_yaw_deg",         ValueType::Double, 1.0,      180.0,    "5.0",                            ReloadClass::Recalibrate, "Particle filter seed cloud yaw std (deg)."},
    {"amcl.sigma_xy_jitter_live_m",     ValueType::Double, 0.001,    0.5,      "0.015",                          ReloadClass::Recalibrate, "Live mode motion-model XY sigma (per-tick injected noise)."},
    {"amcl.sigma_xy_jitter_m",          ValueType::Double, 0.001,    0.5,      "0.005",                          ReloadClass::Recalibrate, "OneShot motion-model XY sigma (m)."},
    {"amcl.sigma_yaw_jitter_deg",       ValueType::Double, 0.05,     30.0,     "0.5",                            ReloadClass::Recalibrate, "OneShot motion-model yaw sigma (deg)."},
    {"amcl.sigma_yaw_jitter_live_deg",  ValueType::Double, 0.05,     30.0,     "1.5",                            ReloadClass::Recalibrate, "Live mode motion-model yaw sigma (per-tick injected noise)."},
    {"amcl.trigger_poll_ms",            ValueType::Int,    10.0,     1000.0,   "50",                             ReloadClass::Hot,         "Cold-writer Idle wake cadence (ms)."},
    {"amcl.yaw_tripwire_deg",           ValueType::Double, 0.5,      45.0,     "5.0",                            ReloadClass::Hot,         "Yaw drift WARN threshold (deg) vs. origin_yaw_deg."},
    {"gpio.calibrate_pin",              ValueType::Int,    0.0,      27.0,     "16",                             ReloadClass::Restart,     "BCM pin for calibrate button."},
    {"gpio.live_toggle_pin",            ValueType::Int,    0.0,      27.0,     "20",                             ReloadClass::Restart,     "BCM pin for live toggle button."},
    {"ipc.uds_socket",                  ValueType::String, 0.0,      0.0,      "/run/godo/ctl.sock",             ReloadClass::Restart,     "UDS control-plane socket path."},
    {"network.ue_host",                 ValueType::String, 0.0,      0.0,      "192.168.0.0",                    ReloadClass::Restart,     "UE receiver IPv4 / hostname."},
    {"network.ue_port",                 ValueType::Int,    1.0,      65535.0,  "6666",                           ReloadClass::Restart,     "UE receiver UDP port."},
    {"rt.cpu",                          ValueType::Int,    0.0,      7.0,      "3",                              ReloadClass::Restart,     "RT thread CPU pin."},
    {"rt.priority",                     ValueType::Int,    1.0,      99.0,     "50",                             ReloadClass::Restart,     "SCHED_FIFO priority for Thread D."},
    {"serial.freed_baud",               ValueType::Int,    9600.0,   921600.0, "38400",                          ReloadClass::Restart,     "FreeD serial baud."},
    {"serial.freed_port",               ValueType::String, 0.0,      0.0,      "/dev/ttyAMA0",                   ReloadClass::Restart,     "FreeD serial device path."},
    {"serial.lidar_baud",               ValueType::Int,    9600.0,   921600.0, "460800",                         ReloadClass::Restart,     "LiDAR serial baud."},
    {"serial.lidar_port",               ValueType::String, 0.0,      0.0,      "/dev/ttyUSB0",                   ReloadClass::Restart,     "LiDAR serial device path."},
    {"smoother.deadband_deg",           ValueType::Double, 0.0,      5.0,      "0.1",                            ReloadClass::Hot,         "Deadband on yaw (deg)."},
    {"smoother.deadband_mm",            ValueType::Double, 0.0,      200.0,    "10.0",                           ReloadClass::Hot,         "Deadband on translation (mm)."},
    {"smoother.divergence_deg",         ValueType::Double, 1.0,      45.0,     "10.0",                           ReloadClass::Restart,     "Divergence reject threshold (deg)."},
    {"smoother.divergence_mm",          ValueType::Double, 100.0,    10000.0,  "2000.0",                         ReloadClass::Restart,     "Divergence reject threshold (mm)."},
    {"smoother.t_ramp_ms",              ValueType::Int,    50.0,     5000.0,   "500",                            ReloadClass::Restart,     "Smoother ramp duration (ms)."},
}};
// clang-format on

static_assert(CONFIG_SCHEMA.size() == 37,
              "CONFIG_SCHEMA row count drifted; update tests + schema mirror");

// O(N) lookup. N=37 keeps this trivially fine; O(log N) binary search is
// avoidable churn for a 1-Hz operator-cadence call. Returns nullptr if
// the key is unknown — callers map this to `bad_key`.
inline constexpr const ConfigSchemaRow* find(std::string_view key) noexcept {
    for (const auto& row : CONFIG_SCHEMA) {
        if (row.name == key) return &row;
    }
    return nullptr;
}

inline constexpr std::string_view reload_class_to_string(ReloadClass cls) noexcept {
    switch (cls) {
        case ReloadClass::Hot:         return "hot";
        case ReloadClass::Restart:     return "restart";
        case ReloadClass::Recalibrate: return "recalibrate";
    }
    return "hot";  // unreachable; static analyzers like a default.
}

inline constexpr std::string_view value_type_to_string(ValueType t) noexcept {
    switch (t) {
        case ValueType::Int:    return "int";
        case ValueType::Double: return "double";
        case ValueType::String: return "string";
    }
    return "string";  // unreachable.
}

}  // namespace godo::core::config_schema
