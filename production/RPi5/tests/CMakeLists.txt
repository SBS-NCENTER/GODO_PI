# Test targets are split so that the "read back" side cannot accidentally
# include production headers. See CODEBASE.md invariant (b).

set(GODO_SMOKE_SRC_DIR "${CMAKE_SOURCE_DIR}/src/godo_smoke")

# ----------------------------------------------------------------------------
# test_write_driving — exercises production code paths (writer, args,
# session_log, sample validation, and the duck-typed fake source).
# ----------------------------------------------------------------------------

add_executable(test_csv_writer_writes
    test_csv_writer_writes.cpp
    ${GODO_SMOKE_SRC_DIR}/csv_writer.cpp
)
target_include_directories(test_csv_writer_writes PRIVATE
    "${GODO_SMOKE_SRC_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}"
)
target_link_libraries(test_csv_writer_writes PRIVATE doctest::doctest godo_lidar)
add_test(NAME test_csv_writer_writes COMMAND test_csv_writer_writes)
set_tests_properties(test_csv_writer_writes PROPERTIES
    LABELS "hardware-free")

add_executable(test_args
    test_args.cpp
    ${GODO_SMOKE_SRC_DIR}/args.cpp
)
target_include_directories(test_args PRIVATE
    "${GODO_SMOKE_SRC_DIR}"
)
target_link_libraries(test_args PRIVATE doctest::doctest)
add_test(NAME test_args COMMAND test_args)
set_tests_properties(test_args PROPERTIES LABELS "hardware-free")

add_executable(test_session_log
    test_session_log.cpp
    ${GODO_SMOKE_SRC_DIR}/session_log.cpp
    ${GODO_SMOKE_SRC_DIR}/timestamp.cpp
)
target_include_directories(test_session_log PRIVATE
    "${GODO_SMOKE_SRC_DIR}"
)
target_link_libraries(test_session_log PRIVATE
    doctest::doctest
    OpenSSL::Crypto
)
add_test(NAME test_session_log COMMAND test_session_log)
set_tests_properties(test_session_log PROPERTIES LABELS "hardware-free")

add_executable(test_sample_invariants
    test_sample_invariants.cpp
    lidar_source_fake.cpp
)
target_include_directories(test_sample_invariants PRIVATE
    "${GODO_SMOKE_SRC_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}"
)
target_link_libraries(test_sample_invariants PRIVATE doctest::doctest godo_lidar)
add_test(NAME test_sample_invariants COMMAND test_sample_invariants)
set_tests_properties(test_sample_invariants PROPERTIES LABELS "hardware-free")

# ----------------------------------------------------------------------------
# test_read_back — parses a literal CSV string with stdlib only. Include
# path intentionally EXCLUDES ${GODO_SMOKE_SRC_DIR} so any accidental
# `#include "csv_writer.hpp"` fails to compile.
# ----------------------------------------------------------------------------

add_executable(test_csv_writer_readback
    test_csv_writer_readback.cpp
)
target_include_directories(test_csv_writer_readback PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}"
)
target_link_libraries(test_csv_writer_readback PRIVATE doctest::doctest)
add_test(NAME test_csv_writer_readback COMMAND test_csv_writer_readback)
set_tests_properties(test_csv_writer_readback PROPERTIES
    LABELS "hardware-free")

# ----------------------------------------------------------------------------
# test_csv_parity — byte-identity vs. the Python prototype. Conditional
# on `uv` and the prototype's uv.lock being present.
# ----------------------------------------------------------------------------

find_program(UV_EXE uv)
set(GODO_PYTHON_DIR "${CMAKE_SOURCE_DIR}/../../prototype/Python")
if(UV_EXE AND EXISTS "${GODO_PYTHON_DIR}/uv.lock")
    add_executable(test_csv_parity
        test_csv_parity.cpp
        ${GODO_SMOKE_SRC_DIR}/csv_writer.cpp
    )
    target_include_directories(test_csv_parity PRIVATE
        "${GODO_SMOKE_SRC_DIR}"
    )
    target_link_libraries(test_csv_parity PRIVATE doctest::doctest godo_lidar)
    # CMake needs the raw absolute path in the compile-definition; use
    # get_filename_component to normalise.
    get_filename_component(GODO_PYTHON_DIR_ABS "${GODO_PYTHON_DIR}" ABSOLUTE)
    target_compile_definitions(test_csv_parity PRIVATE
        GODO_PYTHON_PROJECT_DIR="${GODO_PYTHON_DIR_ABS}"
    )
    add_test(NAME test_csv_parity COMMAND test_csv_parity)
    set_tests_properties(test_csv_parity PROPERTIES
        LABELS "hardware-free;python-required")
    message(STATUS "test_csv_parity enabled (uv=${UV_EXE})")
