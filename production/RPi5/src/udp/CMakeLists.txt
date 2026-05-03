add_library(godo_udp STATIC
    sender.cpp
    output_transform.cpp
)

target_include_directories(godo_udp PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_udp PUBLIC
    godo_core
    godo_yaw
    godo_freed
)
