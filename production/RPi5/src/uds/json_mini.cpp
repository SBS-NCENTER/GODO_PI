#include "json_mini.hpp"

#include <cctype>
#include <string>

namespace godo::uds {

namespace {

// Skip ASCII whitespace; returns the position of the next non-WS char or
// sv.size() if exhausted.
std::size_t skip_ws(std::string_view sv, std::size_t i) noexcept {
    while (i < sv.size() &&
           (sv[i] == ' ' || sv[i] == '\t' || sv[i] == '\n' || sv[i] == '\r')) {
        ++i;
    }
    return i;
}

// Expects `sv[i] == c`; returns i+1 on match, npos on miss.
std::size_t expect(std::string_view sv, std::size_t i, char c) noexcept {
    if (i >= sv.size() || sv[i] != c) return std::string_view::npos;
    return i + 1;
}

// Parse a bare-ASCII JSON string (no escapes). Stores contents in `out`,
// returns the index after the closing quote, or npos on error.
std::size_t parse_string(std::string_view sv, std::size_t i,
                         std::string& out) {
    i = expect(sv, i, '"');
    if (i == std::string_view::npos) return std::string_view::npos;
    const std::size_t start = i;
    while (i < sv.size() && sv[i] != '"') {
        // Reject backslash escapes — schema is pure ASCII.
        if (sv[i] == '\\') return std::string_view::npos;
        ++i;
    }
    if (i >= sv.size()) return std::string_view::npos;  // unterminated
    out.assign(sv.data() + start, i - start);
    return i + 1;  // skip closing quote
}

}  // namespace

Request parse_request(std::string_view line) {
    Request req;
    std::size_t i = skip_ws(line, 0);
    i = expect(line, i, '{');
    if (i == std::string_view::npos) return {};

    bool got_cmd  = false;
    bool got_mode = false;
    bool first    = true;

    while (true) {
        i = skip_ws(line, i);
        if (i < line.size() && line[i] == '}') { ++i; break; }
        if (!first) {
            i = expect(line, i, ',');
            if (i == std::string_view::npos) return {};
            i = skip_ws(line, i);
        }
        first = false;

        std::string key;
        i = parse_string(line, i, key);
        if (i == std::string_view::npos) return {};
        i = skip_ws(line, i);
        i = expect(line, i, ':');
        if (i == std::string_view::npos) return {};
        i = skip_ws(line, i);

        std::string value;
        i = parse_string(line, i, value);
        if (i == std::string_view::npos) return {};

        if (key == "cmd") {
            if (got_cmd) return {};      // duplicate key
            req.cmd = std::move(value);
            got_cmd = true;
        } else if (key == "mode") {
            if (got_mode) return {};
            req.mode_arg = std::move(value);
            got_mode = true;
        } else {
            return {};                   // unknown key
        }
    }

    // Trailing whitespace / newline is OK; any non-WS after the closing
    // brace is a parse error.
    i = skip_ws(line, i);
    if (i != line.size()) return {};

    if (!got_cmd) return {};
    return req;
}

std::string format_ok() {
    return std::string("{\"ok\":true}\n");
}

std::string format_ok_mode(godo::rt::AmclMode mode) {
    std::string s = "{\"ok\":true,\"mode\":\"";
    s.append(mode_to_string(mode));
    s.append("\"}\n");
    return s;
}

std::string format_err(std::string_view code) {
    std::string s = "{\"ok\":false,\"err\":\"";
    s.append(code);
    s.append("\"}\n");
    return s;
}

std::string_view mode_to_string(godo::rt::AmclMode mode) noexcept {
    switch (mode) {
        case godo::rt::AmclMode::Idle:    return "Idle";
        case godo::rt::AmclMode::OneShot: return "OneShot";
        case godo::rt::AmclMode::Live:    return "Live";
    }
    return "Idle";
}

bool parse_mode_arg(std::string_view arg, godo::rt::AmclMode& out) noexcept {
    if (arg == "Idle")    { out = godo::rt::AmclMode::Idle;    return true; }
    if (arg == "OneShot") { out = godo::rt::AmclMode::OneShot; return true; }
    if (arg == "Live")    { out = godo::rt::AmclMode::Live;    return true; }
    return false;
}

}  // namespace godo::uds
