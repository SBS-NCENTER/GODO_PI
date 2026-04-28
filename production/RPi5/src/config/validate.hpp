#pragma once

// Pure validation of a single (key, value_text) pair against
// CONFIG_SCHEMA. Track B-CONFIG (PR-CONFIG-α) — no file I/O, no Config
// mutation; the caller (config/apply.cpp) does the side effects.
//
// Error code surface (matches the wire `err` field):
//   - ""           — ok; `parsed_double` and `parsed_string` populated.
//   - "bad_key"    — key not in CONFIG_SCHEMA.
//   - "bad_type"   — value_text fails strict parse for the schema type
//                    (int rejects decimal/exp form; double accepts both;
//                    string is verbatim with a length cap).
//   - "bad_value"  — numeric out-of-range OR non-ASCII / over-long string.

#include <string>
#include <string_view>

#include "core/config_schema.hpp"

namespace godo::config {

struct ValidateResult {
    bool                                      ok            = false;
    std::string                               err;
    std::string                               err_detail;
    double                                    parsed_double = 0.0;  // numeric only.
    std::string                               parsed_string;        // String only.
    const godo::core::config_schema::ConfigSchemaRow* row = nullptr;
};

// Validate `value_text` against the schema row for `key`. Pure;
// no allocation beyond the returned result string fields.
ValidateResult validate(std::string_view key, std::string_view value_text);

}  // namespace godo::config