else()
    message(STATUS
        "test_csv_parity skipped (uv or prototype/Python/uv.lock not found)")
endif()

# ----------------------------------------------------------------------------
# test_lidar_live — hardware-required; built but not run by default ctest.
# ----------------------------------------------------------------------------

add_executable(test_lidar_live
    test_lidar_live.cpp
)
target_include_directories(test_lidar_live PRIVATE
    "${GODO_SMOKE_SRC_DIR}"
)
target_link_libraries(test_lidar_live PRIVATE
    doctest::doctest
    godo_lidar
)
add_test(NAME test_lidar_live COMMAND test_lidar_live)
set_tests_properties(test_lidar_live PROPERTIES LABELS "hardware-required")

# ----------------------------------------------------------------------------
# Phase 4-1 tests — hardware-free.
# ----------------------------------------------------------------------------

add_executable(test_yaw test_yaw.cpp)
target_link_libraries(test_yaw PRIVATE doctest::doctest godo_yaw)
add_test(NAME test_yaw COMMAND test_yaw)
set_tests_properties(test_yaw PROPERTIES LABELS "hardware-free")

add_executable(test_smoother test_smoother.cpp)
target_link_libraries(test_smoother PRIVATE doctest::doctest godo_smoother)
add_test(NAME test_smoother COMMAND test_smoother)
set_tests_properties(test_smoother PROPERTIES LABELS "hardware-free")

add_executable(test_freed_parser test_freed_parser.cpp)
target_link_libraries(test_freed_parser PRIVATE doctest::doctest godo_freed)
add_test(NAME test_freed_parser COMMAND test_freed_parser)
set_tests_properties(test_freed_parser PROPERTIES LABELS "hardware-free")

add_executable(test_udp_apply_offset test_udp_apply_offset.cpp)
target_link_libraries(test_udp_apply_offset PRIVATE
    doctest::doctest godo_udp)
add_test(NAME test_udp_apply_offset COMMAND test_udp_apply_offset)
set_tests_properties(test_udp_apply_offset PROPERTIES LABELS "hardware-free")

add_executable(test_udp_loopback test_udp_loopback.cpp)
target_link_libraries(test_udp_loopback PRIVATE doctest::doctest godo_udp)
add_test(NAME test_udp_loopback COMMAND test_udp_loopback)
set_tests_properties(test_udp_loopback PROPERTIES LABELS "hardware-free")

add_executable(test_config test_config.cpp)
target_link_libraries(test_config PRIVATE doctest::doctest godo_core)
add_test(NAME test_config COMMAND test_config)
set_tests_properties(test_config PROPERTIES LABELS "hardware-free")

add_executable(test_rt_setup test_rt_setup.cpp)
target_link_libraries(test_rt_setup PRIVATE doctest::doctest godo_rt)
add_test(NAME test_rt_setup COMMAND test_rt_setup)
set_tests_properties(test_rt_setup PROPERTIES LABELS "hardware-free")

add_executable(test_seqlock_roundtrip test_seqlock_roundtrip.cpp)
target_link_libraries(test_seqlock_roundtrip PRIVATE
    doctest::doctest godo_core)
add_test(NAME test_seqlock_roundtrip COMMAND test_seqlock_roundtrip)
set_tests_properties(test_seqlock_roundtrip PROPERTIES LABELS "hardware-free")

# PTY-based serial reader test — linked against godo_freed; needs libutil
# for openpty().
add_executable(test_freed_serial_reader test_freed_serial_reader.cpp)
target_link_libraries(test_freed_serial_reader PRIVATE
    doctest::doctest godo_freed util)
add_test(NAME test_freed_serial_reader COMMAND test_freed_serial_reader)
set_tests_properties(test_freed_serial_reader PROPERTIES LABELS "hardware-free")

