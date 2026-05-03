#include "apply.hpp"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "atomic_toml_writer.hpp"
#include "core/time.hpp"
#include "restart_pending.hpp"
#include "validate.hpp"

namespace godo::config {

namespace {

using godo::core::Config;
using godo::core::config_schema::CONFIG_SCHEMA;
using godo::core::config_schema::ConfigSchemaRow;
using godo::core::config_schema::ReloadClass;
using godo::core::config_schema::ValueType;

// JSON-string escape for the small ASCII subset we accept. Backslash
// and double-quote get escaped; other ASCII passes through. Mirrors
// uds/json_mini.cpp's input-side rejection (no backslash on the wire).
void append_json_string(std::string& out, std::string_view s) {
    out.push_back('"');
    for (char c : s) {
        if (c == '"' || c == '\\') out.push_back('\\');
        out.push_back(c);
    }
    out.push_back('"');
}

// Read the current effective value of a Config field by schema name.
// Returns the value as a typed variant via `is_int` / `out_int` /
// `out_double` / `out_string`. Mirrors apply_one; both must stay in
// sync with config.cpp's apply_toml_file / apply_env / apply_cli.
struct EffectiveValue {
    ValueType   type        = ValueType::String;
    long long   as_int      = 0;
    double      as_double   = 0.0;
    std::string as_string;
};

// Track D-5 — Local CSV parsers, mirroring the ones in core/config.cpp.
// Duplicated (rather than exported) because the config namespace's
// anonymous-namespace helpers stay private; the alternative would be to
// expose them via core/config.hpp, churning that header.
std::vector<double> apply_parse_csv_doubles(std::string_view src) {
    std::vector<double> out;
    std::string token;
    bool any = false;
    auto flush = [&]() {
        std::size_t a = 0, b = token.size();
        while (a < b && std::isspace(static_cast<unsigned char>(token[a]))) ++a;
        while (b > a && std::isspace(static_cast<unsigned char>(token[b - 1]))) --b;
        if (a == b) {
            throw std::runtime_error("schedule has empty entry");
        }
        const std::string trimmed = token.substr(a, b - a);
        char* end = nullptr;
        const double v = std::strtod(trimmed.c_str(), &end);
        if (end == nullptr || *end != '\0') {
            throw std::runtime_error("schedule entry not a valid number: " + trimmed);
        }
        out.push_back(v);
        token.clear();
    };
    for (char c : src) {
        if (c == ',') { flush(); any = true; }
        else { token.push_back(c); any = true; }
    }
    if (!any) throw std::runtime_error("schedule must be non-empty");
    flush();
    return out;
}

std::vector<double> apply_parse_csv_doubles_with_sentinel(std::string_view src) {
    std::vector<double> out;
    std::string token;
    bool any = false;
    bool first = true;
    auto flush = [&]() {
        std::size_t a = 0, b = token.size();
        while (a < b && std::isspace(static_cast<unsigned char>(token[a]))) ++a;
        while (b > a && std::isspace(static_cast<unsigned char>(token[b - 1]))) --b;
        if (a == b) {
            throw std::runtime_error("schedule has empty entry");
        }
        const std::string trimmed = token.substr(a, b - a);
        if (first) {
            if (trimmed != "-") {
                throw std::runtime_error("first entry must be sentinel '-'");
            }
            out.push_back(std::numeric_limits<double>::quiet_NaN());
            first = false;
        } else {
            char* end = nullptr;
            const double v = std::strtod(trimmed.c_str(), &end);
            if (end == nullptr || *end != '\0') {
                throw std::runtime_error("schedule entry not a valid number: " + trimmed);
            }
            if (!(v > 0.0)) {
                throw std::runtime_error("schedule entry must be > 0: " + trimmed);
            }
            out.push_back(v);
        }
        token.clear();
    };
    for (char c : src) {
        if (c == ',') { flush(); any = true; }
        else { token.push_back(c); any = true; }
    }
    if (!any) throw std::runtime_error("schedule must be non-empty");
    flush();
    return out;
}

// Track D-5 — Render an annealing schedule (CSV doubles or sentinel-aware)
// back to its operator-readable string form. Mirrors the parser side in
// core/config.cpp's parse_csv_doubles_or_throw /
// parse_csv_doubles_with_sentinel_or_throw.
std::string format_schedule_csv(const std::vector<double>& vec) {
    std::string out;
    for (std::size_t i = 0; i < vec.size(); ++i) {
        if (i > 0) out.push_back(',');
        char buf[64];
        const int n = std::snprintf(buf, sizeof(buf), "%.9g", vec[i]);
        if (n > 0) out.append(buf, static_cast<std::size_t>(n));
    }
    return out;
}

std::string format_schedule_csv_sentinel(const std::vector<double>& vec) {
    std::string out;
    for (std::size_t i = 0; i < vec.size(); ++i) {
        if (i > 0) out.push_back(',');
        if (i == 0 || std::isnan(vec[i])) {
            out.push_back('-');
        } else {
            char buf[64];
            const int n = std::snprintf(buf, sizeof(buf), "%.9g", vec[i]);
            if (n > 0) out.append(buf, static_cast<std::size_t>(n));
        }
    }
    return out;
}

EffectiveValue read_effective(const Config& c, const ConfigSchemaRow& row) {
    EffectiveValue v;
    v.type = row.type;
    const std::string_view k = row.name;
    // Sections by alphabetical name — matches the schema ordering.
    if      (k == "amcl.anneal_iters_per_phase")     v.as_int    = c.amcl_anneal_iters_per_phase;
    else if (k == "amcl.converge_xy_std_m")          v.as_double = c.amcl_converge_xy_std_m;
    else if (k == "amcl.converge_yaw_std_deg")       v.as_double = c.amcl_converge_yaw_std_deg;
    else if (k == "amcl.downsample_stride")          v.as_int    = c.amcl_downsample_stride;
    else if (k == "amcl.hint_sigma_xy_m_default")    v.as_double = c.amcl_hint_sigma_xy_m_default;
    else if (k == "amcl.hint_sigma_yaw_deg_default") v.as_double = c.amcl_hint_sigma_yaw_deg_default;
    // issue#5 — Live pipelined-hint kernel keys. Bool-as-Int wire shape
    // for live_carry_pose_as_hint: true → 1, false → 0.
    else if (k == "amcl.live_carry_pose_as_hint")    v.as_int    = c.live_carry_pose_as_hint ? 1 : 0;
    else if (k == "amcl.live_carry_schedule_m")      v.as_string = format_schedule_csv(c.amcl_live_carry_schedule_m);
    else if (k == "amcl.live_carry_sigma_xy_m")      v.as_double = c.amcl_live_carry_sigma_xy_m;
    else if (k == "amcl.live_carry_sigma_yaw_deg")   v.as_double = c.amcl_live_carry_sigma_yaw_deg;
    else if (k == "amcl.map_path")                   v.as_string = c.amcl_map_path;
    else if (k == "amcl.max_iters")                  v.as_int    = c.amcl_max_iters;
    else if (k == "amcl.origin_x_m")                 v.as_double = c.amcl_origin_x_m;
    else if (k == "amcl.origin_y_m")                 v.as_double = c.amcl_origin_y_m;
    else if (k == "amcl.origin_yaw_deg")             v.as_double = c.amcl_origin_yaw_deg;
    else if (k == "amcl.particles_global_n")         v.as_int    = c.amcl_particles_global_n;
    else if (k == "amcl.particles_local_n")          v.as_int    = c.amcl_particles_local_n;
    else if (k == "amcl.range_max_m")                v.as_double = c.amcl_range_max_m;
    else if (k == "amcl.range_min_m")                v.as_double = c.amcl_range_min_m;
    else if (k == "amcl.sigma_hit_m")                v.as_double = c.amcl_sigma_hit_m;
    else if (k == "amcl.sigma_hit_schedule_m")       v.as_string = format_schedule_csv(c.amcl_sigma_hit_schedule_m);
    else if (k == "amcl.sigma_seed_xy_m")            v.as_double = c.amcl_sigma_seed_xy_m;
    else if (k == "amcl.sigma_seed_xy_schedule_m")   v.as_string = format_schedule_csv_sentinel(c.amcl_sigma_seed_xy_schedule_m);
    else if (k == "amcl.sigma_seed_yaw_deg")         v.as_double = c.amcl_sigma_seed_yaw_deg;
    else if (k == "amcl.sigma_xy_jitter_live_m")     v.as_double = c.amcl_sigma_xy_jitter_live_m;
    else if (k == "amcl.sigma_xy_jitter_m")          v.as_double = c.amcl_sigma_xy_jitter_m;
    else if (k == "amcl.sigma_yaw_jitter_deg")       v.as_double = c.amcl_sigma_yaw_jitter_deg;
    else if (k == "amcl.sigma_yaw_jitter_live_deg")  v.as_double = c.amcl_sigma_yaw_jitter_live_deg;
    else if (k == "amcl.trigger_poll_ms")            v.as_int    = c.amcl_trigger_poll_ms;
    else if (k == "amcl.yaw_tripwire_deg")           v.as_double = c.amcl_yaw_tripwire_deg;
    else if (k == "gpio.calibrate_pin")              v.as_int    = c.gpio_calibrate_pin;
    else if (k == "gpio.live_toggle_pin")            v.as_int    = c.gpio_live_toggle_pin;
    else if (k == "ipc.uds_socket")                  v.as_string = c.uds_socket;
    else if (k == "network.ue_host")                 v.as_string = c.ue_host;
    else if (k == "network.ue_port")                 v.as_int    = c.ue_port;
    else if (k == "rt.cpu")                          v.as_int    = c.rt_cpu;
    else if (k == "rt.priority")                     v.as_int    = c.rt_priority;
    else if (k == "serial.freed_baud")               v.as_int    = c.freed_baud;
    else if (k == "serial.freed_port")               v.as_string = c.freed_port;
    else if (k == "serial.lidar_baud")               v.as_int    = c.lidar_baud;
    else if (k == "serial.lidar_port")               v.as_string = c.lidar_port;
    else if (k == "serial.lidar_udev_serial")        v.as_string = c.lidar_udev_serial;
    else if (k == "smoother.deadband_deg")           v.as_double = c.deadband_deg;
    else if (k == "smoother.deadband_mm")            v.as_double = c.deadband_mm;
    else if (k == "smoother.divergence_deg")         v.as_double = c.divergence_deg;
    else if (k == "smoother.divergence_mm")          v.as_double = c.divergence_mm;
    else if (k == "smoother.t_ramp_ms")              v.as_int    = c.t_ramp_ns / 1'000'000LL;
    // issue#12 — webctl-owned schema rows. Tracker stores the value
    // verbatim and emits it back through render_toml; no tracker logic
    // path consumes it. See production/RPi5/CODEBASE.md invariant (r).
    else if (k == "webctl.pose_stream_hz")           v.as_int    = c.webctl_pose_stream_hz;
    else if (k == "webctl.scan_stream_hz")           v.as_int    = c.webctl_scan_stream_hz;
    // issue#14 Maj-1 / issue#16.1 — webctl-owned mapping-stop timing ladder.
    else if (k == "webctl.mapping_docker_stop_grace_s")          v.as_int = c.webctl_mapping_docker_stop_grace_s;
    else if (k == "webctl.mapping_systemctl_subprocess_timeout_s") v.as_int = c.webctl_mapping_systemctl_subprocess_timeout_s;
    else if (k == "webctl.mapping_systemd_stop_timeout_s")        v.as_int = c.webctl_mapping_systemd_stop_timeout_s;
    else if (k == "webctl.mapping_webctl_stop_timeout_s")         v.as_int = c.webctl_mapping_webctl_stop_timeout_s;
    // issue#27 — final-output transform + OriginPicker step.
    else if (k == "origin_step.x_m")                              v.as_double = c.origin_step_x_m;
    else if (k == "origin_step.y_m")                              v.as_double = c.origin_step_y_m;
    else if (k == "origin_step.yaw_deg")                          v.as_double = c.origin_step_yaw_deg;
    else if (k == "output_transform.x_offset_m")                  v.as_double = c.output_transform_x_offset_m;
    else if (k == "output_transform.y_offset_m")                  v.as_double = c.output_transform_y_offset_m;
    else if (k == "output_transform.z_offset_m")                  v.as_double = c.output_transform_z_offset_m;
    else if (k == "output_transform.pan_offset_deg")              v.as_double = c.output_transform_pan_offset_deg;
    else if (k == "output_transform.tilt_offset_deg")             v.as_double = c.output_transform_tilt_offset_deg;
    else if (k == "output_transform.roll_offset_deg")             v.as_double = c.output_transform_roll_offset_deg;
    else if (k == "output_transform.x_sign")                      v.as_int    = c.output_transform_x_sign;
    else if (k == "output_transform.y_sign")                      v.as_int    = c.output_transform_y_sign;
    else if (k == "output_transform.z_sign")                      v.as_int    = c.output_transform_z_sign;
    else if (k == "output_transform.pan_sign")                    v.as_int    = c.output_transform_pan_sign;
    else if (k == "output_transform.tilt_sign")                   v.as_int    = c.output_transform_tilt_sign;
    else if (k == "output_transform.roll_sign")                   v.as_int    = c.output_transform_roll_sign;
    return v;
}

// Apply a validated value to the staging Config. Mirrors read_effective
// (1:1 mapping). Returns true if applied; false on internal mismatch
// (which would indicate a schema-vs-Config drift bug).
bool apply_one(Config& c,
               const ConfigSchemaRow& row,
               const ValidateResult& vr) {
    const std::string_view k = row.name;
    if      (k == "amcl.anneal_iters_per_phase")     c.amcl_anneal_iters_per_phase     = static_cast<int>(vr.parsed_double);
    else if (k == "amcl.converge_xy_std_m")          c.amcl_converge_xy_std_m          = vr.parsed_double;
    else if (k == "amcl.converge_yaw_std_deg")       c.amcl_converge_yaw_std_deg       = vr.parsed_double;
    else if (k == "amcl.downsample_stride")          c.amcl_downsample_stride          = static_cast<int>(vr.parsed_double);
    else if (k == "amcl.hint_sigma_xy_m_default")    c.amcl_hint_sigma_xy_m_default    = vr.parsed_double;
    else if (k == "amcl.hint_sigma_yaw_deg_default") c.amcl_hint_sigma_yaw_deg_default = vr.parsed_double;
    // issue#5 — Live pipelined-hint kernel keys.
    else if (k == "amcl.live_carry_pose_as_hint")    c.live_carry_pose_as_hint         = (static_cast<int>(vr.parsed_double) != 0);
    else if (k == "amcl.live_carry_schedule_m")      c.amcl_live_carry_schedule_m      = apply_parse_csv_doubles(vr.parsed_string);
    else if (k == "amcl.live_carry_sigma_xy_m")      c.amcl_live_carry_sigma_xy_m      = vr.parsed_double;
    else if (k == "amcl.live_carry_sigma_yaw_deg")   c.amcl_live_carry_sigma_yaw_deg   = vr.parsed_double;
    else if (k == "amcl.map_path")                   c.amcl_map_path                   = vr.parsed_string;
    else if (k == "amcl.max_iters")                  c.amcl_max_iters                  = static_cast<int>(vr.parsed_double);
    else if (k == "amcl.origin_x_m")                 c.amcl_origin_x_m                 = vr.parsed_double;
    else if (k == "amcl.origin_y_m")                 c.amcl_origin_y_m                 = vr.parsed_double;
    else if (k == "amcl.origin_yaw_deg")             c.amcl_origin_yaw_deg             = vr.parsed_double;
    else if (k == "amcl.particles_global_n")         c.amcl_particles_global_n         = static_cast<int>(vr.parsed_double);
    else if (k == "amcl.particles_local_n")          c.amcl_particles_local_n          = static_cast<int>(vr.parsed_double);
    else if (k == "amcl.range_max_m")                c.amcl_range_max_m                = vr.parsed_double;
    else if (k == "amcl.range_min_m")                c.amcl_range_min_m                = vr.parsed_double;
    else if (k == "amcl.sigma_hit_m")                c.amcl_sigma_hit_m                = vr.parsed_double;
    else if (k == "amcl.sigma_hit_schedule_m")       c.amcl_sigma_hit_schedule_m       = apply_parse_csv_doubles(vr.parsed_string);
    else if (k == "amcl.sigma_seed_xy_m")            c.amcl_sigma_seed_xy_m            = vr.parsed_double;
    else if (k == "amcl.sigma_seed_xy_schedule_m")   c.amcl_sigma_seed_xy_schedule_m   = apply_parse_csv_doubles_with_sentinel(vr.parsed_string);
    else if (k == "amcl.sigma_seed_yaw_deg")         c.amcl_sigma_seed_yaw_deg         = vr.parsed_double;
    else if (k == "amcl.sigma_xy_jitter_live_m")     c.amcl_sigma_xy_jitter_live_m     = vr.parsed_double;
    else if (k == "amcl.sigma_xy_jitter_m")          c.amcl_sigma_xy_jitter_m          = vr.parsed_double;
    else if (k == "amcl.sigma_yaw_jitter_deg")       c.amcl_sigma_yaw_jitter_deg       = vr.parsed_double;
    else if (k == "amcl.sigma_yaw_jitter_live_deg")  c.amcl_sigma_yaw_jitter_live_deg  = vr.parsed_double;
    else if (k == "amcl.trigger_poll_ms")            c.amcl_trigger_poll_ms            = static_cast<int>(vr.parsed_double);
    else if (k == "amcl.yaw_tripwire_deg")           c.amcl_yaw_tripwire_deg           = vr.parsed_double;
    else if (k == "gpio.calibrate_pin")              c.gpio_calibrate_pin              = static_cast<int>(vr.parsed_double);
    else if (k == "gpio.live_toggle_pin")            c.gpio_live_toggle_pin            = static_cast<int>(vr.parsed_double);
    else if (k == "ipc.uds_socket")                  c.uds_socket                      = vr.parsed_string;
    else if (k == "network.ue_host")                 c.ue_host                         = vr.parsed_string;
    else if (k == "network.ue_port")                 c.ue_port                         = static_cast<int>(vr.parsed_double);
    else if (k == "rt.cpu")                          c.rt_cpu                          = static_cast<int>(vr.parsed_double);
    else if (k == "rt.priority")                     c.rt_priority                     = static_cast<int>(vr.parsed_double);
    else if (k == "serial.freed_baud")               c.freed_baud                      = static_cast<int>(vr.parsed_double);
    else if (k == "serial.freed_port")               c.freed_port                      = vr.parsed_string;
    else if (k == "serial.lidar_baud")               c.lidar_baud                      = static_cast<int>(vr.parsed_double);
    else if (k == "serial.lidar_port")               c.lidar_port                      = vr.parsed_string;
    else if (k == "serial.lidar_udev_serial")        c.lidar_udev_serial               = vr.parsed_string;
    else if (k == "smoother.deadband_deg")           c.deadband_deg                    = vr.parsed_double;
    else if (k == "smoother.deadband_mm")            c.deadband_mm                     = vr.parsed_double;
    else if (k == "smoother.divergence_deg")         c.divergence_deg                  = vr.parsed_double;
    else if (k == "smoother.divergence_mm")          c.divergence_mm                   = vr.parsed_double;
    else if (k == "smoother.t_ramp_ms")              c.t_ramp_ns                       = static_cast<long long>(vr.parsed_double) * 1'000'000LL;
    // issue#12 — webctl-owned schema rows.
    else if (k == "webctl.pose_stream_hz")           c.webctl_pose_stream_hz           = static_cast<int>(vr.parsed_double);
    else if (k == "webctl.scan_stream_hz")           c.webctl_scan_stream_hz           = static_cast<int>(vr.parsed_double);
    // issue#14 Maj-1 / issue#16.1 — webctl-owned mapping-stop timing ladder.
    else if (k == "webctl.mapping_docker_stop_grace_s")          c.webctl_mapping_docker_stop_grace_s          = static_cast<int>(vr.parsed_double);
    else if (k == "webctl.mapping_systemctl_subprocess_timeout_s") c.webctl_mapping_systemctl_subprocess_timeout_s = static_cast<int>(vr.parsed_double);
    else if (k == "webctl.mapping_systemd_stop_timeout_s")        c.webctl_mapping_systemd_stop_timeout_s        = static_cast<int>(vr.parsed_double);
    else if (k == "webctl.mapping_webctl_stop_timeout_s")         c.webctl_mapping_webctl_stop_timeout_s         = static_cast<int>(vr.parsed_double);
    // issue#27 — final-output transform + OriginPicker step.
    else if (k == "origin_step.x_m")                              c.origin_step_x_m   = vr.parsed_double;
    else if (k == "origin_step.y_m")                              c.origin_step_y_m   = vr.parsed_double;
    else if (k == "origin_step.yaw_deg")                          c.origin_step_yaw_deg = vr.parsed_double;
    else if (k == "output_transform.x_offset_m")                  c.output_transform_x_offset_m    = vr.parsed_double;
    else if (k == "output_transform.y_offset_m")                  c.output_transform_y_offset_m    = vr.parsed_double;
    else if (k == "output_transform.z_offset_m")                  c.output_transform_z_offset_m    = vr.parsed_double;
    else if (k == "output_transform.pan_offset_deg")              c.output_transform_pan_offset_deg  = vr.parsed_double;
    else if (k == "output_transform.tilt_offset_deg")             c.output_transform_tilt_offset_deg = vr.parsed_double;
    else if (k == "output_transform.roll_offset_deg")             c.output_transform_roll_offset_deg = vr.parsed_double;
    else if (k == "output_transform.x_sign")                      c.output_transform_x_sign         = static_cast<int>(vr.parsed_double);
    else if (k == "output_transform.y_sign")                      c.output_transform_y_sign         = static_cast<int>(vr.parsed_double);
    else if (k == "output_transform.z_sign")                      c.output_transform_z_sign         = static_cast<int>(vr.parsed_double);
    else if (k == "output_transform.pan_sign")                    c.output_transform_pan_sign       = static_cast<int>(vr.parsed_double);
    else if (k == "output_transform.tilt_sign")                   c.output_transform_tilt_sign      = static_cast<int>(vr.parsed_double);
    else if (k == "output_transform.roll_sign")                   c.output_transform_roll_sign      = static_cast<int>(vr.parsed_double);
    else                                             return false;
    return true;
}

// Split "section.leaf" into the two halves on the first dot. Schema
// guarantees exactly one dot per name.
void split_section(std::string_view name,
                   std::string_view& section,
                   std::string_view& leaf) noexcept {
    const auto dot = name.find('.');
    section = name.substr(0, dot);
    leaf    = name.substr(dot + 1);
}

void append_int(std::string& out, long long v) {
    char buf[32];
    const int n = std::snprintf(buf, sizeof(buf), "%lld", v);
    if (n > 0) out.append(buf, static_cast<std::size_t>(n));
}

void append_double(std::string& out, double v) {
    // %.9g — round-trip-safe for double; matches operator-readable form.
    char buf[64];
    const int n = std::snprintf(buf, sizeof(buf), "%.9g", v);
    if (n > 0) out.append(buf, static_cast<std::size_t>(n));
}

}  // namespace

std::string render_toml(const Config& cfg) {
    // Group rows by section so the rendered TOML is operator-readable.
    // Schema is alphabetical by full name; alphabetical sections fall
    // out naturally (amcl < gpio < ipc < network < rt < serial <
    // smoother). Within each section we keep schema row order.
    std::string out;
    out.reserve(2048);

    std::string_view current_section;
    for (const auto& row : CONFIG_SCHEMA) {
        std::string_view section, leaf;
        split_section(row.name, section, leaf);

        if (section != current_section) {
            if (!current_section.empty()) out.push_back('\n');
            out.append("[");
            out.append(section);
            out.append("]\n");
            current_section = section;
        }

        out.append(leaf);
        out.append(" = ");

        const EffectiveValue v = read_effective(cfg, row);
        switch (v.type) {
            case ValueType::Int:
                append_int(out, v.as_int);
                break;
            case ValueType::Double:
                append_double(out, v.as_double);
                break;
            case ValueType::String:
                out.push_back('"');
                for (char c : v.as_string) {
                    if (c == '"' || c == '\\') out.push_back('\\');
                    out.push_back(c);
                }
                out.push_back('"');
                break;
        }
        out.push_back('\n');
    }
    return out;
}

ApplyResult apply_set(std::string_view                              key,
                      std::string_view                              value_text,
                      Config&                                       live_cfg,
                      std::mutex&                                   live_cfg_mtx,
                      godo::rt::Seqlock<godo::core::HotConfig>&     hot_seq,
                      const std::filesystem::path&                  toml_path,
                      const std::filesystem::path&                  restart_pending_flag) {
    ApplyResult ar;

    // Step 1 — pure validation.
    const ValidateResult vr = validate(key, value_text);
    if (!vr.ok) {
        ar.err        = vr.err;
        ar.err_detail = vr.err_detail;
        return ar;
    }

    // issue#27 — strict {-1, +1} validator for output_transform.*_sign
    // keys. The schema validator enforces the relaxed [-1, +1] Int range
    // (defence-in-depth: rejects 2 / -2); the strict {-1, +1} (rejecting
    // 0) lives here at the consumer boundary per
    // .claude/memory/feedback_relaxed_validator_strict_installer.md.
    // Zero would silently zero the channel — surely an operator typo.
    if (vr.row != nullptr) {
        const std::string_view name = vr.row->name;
        if (name == "output_transform.x_sign" ||
            name == "output_transform.y_sign" ||
            name == "output_transform.z_sign" ||
            name == "output_transform.pan_sign" ||
            name == "output_transform.tilt_sign" ||
            name == "output_transform.roll_sign") {
            const int sign = static_cast<int>(vr.parsed_double);
            if (sign != -1 && sign != 1) {
                ar.err        = "bad_value";
                ar.err_detail.assign(name);
                ar.err_detail.append(": sign must be -1 or +1 (got ");
                ar.err_detail.append(std::to_string(sign));
                ar.err_detail.append(")");
                return ar;
            }
        }
    }

    // Steps 2–6 under the live_cfg mutex.
    std::lock_guard<std::mutex> lock(live_cfg_mtx);

    Config staging = live_cfg;
    try {
        if (!apply_one(staging, *vr.row, vr)) {
            // Schema↔Config drift — should be caught by parity test.
            ar.err        = "internal_error";
            ar.err_detail = "schema row has no Config applicator: ";
            ar.err_detail.append(vr.row->name);
            return ar;
        }
    } catch (const std::exception& e) {
        // Track D-5: schedule-key parse failures throw out of apply_one.
        // Map to bad_value so the operator gets an actionable message.
        ar.err        = "bad_value";
        ar.err_detail = vr.row->name;
        ar.err_detail.append(": ");
        ar.err_detail.append(e.what());
        return ar;
    }

    // Track D-5: re-validate amcl-schedule cross-field invariants
    // (length match, monotonicity) before commit. validate_amcl in
    // core/config.cpp would catch these on the next Config::load, but
    // operator-set keys must reject inconsistent payloads at apply time.
    if (vr.row->name == "amcl.sigma_hit_schedule_m" ||
        vr.row->name == "amcl.sigma_seed_xy_schedule_m") {
        if (staging.amcl_sigma_hit_schedule_m.size() !=
            staging.amcl_sigma_seed_xy_schedule_m.size()) {
            ar.err        = "bad_value";
            ar.err_detail = vr.row->name;
            ar.err_detail.append(": schedule length must match the paired "
                                 "sigma_*_schedule_m key");
            return ar;
        }
        // Monotonic-decreasing check on sigma_hit_schedule.
        for (std::size_t i = 1;
             i < staging.amcl_sigma_hit_schedule_m.size();
             ++i) {
            const double prev = staging.amcl_sigma_hit_schedule_m[i - 1];
            const double curr = staging.amcl_sigma_hit_schedule_m[i];
            if (!(curr < prev)) {
                ar.err        = "bad_value";
                ar.err_detail = "amcl.sigma_hit_schedule_m: must be "
                                "strictly monotonically decreasing";
                return ar;
            }
            if (!(curr >= 0.005) || !(curr <= 5.0)) {
                ar.err        = "bad_value";
                ar.err_detail = "amcl.sigma_hit_schedule_m: each entry must "
                                "be in [0.005, 5.0]";
                return ar;
            }
        }
        if (!staging.amcl_sigma_hit_schedule_m.empty()) {
            const double v0 = staging.amcl_sigma_hit_schedule_m[0];
            if (!(v0 >= 0.005) || !(v0 <= 5.0)) {
                ar.err        = "bad_value";
                ar.err_detail = "amcl.sigma_hit_schedule_m: each entry must "
                                "be in [0.005, 5.0]";
                return ar;
            }
        }
    }

    // issue#5: cross-field check for the Live carry schedule. Same
    // monotonic-decreasing + per-entry range rules as the OneShot
    // sigma_hit_schedule_m, applied at apply time so an inconsistent
    // edit is rejected without waiting for the next Config::load.
    if (vr.row->name == "amcl.live_carry_schedule_m") {
        if (staging.amcl_live_carry_schedule_m.empty()) {
            ar.err        = "bad_value";
            ar.err_detail = "amcl.live_carry_schedule_m: must be non-empty";
            return ar;
        }
        for (std::size_t i = 0;
             i < staging.amcl_live_carry_schedule_m.size();
             ++i) {
            const double curr = staging.amcl_live_carry_schedule_m[i];
            if (!(curr >= 0.005) || !(curr <= 5.0)) {
                ar.err        = "bad_value";
                ar.err_detail = "amcl.live_carry_schedule_m: each entry must "
                                "be in [0.005, 5.0]";
                return ar;
            }
            if (i > 0) {
                const double prev = staging.amcl_live_carry_schedule_m[i - 1];
                if (!(curr < prev)) {
                    ar.err        = "bad_value";
                    ar.err_detail = "amcl.live_carry_schedule_m: must be "
                                    "strictly monotonically decreasing";
                    return ar;
                }
            }
        }
    }

    // issue#14 Mode-B M1 fix (2026-05-02 KST) — cross-trio ordering
    // invariant for the webctl mapping-stop timing ladder. The schema
    // ranges overlap ([10,60]/[20,90]/[25,120]); without this check at
    // apply time, an operator can save `docker=60, systemd=20` via the
    // Config tab. Each individual row passes its range check, the
    // tracker writes the inverted trio to tracker.toml, and the next
    // webctl boot's read_webctl_section() raises WebctlTomlError →
    // crash loop, recoverable only via SSH + manual file edit.
    //
    // Same enforcement also lives at Config::load (validate_webctl_ladder
    // in core/config.cpp) so a hand-edited tracker.toml catches at next
    // Config::load. Apply-time + load-time = belt-and-suspenders.
    if (vr.row->name == "webctl.mapping_docker_stop_grace_s" ||
        vr.row->name == "webctl.mapping_systemctl_subprocess_timeout_s" ||
        vr.row->name == "webctl.mapping_systemd_stop_timeout_s" ||
        vr.row->name == "webctl.mapping_webctl_stop_timeout_s") {
        const int docker_s    = staging.webctl_mapping_docker_stop_grace_s;
        const int systemctl_s = staging.webctl_mapping_systemctl_subprocess_timeout_s;
        const int systemd_s   = staging.webctl_mapping_systemd_stop_timeout_s;
        const int webctl_s    = staging.webctl_mapping_webctl_stop_timeout_s;
        if (!(docker_s < systemd_s)) {
            ar.err        = "bad_value";
            ar.err_detail = "webctl.mapping ladder: docker_stop_grace_s ("
                          + std::to_string(docker_s)
                          + ") must be < systemd_stop_timeout_s ("
                          + std::to_string(systemd_s) + ")";
            return ar;
        }
        if (!(systemd_s < webctl_s)) {
            ar.err        = "bad_value";
            ar.err_detail = "webctl.mapping ladder: systemd_stop_timeout_s ("
                          + std::to_string(systemd_s)
                          + ") must be < webctl_stop_timeout_s ("
                          + std::to_string(webctl_s) + ")";
            return ar;
        }
        // issue#16.1 — systemctl_subprocess deadline must nest inside
        // the webctl coordinator's overall poll deadline.
        if (!(systemctl_s < webctl_s)) {
            ar.err        = "bad_value";
            ar.err_detail = "webctl.mapping ladder: systemctl_subprocess_timeout_s ("
                          + std::to_string(systemctl_s)
                          + ") must be < webctl_stop_timeout_s ("
                          + std::to_string(webctl_s) + ")";
            return ar;
        }
    }

    const std::string body = render_toml(staging);
    const WriteResult wr = write_atomic(toml_path, body);
    if (wr.outcome != WriteOutcome::Ok) {
        ar.err        = "write_failed";
        ar.err_detail.assign(outcome_to_string(wr.outcome));
        if (wr.errno_capture != 0) {
            ar.err_detail.append(": ");
            ar.err_detail.append(std::strerror(wr.errno_capture));
        }
        return ar;
    }

    live_cfg = staging;
    ar.reload_class = vr.row->reload_class;
    ar.ok = true;

    if (vr.row->reload_class == ReloadClass::Hot) {
        // [hot-config-publisher-grep]: this is the SOLE production
        // call site for hot_seq.store(). main.cpp does the boot init
        // (allow-listed in the grep).
        godo::core::HotConfig snap = godo::core::snapshot_hot(live_cfg);
        snap.published_mono_ns =
            static_cast<std::uint64_t>(godo::rt::monotonic_ns());
        hot_seq.store(snap);
    } else {
        touch_pending_flag(restart_pending_flag);
    }

    return ar;
}

std::string apply_get_all(Config& live_cfg, std::mutex& live_cfg_mtx) {
    // Snapshot under lock; format outside lock.
    Config snapshot;
    {
        std::lock_guard<std::mutex> lock(live_cfg_mtx);
        snapshot = live_cfg;
    }

    std::string out;
    out.reserve(2048);
    out.push_back('{');
    bool first = true;
    for (const auto& row : CONFIG_SCHEMA) {
        if (!first) out.push_back(',');
        first = false;
        append_json_string(out, row.name);
        out.push_back(':');
        const EffectiveValue v = read_effective(snapshot, row);
        switch (v.type) {
            case ValueType::Int:    append_int(out, v.as_int);       break;
            case ValueType::Double: append_double(out, v.as_double); break;
            case ValueType::String: append_json_string(out, v.as_string); break;
        }
    }
    out.push_back('}');
    return out;
}

std::string apply_get_schema() {
    std::string out;
    out.reserve(8192);
    out.push_back('[');
    bool first = true;
    for (const auto& row : CONFIG_SCHEMA) {
        if (!first) out.push_back(',');
        first = false;
        out.push_back('{');
        append_json_string(out, "name");
        out.push_back(':');
        append_json_string(out, row.name);
        out.push_back(',');

        append_json_string(out, "type");
        out.push_back(':');
        append_json_string(out,
            godo::core::config_schema::value_type_to_string(row.type));
        out.push_back(',');

        append_json_string(out, "min");
        out.push_back(':');
        append_double(out, row.min_d);
        out.push_back(',');

        append_json_string(out, "max");
        out.push_back(':');
        append_double(out, row.max_d);
        out.push_back(',');

        append_json_string(out, "default");
        out.push_back(':');
        append_json_string(out, row.default_repr);
        out.push_back(',');

        append_json_string(out, "reload_class");
        out.push_back(':');
        append_json_string(out,
            godo::core::config_schema::reload_class_to_string(row.reload_class));
        out.push_back(',');

        append_json_string(out, "description");
        out.push_back(':');
        append_json_string(out, row.description);
        out.push_back('}');
    }
    out.push_back(']');
    return out;
}

}  // namespace godo::config
