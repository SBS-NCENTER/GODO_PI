#!/usr/bin/env bash
# Build + hardware-free test gate for godo_rpi5.
#
# Usage: scripts/build.sh [cmake-build-type]
#   default build type: RelWithDebInfo
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build"
BUILD_TYPE="${1:-RelWithDebInfo}"

cmake -S "${ROOT_DIR}" -B "${BUILD_DIR}" \
    -DCMAKE_BUILD_TYPE="${BUILD_TYPE}"
cmake --build "${BUILD_DIR}" -j"$(nproc)"

# Hardware-free gate: every test labelled hardware-free must pass.
ctest --test-dir "${BUILD_DIR}" -L hardware-free --output-on-failure
