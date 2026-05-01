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

// 48 rows — issue#12 fold (2026-05-01 PM KST). Two new webctl-owned
// schema rows (`webctl.pose_stream_hz`, `webctl.scan_stream_hz`,
// default 30 Hz, Restart class) round out the count from 46 to 48.
// Tracker stores them in Config via the standard apply/read_effective
// round-trip but no tracker logic path reads the value — godo-webctl is
// the sole consumer (see production/RPi5/CODEBASE.md invariant (r)).
// issue#5 fold (2026-05-01) added 4 Live-carry rows (42 → 46). issue#3
// fold (40 → 42) added 2 hint-σ default rows. Track D-5 fold (37 → 40)
// added 3 annealing rows; see git history for the earlier folds.
//
// Ordering: alphabetical by `name`. Section grouping (network, serial,
// smoother, rt, ipc, amcl, gpio, webctl) emerges naturally from the
// alphabet.
//
// NOTE: `t_ramp_ms` reload_class is `restart` (Mode-A M2 fold) — mid-
// run ramp duration changes would race the smoother's state machine.
// issue#12 lowered its `default_repr` "500" → "100" in lockstep with
// the C++ T_RAMP_NS default (Live-primary architecture).
//
// NOTE (issue#5): `amcl.live_carry_pose_as_hint` is the project's first
// Bool-as-Int row — encoded as `Int` with `min=0, max=1, default_repr="1"`
// until a future PR adds first-class `ValueType::Bool`. Precedent-setting
// key for the convention. issue#5 follow-up (2026-05-01 PM KST) flipped
// the default 0 → 1 after operator HIL approval. See production/RPi5/
// CODEBASE.md invariant (q).

