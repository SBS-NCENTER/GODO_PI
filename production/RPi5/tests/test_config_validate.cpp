// Track B-CONFIG (PR-CONFIG-α) — validate() unit tests.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include "config/validate.hpp"

using godo::config::validate;
using godo::core::config_schema::ReloadClass;

TEST_CASE("validate: bad_key for unknown name") {
    const auto r = validate("nope.foo", "1");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_key");
    CHECK(r.err_detail.find("unknown key") != std::string::npos);
    CHECK(r.row == nullptr);
}

TEST_CASE("validate: bad_key for empty key") {
    const auto r = validate("", "1");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_key");
}

TEST_CASE("validate: int happy path") {
    const auto r = validate("network.ue_port", "6677");
    CHECK(r.ok);
    CHECK(r.err.empty());
    CHECK(r.parsed_double == 6677.0);
    REQUIRE(r.row != nullptr);
    CHECK(r.row->reload_class == ReloadClass::Restart);
}

TEST_CASE("validate: int rejects decimal form") {
    const auto r = validate("network.ue_port", "6677.0");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_type");
}

TEST_CASE("validate: int rejects exponent form") {
    const auto r = validate("network.ue_port", "6e3");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_type");
}

TEST_CASE("validate: int rejects empty value") {
    const auto r = validate("network.ue_port", "");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_type");
}

TEST_CASE("validate: int rejects trailing garbage") {
    const auto r = validate("network.ue_port", "6677abc");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_type");
}

TEST_CASE("validate: int out of range below min") {
    const auto r = validate("network.ue_port", "0");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
    CHECK(r.err_detail.find("out of range") != std::string::npos);
}

TEST_CASE("validate: int out of range above max") {
    const auto r = validate("network.ue_port", "65536");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
}

TEST_CASE("validate: double happy path with integer literal") {
    const auto r = validate("smoother.deadband_mm", "12");
    CHECK(r.ok);
    CHECK(r.parsed_double == 12.0);
    REQUIRE(r.row != nullptr);
    CHECK(r.row->reload_class == ReloadClass::Hot);
}

TEST_CASE("validate: double happy path with float literal") {
    const auto r = validate("smoother.deadband_mm", "12.5");
    CHECK(r.ok);
    CHECK(r.parsed_double == 12.5);
}

TEST_CASE("validate: double happy path with exponent literal") {
    const auto r = validate("amcl.sigma_hit_m", "5e-2");
    CHECK(r.ok);
    CHECK(r.parsed_double == doctest::Approx(0.05));
}

TEST_CASE("validate: double rejects trailing junk") {
    const auto r = validate("smoother.deadband_mm", "12.5x");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_type");
}

TEST_CASE("validate: double out of range below min") {
    const auto r = validate("smoother.deadband_mm", "-1.0");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
}

TEST_CASE("validate: double out of range above max") {
    const auto r = validate("smoother.deadband_mm", "250.0");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
}

TEST_CASE("validate: string happy path") {
    const auto r = validate("network.ue_host", "10.0.0.1");
    CHECK(r.ok);
    CHECK(r.parsed_string == "10.0.0.1");
}

TEST_CASE("validate: string rejects empty") {
    const auto r = validate("network.ue_host", "");
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
}

TEST_CASE("validate: string rejects non-ASCII (UTF-8 high byte)") {
    const auto r = validate("network.ue_host", std::string("hostname\xC3\xA9"));
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
}

TEST_CASE("validate: string rejects control characters") {
    const auto r = validate("network.ue_host", std::string("host\nname"));
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
}

TEST_CASE("validate: string rejects oversized (> 256)") {
    std::string big(300, 'x');
    const auto r = validate("network.ue_host", big);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
}

TEST_CASE("validate: hot-class key returns Hot reload class") {
    const auto r = validate("smoother.deadband_mm", "12.0");
    CHECK(r.ok);
    REQUIRE(r.row != nullptr);
    CHECK(r.row->reload_class == ReloadClass::Hot);
}

TEST_CASE("validate: restart-class key returns Restart reload class") {
    const auto r = validate("rt.priority", "60");
    CHECK(r.ok);
    REQUIRE(r.row != nullptr);
    CHECK(r.row->reload_class == ReloadClass::Restart);
}

TEST_CASE("validate: recalibrate-class key returns Recalibrate reload class") {
    const auto r = validate("amcl.origin_x_m", "1.5");
    CHECK(r.ok);
    REQUIRE(r.row != nullptr);
    CHECK(r.row->reload_class == ReloadClass::Recalibrate);
}

TEST_CASE("validate: t_ramp_ms is restart-class (Mode-A M2)") {
    const auto r = validate("smoother.t_ramp_ms", "750");
    CHECK(r.ok);
    REQUIRE(r.row != nullptr);
    CHECK(r.row->reload_class == ReloadClass::Restart);
}
