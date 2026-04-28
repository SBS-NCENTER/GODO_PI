#include "json_mini.hpp"

#include <cctype>
#include <cstdio>
#include <string>

#include "core/constants.hpp"

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

// Field order pin — MUST match godo::rt::LastScan declaration in
// core/rt_types.hpp. The Python mirror godo-webctl/protocol.py::
// LAST_SCAN_HEADER_FIELDS is regex-extracted from rt_types.hpp at
// test time (tests/test_protocol.py drift pin). Touching the field
// names or order here without updating rt_types.hpp + the Python
// mirror breaks the drift pin; touch all three in the same commit.
//
// Precision split (Track D):
//   - pose anchors  → %.6f  (µm / µdeg)
//   - ranges_m[i]   → %.4f  (0.1 mm; below C1 ~25 mm noise floor)
//   - angles_deg[i] → %.4f  (0.0001°; below C1 ~0.36° step)
//   - published_mono_ns → %llu (uint64_t)
//   - iterations    → %d
//   - flags         → %u    (uint8_t → unsigned int)
//
// Worst-case payload size pin: header (~250 B) + 720 angles × ~12 B
// + array structure + 720 ranges × ~12 B ≈ 17.5 KiB. JSON_SCRATCH_BYTES
// (24 KiB) leaves >35% headroom; the static_assert below catches a
// future precision bump that would push past the cap.
std::string format_ok_scan(const godo::rt::LastScan& s) {
    static_assert(godo::constants::JSON_SCRATCH_BYTES >= 24576,
                  "format_ok_scan worst case requires >= 24 KiB scratch");
    char buf[godo::constants::JSON_SCRATCH_BYTES];

    // Clamp `n` at the wire cap. The cold writer applies the same
    // bound at publish time, so this is a defence-in-depth — a malformed
    // snapshot from a future regression cannot blow the buffer.
    const std::size_t n = (s.n > godo::constants::LAST_SCAN_RANGES_MAX)
        ? static_cast<std::size_t>(godo::constants::LAST_SCAN_RANGES_MAX)
        : static_cast<std::size_t>(s.n);

    int wrote = std::snprintf(buf, sizeof(buf),
        "{\"ok\":true,\"valid\":%u,\"forced\":%u,\"pose_valid\":%u,"
        "\"iterations\":%d,\"published_mono_ns\":%llu,"
        "\"pose_x_m\":%.6f,\"pose_y_m\":%.6f,\"pose_yaw_deg\":%.6f,"
        "\"n\":%u,\"angles_deg\":[",
        static_cast<unsigned>(s.valid),
        static_cast<unsigned>(s.forced),
        static_cast<unsigned>(s.pose_valid),
        static_cast<int>(s.iterations),
        static_cast<unsigned long long>(s.published_mono_ns),
        s.pose_x_m, s.pose_y_m, s.pose_yaw_deg,
        static_cast<unsigned>(n));
    if (wrote <= 0 || static_cast<std::size_t>(wrote) >= sizeof(buf)) {
        return std::string("{\"ok\":true,\"valid\":0,\"forced\":0,"
            "\"pose_valid\":0,\"iterations\":-1,\"published_mono_ns\":0,"
            "\"pose_x_m\":0.000000,\"pose_y_m\":0.000000,"
            "\"pose_yaw_deg\":0.000000,\"n\":0,\"angles_deg\":[],"
            "\"ranges_m\":[]}\n");
    }
    std::size_t pos = static_cast<std::size_t>(wrote);

    // angles_deg array body.
    for (std::size_t i = 0; i < n; ++i) {
        const char* sep = (i == 0) ? "" : ",";
        const int w = std::snprintf(buf + pos, sizeof(buf) - pos,
            "%s%.4f", sep, s.angles_deg[i]);
        if (w <= 0 || static_cast<std::size_t>(w) >= sizeof(buf) - pos) {
            // Truncation guard: emit a structurally valid but empty reply
            // rather than a half-formed JSON line.
            return std::string("{\"ok\":true,\"valid\":0,\"forced\":0,"
                "\"pose_valid\":0,\"iterations\":-1,\"published_mono_ns\":0,"
                "\"pose_x_m\":0.000000,\"pose_y_m\":0.000000,"
                "\"pose_yaw_deg\":0.000000,\"n\":0,\"angles_deg\":[],"
                "\"ranges_m\":[]}\n");
        }
        pos += static_cast<std::size_t>(w);
    }

    int w = std::snprintf(buf + pos, sizeof(buf) - pos, "],\"ranges_m\":[");
    if (w <= 0 || static_cast<std::size_t>(w) >= sizeof(buf) - pos) {
        return std::string("{\"ok\":true,\"valid\":0,\"forced\":0,"
            "\"pose_valid\":0,\"iterations\":-1,\"published_mono_ns\":0,"
            "\"pose_x_m\":0.000000,\"pose_y_m\":0.000000,"
            "\"pose_yaw_deg\":0.000000,\"n\":0,\"angles_deg\":[],"
            "\"ranges_m\":[]}\n");
    }
    pos += static_cast<std::size_t>(w);

    // ranges_m array body.
    for (std::size_t i = 0; i < n; ++i) {
        const char* sep = (i == 0) ? "" : ",";
        const int rw = std::snprintf(buf + pos, sizeof(buf) - pos,
            "%s%.4f", sep, s.ranges_m[i]);
        if (rw <= 0 || static_cast<std::size_t>(rw) >= sizeof(buf) - pos) {
            return std::string("{\"ok\":true,\"valid\":0,\"forced\":0,"
                "\"pose_valid\":0,\"iterations\":-1,\"published_mono_ns\":0,"
                "\"pose_x_m\":0.000000,\"pose_y_m\":0.000000,"
                "\"pose_yaw_deg\":0.000000,\"n\":0,\"angles_deg\":[],"
                "\"ranges_m\":[]}\n");
        }
        pos += static_cast<std::size_t>(rw);
    }

    const int closer = std::snprintf(buf + pos, sizeof(buf) - pos, "]}\n");
    if (closer <= 0 || static_cast<std::size_t>(closer) >= sizeof(buf) - pos) {
        return std::string("{\"ok\":true,\"valid\":0,\"forced\":0,"
            "\"pose_valid\":0,\"iterations\":-1,\"published_mono_ns\":0,"
            "\"pose_x_m\":0.000000,\"pose_y_m\":0.000000,"
            "\"pose_yaw_deg\":0.000000,\"n\":0,\"angles_deg\":[],"
            "\"ranges_m\":[]}\n");
    }
    pos += static_cast<std::size_t>(closer);

    return std::string(buf, pos);
}

