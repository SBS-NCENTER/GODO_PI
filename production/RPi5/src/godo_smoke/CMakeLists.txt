# godo_smoke executable target.
#
# Note: the test targets (../tests/) substitute lidar_source_rplidar.cpp
# with tests/lidar_source_fake.cpp at link time. Each target has its own
# source list; the classes are deliberately NOT related by inheritance
# (see CODEBASE.md invariant (a)).

add_executable(godo_smoke
    main.cpp
    args.cpp
    timestamp.cpp
    csv_writer.cpp
    session_log.cpp
    lidar_source_rplidar.cpp
)

target_include_directories(godo_smoke PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}"
)

target_link_libraries(godo_smoke PRIVATE
    OpenSSL::Crypto
    rplidar_sdk::static
)

# Disable assert() in optimised builds — runtime-critical checks are
# explicit `if (...) abort()` / exception throws (see CODEBASE.md).
target_compile_definitions(godo_smoke PRIVATE
    $<$<OR:$<CONFIG:Release>,$<CONFIG:RelWithDebInfo>>:NDEBUG>
)
