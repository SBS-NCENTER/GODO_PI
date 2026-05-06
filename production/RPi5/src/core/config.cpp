#include "config.hpp"

#include <cctype>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <functional>
#include <limits>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include <toml++/toml.hpp>

#include "config_defaults.hpp"
#include "constants.hpp"

namespace godo::core {

namespace {

namespace cfg_defaults = godo::config::defaults;

// Forward declarations for CSV parsers used by apply_toml_file before
// their definitions (Track D-5).
std::vector<double> parse_csv_doubles_or_throw(std::string_view src,
                                               std::string_view key);
std::vector<double> parse_csv_doubles_with_sentinel_or_throw(
    std::string_view src, std::string_view key);

// Allowed TOML keys, flat "section.key" form. Unknown → error.
const std::set<std::string>& allowed_keys() {
    static const std::set<std::string> k = {
        "network.ue_host",
        "network.ue_port",
        "serial.lidar_port",
        "serial.lidar_udev_serial",
        "serial.lidar_baud",
        "serial.freed_port",
        "serial.freed_baud",
        "smoother.t_ramp_ms",
        "smoother.deadband_mm",
        "smoother.deadband_deg",
        "smoother.divergence_mm",
        "smoother.divergence_deg",
        "rt.cpu",
        "rt.priority",
        "ipc.uds_socket",
        "ipc.tracker_pidfile",
        "amcl.map_path",
        "amcl.origin_x_m",
        "amcl.origin_y_m",
        "amcl.particles_global_n",
        "amcl.particles_local_n",
        "amcl.max_iters",
        "amcl.sigma_hit_m",
        "amcl.sigma_xy_jitter_m",
        "amcl.sigma_yaw_jitter_deg",
        "amcl.sigma_seed_xy_m",
        "amcl.sigma_seed_yaw_deg",
        "amcl.downsample_stride",
        "amcl.range_min_m",
        "amcl.range_max_m",
        "amcl.converge_xy_std_m",
        "amcl.converge_yaw_std_deg",
        "amcl.yaw_tripwire_deg",
        "amcl.trigger_poll_ms",
        "amcl.seed",
        "amcl.sigma_xy_jitter_live_m",
        "amcl.sigma_yaw_jitter_live_deg",
        "amcl.sigma_hit_schedule_m",
        "amcl.sigma_seed_xy_schedule_m",
        "amcl.anneal_iters_per_phase",
        "amcl.parallel_eval_workers",
        "amcl.hint_sigma_xy_m_default",
        "amcl.hint_sigma_yaw_deg_default",
        "amcl.live_carry_pose_as_hint",
        "amcl.live_carry_schedule_m",
        "amcl.live_carry_sigma_xy_m",
        "amcl.live_carry_sigma_yaw_deg",
        "gpio.calibrate_pin",
        "gpio.live_toggle_pin",
        // issue#12 — webctl-owned schema rows. Tracker validates these
        // here so toml++ does not throw on unknown-key, then stores
        // them via apply_one + emits via read_effective + render_toml,
        // but no tracker logic path consumes the value. webctl reads
        // /var/lib/godo/tracker.toml directly via webctl_toml.py. See
        // production/RPi5/CODEBASE.md invariant (r).
        "webctl.pose_stream_hz",
        "webctl.scan_stream_hz",
        // issue#14 Maj-1 — webctl-owned mapping-stop timing ladder.
        // Same ownership pattern as pose/scan_stream_hz: tracker stores
        // verbatim, webctl is the sole consumer (install.sh seds the
        // docker + systemd values into the unit file; mapping.py reads
        // the webctl deadline at stop time).
        "webctl.mapping_docker_stop_grace_s",
        "webctl.mapping_systemctl_subprocess_timeout_s",
        "webctl.mapping_systemd_stop_timeout_s",
        "webctl.mapping_webctl_stop_timeout_s",
        // issue#27 — final-output transform (12 rows) + OriginPicker
        // step (3 rows). The transform rows are consumed by Thread D's
        // `apply_output_transform_inplace`; the origin_step rows are
        // frontend-only consumers (SPA's <OriginPicker/> +/- buttons).
        "origin_step.x_m",
        "origin_step.y_m",
        "origin_step.yaw_deg",
        "output_transform.x_offset_m",
        "output_transform.y_offset_m",
        "output_transform.z_offset_m",
        "output_transform.pan_offset_deg",
        "output_transform.tilt_offset_deg",
        "output_transform.roll_offset_deg",
        "output_transform.x_sign",
        "output_transform.y_sign",
        "output_transform.z_sign",
        "output_transform.pan_sign",
        "output_transform.tilt_sign",
        "output_transform.roll_sign",
    };
    return k;
}

void check_unknown_keys(const toml::table& tbl) {
    const auto& allowed = allowed_keys();
    for (auto&& [section_key, section_val] : tbl) {
        if (!section_val.is_table()) {
            throw std::runtime_error(
                std::string("config: top-level key '") +
                std::string(section_key.str()) +
                "' must be a section table");
        }
        const std::string section = std::string(section_key.str());
        for (auto&& [leaf_key, /*unused*/_] : *section_val.as_table()) {
            (void)_;
            const std::string flat = section + "." + std::string(leaf_key.str());
            if (allowed.find(flat) == allowed.end()) {
                throw std::runtime_error(
                    std::string("config: unknown TOML key '") + flat +
                    "'. See SYSTEM_DESIGN.md §11.2 for the accepted set.");
            }
        }
    }
}

void apply_toml_file(Config& c, const std::filesystem::path& path) {
    toml::table tbl;
    try {
        tbl = toml::parse_file(path.string());
    } catch (const toml::parse_error& e) {
        throw std::runtime_error(
            std::string("config: failed to parse '") + path.string() +
            "': " + e.what());
    }
    check_unknown_keys(tbl);

    if (auto v = tbl["network"]["ue_host"].value<std::string>();   v) c.ue_host = *v;
    if (auto v = tbl["network"]["ue_port"].value<int64_t>();       v) c.ue_port = static_cast<int>(*v);

    if (auto v = tbl["serial"]["lidar_port"].value<std::string>(); v) c.lidar_port = *v;
    if (auto v = tbl["serial"]["lidar_udev_serial"].value<std::string>(); v) c.lidar_udev_serial = *v;
    if (auto v = tbl["serial"]["lidar_baud"].value<int64_t>();     v) c.lidar_baud = static_cast<int>(*v);
    if (auto v = tbl["serial"]["freed_port"].value<std::string>(); v) c.freed_port = *v;
    if (auto v = tbl["serial"]["freed_baud"].value<int64_t>();     v) c.freed_baud = static_cast<int>(*v);

    // T_ramp in the TOML is expressed in milliseconds for operator clarity.
    if (auto v = tbl["smoother"]["t_ramp_ms"].value<int64_t>();    v) {
        c.t_ramp_ns = static_cast<std::int64_t>(*v) * 1'000'000LL;
    }
    if (auto v = tbl["smoother"]["deadband_mm"].value<double>();   v) c.deadband_mm   = *v;
    if (auto v = tbl["smoother"]["deadband_deg"].value<double>();  v) c.deadband_deg  = *v;
    if (auto v = tbl["smoother"]["divergence_mm"].value<double>(); v) c.divergence_mm = *v;
    if (auto v = tbl["smoother"]["divergence_deg"].value<double>();v) c.divergence_deg = *v;

    if (auto v = tbl["rt"]["cpu"].value<int64_t>();                v) c.rt_cpu      = static_cast<int>(*v);
    if (auto v = tbl["rt"]["priority"].value<int64_t>();           v) c.rt_priority = static_cast<int>(*v);

    if (auto v = tbl["ipc"]["uds_socket"].value<std::string>();    v) c.uds_socket  = *v;
    if (auto v = tbl["ipc"]["tracker_pidfile"].value<std::string>();v) c.tracker_pidfile = *v;

    if (auto v = tbl["amcl"]["map_path"].value<std::string>();        v) c.amcl_map_path           = *v;
    if (auto v = tbl["amcl"]["origin_x_m"].value<double>();           v) c.amcl_origin_x_m         = *v;
    if (auto v = tbl["amcl"]["origin_y_m"].value<double>();           v) c.amcl_origin_y_m         = *v;
    if (auto v = tbl["amcl"]["particles_global_n"].value<int64_t>();  v) c.amcl_particles_global_n = static_cast<int>(*v);
    if (auto v = tbl["amcl"]["particles_local_n"].value<int64_t>();   v) c.amcl_particles_local_n  = static_cast<int>(*v);
    if (auto v = tbl["amcl"]["max_iters"].value<int64_t>();           v) c.amcl_max_iters          = static_cast<int>(*v);
    if (auto v = tbl["amcl"]["sigma_hit_m"].value<double>();          v) c.amcl_sigma_hit_m        = *v;
    if (auto v = tbl["amcl"]["sigma_xy_jitter_m"].value<double>();    v) c.amcl_sigma_xy_jitter_m  = *v;
    if (auto v = tbl["amcl"]["sigma_yaw_jitter_deg"].value<double>(); v) c.amcl_sigma_yaw_jitter_deg = *v;
    if (auto v = tbl["amcl"]["sigma_seed_xy_m"].value<double>();      v) c.amcl_sigma_seed_xy_m    = *v;
    if (auto v = tbl["amcl"]["sigma_seed_yaw_deg"].value<double>();   v) c.amcl_sigma_seed_yaw_deg = *v;
    if (auto v = tbl["amcl"]["downsample_stride"].value<int64_t>();   v) c.amcl_downsample_stride  = static_cast<int>(*v);
    if (auto v = tbl["amcl"]["range_min_m"].value<double>();          v) c.amcl_range_min_m        = *v;
    if (auto v = tbl["amcl"]["range_max_m"].value<double>();          v) c.amcl_range_max_m        = *v;
    if (auto v = tbl["amcl"]["converge_xy_std_m"].value<double>();    v) c.amcl_converge_xy_std_m  = *v;
    if (auto v = tbl["amcl"]["converge_yaw_std_deg"].value<double>(); v) c.amcl_converge_yaw_std_deg = *v;
    if (auto v = tbl["amcl"]["yaw_tripwire_deg"].value<double>();     v) c.amcl_yaw_tripwire_deg   = *v;
    if (auto v = tbl["amcl"]["trigger_poll_ms"].value<int64_t>();     v) c.amcl_trigger_poll_ms    = static_cast<int>(*v);
    if (auto v = tbl["amcl"]["seed"].value<int64_t>();                v) {
        if (*v < 0) {
            throw std::runtime_error(
                "config: amcl.seed must be non-negative (0 = time-derived)");
        }
        c.amcl_seed = static_cast<std::uint64_t>(*v);
    }
    if (auto v = tbl["amcl"]["sigma_xy_jitter_live_m"].value<double>();    v) c.amcl_sigma_xy_jitter_live_m    = *v;
    if (auto v = tbl["amcl"]["sigma_yaw_jitter_live_deg"].value<double>(); v) c.amcl_sigma_yaw_jitter_live_deg = *v;

    // Track D-5 — annealing keys.
    if (auto v = tbl["amcl"]["sigma_hit_schedule_m"].value<std::string>(); v) {
        c.amcl_sigma_hit_schedule_m =
            parse_csv_doubles_or_throw(*v, "amcl.sigma_hit_schedule_m");
    }
    if (auto v = tbl["amcl"]["sigma_seed_xy_schedule_m"].value<std::string>(); v) {
        c.amcl_sigma_seed_xy_schedule_m =
            parse_csv_doubles_with_sentinel_or_throw(*v,
                "amcl.sigma_seed_xy_schedule_m");
    }
    if (auto v = tbl["amcl"]["anneal_iters_per_phase"].value<int64_t>();   v) {
        c.amcl_anneal_iters_per_phase = static_cast<int>(*v);
    }
    // issue#11 — fork-join particle eval pool workers.
    if (auto v = tbl["amcl"]["parallel_eval_workers"].value<int64_t>();   v) {
        c.amcl_parallel_eval_workers = static_cast<int>(*v);
    }
    // issue#3 — hint-σ defaults.
    if (auto v = tbl["amcl"]["hint_sigma_xy_m_default"].value<double>();   v) {
        c.amcl_hint_sigma_xy_m_default = *v;
    }
    if (auto v = tbl["amcl"]["hint_sigma_yaw_deg_default"].value<double>(); v) {
        c.amcl_hint_sigma_yaw_deg_default = *v;
    }

    // issue#5 — Live pipelined-hint kernel selector + per-tick σ + schedule.
    // Bool-as-Int wire shape: TOML bool true/false maps to 1/0. Accept both
    // bool and int so operator-friendly `live_carry_pose_as_hint = true`
    // works identically to a raw `1`.
    if (auto vb = tbl["amcl"]["live_carry_pose_as_hint"].value<bool>(); vb) {
        c.live_carry_pose_as_hint = *vb;
    } else if (auto vi = tbl["amcl"]["live_carry_pose_as_hint"].value<int64_t>(); vi) {
        c.live_carry_pose_as_hint = (*vi != 0);
    }
    if (auto v = tbl["amcl"]["live_carry_sigma_xy_m"].value<double>();    v) {
        c.amcl_live_carry_sigma_xy_m = *v;
    }
    if (auto v = tbl["amcl"]["live_carry_sigma_yaw_deg"].value<double>(); v) {
        c.amcl_live_carry_sigma_yaw_deg = *v;
    }
    if (auto v = tbl["amcl"]["live_carry_schedule_m"].value<std::string>(); v) {
        c.amcl_live_carry_schedule_m =
            parse_csv_doubles_or_throw(*v, "amcl.live_carry_schedule_m");
    }

    if (auto v = tbl["gpio"]["calibrate_pin"].value<int64_t>();    v) c.gpio_calibrate_pin   = static_cast<int>(*v);
    if (auto v = tbl["gpio"]["live_toggle_pin"].value<int64_t>();  v) c.gpio_live_toggle_pin = static_cast<int>(*v);

    // issue#12 — webctl-owned schema rows. Tracker stores the value
    // verbatim; no tracker logic path consumes it (CODEBASE.md (r)).
    if (auto v = tbl["webctl"]["pose_stream_hz"].value<int64_t>(); v) c.webctl_pose_stream_hz = static_cast<int>(*v);
    if (auto v = tbl["webctl"]["scan_stream_hz"].value<int64_t>(); v) c.webctl_scan_stream_hz = static_cast<int>(*v);
    // issue#14 Maj-1 / issue#16.1 — webctl-owned mapping-stop timing ladder.
    if (auto v = tbl["webctl"]["mapping_docker_stop_grace_s"].value<int64_t>();          v) c.webctl_mapping_docker_stop_grace_s          = static_cast<int>(*v);
    if (auto v = tbl["webctl"]["mapping_systemctl_subprocess_timeout_s"].value<int64_t>();v) c.webctl_mapping_systemctl_subprocess_timeout_s = static_cast<int>(*v);
    if (auto v = tbl["webctl"]["mapping_systemd_stop_timeout_s"].value<int64_t>();        v) c.webctl_mapping_systemd_stop_timeout_s        = static_cast<int>(*v);
    if (auto v = tbl["webctl"]["mapping_webctl_stop_timeout_s"].value<int64_t>();         v) c.webctl_mapping_webctl_stop_timeout_s         = static_cast<int>(*v);

    // issue#27 — final-output transform + OriginPicker step.
    if (auto v = tbl["output_transform"]["x_offset_m"].value<double>();    v) c.output_transform_x_offset_m    = *v;
    if (auto v = tbl["output_transform"]["y_offset_m"].value<double>();    v) c.output_transform_y_offset_m    = *v;
    if (auto v = tbl["output_transform"]["z_offset_m"].value<double>();    v) c.output_transform_z_offset_m    = *v;
    if (auto v = tbl["output_transform"]["pan_offset_deg"].value<double>();v) c.output_transform_pan_offset_deg  = *v;
    if (auto v = tbl["output_transform"]["tilt_offset_deg"].value<double>();v) c.output_transform_tilt_offset_deg = *v;
    if (auto v = tbl["output_transform"]["roll_offset_deg"].value<double>();v) c.output_transform_roll_offset_deg = *v;
    if (auto v = tbl["output_transform"]["x_sign"].value<int64_t>();       v) c.output_transform_x_sign         = static_cast<int>(*v);
    if (auto v = tbl["output_transform"]["y_sign"].value<int64_t>();       v) c.output_transform_y_sign         = static_cast<int>(*v);
    if (auto v = tbl["output_transform"]["z_sign"].value<int64_t>();       v) c.output_transform_z_sign         = static_cast<int>(*v);
    if (auto v = tbl["output_transform"]["pan_sign"].value<int64_t>();     v) c.output_transform_pan_sign       = static_cast<int>(*v);
    if (auto v = tbl["output_transform"]["tilt_sign"].value<int64_t>();    v) c.output_transform_tilt_sign      = static_cast<int>(*v);
    if (auto v = tbl["output_transform"]["roll_sign"].value<int64_t>();    v) c.output_transform_roll_sign      = static_cast<int>(*v);
    if (auto v = tbl["origin_step"]["x_m"].value<double>();                v) c.origin_step_x_m   = *v;
    if (auto v = tbl["origin_step"]["y_m"].value<double>();                v) c.origin_step_y_m   = *v;
    if (auto v = tbl["origin_step"]["yaw_deg"].value<double>();            v) c.origin_step_yaw_deg = *v;
}

// Linear search over the envp array.
std::optional<std::string> env_get(char** envp, std::string_view name) {
    if (envp == nullptr) return std::nullopt;
    const std::string prefix = std::string(name) + "=";
    for (char** e = envp; *e != nullptr; ++e) {
        std::string_view s(*e);
        if (s.size() > prefix.size() &&
            s.substr(0, prefix.size()) == prefix) {
            return std::string(s.substr(prefix.size()));
        }
    }
    return std::nullopt;
}

int parse_int_or_throw(std::string_view src, std::string_view key) {
    try {
        size_t pos = 0;
        const std::string s(src);
        const long v = std::stol(s, &pos, 10);
        if (pos != s.size()) {
            throw std::runtime_error(
                std::string("config: ") + std::string(key) +
                " = '" + s + "' is not a valid integer");
        }
        return static_cast<int>(v);
    } catch (const std::exception& e) {
        throw std::runtime_error(
            std::string("config: ") + std::string(key) +
            " = '" + std::string(src) + "' is not a valid integer");
    }
}

std::uint64_t parse_u64_or_throw(std::string_view src, std::string_view key) {
    try {
        size_t pos = 0;
        const std::string s(src);
        if (!s.empty() && s[0] == '-') {
            throw std::runtime_error(
                std::string("config: ") + std::string(key) +
                " = '" + s + "' must be a non-negative integer");
        }
        const unsigned long long v = std::stoull(s, &pos, 10);
        if (pos != s.size()) {
            throw std::runtime_error(
                std::string("config: ") + std::string(key) +
                " = '" + s + "' is not a valid unsigned integer");
        }
        return static_cast<std::uint64_t>(v);
    } catch (const std::runtime_error&) {
        throw;
    } catch (const std::exception&) {
        throw std::runtime_error(
            std::string("config: ") + std::string(key) +
            " = '" + std::string(src) + "' is not a valid unsigned integer");
    }
}

double parse_double_or_throw(std::string_view src, std::string_view key) {
    try {
        size_t pos = 0;
        const std::string s(src);
        const double v = std::stod(s, &pos);
        if (pos != s.size()) {
            throw std::runtime_error(
                std::string("config: ") + std::string(key) +
                " = '" + s + "' is not a valid number");
        }
        return v;
    } catch (const std::exception& e) {
        throw std::runtime_error(
            std::string("config: ") + std::string(key) +
            " = '" + std::string(src) + "' is not a valid number");
    }
}

// Track D-5 — CSV-of-doubles parser. Trims surrounding whitespace per
// entry; rejects empty or all-whitespace strings; rejects empty entries
// (consecutive commas). Used by `amcl.sigma_hit_schedule_m`.
std::vector<double> parse_csv_doubles_or_throw(std::string_view src,
                                               std::string_view key) {
    std::vector<double> out;
    const std::string s(src);
    std::string token;
    auto flush = [&](bool is_last) {
        // Trim leading/trailing whitespace.
        std::size_t a = 0, b = token.size();
        while (a < b && std::isspace(static_cast<unsigned char>(token[a]))) ++a;
        while (b > a && std::isspace(static_cast<unsigned char>(token[b - 1]))) --b;
        if (a == b) {
            throw std::runtime_error(
                std::string("config: ") + std::string(key) +
                " = '" + s + "' has an empty entry");
        }
        const std::string trimmed = token.substr(a, b - a);
        out.push_back(parse_double_or_throw(trimmed, key));
        token.clear();
        (void)is_last;
    };
    bool any = false;
    for (char c : s) {
        if (c == ',') {
            flush(false);
            any = true;
        } else {
            token.push_back(c);
            any = true;
        }
    }
    if (!any) {
        throw std::runtime_error(
            std::string("config: ") + std::string(key) +
            " must be a non-empty CSV of doubles (got '" + s + "')");
    }
    flush(true);
    return out;
}

// Track D-5 — Sentinel-aware CSV-of-doubles parser. The first entry MUST
// be the literal "-" sentinel (phase 0 uses seed_global, not seed_around);
// the parsed first slot is set to NaN so downstream code can detect "not
// applicable" without sharing a magic finite value with real data.
// Entries 1..N-1 must be positive doubles. Used by
// `amcl.sigma_seed_xy_schedule_m`.
std::vector<double> parse_csv_doubles_with_sentinel_or_throw(
    std::string_view src, std::string_view key) {
    std::vector<double> out;
    const std::string s(src);
    std::string token;
    bool first = true;
    auto flush = [&]() {
        std::size_t a = 0, b = token.size();
        while (a < b && std::isspace(static_cast<unsigned char>(token[a]))) ++a;
        while (b > a && std::isspace(static_cast<unsigned char>(token[b - 1]))) --b;
        if (a == b) {
            throw std::runtime_error(
                std::string("config: ") + std::string(key) +
                " = '" + s + "' has an empty entry");
        }
        const std::string trimmed = token.substr(a, b - a);
        if (first) {
            if (trimmed != "-") {
                throw std::runtime_error(
                    std::string("config: ") + std::string(key) +
                    " first entry must be sentinel '-' (phase 0 uses "
                    "seed_global); got '" + trimmed + "'");
            }
            out.push_back(std::numeric_limits<double>::quiet_NaN());
            first = false;
        } else {
            const double v = parse_double_or_throw(trimmed, key);
            if (!(v > 0.0)) {
                throw std::runtime_error(
                    std::string("config: ") + std::string(key) +
                    " entry '" + trimmed + "' must be > 0");
            }
            out.push_back(v);
        }
        token.clear();
    };
    bool any = false;
    for (char c : s) {
        if (c == ',') {
            flush();
            any = true;
        } else {
            token.push_back(c);
            any = true;
        }
    }
    if (!any) {
        throw std::runtime_error(
            std::string("config: ") + std::string(key) +
            " must be a non-empty CSV (got '" + s + "')");
    }
    flush();
    return out;
}

void apply_env(Config& c, char** envp) {
    if (auto v = env_get(envp, "GODO_UE_HOST"))       c.ue_host = *v;
    if (auto v = env_get(envp, "GODO_UE_PORT"))       c.ue_port = parse_int_or_throw(*v, "GODO_UE_PORT");
    if (auto v = env_get(envp, "GODO_LIDAR_PORT"))    c.lidar_port = *v;
    if (auto v = env_get(envp, "GODO_LIDAR_UDEV_SERIAL")) c.lidar_udev_serial = *v;
    if (auto v = env_get(envp, "GODO_LIDAR_BAUD"))    c.lidar_baud = parse_int_or_throw(*v, "GODO_LIDAR_BAUD");
    if (auto v = env_get(envp, "GODO_FREED_PORT"))    c.freed_port = *v;
    if (auto v = env_get(envp, "GODO_FREED_BAUD"))    c.freed_baud = parse_int_or_throw(*v, "GODO_FREED_BAUD");
    if (auto v = env_get(envp, "GODO_T_RAMP_MS"))     c.t_ramp_ns = static_cast<std::int64_t>(parse_int_or_throw(*v, "GODO_T_RAMP_MS")) * 1'000'000LL;
    if (auto v = env_get(envp, "GODO_DEADBAND_MM"))   c.deadband_mm   = parse_double_or_throw(*v, "GODO_DEADBAND_MM");
    if (auto v = env_get(envp, "GODO_DEADBAND_DEG")) c.deadband_deg  = parse_double_or_throw(*v, "GODO_DEADBAND_DEG");
    if (auto v = env_get(envp, "GODO_DIVERGENCE_MM")) c.divergence_mm = parse_double_or_throw(*v, "GODO_DIVERGENCE_MM");
    if (auto v = env_get(envp, "GODO_DIVERGENCE_DEG"))c.divergence_deg = parse_double_or_throw(*v, "GODO_DIVERGENCE_DEG");
    if (auto v = env_get(envp, "GODO_RT_CPU"))        c.rt_cpu      = parse_int_or_throw(*v, "GODO_RT_CPU");
    if (auto v = env_get(envp, "GODO_RT_PRIORITY"))   c.rt_priority = parse_int_or_throw(*v, "GODO_RT_PRIORITY");
    if (auto v = env_get(envp, "GODO_UDS_SOCKET"))    c.uds_socket  = *v;
    if (auto v = env_get(envp, "GODO_TRACKER_PIDFILE")) c.tracker_pidfile = *v;

    if (auto v = env_get(envp, "GODO_AMCL_MAP_PATH"))             c.amcl_map_path           = *v;
    if (auto v = env_get(envp, "GODO_AMCL_ORIGIN_X_M"))           c.amcl_origin_x_m         = parse_double_or_throw(*v, "GODO_AMCL_ORIGIN_X_M");
    if (auto v = env_get(envp, "GODO_AMCL_ORIGIN_Y_M"))           c.amcl_origin_y_m         = parse_double_or_throw(*v, "GODO_AMCL_ORIGIN_Y_M");
    if (auto v = env_get(envp, "GODO_AMCL_PARTICLES_GLOBAL_N"))   c.amcl_particles_global_n = parse_int_or_throw(*v, "GODO_AMCL_PARTICLES_GLOBAL_N");
    if (auto v = env_get(envp, "GODO_AMCL_PARTICLES_LOCAL_N"))    c.amcl_particles_local_n  = parse_int_or_throw(*v, "GODO_AMCL_PARTICLES_LOCAL_N");
    if (auto v = env_get(envp, "GODO_AMCL_MAX_ITERS"))            c.amcl_max_iters          = parse_int_or_throw(*v, "GODO_AMCL_MAX_ITERS");
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_HIT_M"))          c.amcl_sigma_hit_m        = parse_double_or_throw(*v, "GODO_AMCL_SIGMA_HIT_M");
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_XY_JITTER_M"))    c.amcl_sigma_xy_jitter_m  = parse_double_or_throw(*v, "GODO_AMCL_SIGMA_XY_JITTER_M");
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_YAW_JITTER_DEG")) c.amcl_sigma_yaw_jitter_deg = parse_double_or_throw(*v, "GODO_AMCL_SIGMA_YAW_JITTER_DEG");
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_SEED_XY_M"))      c.amcl_sigma_seed_xy_m    = parse_double_or_throw(*v, "GODO_AMCL_SIGMA_SEED_XY_M");
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_SEED_YAW_DEG"))   c.amcl_sigma_seed_yaw_deg = parse_double_or_throw(*v, "GODO_AMCL_SIGMA_SEED_YAW_DEG");
    if (auto v = env_get(envp, "GODO_AMCL_DOWNSAMPLE_STRIDE"))    c.amcl_downsample_stride  = parse_int_or_throw(*v, "GODO_AMCL_DOWNSAMPLE_STRIDE");
    if (auto v = env_get(envp, "GODO_AMCL_RANGE_MIN_M"))          c.amcl_range_min_m        = parse_double_or_throw(*v, "GODO_AMCL_RANGE_MIN_M");
    if (auto v = env_get(envp, "GODO_AMCL_RANGE_MAX_M"))          c.amcl_range_max_m        = parse_double_or_throw(*v, "GODO_AMCL_RANGE_MAX_M");
    if (auto v = env_get(envp, "GODO_AMCL_CONVERGE_XY_STD_M"))    c.amcl_converge_xy_std_m  = parse_double_or_throw(*v, "GODO_AMCL_CONVERGE_XY_STD_M");
    if (auto v = env_get(envp, "GODO_AMCL_CONVERGE_YAW_STD_DEG")) c.amcl_converge_yaw_std_deg = parse_double_or_throw(*v, "GODO_AMCL_CONVERGE_YAW_STD_DEG");
    if (auto v = env_get(envp, "GODO_AMCL_YAW_TRIPWIRE_DEG"))     c.amcl_yaw_tripwire_deg   = parse_double_or_throw(*v, "GODO_AMCL_YAW_TRIPWIRE_DEG");
    if (auto v = env_get(envp, "GODO_AMCL_TRIGGER_POLL_MS"))      c.amcl_trigger_poll_ms    = parse_int_or_throw(*v, "GODO_AMCL_TRIGGER_POLL_MS");
    if (auto v = env_get(envp, "GODO_AMCL_SEED"))                 c.amcl_seed               = parse_u64_or_throw(*v, "GODO_AMCL_SEED");
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_XY_JITTER_LIVE_M"))    c.amcl_sigma_xy_jitter_live_m    = parse_double_or_throw(*v, "GODO_AMCL_SIGMA_XY_JITTER_LIVE_M");
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_YAW_JITTER_LIVE_DEG")) c.amcl_sigma_yaw_jitter_live_deg = parse_double_or_throw(*v, "GODO_AMCL_SIGMA_YAW_JITTER_LIVE_DEG");

    // Track D-5 — annealing keys.
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_HIT_SCHEDULE_M")) {
        c.amcl_sigma_hit_schedule_m =
            parse_csv_doubles_or_throw(*v, "GODO_AMCL_SIGMA_HIT_SCHEDULE_M");
    }
    if (auto v = env_get(envp, "GODO_AMCL_SIGMA_SEED_XY_SCHEDULE_M")) {
        c.amcl_sigma_seed_xy_schedule_m =
            parse_csv_doubles_with_sentinel_or_throw(*v,
                "GODO_AMCL_SIGMA_SEED_XY_SCHEDULE_M");
    }
    if (auto v = env_get(envp, "GODO_AMCL_ANNEAL_ITERS_PER_PHASE")) {
        c.amcl_anneal_iters_per_phase =
            parse_int_or_throw(*v, "GODO_AMCL_ANNEAL_ITERS_PER_PHASE");
    }
    // issue#11 — fork-join particle eval pool workers.
    if (auto v = env_get(envp, "GODO_AMCL_PARALLEL_EVAL_WORKERS")) {
        c.amcl_parallel_eval_workers =
            parse_int_or_throw(*v, "GODO_AMCL_PARALLEL_EVAL_WORKERS");
    }
    // issue#3 — hint-σ defaults.
    if (auto v = env_get(envp, "GODO_AMCL_HINT_SIGMA_XY_M_DEFAULT")) {
        c.amcl_hint_sigma_xy_m_default =
            parse_double_or_throw(*v, "GODO_AMCL_HINT_SIGMA_XY_M_DEFAULT");
    }
    if (auto v = env_get(envp, "GODO_AMCL_HINT_SIGMA_YAW_DEG_DEFAULT")) {
        c.amcl_hint_sigma_yaw_deg_default =
            parse_double_or_throw(*v, "GODO_AMCL_HINT_SIGMA_YAW_DEG_DEFAULT");
    }

