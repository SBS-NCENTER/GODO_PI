add_library(godo_yaw STATIC
    yaw.cpp
)

target_include_directories(godo_yaw PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
