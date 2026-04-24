add_library(godo_freed STATIC
    d1_parser.cpp
    serial_reader.cpp
)

target_include_directories(godo_freed PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_freed PUBLIC
    godo_core
)
