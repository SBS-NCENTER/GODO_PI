add_executable(godo_tracker_rt
    main.cpp
)

target_link_libraries(godo_tracker_rt PRIVATE
    godo_core
    godo_rt
    godo_yaw
    godo_freed
    godo_smoother
    godo_udp
    godo_localization
    godo_gpio
    godo_uds
    godo_config
)
