add_executable(godo_freed_passthrough
    main.cpp
)

target_link_libraries(godo_freed_passthrough PRIVATE
    godo_core
    godo_freed
    godo_udp
)
