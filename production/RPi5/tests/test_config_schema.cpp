// Track B-CONFIG (PR-CONFIG-α) — schema table integrity tests.
//
// The schema is the SSOT for the config edit pipeline; drift between
// the count, the alphabetical ordering, and the per-row contents is
// caught here at compile + ctest time.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <set>
#include <string>
#include <string_view>

#include "core/config_schema.hpp"

using godo::core::config_schema::CONFIG_SCHEMA;
using godo::core::config_schema::find;
using godo::core::config_schema::ReloadClass;
using godo::core::config_schema::reload_class_to_string;
using godo::core::config_schema::ValueType;
using godo::core::config_schema::value_type_to_string;

TEST_CASE("CONFIG_SCHEMA has exactly 37 rows (Mode-A M2)") {
    CHECK(CONFIG_SCHEMA.size() == 37);
}

TEST_CASE("CONFIG_SCHEMA rows are alphabetically ordered by name") {
    for (std::size_t i = 1; i < CONFIG_SCHEMA.size(); ++i) {
        const auto prev = CONFIG_SCHEMA[i - 1].name;
        const auto curr = CONFIG_SCHEMA[i].name;
        const std::string msg =
            "ordering broken between '" + std::string(prev) +
            "' and '" + std::string(curr) + "'";
        CHECK_MESSAGE(prev < curr, msg);
    }
}

TEST_CASE("CONFIG_SCHEMA names are unique") {
    std::set<std::string> seen;
    for (const auto& row : CONFIG_SCHEMA) {
        const auto [_it, inserted] = seen.insert(std::string(row.name));
        CHECK(inserted);
    }
    CHECK(seen.size() == CONFIG_SCHEMA.size());
}

TEST_CASE("find() resolves every row by name") {
    for (const auto& row : CONFIG_SCHEMA) {
        const auto* found = find(row.name);
        REQUIRE(found != nullptr);
        CHECK(found->name == row.name);
    }
}

TEST_CASE("find() returns nullptr for unknown keys") {
    CHECK(find("") == nullptr);
    CHECK(find("nope.unknown") == nullptr);
    CHECK(find("smoother.deadband_mm.x") == nullptr);
    CHECK(find("smoother") == nullptr);  // missing leaf
    CHECK(find("amcl") == nullptr);
}

TEST_CASE("reload_class_to_string round-trip") {
    CHECK(reload_class_to_string(ReloadClass::Hot)         == "hot");
    CHECK(reload_class_to_string(ReloadClass::Restart)     == "restart");
    CHECK(reload_class_to_string(ReloadClass::Recalibrate) == "recalibrate");
}

TEST_CASE("value_type_to_string round-trip") {
    CHECK(value_type_to_string(ValueType::Int)    == "int");
    CHECK(value_type_to_string(ValueType::Double) == "double");
    CHECK(value_type_to_string(ValueType::String) == "string");
}

TEST_CASE("Mode-A M2: t_ramp_ms reload class is restart") {
    const auto* row = find("smoother.t_ramp_ms");
    REQUIRE(row != nullptr);
    CHECK(row->reload_class == ReloadClass::Restart);
}

TEST_CASE("Mode-A M2: live-σ rows have updated descriptions") {
    const auto* xy   = find("amcl.sigma_xy_jitter_live_m");
    const auto* yaw  = find("amcl.sigma_yaw_jitter_live_deg");
    REQUIRE(xy  != nullptr);
    REQUIRE(yaw != nullptr);
    CHECK(std::string_view(xy->description).find("Live mode")  != std::string_view::npos);
    CHECK(std::string_view(yaw->description).find("Live mode") != std::string_view::npos);
    CHECK(std::string_view(xy->description).find("per-tick")   != std::string_view::npos);
    CHECK(std::string_view(yaw->description).find("per-tick")  != std::string_view::npos);
}

TEST_CASE("Mode-A M2: seed-σ rows present (count went 35 → 37)") {
    const auto* seed_xy  = find("amcl.sigma_seed_xy_m");
    const auto* seed_yaw = find("amcl.sigma_seed_yaw_deg");
    REQUIRE(seed_xy  != nullptr);
    REQUIRE(seed_yaw != nullptr);
    CHECK(seed_xy->reload_class  == ReloadClass::Recalibrate);
    CHECK(seed_yaw->reload_class == ReloadClass::Recalibrate);
}

TEST_CASE("Each row has a non-empty description and consistent name format") {
    for (const auto& row : CONFIG_SCHEMA) {
        CHECK_FALSE(row.name.empty());
        CHECK_FALSE(row.description.empty());
        CHECK_FALSE(row.default_repr.empty());
        // Every name has exactly one dot (section.leaf form).
        const std::string_view n = row.name;
        const auto first_dot = n.find('.');
        CHECK(first_dot != std::string_view::npos);
        CHECK(n.find('.', first_dot + 1) == std::string_view::npos);
    }
}

TEST_CASE("Numeric rows have min < max; string rows have 0/0 placeholder") {
    for (const auto& row : CONFIG_SCHEMA) {
        if (row.type == ValueType::String) {
            CHECK(row.min_d == 0.0);
            CHECK(row.max_d == 0.0);
        } else {
            CHECK(row.min_d <= row.max_d);
        }
    }
}
