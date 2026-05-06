# Phase 4-2 B — AMCL localization static library.
#
# Wave 1 landed the substrate: pose / rng / occupancy_grid / likelihood_field
# / scan_ops. Wave 2 appends amcl, amcl_result, and cold_writer.
#
# Depends on godo_core (constants, config, seqlock, rt_flags), godo_lidar
# (Frame/Sample, LidarSourceRplidar), and Eigen3 (header-only; reserved for
# future EDT scratch).

add_library(godo_localization STATIC
    pose.cpp
    rng.cpp
    occupancy_grid.cpp
    likelihood_field.cpp
    scan_ops.cpp
    amcl_result.cpp
    amcl.cpp
    cold_writer.cpp
)

target_include_directories(godo_localization PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_localization PUBLIC
    godo_core
    godo_lidar
    godo_parallel
    Eigen3::Eigen
)
