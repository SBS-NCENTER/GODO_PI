add_library(godo_rt STATIC
    rt_setup.cpp
)

target_include_directories(godo_rt PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_rt PUBLIC
    pthread
)
