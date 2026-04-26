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

# -----------------------------------------------------------------------
# [m1-no-mutex] — wait-free contract on the AMCL → Thread D publish seam.
# CODEBASE.md invariant (f) + plan §M1: cold_writer.cpp must contain ZERO
# std::mutex / std::shared_mutex / std::condition_variable / lock_guard /
# unique_lock references. The seqlock store is the sole synchronization
# primitive on the cold-writer publish path. Hits FAIL the build (this is
# load-bearing for invariant compliance, not a soft warning).
# -----------------------------------------------------------------------
M1_TARGET="${ROOT_DIR}/src/localization/cold_writer.cpp"
M1_PATTERN='\bstd::(mutex|shared_mutex|condition_variable|lock_guard|unique_lock)\b'
if [[ -f "${M1_TARGET}" ]]; then
    M1_HITS="$(grep -nE "${M1_PATTERN}" "${M1_TARGET}" 2>/dev/null || true)"
    if [[ -n "${M1_HITS}" ]]; then
        echo "[m1-no-mutex] FAIL — wait-free contract violated in cold_writer.cpp:" >&2
        echo "${M1_HITS}" | sed 's/^/[m1-no-mutex]   /' >&2
        exit 1
    fi
    echo "[m1-no-mutex] clean (no mutex / cv references in cold_writer.cpp)"
fi
