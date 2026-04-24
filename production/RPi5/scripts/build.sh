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

# -----------------------------------------------------------------------
# [rt-alloc-grep] — best-effort check that the RT hot path does not
# contain obvious heap-allocating calls. See CODEBASE.md invariant (e).
# Warnings here do NOT fail the build; they are reviewed manually.
# -----------------------------------------------------------------------
RT_PATHS=(
    "${ROOT_DIR}/src/rt"
    "${ROOT_DIR}/src/udp"
    "${ROOT_DIR}/src/smoother"
    "${ROOT_DIR}/src/yaw"
    "${ROOT_DIR}/src/godo_tracker_rt/main.cpp"
    "${ROOT_DIR}/src/freed/serial_reader.cpp"
)
PATTERN='\bnew\s+[A-Za-z_]|\bmalloc\(|\bstd::string\(|\bstd::vector<[^>]*>::(push_back|emplace_back|resize)'

ALLOC_HITS="$(grep -rnE "${PATTERN}" "${RT_PATHS[@]}" 2>/dev/null || true)"
if [[ -n "${ALLOC_HITS}" ]]; then
    echo "[rt-alloc-grep] possible hot-path allocations under review:" >&2
    echo "${ALLOC_HITS}" | sed 's/^/[rt-alloc-grep]   /' >&2
else
    echo "[rt-alloc-grep] clean (no heap-allocating calls detected on RT paths)"
fi