    // issue#5 — Live pipelined-hint kernel keys. Bool-as-Int env wire form:
    // accept "0", "1", "true", "false" (case-insensitive) for the flag.
    if (auto v = env_get(envp, "GODO_LIVE_CARRY_POSE_AS_HINT")) {
        const std::string s = *v;
        std::string lower;
        lower.reserve(s.size());
        for (char ch : s) {
            lower.push_back(static_cast<char>(std::tolower(
                static_cast<unsigned char>(ch))));
        }
        if (lower == "true" || lower == "1") {
            c.live_carry_pose_as_hint = true;
        } else if (lower == "false" || lower == "0") {
            c.live_carry_pose_as_hint = false;
        } else {
            throw std::runtime_error(
                std::string("config: GODO_LIVE_CARRY_POSE_AS_HINT='") + s +
                "' must be one of {0, 1, true, false}");
        }
    }
    if (auto v = env_get(envp, "GODO_AMCL_LIVE_CARRY_SIGMA_XY_M")) {
        c.amcl_live_carry_sigma_xy_m =
            parse_double_or_throw(*v, "GODO_AMCL_LIVE_CARRY_SIGMA_XY_M");
    }
    if (auto v = env_get(envp, "GODO_AMCL_LIVE_CARRY_SIGMA_YAW_DEG")) {
        c.amcl_live_carry_sigma_yaw_deg =
            parse_double_or_throw(*v, "GODO_AMCL_LIVE_CARRY_SIGMA_YAW_DEG");
    }
    if (auto v = env_get(envp, "GODO_AMCL_LIVE_CARRY_SCHEDULE_M")) {
        c.amcl_live_carry_schedule_m =
            parse_csv_doubles_or_throw(*v, "GODO_AMCL_LIVE_CARRY_SCHEDULE_M");
    }

