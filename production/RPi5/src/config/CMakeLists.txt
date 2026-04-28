# Track B-CONFIG (PR-CONFIG-α) — config edit module.
#
# Owns: schema lookup, validation, atomic TOML writer, restart-pending
# flag manager, central apply_set / apply_get JSON encoders.
#
# Hot-path constraint: nothing under godo_config is reachable from
# Thread D. Build greps in scripts/build.sh enforce this.

add_library(godo_config STATIC
    validate.cpp
    atomic_toml_writer.cpp
    restart_pending.cpp
    apply.cpp
)

target_include_directories(godo_config PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_config PUBLIC
    godo_core
)
