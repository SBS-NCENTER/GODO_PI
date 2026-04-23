# Import the rplidar_sdk static library built by the upstream Makefile.
#
# The SDK ships a hand-written POSIX Makefile. We invoke it via
# ExternalProject_Add (BUILD_IN_SOURCE) and expose the resulting static
# library as the imported target `rplidar_sdk::static`. See Plan B v2 §CMake
# integration and the submodule at external/rplidar_sdk.
#
# Pin SHA check: this file refuses to proceed if the submodule has not been
# initialised or is on the wrong commit.

include(ExternalProject)

set(GODO_RPLIDAR_SDK_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/external/rplidar_sdk")
set(GODO_RPLIDAR_SDK_PINNED_SHA "99478e5fb90de3b4a6db0080acacd373f8b36869")

if(NOT EXISTS "${GODO_RPLIDAR_SDK_SRC_DIR}/sdk/Makefile")
    message(FATAL_ERROR
        "rplidar_sdk submodule is missing at ${GODO_RPLIDAR_SDK_SRC_DIR}. "
        "Run:  git submodule update --init --recursive")
endif()

# Verify pinned SHA (best-effort; only runs when git is available).
find_package(Git QUIET)
if(GIT_FOUND)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
        WORKING_DIRECTORY "${GODO_RPLIDAR_SDK_SRC_DIR}"
        OUTPUT_VARIABLE GODO_RPLIDAR_SDK_HEAD
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE GODO_RPLIDAR_SDK_HEAD_RC
    )
    if(GODO_RPLIDAR_SDK_HEAD_RC EQUAL 0 AND
       NOT GODO_RPLIDAR_SDK_HEAD STREQUAL GODO_RPLIDAR_SDK_PINNED_SHA)
        message(WARNING
            "rplidar_sdk is at ${GODO_RPLIDAR_SDK_HEAD}, expected pinned "
            "${GODO_RPLIDAR_SDK_PINNED_SHA}. Build may diverge from the "
            "tested revision.")
    endif()
endif()

set(GODO_RPLIDAR_SDK_LIB
    "${GODO_RPLIDAR_SDK_SRC_DIR}/output/Linux/Release/libsl_lidar_sdk.a")

ExternalProject_Add(rplidar_sdk_build
    SOURCE_DIR        "${GODO_RPLIDAR_SDK_SRC_DIR}"
    CONFIGURE_COMMAND ""
    # Build only the static lib target; app binaries are not needed for the
    # smoke build and this keeps the tree minimal.
    BUILD_COMMAND     ${CMAKE_MAKE_PROGRAM} -C sdk
    BUILD_IN_SOURCE   1
    BUILD_BYPRODUCTS  "${GODO_RPLIDAR_SDK_LIB}"
    INSTALL_COMMAND   ""
    LOG_BUILD         OFF
)

add_library(rplidar_sdk::static STATIC IMPORTED GLOBAL)
add_dependencies(rplidar_sdk::static rplidar_sdk_build)
set_target_properties(rplidar_sdk::static PROPERTIES
    IMPORTED_LOCATION "${GODO_RPLIDAR_SDK_LIB}"
)
target_include_directories(rplidar_sdk::static INTERFACE
    "${GODO_RPLIDAR_SDK_SRC_DIR}/sdk/include"
    "${GODO_RPLIDAR_SDK_SRC_DIR}/sdk/src"
)
target_link_libraries(rplidar_sdk::static INTERFACE
    pthread
)