    if (auto v = env_get(envp, "GODO_GPIO_CALIBRATE_PIN"))             c.gpio_calibrate_pin             = parse_int_or_throw(*v, "GODO_GPIO_CALIBRATE_PIN");
    if (auto v = env_get(envp, "GODO_GPIO_LIVE_TOGGLE_PIN"))           c.gpio_live_toggle_pin           = parse_int_or_throw(*v, "GODO_GPIO_LIVE_TOGGLE_PIN");

    // issue#12 — webctl-owned schema rows.
    if (auto v = env_get(envp, "GODO_WEBCTL_POSE_STREAM_HZ")) c.webctl_pose_stream_hz = parse_int_or_throw(*v, "GODO_WEBCTL_POSE_STREAM_HZ");
    if (auto v = env_get(envp, "GODO_WEBCTL_SCAN_STREAM_HZ")) c.webctl_scan_stream_hz = parse_int_or_throw(*v, "GODO_WEBCTL_SCAN_STREAM_HZ");
    // issue#14 Maj-1 / issue#16.1 — webctl-owned mapping-stop timing ladder.
    if (auto v = env_get(envp, "GODO_WEBCTL_MAPPING_DOCKER_STOP_GRACE_S"))           c.webctl_mapping_docker_stop_grace_s          = parse_int_or_throw(*v, "GODO_WEBCTL_MAPPING_DOCKER_STOP_GRACE_S");
    if (auto v = env_get(envp, "GODO_WEBCTL_MAPPING_SYSTEMCTL_SUBPROCESS_TIMEOUT_S")) c.webctl_mapping_systemctl_subprocess_timeout_s = parse_int_or_throw(*v, "GODO_WEBCTL_MAPPING_SYSTEMCTL_SUBPROCESS_TIMEOUT_S");
    if (auto v = env_get(envp, "GODO_WEBCTL_MAPPING_SYSTEMD_STOP_TIMEOUT_S"))         c.webctl_mapping_systemd_stop_timeout_s        = parse_int_or_throw(*v, "GODO_WEBCTL_MAPPING_SYSTEMD_STOP_TIMEOUT_S");
    if (auto v = env_get(envp, "GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S"))          c.webctl_mapping_webctl_stop_timeout_s         = parse_int_or_throw(*v, "GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S");
}

// CLI parser — tiny, explicit. `--key=value` or `--key value`.
// Unknown flags are rejected so typos do not silently fall through.
struct CliKV {
    std::string key;
    std::string value;
};

std::vector<CliKV> parse_cli(int argc, char** argv) {
    std::vector<CliKV> out;
    if (argv == nullptr) return out;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a.size() < 3 || a.substr(0, 2) != "--") {
            throw std::runtime_error(
                std::string("config: unexpected argument '") + a +
                "' (expected --key=value or --key value)");
        }
        const std::string body = a.substr(2);
        auto eq = body.find('=');
        if (eq != std::string::npos) {
            out.push_back({body.substr(0, eq), body.substr(eq + 1)});
        } else {
            if (i + 1 >= argc) {
                throw std::runtime_error(
                    std::string("config: flag '--") + body +
                    "' requires a value");
            }
            out.push_back({body, argv[i + 1]});
            ++i;
        }
    }
    return out;
}

