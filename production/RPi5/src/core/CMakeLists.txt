# core library — headers + rt_flags definition + config loader.
# Depends only on tomlplusplus (for the config loader).

add_library(godo_core STATIC
    rt_flags.cpp
    config.cpp
    hot_config.cpp
    pidfile.cpp
)

target_include_directories(godo_core PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_core PUBLIC
    tomlplusplus::tomlplusplus
)
