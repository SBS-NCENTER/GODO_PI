# Reusable LiDAR component (Phase 4-2 onward).
#
# Promoted from src/godo_smoke/ — godo_smoke now links this lib instead of
# compiling lidar_source_rplidar.cpp directly. AMCL writer thread (Phase 4-2)
# and any future LiDAR consumer should link `godo_lidar`.
#
# The header sample.hpp is intentionally light (PODs + free function) so
# AMCL / cold-path code can include it without dragging in the rplidar SDK.

add_library(godo_lidar STATIC
    lidar_source_rplidar.cpp
)

target_include_directories(godo_lidar PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_lidar PUBLIC
    rplidar_sdk::static
)

# Disable assert() in optimised builds — runtime-critical checks are
# explicit `if (...) abort()` / exception throws (see CODEBASE.md).
target_compile_definitions(godo_lidar PRIVATE
    $<$<OR:$<CONFIG:Release>,$<CONFIG:RelWithDebInfo>>:NDEBUG>
)