void apply_cli(Config& c, int argc, char** argv) {
    const std::unordered_map<std::string, std::function<void(Config&, const std::string&)>>
        handlers = {
        {"ue-host",        [](Config& cc, const std::string& v){ cc.ue_host = v; }},
        {"ue-port",        [](Config& cc, const std::string& v){ cc.ue_port = parse_int_or_throw(v, "--ue-port"); }},
        {"lidar-port",     [](Config& cc, const std::string& v){ cc.lidar_port = v; }},
        {"lidar-udev-serial", [](Config& cc, const std::string& v){ cc.lidar_udev_serial = v; }},
        {"lidar-baud",     [](Config& cc, const std::string& v){ cc.lidar_baud = parse_int_or_throw(v, "--lidar-baud"); }},
        {"freed-port",     [](Config& cc, const std::string& v){ cc.freed_port = v; }},
        {"freed-baud",     [](Config& cc, const std::string& v){ cc.freed_baud = parse_int_or_throw(v, "--freed-baud"); }},
        {"t-ramp-ms",      [](Config& cc, const std::string& v){ cc.t_ramp_ns = static_cast<std::int64_t>(parse_int_or_throw(v, "--t-ramp-ms")) * 1'000'000LL; }},
        {"deadband-mm",    [](Config& cc, const std::string& v){ cc.deadband_mm = parse_double_or_throw(v, "--deadband-mm"); }},
        {"deadband-deg",   [](Config& cc, const std::string& v){ cc.deadband_deg = parse_double_or_throw(v, "--deadband-deg"); }},
        {"divergence-mm",  [](Config& cc, const std::string& v){ cc.divergence_mm = parse_double_or_throw(v, "--divergence-mm"); }},
        {"divergence-deg", [](Config& cc, const std::string& v){ cc.divergence_deg = parse_double_or_throw(v, "--divergence-deg"); }},
        {"rt-cpu",         [](Config& cc, const std::string& v){ cc.rt_cpu = parse_int_or_throw(v, "--rt-cpu"); }},
        {"rt-priority",    [](Config& cc, const std::string& v){ cc.rt_priority = parse_int_or_throw(v, "--rt-priority"); }},
        {"uds-socket",     [](Config& cc, const std::string& v){ cc.uds_socket = v; }},
        {"pidfile",        [](Config& cc, const std::string& v){ cc.tracker_pidfile = v; }},
        {"amcl-map-path",            [](Config& cc, const std::string& v){ cc.amcl_map_path           = v; }},
        {"amcl-origin-x-m",          [](Config& cc, const std::string& v){ cc.amcl_origin_x_m         = parse_double_or_throw(v, "--amcl-origin-x-m"); }},
        {"amcl-origin-y-m",          [](Config& cc, const std::string& v){ cc.amcl_origin_y_m         = parse_double_or_throw(v, "--amcl-origin-y-m"); }},
        {"amcl-particles-global-n",  [](Config& cc, const std::string& v){ cc.amcl_particles_global_n = parse_int_or_throw(v, "--amcl-particles-global-n"); }},
        {"amcl-particles-local-n",   [](Config& cc, const std::string& v){ cc.amcl_particles_local_n  = parse_int_or_throw(v, "--amcl-particles-local-n"); }},
        {"amcl-max-iters",           [](Config& cc, const std::string& v){ cc.amcl_max_iters          = parse_int_or_throw(v, "--amcl-max-iters"); }},
        {"amcl-sigma-hit-m",         [](Config& cc, const std::string& v){ cc.amcl_sigma_hit_m        = parse_double_or_throw(v, "--amcl-sigma-hit-m"); }},
        {"amcl-sigma-xy-jitter-m",   [](Config& cc, const std::string& v){ cc.amcl_sigma_xy_jitter_m  = parse_double_or_throw(v, "--amcl-sigma-xy-jitter-m"); }},
        {"amcl-sigma-yaw-jitter-deg",[](Config& cc, const std::string& v){ cc.amcl_sigma_yaw_jitter_deg = parse_double_or_throw(v, "--amcl-sigma-yaw-jitter-deg"); }},
        {"amcl-sigma-seed-xy-m",     [](Config& cc, const std::string& v){ cc.amcl_sigma_seed_xy_m    = parse_double_or_throw(v, "--amcl-sigma-seed-xy-m"); }},
        {"amcl-sigma-seed-yaw-deg",  [](Config& cc, const std::string& v){ cc.amcl_sigma_seed_yaw_deg = parse_double_or_throw(v, "--amcl-sigma-seed-yaw-deg"); }},
        {"amcl-downsample-stride",   [](Config& cc, const std::string& v){ cc.amcl_downsample_stride  = parse_int_or_throw(v, "--amcl-downsample-stride"); }},
        {"amcl-range-min-m",         [](Config& cc, const std::string& v){ cc.amcl_range_min_m        = parse_double_or_throw(v, "--amcl-range-min-m"); }},
        {"amcl-range-max-m",         [](Config& cc, const std::string& v){ cc.amcl_range_max_m        = parse_double_or_throw(v, "--amcl-range-max-m"); }},
        {"amcl-converge-xy-std-m",   [](Config& cc, const std::string& v){ cc.amcl_converge_xy_std_m  = parse_double_or_throw(v, "--amcl-converge-xy-std-m"); }},
        {"amcl-converge-yaw-std-deg",[](Config& cc, const std::string& v){ cc.amcl_converge_yaw_std_deg = parse_double_or_throw(v, "--amcl-converge-yaw-std-deg"); }},
        {"amcl-yaw-tripwire-deg",    [](Config& cc, const std::string& v){ cc.amcl_yaw_tripwire_deg   = parse_double_or_throw(v, "--amcl-yaw-tripwire-deg"); }},
        {"amcl-trigger-poll-ms",     [](Config& cc, const std::string& v){ cc.amcl_trigger_poll_ms    = parse_int_or_throw(v, "--amcl-trigger-poll-ms"); }},
        {"amcl-seed",                [](Config& cc, const std::string& v){ cc.amcl_seed               = parse_u64_or_throw(v, "--amcl-seed"); }},
        {"amcl-sigma-xy-jitter-live-m",    [](Config& cc, const std::string& v){ cc.amcl_sigma_xy_jitter_live_m    = parse_double_or_throw(v, "--amcl-sigma-xy-jitter-live-m"); }},
        {"amcl-sigma-yaw-jitter-live-deg", [](Config& cc, const std::string& v){ cc.amcl_sigma_yaw_jitter_live_deg = parse_double_or_throw(v, "--amcl-sigma-yaw-jitter-live-deg"); }},
        {"amcl-sigma-hit-schedule-m",      [](Config& cc, const std::string& v){ cc.amcl_sigma_hit_schedule_m      = parse_csv_doubles_or_throw(v, "--amcl-sigma-hit-schedule-m"); }},
        {"amcl-sigma-seed-xy-schedule-m",  [](Config& cc, const std::string& v){ cc.amcl_sigma_seed_xy_schedule_m  = parse_csv_doubles_with_sentinel_or_throw(v, "--amcl-sigma-seed-xy-schedule-m"); }},
        {"amcl-anneal-iters-per-phase",    [](Config& cc, const std::string& v){ cc.amcl_anneal_iters_per_phase    = parse_int_or_throw(v, "--amcl-anneal-iters-per-phase"); }},
        // issue#11 — fork-join particle eval pool workers.
        {"amcl-parallel-eval-workers",     [](Config& cc, const std::string& v){ cc.amcl_parallel_eval_workers     = parse_int_or_throw(v, "--amcl-parallel-eval-workers"); }},
        {"amcl-hint-sigma-xy-m-default",   [](Config& cc, const std::string& v){ cc.amcl_hint_sigma_xy_m_default   = parse_double_or_throw(v, "--amcl-hint-sigma-xy-m-default"); }},
        {"amcl-hint-sigma-yaw-deg-default",[](Config& cc, const std::string& v){ cc.amcl_hint_sigma_yaw_deg_default = parse_double_or_throw(v, "--amcl-hint-sigma-yaw-deg-default"); }},
        // issue#5 — Live pipelined-hint kernel keys. Flag accepts the
        // {0, 1, true, false} CLI tokens; sigma + schedule pair with
        // the existing AMCL keys' parser pattern.
        {"live-carry-pose-as-hint",        [](Config& cc, const std::string& v){
            std::string lower;
            lower.reserve(v.size());
            for (char ch : v) {
                lower.push_back(static_cast<char>(std::tolower(
                    static_cast<unsigned char>(ch))));
            }
            if (lower == "true" || lower == "1") cc.live_carry_pose_as_hint = true;
            else if (lower == "false" || lower == "0") cc.live_carry_pose_as_hint = false;
            else {
                throw std::runtime_error(
                    std::string("config: --live-carry-pose-as-hint='") + v +
                    "' must be one of {0, 1, true, false}");
            }
        }},
        {"amcl-live-carry-sigma-xy-m",     [](Config& cc, const std::string& v){ cc.amcl_live_carry_sigma_xy_m     = parse_double_or_throw(v, "--amcl-live-carry-sigma-xy-m"); }},
        {"amcl-live-carry-sigma-yaw-deg",  [](Config& cc, const std::string& v){ cc.amcl_live_carry_sigma_yaw_deg  = parse_double_or_throw(v, "--amcl-live-carry-sigma-yaw-deg"); }},
        {"amcl-live-carry-schedule-m",     [](Config& cc, const std::string& v){ cc.amcl_live_carry_schedule_m     = parse_csv_doubles_or_throw(v, "--amcl-live-carry-schedule-m"); }},
        {"gpio-calibrate-pin",             [](Config& cc, const std::string& v){ cc.gpio_calibrate_pin             = parse_int_or_throw(v, "--gpio-calibrate-pin"); }},
        {"gpio-live-toggle-pin",           [](Config& cc, const std::string& v){ cc.gpio_live_toggle_pin           = parse_int_or_throw(v, "--gpio-live-toggle-pin"); }},
        // issue#12 — webctl-owned schema rows.
        {"webctl-pose-stream-hz",          [](Config& cc, const std::string& v){ cc.webctl_pose_stream_hz          = parse_int_or_throw(v, "--webctl-pose-stream-hz"); }},
        {"webctl-scan-stream-hz",          [](Config& cc, const std::string& v){ cc.webctl_scan_stream_hz          = parse_int_or_throw(v, "--webctl-scan-stream-hz"); }},
        // issue#14 Maj-1 / issue#16.1 — webctl-owned mapping-stop timing ladder.
        {"webctl-mapping-docker-stop-grace-s",          [](Config& cc, const std::string& v){ cc.webctl_mapping_docker_stop_grace_s          = parse_int_or_throw(v, "--webctl-mapping-docker-stop-grace-s"); }},
        {"webctl-mapping-systemctl-subprocess-timeout-s",[](Config& cc, const std::string& v){ cc.webctl_mapping_systemctl_subprocess_timeout_s = parse_int_or_throw(v, "--webctl-mapping-systemctl-subprocess-timeout-s"); }},
        {"webctl-mapping-systemd-stop-timeout-s",       [](Config& cc, const std::string& v){ cc.webctl_mapping_systemd_stop_timeout_s        = parse_int_or_throw(v, "--webctl-mapping-systemd-stop-timeout-s"); }},
        {"webctl-mapping-webctl-stop-timeout-s",        [](Config& cc, const std::string& v){ cc.webctl_mapping_webctl_stop_timeout_s         = parse_int_or_throw(v, "--webctl-mapping-webctl-stop-timeout-s"); }},
    };
    for (const auto& kv : parse_cli(argc, argv)) {
        auto it = handlers.find(kv.key);
        if (it == handlers.end()) {
            throw std::runtime_error(
                std::string("config: unknown CLI flag '--") + kv.key + "'");
        }
        it->second(c, kv.value);
    }
}

