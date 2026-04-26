#pragma once

// 2D occupancy grid + slam_toolbox-compatible PGM/YAML loader.
//
// Cell encoding follows the slam_toolbox / map_server convention:
//   255 = free, 0 = occupied. Intermediate values mirror the per-pixel
//   probability the source map encodes; the AMCL likelihood field treats
//   any cell with grayscale value <= occupied_thresh*255 as an obstacle.
//
// `load_map` reads the binary PGM (P5) and the sibling YAML (same base path
// with `.pgm` swapped for `.yaml`). The YAML key whitelist is enforced
// strictly:
//   required:           image, resolution, origin, occupied_thresh,
//                       free_thresh, negate
//   warn-but-accept:    mode, unknown_thresh
//   any other key       → std::runtime_error
//
// Cell-count cap: width * height must not exceed
// `godo::constants::EDT_MAX_CELLS` (4'000'000) — this bounds the EDT
// scratch footprint at ~16 MB float32. M6 mitigation in the Wave 1 plan.

#include <cstdint>
#include <string>
#include <vector>

namespace godo::localization {

// Cell-encoding cutoff used by every consumer that needs a binary
// "obstacle vs free" classification:
//   - build_likelihood_field's EDT seeding (occupied = 0-distance source)
//   - Amcl::seed_global's free-cell index (passable cells for global init)
// slam_toolbox emits 0 for occupied, 254 for free, ~205 for unknown; we
// treat anything < OCCUPIED_CUTOFF_U8 as obstacle, ≥ as free / unknown.
// Single source of truth so the EDT and seed_global cannot drift out of
// sync. (S5 mitigation, Mode-B follow-up.)
inline constexpr std::uint8_t OCCUPIED_CUTOFF_U8 = 100;

struct OccupancyGrid {
    int    width{};
    int    height{};
    double resolution_m{};        // metres per cell
    double origin_x_m{};          // world coords of cell (0, 0) lower-left
    double origin_y_m{};
    double origin_yaw_deg{};      // map yaw rotation; usually 0
    std::vector<std::uint8_t> cells;  // size = width * height; row-major
};

// Throws std::runtime_error on any parse / sanity failure. Error messages
// always name the input path AND the specific failing condition so an
// operator can fix the problem without reading source.
OccupancyGrid load_map(const std::string& pgm_path);

}  // namespace godo::localization