# ----------------------------------------------------------------------------
# Phase 4-2 B Wave 1 — AMCL substrate (occupancy grid, likelihood field,
# resampler). The Amcl class itself, cold writer, scenario test, circular
# stats, pose helpers, and offset-invariant test land in Wave 2.
# ----------------------------------------------------------------------------

add_executable(test_occupancy_grid test_occupancy_grid.cpp)
target_link_libraries(test_occupancy_grid PRIVATE
    doctest::doctest godo_localization)
target_compile_definitions(test_occupancy_grid PRIVATE
    GODO_FIXTURES_MAPS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/maps"
)
add_test(NAME test_occupancy_grid COMMAND test_occupancy_grid)
set_tests_properties(test_occupancy_grid PROPERTIES LABELS "hardware-free")

add_executable(test_likelihood_field test_likelihood_field.cpp)
target_link_libraries(test_likelihood_field PRIVATE
    doctest::doctest godo_localization)
add_test(NAME test_likelihood_field COMMAND test_likelihood_field)
set_tests_properties(test_likelihood_field PROPERTIES LABELS "hardware-free")

add_executable(test_resampler test_resampler.cpp)
target_link_libraries(test_resampler PRIVATE
    doctest::doctest godo_localization)
add_test(NAME test_resampler COMMAND test_resampler)
set_tests_properties(test_resampler PROPERTIES LABELS "hardware-free")

# ----------------------------------------------------------------------------
# Phase 4-2 B Wave 2 — class Amcl + cold_writer publish path + circular
# stats + pose helpers + scenario tests.
# ----------------------------------------------------------------------------

add_executable(test_circular_stats test_circular_stats.cpp)
target_link_libraries(test_circular_stats PRIVATE
    doctest::doctest godo_localization)
add_test(NAME test_circular_stats COMMAND test_circular_stats)
set_tests_properties(test_circular_stats PROPERTIES LABELS "hardware-free")

add_executable(test_pose test_pose.cpp)
target_link_libraries(test_pose PRIVATE
    doctest::doctest godo_localization godo_core)
add_test(NAME test_pose COMMAND test_pose)
set_tests_properties(test_pose PROPERTIES LABELS "hardware-free")

add_executable(test_amcl_components test_amcl_components.cpp)
target_link_libraries(test_amcl_components PRIVATE
    doctest::doctest godo_localization godo_core)
target_compile_definitions(test_amcl_components PRIVATE
    GODO_FIXTURES_MAPS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/maps"
)
add_test(NAME test_amcl_components COMMAND test_amcl_components)
set_tests_properties(test_amcl_components PROPERTIES LABELS "hardware-free")

add_executable(test_cold_writer_offset_invariant
    test_cold_writer_offset_invariant.cpp)
target_link_libraries(test_cold_writer_offset_invariant PRIVATE
    doctest::doctest godo_localization godo_core godo_lidar)
target_compile_definitions(test_cold_writer_offset_invariant PRIVATE
    GODO_FIXTURES_MAPS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/maps"
)
add_test(NAME test_cold_writer_offset_invariant
    COMMAND test_cold_writer_offset_invariant)
set_tests_properties(test_cold_writer_offset_invariant PROPERTIES
    LABELS "hardware-free")

add_executable(test_amcl_scenarios test_amcl_scenarios.cpp)
target_link_libraries(test_amcl_scenarios PRIVATE
    doctest::doctest godo_localization godo_core)
target_compile_definitions(test_amcl_scenarios PRIVATE
    GODO_FIXTURES_MAPS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/maps"
)
add_test(NAME test_amcl_scenarios COMMAND test_amcl_scenarios)
set_tests_properties(test_amcl_scenarios PROPERTIES LABELS "hardware-free")

# ----------------------------------------------------------------------------
# Phase 4-2 C — cold-path deadband filter at the publish seam.
# Pure predicate tests + Seqlock-driven seam composition tests; no AMCL
# fixture dependency, no LiDAR.
# ----------------------------------------------------------------------------

add_executable(test_deadband test_deadband.cpp)
target_link_libraries(test_deadband PRIVATE
    doctest::doctest godo_localization godo_core)
add_test(NAME test_deadband COMMAND test_deadband)
set_tests_properties(test_deadband PROPERTIES LABELS "hardware-free")