// Range / sign checks for AMCL keys. Run after the precedence chain
// settles so any layer (defaults, TOML, env, CLI) that pushes an
// invalid value gets a single, consistent error message naming the key.
void validate_amcl(const Config& c) {
    auto require_positive_int = [](int v, const char* name) {
        if (v <= 0) {
            throw std::runtime_error(
                std::string("config: ") + name +
                " must be > 0 (got " + std::to_string(v) + ")");
        }
    };
    auto require_positive_double = [](double v, const char* name) {
        if (!(v > 0.0)) {
            throw std::runtime_error(
                std::string("config: ") + name +
                " must be > 0.0 (got " + std::to_string(v) + ")");
        }
    };
    auto require_nonneg_double = [](double v, const char* name) {
        if (!(v >= 0.0)) {
            throw std::runtime_error(
                std::string("config: ") + name +
                " must be >= 0.0 (got " + std::to_string(v) + ")");
        }
    };

    if (c.amcl_map_path.empty()) {
        throw std::runtime_error("config: amcl_map_path must not be empty");
    }
    require_positive_int(c.amcl_particles_global_n, "amcl_particles_global_n");
    require_positive_int(c.amcl_particles_local_n,  "amcl_particles_local_n");
    if (c.amcl_particles_global_n > godo::constants::PARTICLE_BUFFER_MAX) {
        throw std::runtime_error(
            "config: amcl_particles_global_n exceeds PARTICLE_BUFFER_MAX (" +
            std::to_string(godo::constants::PARTICLE_BUFFER_MAX) +
            "); raise the constant in core/constants.hpp or shrink the value");
    }
    if (c.amcl_particles_local_n > godo::constants::PARTICLE_BUFFER_MAX) {
        throw std::runtime_error(
            "config: amcl_particles_local_n exceeds PARTICLE_BUFFER_MAX (" +
            std::to_string(godo::constants::PARTICLE_BUFFER_MAX) +
            "); raise the constant in core/constants.hpp or shrink the value");
    }
    require_positive_int(c.amcl_max_iters,         "amcl_max_iters");
    require_positive_int(c.amcl_downsample_stride, "amcl_downsample_stride");
    require_positive_int(c.amcl_trigger_poll_ms,   "amcl_trigger_poll_ms");

    require_positive_double(c.amcl_sigma_hit_m,               "amcl_sigma_hit_m");
    require_positive_double(c.amcl_sigma_xy_jitter_m,         "amcl_sigma_xy_jitter_m");
    require_positive_double(c.amcl_sigma_yaw_jitter_deg,      "amcl_sigma_yaw_jitter_deg");
    require_positive_double(c.amcl_sigma_xy_jitter_live_m,    "amcl_sigma_xy_jitter_live_m");
    require_positive_double(c.amcl_sigma_yaw_jitter_live_deg, "amcl_sigma_yaw_jitter_live_deg");
    require_positive_double(c.amcl_sigma_seed_xy_m,           "amcl_sigma_seed_xy_m");
    require_positive_double(c.amcl_sigma_seed_yaw_deg,        "amcl_sigma_seed_yaw_deg");
    // issue#5 — Live carry σ + schedule bounds (matches config_schema.hpp).
    if (!(c.amcl_live_carry_sigma_xy_m >= 0.001 &&
          c.amcl_live_carry_sigma_xy_m <= 0.5)) {
        throw std::runtime_error(
            "config: amcl_live_carry_sigma_xy_m must be in [0.001, 0.5] "
            "(got " + std::to_string(c.amcl_live_carry_sigma_xy_m) + ")");
    }
    if (!(c.amcl_live_carry_sigma_yaw_deg >= 0.05 &&
          c.amcl_live_carry_sigma_yaw_deg <= 30.0)) {
        throw std::runtime_error(
            "config: amcl_live_carry_sigma_yaw_deg must be in [0.05, 30.0] "
            "(got " + std::to_string(c.amcl_live_carry_sigma_yaw_deg) + ")");
    }
    if (c.amcl_live_carry_schedule_m.empty()) {
        throw std::runtime_error(
            "config: amcl_live_carry_schedule_m must be non-empty");
    }
    {
        constexpr double kSigmaMin = 0.005;
        constexpr double kSigmaMax = 5.0;
        for (std::size_t i = 0; i < c.amcl_live_carry_schedule_m.size(); ++i) {
            const double v = c.amcl_live_carry_schedule_m[i];
            if (!(v >= kSigmaMin) || !(v <= kSigmaMax)) {
                throw std::runtime_error(
                    "config: amcl_live_carry_schedule_m[" + std::to_string(i) +
                    "] = " + std::to_string(v) +
                    " out of range [" + std::to_string(kSigmaMin) + ", " +
                    std::to_string(kSigmaMax) + "]");
            }
            if (i > 0) {
                const double prev = c.amcl_live_carry_schedule_m[i - 1];
                if (!(v < prev)) {
                    throw std::runtime_error(
                        "config: amcl_live_carry_schedule_m must be strictly "
                        "monotonically decreasing; entry " + std::to_string(i) +
                        " (" + std::to_string(v) + ") is not < entry " +
                        std::to_string(i - 1) + " (" + std::to_string(prev) + ")");
                }
            }
        }
    }
    // issue#3 — hint default σ bounds (Mode-A schema bounds; matches
    // config_schema.hpp + webctl Pydantic CalibrateBody).
    if (!(c.amcl_hint_sigma_xy_m_default >= 0.05 &&
          c.amcl_hint_sigma_xy_m_default <= 5.0)) {
        throw std::runtime_error(
            "config: amcl_hint_sigma_xy_m_default must be in [0.05, 5.0] "
            "(got " + std::to_string(c.amcl_hint_sigma_xy_m_default) + ")");
    }
    if (!(c.amcl_hint_sigma_yaw_deg_default >= 1.0 &&
          c.amcl_hint_sigma_yaw_deg_default <= 90.0)) {
        throw std::runtime_error(
            "config: amcl_hint_sigma_yaw_deg_default must be in [1.0, 90.0] "
            "(got " + std::to_string(c.amcl_hint_sigma_yaw_deg_default) + ")");
    }
    require_positive_double(c.amcl_converge_xy_std_m,         "amcl_converge_xy_std_m");
    require_positive_double(c.amcl_converge_yaw_std_deg,      "amcl_converge_yaw_std_deg");

    require_nonneg_double(c.amcl_range_min_m,    "amcl_range_min_m");
    require_positive_double(c.amcl_range_max_m,  "amcl_range_max_m");
    if (!(c.amcl_range_max_m > c.amcl_range_min_m)) {
        throw std::runtime_error(
            "config: amcl_range_max_m (" + std::to_string(c.amcl_range_max_m) +
            ") must exceed amcl_range_min_m (" +
            std::to_string(c.amcl_range_min_m) + ")");
    }
    require_nonneg_double(c.amcl_yaw_tripwire_deg, "amcl_yaw_tripwire_deg");

    // Track D-5 — annealing schedule + seed_xy schedule + iters_per_phase.
    require_positive_int(c.amcl_anneal_iters_per_phase,
                         "amcl_anneal_iters_per_phase");
    // issue#11 — pool worker count must be in [1, 3] (CPU 3 reserved for
    // Thread D; project_cpu3_isolation.md). The schema row enforces the
    // same bounds for `set_config` payloads.
    if (c.amcl_parallel_eval_workers < 1 || c.amcl_parallel_eval_workers > 3) {
        throw std::runtime_error(
            "config: amcl_parallel_eval_workers must be in [1, 3] (got " +
            std::to_string(c.amcl_parallel_eval_workers) + ")");
    }
    if (c.amcl_sigma_hit_schedule_m.empty()) {
        throw std::runtime_error(
            "config: amcl_sigma_hit_schedule_m must be non-empty");
    }
    constexpr double kSigmaMin = 0.005;
    constexpr double kSigmaMax = 5.0;
    for (std::size_t i = 0; i < c.amcl_sigma_hit_schedule_m.size(); ++i) {
        const double v = c.amcl_sigma_hit_schedule_m[i];
        if (!(v >= kSigmaMin) || !(v <= kSigmaMax)) {
            throw std::runtime_error(
                "config: amcl_sigma_hit_schedule_m[" + std::to_string(i) +
                "] = " + std::to_string(v) +
                " out of range [" + std::to_string(kSigmaMin) + ", " +
                std::to_string(kSigmaMax) + "]");
        }
        if (i > 0) {
            const double prev = c.amcl_sigma_hit_schedule_m[i - 1];
            if (!(v < prev)) {
                throw std::runtime_error(
                    "config: amcl_sigma_hit_schedule_m must be strictly "
                    "monotonically decreasing; entry " + std::to_string(i) +
                    " (" + std::to_string(v) + ") is not < entry " +
                    std::to_string(i - 1) + " (" + std::to_string(prev) + ")");
            }
        }
    }
    if (c.amcl_sigma_seed_xy_schedule_m.size() !=
        c.amcl_sigma_hit_schedule_m.size()) {
        throw std::runtime_error(
            "config: amcl_sigma_seed_xy_schedule_m length (" +
            std::to_string(c.amcl_sigma_seed_xy_schedule_m.size()) +
            ") must match amcl_sigma_hit_schedule_m length (" +
            std::to_string(c.amcl_sigma_hit_schedule_m.size()) + ")");
    }
    // First entry must be the NaN sentinel; entries 1..N-1 must be > 0.
    if (!c.amcl_sigma_seed_xy_schedule_m.empty()) {
        if (!std::isnan(c.amcl_sigma_seed_xy_schedule_m[0])) {
            throw std::runtime_error(
                "config: amcl_sigma_seed_xy_schedule_m[0] must be sentinel "
                "'-' (NaN); phase 0 uses seed_global");
        }
        for (std::size_t i = 1; i < c.amcl_sigma_seed_xy_schedule_m.size();
             ++i) {
            const double v = c.amcl_sigma_seed_xy_schedule_m[i];
            if (!(v > 0.0)) {
                throw std::runtime_error(
                    "config: amcl_sigma_seed_xy_schedule_m[" +
                    std::to_string(i) + "] = " + std::to_string(v) +
                    " must be > 0");
            }
        }
    }
}

