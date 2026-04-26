#include "occupancy_grid.hpp"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "core/constants.hpp"

namespace godo::localization {

namespace {

[[noreturn]] void throw_with_path(const std::string& path,
                                  const std::string& detail) {
    throw std::runtime_error(
        "load_map(" + path + "): " + detail);
}

// Trim ASCII whitespace from both ends in place.
void trim(std::string& s) {
    auto not_space = [](unsigned char c) { return !std::isspace(c); };
    auto front = std::find_if(s.begin(), s.end(), not_space);
    s.erase(s.begin(), front);
    auto back = std::find_if(s.rbegin(), s.rend(), not_space).base();
    s.erase(back, s.end());
}

// Read a PGM P5 token, skipping ASCII whitespace and `#` comments per the
// PGM spec. Returns false on EOF.
bool read_pgm_token(std::ifstream& f, std::string& tok) {
    tok.clear();
    int c = f.get();
    while (c != EOF) {
        if (c == '#') {
            while (c != EOF && c != '\n') c = f.get();
            c = f.get();
        } else if (std::isspace(static_cast<unsigned char>(c))) {
            c = f.get();
        } else {
            break;
        }
    }
    if (c == EOF) return false;
    while (c != EOF && !std::isspace(static_cast<unsigned char>(c))) {
        tok.push_back(static_cast<char>(c));
        c = f.get();
    }
    return !tok.empty();
}

struct YamlFields {
    std::string image;
    double      resolution = -1.0;
    double      origin_x = 0.0;
    double      origin_y = 0.0;
    double      origin_yaw = 0.0;
    double      occupied_thresh = -1.0;
    double      free_thresh = -1.0;
    int         negate = -1;
    bool        has_image = false;
    bool        has_resolution = false;
    bool        has_origin = false;
    bool        has_occupied_thresh = false;
    bool        has_free_thresh = false;
    bool        has_negate = false;
};

// Strip a trailing inline-comment '# ...' that is NOT inside a quoted
// string. The slam_toolbox emitter does not produce inline comments,
// but hand-edited fixtures may; matching that surface keeps test fixtures
// readable.
void strip_inline_comment(std::string& v) {
    bool in_quote = false;
    char quote = '\0';
    for (std::size_t i = 0; i < v.size(); ++i) {
        const char c = v[i];
        if (!in_quote) {
            if (c == '"' || c == '\'') { in_quote = true; quote = c; continue; }
            if (c == '#') { v.erase(i); break; }
        } else if (c == quote) {
            in_quote = false;
        }
    }
}

// Strip surrounding double or single quotes if present.
void unquote(std::string& s) {
    if (s.size() >= 2 &&
        ((s.front() == '"' && s.back() == '"') ||
         (s.front() == '\'' && s.back() == '\''))) {
        s = s.substr(1, s.size() - 2);
    }
}

// Parse a YAML "[a, b, c]" list of three numeric values into out.
// Throws on shape mismatch.
void parse_three_floats(const std::string& v,
                        const std::string& path,
                        double& a, double& b, double& c) {
    auto open = v.find('[');
    auto close = v.rfind(']');
    if (open == std::string::npos || close == std::string::npos ||
        close < open) {
        throw_with_path(path,
            "origin must be a YAML flow list '[x, y, yaw]'; got: '" + v + "'");
    }
    std::string inner = v.substr(open + 1, close - open - 1);
    std::stringstream ss(inner);
    std::string item;
    double parsed[3] = {0.0, 0.0, 0.0};
    int idx = 0;
    while (std::getline(ss, item, ',')) {
        if (idx >= 3) {
            throw_with_path(path,
                "origin list expected 3 values; got more in: '" + v + "'");
        }
        trim(item);
        try {
            parsed[idx++] = std::stod(item);
        } catch (const std::exception&) {
            throw_with_path(path,
                "origin element '" + item + "' is not a number");
        }
    }
    if (idx != 3) {
        throw_with_path(path,
            "origin list expected 3 values; got " +
            std::to_string(idx) + " in: '" + v + "'");
    }
    a = parsed[0];
    b = parsed[1];
    c = parsed[2];
}

YamlFields parse_yaml(const std::string& yaml_path) {
    std::ifstream f(yaml_path);
    if (!f) {
        throw_with_path(yaml_path,
            "cannot open YAML companion file");
    }
    static const std::set<std::string> required = {
        "image", "resolution", "origin",
        "occupied_thresh", "free_thresh", "negate",
    };
    static const std::set<std::string> warn_accept = {
        "mode", "unknown_thresh",
    };

    YamlFields out;
    std::string line;
    int line_no = 0;
    while (std::getline(f, line)) {
        ++line_no;
        // Strip BOM on first line.
        if (line_no == 1 && line.size() >= 3 &&
            static_cast<unsigned char>(line[0]) == 0xEF &&
            static_cast<unsigned char>(line[1]) == 0xBB &&
            static_cast<unsigned char>(line[2]) == 0xBF) {
            line.erase(0, 3);
        }
        // Whole-line comment / blank.
        std::string trimmed = line;
        trim(trimmed);
        if (trimmed.empty() || trimmed[0] == '#') continue;

        const auto colon = trimmed.find(':');
        if (colon == std::string::npos) {
            throw_with_path(yaml_path,
                "line " + std::to_string(line_no) +
                ": missing ':' (godo expects a flat key: value YAML)");
        }
        std::string key = trimmed.substr(0, colon);
        std::string val = trimmed.substr(colon + 1);
        trim(key);
        trim(val);
        strip_inline_comment(val);
        trim(val);

        if (required.find(key) == required.end() &&
            warn_accept.find(key) == warn_accept.end()) {
            throw_with_path(yaml_path,
                "unknown YAML key '" + key + "' on line " +
                std::to_string(line_no) +
                "; accepted keys: image, resolution, origin, "
                "occupied_thresh, free_thresh, negate, mode, unknown_thresh");
        }

        if (key == "image") {
            unquote(val);
            out.image = val;
            out.has_image = true;
        } else if (key == "resolution") {
            try {
                out.resolution = std::stod(val);
            } catch (const std::exception&) {
                throw_with_path(yaml_path,
                    "resolution = '" + val + "' is not a number");
            }
            out.has_resolution = true;
        } else if (key == "origin") {
            parse_three_floats(val, yaml_path,
                               out.origin_x, out.origin_y, out.origin_yaw);
            out.has_origin = true;
        } else if (key == "occupied_thresh") {
            try {
                out.occupied_thresh = std::stod(val);
            } catch (const std::exception&) {
                throw_with_path(yaml_path,
                    "occupied_thresh = '" + val + "' is not a number");
            }
            out.has_occupied_thresh = true;
        } else if (key == "free_thresh") {
            try {
                out.free_thresh = std::stod(val);
            } catch (const std::exception&) {
                throw_with_path(yaml_path,
                    "free_thresh = '" + val + "' is not a number");
            }
            out.has_free_thresh = true;
        } else if (key == "negate") {
            try {
                out.negate = std::stoi(val);
            } catch (const std::exception&) {
                throw_with_path(yaml_path,
                    "negate = '" + val + "' is not an integer");
            }
            if (out.negate != 0 && out.negate != 1) {
                throw_with_path(yaml_path,
                    "negate must be 0 or 1; got " + std::to_string(out.negate));
            }
            out.has_negate = true;
        }
        // mode / unknown_thresh: accepted, ignored. slam_toolbox emits
        // them; godo's likelihood field doesn't currently differentiate.
    }

    if (!out.has_image)           throw_with_path(yaml_path, "missing required key 'image'");
    if (!out.has_resolution)      throw_with_path(yaml_path, "missing required key 'resolution'");
    if (!out.has_origin)          throw_with_path(yaml_path, "missing required key 'origin'");
    if (!out.has_occupied_thresh) throw_with_path(yaml_path, "missing required key 'occupied_thresh'");
    if (!out.has_free_thresh)     throw_with_path(yaml_path, "missing required key 'free_thresh'");
    if (!out.has_negate)          throw_with_path(yaml_path, "missing required key 'negate'");
    return out;
}

std::string yaml_path_for(const std::string& pgm_path) {
    if (pgm_path.size() >= 4 &&
        pgm_path.substr(pgm_path.size() - 4) == ".pgm") {
        return pgm_path.substr(0, pgm_path.size() - 4) + ".yaml";
    }
    return pgm_path + ".yaml";
}

}  // namespace

OccupancyGrid load_map(const std::string& pgm_path) {
    const std::string yaml_path = yaml_path_for(pgm_path);
    YamlFields y = parse_yaml(yaml_path);

    std::ifstream f(pgm_path, std::ios::binary);
    if (!f) {
        throw_with_path(pgm_path, "cannot open PGM file");
    }

    // Header.
    std::string magic, w_tok, h_tok, max_tok;
    if (!read_pgm_token(f, magic) || magic != "P5") {
        throw_with_path(pgm_path, "not a P5 binary PGM (got header '" + magic + "')");
    }
    if (!read_pgm_token(f, w_tok) || !read_pgm_token(f, h_tok) ||
        !read_pgm_token(f, max_tok)) {
        throw_with_path(pgm_path, "truncated PGM header");
    }
    int width = 0, height = 0, maxval = 0;
    try {
        width  = std::stoi(w_tok);
        height = std::stoi(h_tok);
        maxval = std::stoi(max_tok);
    } catch (const std::exception&) {
        throw_with_path(pgm_path,
            "PGM header has non-integer dimensions ('" +
            w_tok + " " + h_tok + " " + max_tok + "')");
    }
    if (width <= 0 || height <= 0) {
        throw_with_path(pgm_path,
            "PGM dimensions must be positive (got " +
            std::to_string(width) + "x" + std::to_string(height) + ")");
    }
    if (maxval != 255) {
        throw_with_path(pgm_path,
            "PGM maxval must be 255 (8-bit single-channel); got " +
            std::to_string(maxval));
    }
    const std::int64_t cells64 =
        static_cast<std::int64_t>(width) * static_cast<std::int64_t>(height);
    if (cells64 > godo::constants::EDT_MAX_CELLS) {
        throw_with_path(pgm_path,
            "map dimensions " + std::to_string(width) + "x" +
            std::to_string(height) + " (" + std::to_string(cells64) +
            " cells) exceed EDT_MAX_CELLS (" +
            std::to_string(godo::constants::EDT_MAX_CELLS) +
            "); raise the constant in core/constants.hpp or shrink the map");
    }

    // PGM convention: header tokens are followed by a single whitespace, then
    // the binary blob. read_pgm_token already consumed exactly the maxval
    // token, leaving the file position at the byte right after it (one whitespace
    // is part of the spec; if a sentinel char remains it's still safe to just
    // read width*height bytes from here per the GIMP / map_server emitter).
    const std::size_t cells_n = static_cast<std::size_t>(cells64);
    std::vector<std::uint8_t> cells(cells_n, 0);
    f.read(reinterpret_cast<char*>(cells.data()),
           static_cast<std::streamsize>(cells_n));
    const auto got = f.gcount();
    if (got != static_cast<std::streamsize>(cells_n)) {
        throw_with_path(pgm_path,
            "PGM payload truncated: expected " + std::to_string(cells_n) +
            " bytes, got " + std::to_string(static_cast<long long>(got)));
    }

    OccupancyGrid g{};
    g.width          = width;
    g.height         = height;
    g.resolution_m   = y.resolution;
    g.origin_x_m     = y.origin_x;
    g.origin_y_m     = y.origin_y;
    g.origin_yaw_deg = y.origin_yaw;
    g.cells          = std::move(cells);
    return g;
}

}  // namespace godo::localization
