add_library(godo_smoother STATIC
    offset_smoother.cpp
)

target_include_directories(godo_smoother PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_smoother PUBLIC
    godo_yaw
)
