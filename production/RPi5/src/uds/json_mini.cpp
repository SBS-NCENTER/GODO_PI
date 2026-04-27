#include "json_mini.hpp"

#include <cctype>
#include <cstdio>
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

// Field order pin — MUST match godo::rt::LastPose declaration in
// core/rt_types.hpp. The Python mirror godo-webctl/protocol.py::
// LAST_POSE_FIELDS is regex-extracted from this format string at test
// time (see tests/test_protocol.py drift pin). Touching the field names
// here breaks the Python mirror; touch both in the same commit.
//
// Precision split (F8):
//   - pose fields (x_m, y_m, yaw_deg)            → %.6f  (µm / µdeg)
//   - std fields  (xy_std_m, yaw_std_deg)        → %.9g  (full mantissa)
//   - published_mono_ns                          → %llu  (uint64_t)
//   - integers (iterations)                      → %d
//   - flags    (valid, converged, forced)        → %u    (uint8_t → unsigned int)
//
// Worst-case reply size budget (F17 pin): well under 512 B — the longest
// double rendering is ~25 chars, 5 doubles + 1 uint64 + 1 int + 3 flags =
// ~250 chars of payload + ~120 chars of fixed JSON structure ≈ 370 B max.
// tests/test_uds_server.cpp pins this with a 512 B assertion.
std::string format_ok_pose(const godo::rt::LastPose& p) {
    char buf[512];
    const int n = std::snprintf(buf, sizeof(buf),
        "{\"ok\":true,\"valid\":%u,\"x_m\":%.6f,\"y_m\":%.6f,"
        "\"yaw_deg\":%.6f,\"xy_std_m\":%.9g,\"yaw_std_deg\":%.9g,"
        "\"iterations\":%d,\"converged\":%u,\"forced\":%u,"
        "\"published_mono_ns\":%llu}\n",
        static_cast<unsigned>(p.valid),
        p.x_m, p.y_m, p.yaw_deg,
        p.xy_std_m, p.yaw_std_deg,
        static_cast<int>(p.iterations),
        static_cast<unsigned>(p.converged),
        static_cast<unsigned>(p.forced),
        static_cast<unsigned long long>(p.published_mono_ns));
    if (n <= 0) {
        // snprintf returned encoding error — fall back to a minimal
        // valid=0 reply so the client receives something parseable.
        return std::string("{\"ok\":true,\"valid\":0,\"x_m\":0.000000,"
            "\"y_m\":0.000000,\"yaw_deg\":0.000000,\"xy_std_m\":0,"
            "\"yaw_std_deg\":0,\"iterations\":-1,\"converged\":0,"
            "\"forced\":0,\"published_mono_ns\":0}\n");
    }
    // Truncation guard: if snprintf would have written more than the
    // buffer holds, n is the would-have-been length; clamp to buffer.
    const std::size_t len = (static_cast<std::size_t>(n) >= sizeof(buf))
                            ? sizeof(buf) - 1
                            : static_cast<std::size_t>(n);
    return std::string(buf, len);
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
