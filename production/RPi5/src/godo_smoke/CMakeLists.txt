# godo_smoke executable target.
#
# Phase 4-2: lidar_source_rplidar.cpp moved to src/lidar/ and linked here
# via godo_lidar. The test targets (../tests/) still substitute the LiDAR
# source via tests/lidar_source_fake.cpp; the classes remain duck-typed
# twins, NOT related by inheritance (see CODEBASE.md invariant (a)).

add_executable(godo_smoke
    main.cpp
    args.cpp
    timestamp.cpp
    csv_writer.cpp
    session_log.cpp
)

target_include_directories(godo_smoke PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}"
)

target_link_libraries(godo_smoke PRIVATE
    OpenSSL::Crypto
    godo_lidar
)

# Disable assert() in optimised builds — runtime-critical checks are
# explicit `if (...) abort()` / exception throws (see CODEBASE.md).
target_compile_definitions(godo_smoke PRIVATE
    $<$<OR:$<CONFIG:Release>,$<CONFIG:RelWithDebInfo>>:NDEBUG>
)