// clang-format off
inline constexpr std::array<ConfigSchemaRow, 48> CONFIG_SCHEMA = {{
    {"amcl.anneal_iters_per_phase",     ValueType::Int,    1.0,      200.0,    "10",                             ReloadClass::Recalibrate, "Track D-5: per-phase upper-bound iteration count for sigma annealing."},
    {"amcl.converge_xy_std_m",          ValueType::Double, 0.001,    1.0,      "0.015",                          ReloadClass::Recalibrate, "AMCL converge() xy_std exit threshold (m)."},
    {"amcl.converge_yaw_std_deg",       ValueType::Double, 0.01,     30.0,     "0.3",                            ReloadClass::Recalibrate, "AMCL converge() yaw_std exit threshold (deg)."},
    {"amcl.downsample_stride",          ValueType::Int,    1.0,      16.0,     "2",                              ReloadClass::Recalibrate, "LiDAR beam decimation stride."},
    {"amcl.hint_sigma_xy_m_default",    ValueType::Double, 0.05,     5.0,      "0.50",                           ReloadClass::Recalibrate, "issue#3: default σ_xy (m) for the calibrate pose hint when the operator omits an override."},
    {"amcl.hint_sigma_yaw_deg_default", ValueType::Double, 1.0,      90.0,     "20.0",                           ReloadClass::Recalibrate, "issue#3: default σ_yaw (deg) for the calibrate pose hint when the operator omits an override."},
    {"amcl.live_carry_pose_as_hint",    ValueType::Int,    0.0,      1.0,      "1",                              ReloadClass::Recalibrate, "issue#5: Live mode kernel selector (Bool-as-Int). 0 = legacy `Amcl::step` per-scan path (rollback). 1 = pipelined `converge_anneal_with_hint` driven by previous-tick pose. Default ON post-PR-#62 HIL approval (Live drift ~4 m → ±5 cm; yaw ~90° → ±1°); operator may set 0 in tracker.toml + restart to roll back."},
    {"amcl.live_carry_schedule_m",      ValueType::String, 0.0,      0.0,      "0.2,0.1,0.05",                   ReloadClass::Recalibrate, "issue#5: CSV sigma_hit schedule for Live pipelined-hint kernel (per-tick anneal). Distinct from amcl.sigma_hit_schedule_m (OneShot). Short by design — tight carry-hint already locks the basin."},
    {"amcl.live_carry_sigma_xy_m",      ValueType::Double, 0.001,    0.5,      "0.050",                          ReloadClass::Recalibrate, "issue#5: Live (pipelined-hint kernel) per-tick carry σ_xy (m). Tight value matches inter-tick crane-base drift; do NOT widen for AMCL search comfort."},
    {"amcl.live_carry_sigma_yaw_deg",   ValueType::Double, 0.05,     30.0,     "5.0",                            ReloadClass::Recalibrate, "issue#5: Live (pipelined-hint kernel) per-tick carry σ_yaw (deg). Pair with amcl.live_carry_sigma_xy_m."},
    {"amcl.map_path",                   ValueType::String, 0.0,      0.0,      "/etc/godo/maps/studio_v1.pgm",   ReloadClass::Recalibrate, "PGM map path; load_map runs at OneShot start."},
    {"amcl.max_iters",                  ValueType::Int,    1.0,      200.0,    "25",                             ReloadClass::Recalibrate, "AMCL converge() upper-bound iteration count."},
    {"amcl.origin_x_m",                 ValueType::Double, -1000.0,  1000.0,   "0.0",                            ReloadClass::Recalibrate, "Calibration origin X (m); affects offset arithmetic."},
    {"amcl.origin_y_m",                 ValueType::Double, -1000.0,  1000.0,   "0.0",                            ReloadClass::Recalibrate, "Calibration origin Y (m)."},
    {"amcl.origin_yaw_deg",             ValueType::Double, -180.0,   180.0,    "0.0",                            ReloadClass::Recalibrate, "Calibration origin yaw (deg)."},
    {"amcl.particles_global_n",         ValueType::Int,    100.0,    10000.0,  "5000",                           ReloadClass::Recalibrate, "Global localization particle count."},
    {"amcl.particles_local_n",          ValueType::Int,    50.0,     2000.0,   "500",                            ReloadClass::Recalibrate, "Local-mode particle count."},
    {"amcl.range_max_m",                ValueType::Double, 1.0,      50.0,     "12.0",                           ReloadClass::Recalibrate, "Max beam range (m)."},
    {"amcl.range_min_m",                ValueType::Double, 0.0,      2.0,      "0.15",                           ReloadClass::Recalibrate, "Min beam range (m); discards LiDAR housing returns."},
    {"amcl.sigma_hit_m",                ValueType::Double, 0.005,    5.0,      "0.05",                           ReloadClass::Recalibrate, "Beam likelihood sigma (m). Bound 5.0 m supports wide basin-lock seeds (Track D-5)."},
    {"amcl.sigma_hit_schedule_m",       ValueType::String, 0.0,      0.0,      "1.0,0.5,0.2,0.1,0.05",           ReloadClass::Recalibrate, "Track D-5: CSV sigma_hit schedule for OneShot AMCL annealing (monotonically decreasing, each in [0.005, 5.0])."},
    {"amcl.sigma_seed_xy_m",            ValueType::Double, 0.05,     5.0,      "0.1",                            ReloadClass::Recalibrate, "Particle filter seed cloud XY std (m)."},
    {"amcl.sigma_seed_xy_schedule_m",   ValueType::String, 0.0,      0.0,      "-,0.10,0.05,0.03,0.02",          ReloadClass::Recalibrate, "Track D-5: CSV per-phase seed_around XY std (m); first entry sentinel '-' (phase 0 = seed_global)."},
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
    {"smoother.t_ramp_ms",              ValueType::Int,    50.0,     5000.0,   "100",                            ReloadClass::Restart,     "Smoother ramp duration (ms). issue#12 default 500 → 100 ms (Live-primary architecture, 10 Hz LiDAR tick)."},
    {"webctl.pose_stream_hz",           ValueType::Int,    1.0,      60.0,     "30",                             ReloadClass::Restart,     "issue#12: SSE pose stream poll cadence (Hz). Webctl-owned — tracker stores the value through render_toml round-trip but never reads it; godo-webctl reads /var/lib/godo/tracker.toml via webctl_toml.read_webctl_section. See production/RPi5/CODEBASE.md invariant (r)."},
    {"webctl.scan_stream_hz",           ValueType::Int,    1.0,      60.0,     "30",                             ReloadClass::Restart,     "issue#12: SSE scan stream poll cadence (Hz). Webctl-owned schema row; same convention as webctl.pose_stream_hz."},
}};
// clang-format on

static_assert(CONFIG_SCHEMA.size() == 48,
              "CONFIG_SCHEMA row count drifted; update tests + schema mirror");

// O(N) lookup. N=40 keeps this trivially fine; O(log N) binary search is
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
