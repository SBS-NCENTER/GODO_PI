// Phase 4-2 B Wave 1 — OccupancyGrid + load_map.
//
// Coverage:
//   - happy-path round-trip on the synthetic_4x4 fixture
//   - YAML key whitelist enforcement (3 malformed inputs)
//   - EDT_MAX_CELLS rejection
//   - actionable error wording
//
// No Bresenham fixture here (bias-block per plan); we only validate the
// loader contract.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

#include <unistd.h>

#include "localization/occupancy_grid.hpp"

#ifndef GODO_FIXTURES_MAPS_DIR
#error "GODO_FIXTURES_MAPS_DIR must be set by CMake"
#endif

using godo::localization::OccupancyGrid;
using godo::localization::load_map;

namespace {

std::string fixture_path(const char* leaf) {
    return std::string(GODO_FIXTURES_MAPS_DIR) + "/" + leaf;
}

struct TempDir {
    std::filesystem::path path;
    TempDir() {
        path = std::filesystem::temp_directory_path() /
               ("godo_map_test_" + std::to_string(::getpid()) + "_" +
                std::to_string(std::rand()));
        std::filesystem::create_directories(path);
    }
    ~TempDir() { std::error_code ec; std::filesystem::remove_all(path, ec); }
};

// Write a 2-byte 1x1 PGM payload alongside a YAML body chosen by the caller.
// Returns the .pgm path.
std::string make_pgm_with_yaml(const std::filesystem::path& dir,
                               const std::string&            yaml_body,
                               int                           w = 1,
                               int                           h = 1) {
    const auto pgm  = dir / "tiny.pgm";
    const auto yaml = dir / "tiny.yaml";
    std::ofstream pf(pgm.string(), std::ios::binary);
    pf << "P5\n" << w << " " << h << "\n255\n";
    for (int i = 0; i < w * h; ++i) pf.put('\xff');
    pf.close();
    std::ofstream yf(yaml.string());
    yf << yaml_body;
    yf.close();
    return pgm.string();
}

const std::string kValidYaml =
    "image: tiny.pgm\n"
    "resolution: 0.05\n"
    "origin: [0.0, 0.0, 0.0]\n"
    "occupied_thresh: 0.65\n"
    "free_thresh: 0.196\n"
    "negate: 0\n";

}  // namespace

// issue#28 — origin_yaw is sourced from YAML row `origin: [a, b, c]`
// element [2]. The pre-issue#28 path read `cfg.amcl_origin_yaw_deg`;
// the field is now deprecated and cold_writer reads grid.origin_yaw_deg
// directly. Pin: the value parses through the loader as RADIANS and
// is converted to DEGREES inside `load_map`. yaml row `0.523599` (rad)
// → grid.origin_yaw_deg ≈ 30.
TEST_CASE("load_map — issue#28 YAML origin[2] feeds grid.origin_yaw_deg") {
    TempDir td;
    const std::string body =
        "image: tiny.pgm\n"
        "resolution: 0.05\n"
        "origin: [1.0, -2.0, 0.523598775]\n"  // 30° in radians
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n"
        "negate: 0\n";
    auto pgm = make_pgm_with_yaml(td.path, body);
    OccupancyGrid g = load_map(pgm);
    CHECK(g.origin_x_m == doctest::Approx(1.0));
    CHECK(g.origin_y_m == doctest::Approx(-2.0));
    CHECK(g.origin_yaw_deg == doctest::Approx(30.0).epsilon(1e-3));
}

TEST_CASE("load_map — round-trips the synthetic_4x4 fixture") {
    OccupancyGrid g = load_map(fixture_path("synthetic_4x4.pgm"));
    CHECK(g.width  == 80);
    CHECK(g.height == 80);
    CHECK(g.resolution_m   == doctest::Approx(0.05));
    CHECK(g.origin_x_m     == doctest::Approx(0.0));
    CHECK(g.origin_y_m     == doctest::Approx(0.0));
    CHECK(g.origin_yaw_deg == doctest::Approx(0.0));
    REQUIRE(g.cells.size() == 80u * 80u);

    // Border cells are 0 (occupied), interior 255 (free).
    CHECK(static_cast<int>(g.cells[0])           == 0);    // (0,0)
    CHECK(static_cast<int>(g.cells[79])          == 0);    // (79,0)
    CHECK(static_cast<int>(g.cells[79 * 80])     == 0);    // (0,79)
    CHECK(static_cast<int>(g.cells[40 * 80 + 40]) == 255); // (40,40)
}

TEST_CASE("load_map — unknown YAML key is rejected with actionable error") {
    TempDir tmp;
    const auto pgm = make_pgm_with_yaml(tmp.path,
        kValidYaml + "totally_made_up_key: 7\n");
    try {
        (void)load_map(pgm);
        FAIL("expected std::runtime_error");
    } catch (const std::runtime_error& e) {
        const std::string m = e.what();
        CHECK(m.find("totally_made_up_key") != std::string::npos);
        CHECK(m.find("accepted keys")       != std::string::npos);
    }
}

