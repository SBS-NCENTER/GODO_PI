# Phase 4-2 D Wave B — GPIO source.
#
# Static lib `godo_gpio` wraps libgpiod v2 (system package libgpiod-dev).
# Production driver opens /dev/gpiochip0; debounce + callback dispatch are
# the only logic beyond the libgpiod call sequence.

add_library(godo_gpio STATIC
    gpio_source_libgpiod.cpp
)

target_include_directories(godo_gpio PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# libgpiodcxx is the C++ wrapper (debian package libgpiod-dev provides
# both libgpiodcxx.so and the underlying libgpiod.so). The link order
# matters: gpiodcxx → gpiod.
target_link_libraries(godo_gpio
    PUBLIC  godo_core
    PRIVATE gpiodcxx gpiod
)
