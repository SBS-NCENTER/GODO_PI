#include "validate.hpp"

#include <cctype>
#include <cstdlib>
#include <string>

namespace godo::config {

namespace {

using godo::core::config_schema::ConfigSchemaRow;
using godo::core::config_schema::ValueType;

// Track B-CONFIG: cap on the string-type config values. Wider than
// CONFIG_VALUE_TEXT_MAX_LEN (256) on the webctl side because the C++
// validator is the last line of defence; align with CONFIG_VALUE_TEXT_MAX
// in core/constants.hpp via an inline constant here to avoid a Tier-1
// addition for a single defensive cap. 256 mirrors webctl.
constexpr std::size_t kStringValueMaxLen = 256;

bool is_ascii_printable(std::string_view s) noexcept {
    for (char c : s) {
        const unsigned char u = static_cast<unsigned char>(c);
        // Allow space..tilde inclusive; reject control characters and
        // non-ASCII high bytes.
        if (u < 0x20 || u > 0x7E) return false;
    }
    return true;
}

// Strict int parse: reject decimal point, exponent marker, leading
// whitespace, trailing characters. Empty input is rejected.
bool parse_strict_int(std::string_view s, long long& out) noexcept {
    if (s.empty()) return false;
    for (char c : s) {
        if (c == '.' || c == 'e' || c == 'E') return false;
    }
    const std::string copy(s);
    char* end = nullptr;
    errno = 0;
    const long long v = std::strtoll(copy.c_str(), &end, 10);
    if (errno != 0) return false;
    if (end == nullptr || *end != '\0') return false;
    out = v;
    return true;
}

// Lenient double parse: accepts integer literal form (`5`) and float
// form (`5.0`, `5e-3`). Rejects trailing characters and empty.
bool parse_strict_double(std::string_view s, double& out) noexcept {
    if (s.empty()) return false;
    const std::string copy(s);
    char* end = nullptr;
    errno = 0;
    const double v = std::strtod(copy.c_str(), &end);
    if (errno != 0) return false;
    if (end == nullptr || *end != '\0') return false;
    out = v;
    return true;
}

}  // namespace

ValidateResult validate(std::string_view key, std::string_view value_text) {
    ValidateResult r;
    const ConfigSchemaRow* row = godo::core::config_schema::find(key);
    if (row == nullptr) {
        r.err        = "bad_key";
        r.err_detail = "unknown key: ";
        r.err_detail.append(key);
        return r;
    }
    r.row = row;

    switch (row->type) {
        case ValueType::Int: {
            long long iv = 0;
            if (!parse_strict_int(value_text, iv)) {
                r.err        = "bad_type";
                r.err_detail.assign(row->name);
                r.err_detail.append(": expected integer literal, got '");
                r.err_detail.append(value_text);
                r.err_detail.append("'");
                return r;
            }
            const double dv = static_cast<double>(iv);
            if (dv < row->min_d || dv > row->max_d) {
                r.err        = "bad_value";
                r.err_detail.assign(row->name);
                r.err_detail.append(": out of range [");
                r.err_detail.append(std::to_string(static_cast<long long>(row->min_d)));
                r.err_detail.append(", ");
                r.err_detail.append(std::to_string(static_cast<long long>(row->max_d)));
                r.err_detail.append("], got ");
                r.err_detail.append(std::to_string(iv));
                return r;
            }
            r.parsed_double = dv;
            r.ok = true;
            return r;
        }
        case ValueType::Double: {
            double dv = 0.0;
            if (!parse_strict_double(value_text, dv)) {
                r.err        = "bad_type";
                r.err_detail.assign(row->name);
                r.err_detail.append(": expected number, got '");
                r.err_detail.append(value_text);
                r.err_detail.append("'");
                return r;
            }
            if (dv < row->min_d || dv > row->max_d) {
                r.err        = "bad_value";
                r.err_detail.assign(row->name);
                r.err_detail.append(": out of range [");
                r.err_detail.append(std::to_string(row->min_d));
                r.err_detail.append(", ");
                r.err_detail.append(std::to_string(row->max_d));
                r.err_detail.append("], got ");
                r.err_detail.append(std::to_string(dv));
                return r;
            }
            r.parsed_double = dv;
            r.ok = true;
            return r;
        }
        case ValueType::String: {
            if (value_text.size() > kStringValueMaxLen) {
                r.err        = "bad_value";
                r.err_detail.assign(row->name);
                r.err_detail.append(": string too long (max 256)");
                return r;
            }
            if (!is_ascii_printable(value_text)) {
                r.err        = "bad_value";
                r.err_detail.assign(row->name);
                r.err_detail.append(": non-ASCII / control characters not allowed");
                return r;
            }
            if (value_text.empty()) {
                r.err        = "bad_value";
                r.err_detail.assign(row->name);
                r.err_detail.append(": empty string not allowed");
                return r;
            }
            r.parsed_string.assign(value_text);
            r.ok = true;
            return r;
        }
    }
    // Unreachable; compiler-warning silencer.
    r.err = "bad_type";
    return r;
}

}  // namespace godo::config
