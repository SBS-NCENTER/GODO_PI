cmake_minimum_required(VERSION 3.22)

project(godo_rpi5
    VERSION 0.1.0
    DESCRIPTION "GODO Phase 3 RPi 5 C++ scaffold — smoke binary"
    LANGUAGES CXX
)

# -----------------------------------------------------------------------------
# Global compiler settings
# -----------------------------------------------------------------------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "RelWithDebInfo" CACHE STRING
        "Build type (Debug / Release / RelWithDebInfo)" FORCE)
endif()

# Warnings-as-errors on gcc/clang. See CODEBASE.md invariant (b).
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -Wpedantic -Werror)
endif()

# Export compile_commands for clangd/editor tooling.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

enable_testing()

# -----------------------------------------------------------------------------
# External dependencies
# -----------------------------------------------------------------------------
# OpenSSL — SHA-256 hashing in session_log.
find_package(OpenSSL REQUIRED COMPONENTS Crypto)

# doctest (Debian 13 package: doctest-dev). Required for tests.
find_package(doctest QUIET)
if(NOT doctest_FOUND)
    # Soft fallback for dev machines that ship doctest as a loose header only.
    find_path(DOCTEST_INCLUDE_DIR doctest/doctest.h)
    if(DOCTEST_INCLUDE_DIR)
        message(WARNING
            "doctest CMake config not found; using loose header at "
            "${DOCTEST_INCLUDE_DIR}. Install 'doctest-dev' on Debian / "
            "Homebrew 'doctest' on macOS for a proper config package.")
        add_library(doctest::doctest INTERFACE IMPORTED)
        target_include_directories(doctest::doctest
            INTERFACE "${DOCTEST_INCLUDE_DIR}")
    else()
        message(FATAL_ERROR
            "doctest is required but was not found. "
            "On Debian: sudo apt install doctest-dev")
    endif()
endif()

# rplidar_sdk submodule — built with its own Makefile, imported as a static lib.
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/rplidar_sdk.cmake)

# tomlplusplus submodule — header-only TOML parser (Phase 4-1 config loader).
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/tomlplusplus.cmake)

# -----------------------------------------------------------------------------
# Targets
# -----------------------------------------------------------------------------
# Phase 3 smoke binary (unchanged).
add_subdirectory(src/godo_smoke)

# Phase 4-1 RT hot-path modules.
add_subdirectory(src/core)
add_subdirectory(src/yaw)
add_subdirectory(src/smoother)
add_subdirectory(src/freed)
add_subdirectory(src/udp)
add_subdirectory(src/rt)
add_subdirectory(src/godo_jitter)
add_subdirectory(src/godo_tracker_rt)
add_subdirectory(src/godo_freed_passthrough)

add_subdirectory(tests)
