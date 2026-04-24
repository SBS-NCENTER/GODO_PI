#include "config.hpp"

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <functional>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include <toml++/toml.hpp>

#include "config_defaults.hpp"

namespace godo::core {

namespace {

namespace cfg_defaults = godo::config::defaults;

// Allowed TOML keys, flat "section.key" form. Unknown → error.
const std::set<std::string>& allowed_keys() {
    static const std::set<std::string> k = {
        "network.ue_host",
        "network.ue_port",
        "serial.lidar_port",
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

void apply_env(Config& c, char** envp) {
    if (auto v = env_get(envp, "GODO_UE_HOST"))       c.ue_host = *v;
    if (auto v = env_get(envp, "GODO_UE_PORT"))       c.ue_port = parse_int_or_throw(*v, "GODO_UE_PORT");
    if (auto v = env_get(envp, "GODO_LIDAR_PORT"))    c.lidar_port = *v;
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

}  // namespace

Config Config::make_default() {
    Config c;
    c.ue_host        = std::string(cfg_defaults::UE_HOST);
    c.ue_port        = cfg_defaults::UE_PORT;
    c.lidar_port     = std::string(cfg_defaults::LIDAR_PORT);
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
    return c;
}

Config Config::load(int argc, char** argv, char** envp) {
    Config c = make_default();

    // TOML — optional file; explicit path via env var wins over the default
    // /etc/godo/tracker.toml. Silently skip if neither exists.
    std::filesystem::path toml_path;
    if (auto p = env_get(envp, "GODO_CONFIG_PATH"); p) {
        toml_path = *p;
        if (!std::filesystem::exists(toml_path)) {
            throw std::runtime_error(
                "config: GODO_CONFIG_PATH='" + toml_path.string() +
                "' was set but the file does not exist");
        }
    } else if (std::filesystem::exists("/etc/godo/tracker.toml")) {
        toml_path = "/etc/godo/tracker.toml";
    }
    if (!toml_path.empty()) {
        apply_toml_file(c, toml_path);
    }

    apply_env(c, envp);
    apply_cli(c, argc, argv);
    return c;
}

}  // namespace godo::core