# ----------------------------------------------------------------------------
# Phase 4-2 D Wave A — Live iteration kernel + σ-overload propagation.
# Drives run_live_iteration directly with synthetic frames; mirrors the
# test_cold_writer_offset_invariant fixture pattern, no LiDAR.
# ----------------------------------------------------------------------------

add_executable(test_cold_writer_live_iteration
    test_cold_writer_live_iteration.cpp)
target_link_libraries(test_cold_writer_live_iteration PRIVATE
    doctest::doctest godo_localization godo_core godo_lidar)
target_compile_definitions(test_cold_writer_live_iteration PRIVATE
    GODO_FIXTURES_MAPS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/maps"
)
add_test(NAME test_cold_writer_live_iteration
    COMMAND test_cold_writer_live_iteration)
set_tests_properties(test_cold_writer_live_iteration PROPERTIES
    LABELS "hardware-free")

# ----------------------------------------------------------------------------
# Track B (F5) — ordering pin: run_one_iteration / run_live_iteration
# publish to last_pose_seq before returning. The verbatim F5 writer
# comment at cold_writer.cpp's OneShot success path explains why the
# publish must happen before `g_amcl_mode = Idle` is stored.
# ----------------------------------------------------------------------------

add_executable(test_cold_writer_ordering
    test_cold_writer_ordering.cpp)
target_link_libraries(test_cold_writer_ordering PRIVATE
    doctest::doctest godo_localization godo_core godo_lidar)
target_compile_definitions(test_cold_writer_ordering PRIVATE
    GODO_FIXTURES_MAPS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/maps"
)
add_test(NAME test_cold_writer_ordering
    COMMAND test_cold_writer_ordering)
set_tests_properties(test_cold_writer_ordering PROPERTIES
    LABELS "hardware-free")

# ----------------------------------------------------------------------------
# Phase 4-2 D Wave B — GPIO + UDS modules.
# - test_gpio_source_fake: hardware-free; exercises the duck-typed twin
#   `GpioSourceFake` to pin debounce + dispatch + S5 OneShot-drop semantics.
# - test_gpio_source_libgpiod: hardware-required-gpio; opens
#   /dev/gpiochip0 and verifies the libgpiod request shape. Not run by
#   default ctest.
# - test_uds_server: hardware-free; spawns the UDS server on a temp path
#   and exercises set_mode / get_mode / ping + parse / unknown / oversized
#   error paths. Uses TempUdsPath RAII guard for cleanup (S7).
# ----------------------------------------------------------------------------

add_executable(test_gpio_source_fake test_gpio_source_fake.cpp)
target_include_directories(test_gpio_source_fake PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}"
)
target_link_libraries(test_gpio_source_fake PRIVATE
    doctest::doctest godo_core godo_gpio)
add_test(NAME test_gpio_source_fake COMMAND test_gpio_source_fake)
set_tests_properties(test_gpio_source_fake PROPERTIES LABELS "hardware-free")

add_executable(test_gpio_source_libgpiod test_gpio_source_libgpiod.cpp)
target_link_libraries(test_gpio_source_libgpiod PRIVATE
    doctest::doctest godo_core godo_gpio)
add_test(NAME test_gpio_source_libgpiod COMMAND test_gpio_source_libgpiod)
set_tests_properties(test_gpio_source_libgpiod PROPERTIES
    LABELS "hardware-required-gpio")

add_executable(test_uds_server test_uds_server.cpp)
target_link_libraries(test_uds_server PRIVATE
    doctest::doctest godo_core godo_uds)
add_test(NAME test_uds_server COMMAND test_uds_server)
set_tests_properties(test_uds_server PROPERTIES LABELS "hardware-free")

# End-to-end replay: spawns the real godo_tracker_rt binary, so it
# depends on that target being built first.
add_executable(test_rt_replay test_rt_replay.cpp)
target_link_libraries(test_rt_replay PRIVATE
    doctest::doctest godo_freed godo_udp util)
target_compile_definitions(test_rt_replay PRIVATE
    GODO_TRACKER_RT_PATH="$<TARGET_FILE:godo_tracker_rt>"
    GODO_FIXTURES_MAPS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/maps"
)
add_dependencies(test_rt_replay godo_tracker_rt)
add_test(NAME test_rt_replay COMMAND test_rt_replay)
set_tests_properties(test_rt_replay PROPERTIES LABELS "hardware-free")
