// Track B-CONFIG (PR-CONFIG-α) — HotConfig layout + snapshot tests.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include "core/config.hpp"
#include "core/hot_config.hpp"

using godo::core::Config;
using godo::core::HotConfig;
using godo::core::snapshot_hot;

TEST_CASE("HotConfig layout is exactly 32 bytes (issue#36 fold)") {
    static_assert(sizeof(HotConfig) == 32,
                  "HotConfig size pin moved without test update");
    CHECK(sizeof(HotConfig) == 32);
}

TEST_CASE("snapshot_hot copies the hot fields from Config") {
    Config c = Config::make_default();
    c.deadband_mm  = 12.5;
    c.deadband_deg = 0.25;
    const auto h = snapshot_hot(c);
    CHECK(h.deadband_mm       == 12.5);
    CHECK(h.deadband_deg      == 0.25);
    CHECK(h.valid             == 1);
    CHECK(h.published_mono_ns == 0);  // caller fills.
}

TEST_CASE("snapshot_hot is deterministic — two calls yield identical layout") {
    Config c = Config::make_default();
    const auto a = snapshot_hot(c);
    const auto b = snapshot_hot(c);
    CHECK(a.deadband_mm  == b.deadband_mm);
    CHECK(a.deadband_deg == b.deadband_deg);
    CHECK(a.valid        == b.valid);
}