// Phase 4-2 D — GPIO pin range check. Pi 5 40-pin header BCM line range
// is [0, 27]; values outside that are either not exposed or reserved by
// the camera/I2C/SPI peripherals. Wave A wires this so a malformed TOML
// rejects at startup instead of failing inside libgpiod at Wave B.
void validate_gpio(const Config& c) {
    auto require_pin_in_range = [](int pin, const char* name) {
        if (pin < 0 || pin > godo::constants::GPIO_MAX_BCM_PIN) {
            throw std::runtime_error(
                std::string("config: ") + name +
                " must be in [0, " +
                std::to_string(godo::constants::GPIO_MAX_BCM_PIN) +
                "] (got " + std::to_string(pin) + ")");
        }
    };
    require_pin_in_range(c.gpio_calibrate_pin,   "gpio_calibrate_pin");
    require_pin_in_range(c.gpio_live_toggle_pin, "gpio_live_toggle_pin");
}

// issue#14 Mode-B M1 fix (2026-05-02 KST) — webctl mapping-stop timing
// ladder ordering invariant. Same check the apply path (apply.cpp)
// enforces, applied at Config::load so a hand-edited tracker.toml is
// rejected at next webctl-driven tracker boot rather than producing a
// torn ladder that webctl cannot read.
void validate_webctl_mapping_ladder(const Config& c) {
    const int docker_s    = c.webctl_mapping_docker_stop_grace_s;
    const int systemctl_s = c.webctl_mapping_systemctl_subprocess_timeout_s;
    const int systemd_s   = c.webctl_mapping_systemd_stop_timeout_s;
    const int webctl_s    = c.webctl_mapping_webctl_stop_timeout_s;
    if (!(docker_s < systemd_s)) {
        throw std::runtime_error(
            "config: webctl.mapping ladder violated: "
            "docker_stop_grace_s (" + std::to_string(docker_s) +
            ") must be < systemd_stop_timeout_s (" +
            std::to_string(systemd_s) + ")");
    }
    if (!(systemd_s < webctl_s)) {
        throw std::runtime_error(
            "config: webctl.mapping ladder violated: "
            "systemd_stop_timeout_s (" + std::to_string(systemd_s) +
            ") must be < webctl_stop_timeout_s (" +
            std::to_string(webctl_s) + ")");
    }
    // issue#16.1 — systemctl subprocess deadline must nest inside the
    // webctl coordinator's overall poll deadline. systemctl_s vs.
    // systemd_s is intentionally NOT enforced — operators may set
    // systemctl_s > systemd_s for diagnostic time after a
    // TimeoutStopSec breach.
    if (!(systemctl_s < webctl_s)) {
        throw std::runtime_error(
            "config: webctl.mapping ladder violated: "
            "systemctl_subprocess_timeout_s (" + std::to_string(systemctl_s) +
            ") must be < webctl_stop_timeout_s (" +
            std::to_string(webctl_s) + ")");
    }
}

}  // namespace

