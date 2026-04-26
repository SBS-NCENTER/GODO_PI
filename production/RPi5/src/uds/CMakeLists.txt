# Phase 4-2 D Wave B — UDS control-plane server.
#
# Static lib `godo_uds` provides a Unix-domain JSON-lines server that
# translates set_mode / get_mode / ping commands into AmclMode transitions.
# Hand-rolled JSON helpers (json_mini) keep the build dependency-free.

add_library(godo_uds STATIC
    uds_server.cpp
    json_mini.cpp
)

target_include_directories(godo_uds PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_uds PUBLIC
    godo_core
)