TEST_CASE("load_map — missing required key is rejected") {
    TempDir tmp;
    // Drop 'origin' from the body.
    const std::string body =
        "image: tiny.pgm\n"
        "resolution: 0.05\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n"
        "negate: 0\n";
    const auto pgm = make_pgm_with_yaml(tmp.path, body);
    try {
        (void)load_map(pgm);
        FAIL("expected std::runtime_error");
    } catch (const std::runtime_error& e) {
        const std::string m = e.what();
        CHECK(m.find("origin") != std::string::npos);
        CHECK(m.find("missing") != std::string::npos);
    }
}

TEST_CASE("load_map — malformed YAML line (no colon) is rejected") {
    TempDir tmp;
    const auto pgm = make_pgm_with_yaml(tmp.path,
        kValidYaml + "this_is_not_a_yaml_line\n");
    try {
        (void)load_map(pgm);
        FAIL("expected std::runtime_error");
    } catch (const std::runtime_error& e) {
        const std::string m = e.what();
        CHECK(m.find("missing ':'") != std::string::npos);
    }
}

TEST_CASE("load_map — warn-but-accept keys do not raise") {
    TempDir tmp;
    const auto pgm = make_pgm_with_yaml(tmp.path,
        kValidYaml +
        "mode: trinary\n"
        "unknown_thresh: 0.1\n");
    OccupancyGrid g = load_map(pgm);
    CHECK(g.width  == 1);
    CHECK(g.height == 1);
}

TEST_CASE("load_map — non-P5 magic is rejected") {
    TempDir tmp;
    const auto pgm  = tmp.path / "p2.pgm";
    const auto yaml = tmp.path / "p2.yaml";
    {
        std::ofstream pf(pgm.string());
        pf << "P2\n1 1\n255\n255\n";
    }
    {
        std::ofstream yf(yaml.string());
        yf << kValidYaml;
    }
    try {
        (void)load_map(pgm.string());
        FAIL("expected std::runtime_error");
    } catch (const std::runtime_error& e) {
        const std::string m = e.what();
        CHECK(m.find("P5") != std::string::npos);
    }
}

TEST_CASE("load_map — width*height over EDT_MAX_CELLS rejected with actionable hint") {
    TempDir tmp;
    const auto pgm  = tmp.path / "huge.pgm";
    const auto yaml = tmp.path / "huge.yaml";
    {
        // 4000*1001 = 4'004'000 > EDT_MAX_CELLS = 4'000'000.
        // We don't actually emit 4M payload bytes — the loader is supposed
        // to reject after parsing the header. Truncated payload is fine
        // because the dimension check fires first.
        std::ofstream pf(pgm.string(), std::ios::binary);
        pf << "P5\n4000 1001\n255\n";
        pf.put('\xff');  // one byte; loader never reaches the read.
    }
    {
        std::ofstream yf(yaml.string());
        yf << kValidYaml;
    }
    try {
        (void)load_map(pgm.string());
        FAIL("expected std::runtime_error");
    } catch (const std::runtime_error& e) {
        const std::string m = e.what();
        CHECK(m.find("EDT_MAX_CELLS") != std::string::npos);
        CHECK(m.find("4000")          != std::string::npos);
        CHECK(m.find("1001")          != std::string::npos);
    }
}

TEST_CASE("load_map — missing PGM file is rejected with the path in the message") {
    try {
        (void)load_map("/does/not/exist/godo_no_such.pgm");
        FAIL("expected std::runtime_error");
    } catch (const std::runtime_error& e) {
        const std::string m = e.what();
        CHECK(m.find("godo_no_such") != std::string::npos);
    }
}

TEST_CASE("load_map — missing YAML companion is rejected") {
    TempDir tmp;
    const auto pgm = tmp.path / "lonely.pgm";
    {
        std::ofstream pf(pgm.string(), std::ios::binary);
        pf << "P5\n1 1\n255\n";
        pf.put('\xff');
    }
    // Note: NO companion YAML emitted.
    try {
        (void)load_map(pgm.string());
        FAIL("expected std::runtime_error");
    } catch (const std::runtime_error& e) {
        const std::string m = e.what();
        CHECK(m.find("lonely.yaml") != std::string::npos);
    }
}

TEST_CASE("load_map — truncated PGM payload is rejected") {
    TempDir tmp;
    const auto pgm  = tmp.path / "trunc.pgm";
    const auto yaml = tmp.path / "trunc.yaml";
    {
        std::ofstream pf(pgm.string(), std::ios::binary);
        pf << "P5\n4 4\n255\n";
        // Only emit 4 bytes instead of 16.
        for (int i = 0; i < 4; ++i) pf.put('\xff');
    }
    {
        std::ofstream yf(yaml.string());
        yf << kValidYaml;
    }
    try {
        (void)load_map(pgm.string());
        FAIL("expected std::runtime_error");
    } catch (const std::runtime_error& e) {
        const std::string m = e.what();
        CHECK(m.find("truncated") != std::string::npos);
    }
}