Config Config::make_default() {
    Config c;
    c.ue_host        = std::string(cfg_defaults::UE_HOST);
    c.ue_port        = cfg_defaults::UE_PORT;
    c.lidar_port     = std::string(cfg_defaults::LIDAR_PORT);
    c.lidar_udev_serial = std::string(cfg_defaults::LIDAR_UDEV_SERIAL);
    c.lidar_baud     = cfg_defaults::LIDAR_BAUD;
    c.freed_port     = std::string(cfg_defaults::FREED_PORT);
    c.freed_baud     = cfg_defaults::FREED_BAUD;
    c.t_ramp_ns      = cfg_defaults::T_RAMP_NS;
    c.deadband_mm    = cfg_defaults::DEADBAND_MM;
    c.deadband_deg   = cfg_defaults::DEADBAND_DEG;
    c.divergence_mm  = cfg_defaults::DIVERGENCE_MM;
    c.divergence_deg = cfg_defaults::DIVERGENCE_DEG;
    c.rt_cpu         = cfg_defaults::RT_CPU;
    c.rt_priority    = cfg_defaults::RT_PRIORITY;
    c.uds_socket     = std::string(cfg_defaults::UDS_SOCKET);
    c.tracker_pidfile = std::string(cfg_defaults::TRACKER_PIDFILE_DEFAULT);

    c.amcl_map_path             = std::string(cfg_defaults::AMCL_MAP_PATH);
    c.amcl_origin_x_m           = cfg_defaults::AMCL_ORIGIN_X_M;
    c.amcl_origin_y_m           = cfg_defaults::AMCL_ORIGIN_Y_M;
    c.amcl_particles_global_n   = cfg_defaults::AMCL_PARTICLES_GLOBAL_N;
    c.amcl_particles_local_n    = cfg_defaults::AMCL_PARTICLES_LOCAL_N;
    c.amcl_max_iters            = cfg_defaults::AMCL_MAX_ITERS;
    c.amcl_sigma_hit_m          = cfg_defaults::AMCL_SIGMA_HIT_M;
    c.amcl_sigma_xy_jitter_m    = cfg_defaults::AMCL_SIGMA_XY_JITTER_M;
    c.amcl_sigma_yaw_jitter_deg = cfg_defaults::AMCL_SIGMA_YAW_JITTER_DEG;
    c.amcl_sigma_seed_xy_m      = cfg_defaults::AMCL_SIGMA_SEED_XY_M;
    c.amcl_sigma_seed_yaw_deg   = cfg_defaults::AMCL_SIGMA_SEED_YAW_DEG;
    c.amcl_downsample_stride    = cfg_defaults::AMCL_DOWNSAMPLE_STRIDE;
    c.amcl_range_min_m          = cfg_defaults::AMCL_RANGE_MIN_M;
    c.amcl_range_max_m          = cfg_defaults::AMCL_RANGE_MAX_M;
    c.amcl_converge_xy_std_m    = cfg_defaults::AMCL_CONVERGE_XY_STD_M;
    c.amcl_converge_yaw_std_deg = cfg_defaults::AMCL_CONVERGE_YAW_STD_DEG;
    c.amcl_yaw_tripwire_deg     = cfg_defaults::AMCL_YAW_TRIPWIRE_DEG;
    c.amcl_trigger_poll_ms      = cfg_defaults::AMCL_TRIGGER_POLL_MS;
    c.amcl_seed                 = cfg_defaults::AMCL_SEED;

    c.amcl_sigma_xy_jitter_live_m    = cfg_defaults::AMCL_SIGMA_XY_JITTER_LIVE_M;
    c.amcl_sigma_yaw_jitter_live_deg = cfg_defaults::AMCL_SIGMA_YAW_JITTER_LIVE_DEG;

    c.gpio_calibrate_pin        = cfg_defaults::GPIO_CALIBRATE_PIN;
    c.gpio_live_toggle_pin      = cfg_defaults::GPIO_LIVE_TOGGLE_PIN;

    // Track D-5 — annealing defaults.
    c.amcl_sigma_hit_schedule_m =
        parse_csv_doubles_or_throw(cfg_defaults::AMCL_SIGMA_HIT_SCHEDULE_M,
                                   "AMCL_SIGMA_HIT_SCHEDULE_M");
    c.amcl_sigma_seed_xy_schedule_m =
        parse_csv_doubles_with_sentinel_or_throw(
            cfg_defaults::AMCL_SIGMA_SEED_XY_SCHEDULE_M,
            "AMCL_SIGMA_SEED_XY_SCHEDULE_M");
    c.amcl_anneal_iters_per_phase = cfg_defaults::AMCL_ANNEAL_ITERS_PER_PHASE;

    // issue#11 — fork-join particle eval pool default.
    c.amcl_parallel_eval_workers  = cfg_defaults::AMCL_PARALLEL_EVAL_WORKERS_DEFAULT;

    // issue#3 — hint-σ defaults.
    c.amcl_hint_sigma_xy_m_default    = cfg_defaults::AMCL_HINT_SIGMA_XY_M_DEFAULT;
    c.amcl_hint_sigma_yaw_deg_default = cfg_defaults::AMCL_HINT_SIGMA_YAW_DEG_DEFAULT;

    // issue#5 — Live pipelined-hint kernel defaults.
    c.live_carry_pose_as_hint        = cfg_defaults::LIVE_CARRY_POSE_AS_HINT;
    c.amcl_live_carry_sigma_xy_m     = cfg_defaults::AMCL_LIVE_CARRY_SIGMA_XY_M;
    c.amcl_live_carry_sigma_yaw_deg  = cfg_defaults::AMCL_LIVE_CARRY_SIGMA_YAW_DEG;
    c.amcl_live_carry_schedule_m     =
        parse_csv_doubles_or_throw(cfg_defaults::AMCL_LIVE_CARRY_SCHEDULE_M,
                                   "AMCL_LIVE_CARRY_SCHEDULE_M");

    // issue#12 — webctl-owned defaults (CODEBASE.md (r)).
    c.webctl_pose_stream_hz          = cfg_defaults::WEBCTL_POSE_STREAM_HZ_DEFAULT;
    c.webctl_scan_stream_hz          = cfg_defaults::WEBCTL_SCAN_STREAM_HZ_DEFAULT;

    // issue#14 Maj-1 / issue#16.1 — webctl-owned mapping-stop timing ladder defaults.
    c.webctl_mapping_docker_stop_grace_s          = cfg_defaults::WEBCTL_MAPPING_DOCKER_STOP_GRACE_S_DEFAULT;
    c.webctl_mapping_systemctl_subprocess_timeout_s = cfg_defaults::WEBCTL_MAPPING_SYSTEMCTL_SUBPROCESS_TIMEOUT_S_DEFAULT;
    c.webctl_mapping_systemd_stop_timeout_s        = cfg_defaults::WEBCTL_MAPPING_SYSTEMD_STOP_TIMEOUT_S_DEFAULT;
    c.webctl_mapping_webctl_stop_timeout_s         = cfg_defaults::WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S_DEFAULT;

    // issue#27 — final-output transform + OriginPicker step defaults.
    c.output_transform_x_offset_m       = cfg_defaults::OUTPUT_TRANSFORM_X_OFFSET_M_DEFAULT;
    c.output_transform_y_offset_m       = cfg_defaults::OUTPUT_TRANSFORM_Y_OFFSET_M_DEFAULT;
    c.output_transform_z_offset_m       = cfg_defaults::OUTPUT_TRANSFORM_Z_OFFSET_M_DEFAULT;
    c.output_transform_pan_offset_deg   = cfg_defaults::OUTPUT_TRANSFORM_PAN_OFFSET_DEG_DEFAULT;
    c.output_transform_tilt_offset_deg  = cfg_defaults::OUTPUT_TRANSFORM_TILT_OFFSET_DEG_DEFAULT;
    c.output_transform_roll_offset_deg  = cfg_defaults::OUTPUT_TRANSFORM_ROLL_OFFSET_DEG_DEFAULT;
    c.output_transform_x_sign           = cfg_defaults::OUTPUT_TRANSFORM_X_SIGN_DEFAULT;
    c.output_transform_y_sign           = cfg_defaults::OUTPUT_TRANSFORM_Y_SIGN_DEFAULT;
    c.output_transform_z_sign           = cfg_defaults::OUTPUT_TRANSFORM_Z_SIGN_DEFAULT;
    c.output_transform_pan_sign         = cfg_defaults::OUTPUT_TRANSFORM_PAN_SIGN_DEFAULT;
    c.output_transform_tilt_sign        = cfg_defaults::OUTPUT_TRANSFORM_TILT_SIGN_DEFAULT;
    c.output_transform_roll_sign        = cfg_defaults::OUTPUT_TRANSFORM_ROLL_SIGN_DEFAULT;
    c.origin_step_x_m                   = cfg_defaults::ORIGIN_STEP_X_M_DEFAULT;
    c.origin_step_y_m                   = cfg_defaults::ORIGIN_STEP_Y_M_DEFAULT;
    c.origin_step_yaw_deg               = cfg_defaults::ORIGIN_STEP_YAW_DEG_DEFAULT;

    return c;
}

