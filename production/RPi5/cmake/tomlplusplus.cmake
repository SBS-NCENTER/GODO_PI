# tomlplusplus — single-header TOML v1.0.0 parser.
#
# Submodule pinned at v3.4.0 (SHA 30172438cee64926dc41fdd9c11fb3ba5b2ba9de).
# Exposed as INTERFACE target `tomlplusplus::tomlplusplus`.

set(GODO_TOMLPLUSPLUS_SRC_DIR
    "${CMAKE_CURRENT_SOURCE_DIR}/external/tomlplusplus")
set(GODO_TOMLPLUSPLUS_PINNED_SHA
    "30172438cee64926dc41fdd9c11fb3ba5b2ba9de")

if(NOT EXISTS "${GODO_TOMLPLUSPLUS_SRC_DIR}/include/toml++/toml.hpp")
    message(FATAL_ERROR
        "tomlplusplus submodule missing at ${GODO_TOMLPLUSPLUS_SRC_DIR}. "
        "Run:  git submodule update --init --recursive")
endif()

find_package(Git QUIET)
if(GIT_FOUND)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
        WORKING_DIRECTORY "${GODO_TOMLPLUSPLUS_SRC_DIR}"
        OUTPUT_VARIABLE GODO_TOMLPLUSPLUS_HEAD
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE GODO_TOMLPLUSPLUS_HEAD_RC
    )
    if(GODO_TOMLPLUSPLUS_HEAD_RC EQUAL 0 AND
       NOT GODO_TOMLPLUSPLUS_HEAD STREQUAL GODO_TOMLPLUSPLUS_PINNED_SHA)
        message(WARNING
            "tomlplusplus is at ${GODO_TOMLPLUSPLUS_HEAD}, expected "
            "${GODO_TOMLPLUSPLUS_PINNED_SHA}.")
    endif()
endif()

add_library(tomlplusplus::tomlplusplus INTERFACE IMPORTED GLOBAL)
target_include_directories(tomlplusplus::tomlplusplus INTERFACE
    "${GODO_TOMLPLUSPLUS_SRC_DIR}/include"
)