// Field order pin — MUST match godo::rt::JitterSnapshot declaration in
// core/rt_types.hpp. The Python mirror godo-webctl/protocol.py::
// JITTER_FIELDS is regex-pinned against this format string at test time
// (tests/test_protocol.py drift pin). Touching the field names here
// breaks the Python mirror; touch both in the same commit.
//
// Precision split (PR-DIAG): %lld for signed-ns scalars, %llu for
// uint64, %u for the uint8 valid flag.
std::string format_ok_jitter(const godo::rt::JitterSnapshot& j) {
    static_assert(godo::constants::JITTER_FORMAT_SCRATCH_BYTES >= 512,
                  "format_ok_jitter worst case requires >= 512 B scratch");
    char buf[godo::constants::JITTER_FORMAT_SCRATCH_BYTES];
    const int n = std::snprintf(buf, sizeof(buf),
        "{\"ok\":true,\"valid\":%u,\"p50_ns\":%lld,\"p95_ns\":%lld,"
        "\"p99_ns\":%lld,\"max_ns\":%lld,\"mean_ns\":%lld,"
        "\"sample_count\":%llu,\"published_mono_ns\":%llu}\n",
        static_cast<unsigned>(j.valid),
        static_cast<long long>(j.p50_ns),
        static_cast<long long>(j.p95_ns),
        static_cast<long long>(j.p99_ns),
        static_cast<long long>(j.max_ns),
        static_cast<long long>(j.mean_ns),
        static_cast<unsigned long long>(j.sample_count),
        static_cast<unsigned long long>(j.published_mono_ns));
    if (n <= 0) {
        return std::string("{\"ok\":true,\"valid\":0,\"p50_ns\":0,"
            "\"p95_ns\":0,\"p99_ns\":0,\"max_ns\":0,\"mean_ns\":0,"
            "\"sample_count\":0,\"published_mono_ns\":0}\n");
    }
    const std::size_t len = (static_cast<std::size_t>(n) >= sizeof(buf))
                            ? sizeof(buf) - 1
                            : static_cast<std::size_t>(n);
    return std::string(buf, len);
}

// Field order pin — MUST match godo::rt::AmclIterationRate declaration in
// core/rt_types.hpp. The Python mirror godo-webctl/protocol.py::
// AMCL_RATE_FIELDS is regex-pinned against this format string at test
// time. Mode-A M2 fold renamed scan_rate → amcl_iteration_rate.
std::string format_ok_amcl_rate(const godo::rt::AmclIterationRate& r) {
    static_assert(godo::constants::AMCL_RATE_FORMAT_SCRATCH_BYTES >= 256,
                  "format_ok_amcl_rate worst case requires >= 256 B scratch");
    char buf[godo::constants::AMCL_RATE_FORMAT_SCRATCH_BYTES];
    const int n = std::snprintf(buf, sizeof(buf),
        "{\"ok\":true,\"valid\":%u,\"hz\":%.6f,"
        "\"last_iteration_mono_ns\":%llu,\"total_iteration_count\":%llu,"
        "\"published_mono_ns\":%llu}\n",
        static_cast<unsigned>(r.valid),
        r.hz,
        static_cast<unsigned long long>(r.last_iteration_mono_ns),
        static_cast<unsigned long long>(r.total_iteration_count),
        static_cast<unsigned long long>(r.published_mono_ns));
    if (n <= 0) {
        return std::string("{\"ok\":true,\"valid\":0,\"hz\":0.000000,"
            "\"last_iteration_mono_ns\":0,\"total_iteration_count\":0,"
            "\"published_mono_ns\":0}\n");
    }
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