Config Config::load(int argc, char** argv, char** envp) {
    Config c = make_default();

    // TOML — optional file; explicit path via env var wins over the
    // default /var/lib/godo/tracker.toml. Default lives under /var/lib
    // because the systemd unit declares ReadOnlyPaths=/etc/godo +
    // ProtectSystem=strict; the atomic-rename writer needs a parent
    // directory the tracker process can mkstemp+rename in. Operators
    // who want a different path override via GODO_CONFIG_PATH in
    // /etc/godo/tracker.env. Silently skip if neither exists.
    std::filesystem::path toml_path;
    if (auto p = env_get(envp, "GODO_CONFIG_PATH"); p) {
        toml_path = *p;
        if (!std::filesystem::exists(toml_path)) {
            throw std::runtime_error(
                "config: GODO_CONFIG_PATH='" + toml_path.string() +
                "' was set but the file does not exist");
        }
    } else if (std::filesystem::exists("/var/lib/godo/tracker.toml")) {
        toml_path = "/var/lib/godo/tracker.toml";
    }
    if (!toml_path.empty()) {
        apply_toml_file(c, toml_path);
    }

    apply_env(c, envp);
    apply_cli(c, argc, argv);
    validate_amcl(c);
    validate_gpio(c);
    validate_webctl_mapping_ladder(c);

    return c;
}

}  // namespace godo::core
