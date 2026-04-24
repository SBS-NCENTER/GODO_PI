add_executable(godo_jitter
    main.cpp
)

target_link_libraries(godo_jitter PRIVATE
    godo_core
    godo_rt
)
