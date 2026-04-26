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
#
# Phase 4-2 D Wave A note: Live mode in cold_writer.cpp re-uses the
# pre-reserved `beams_buf` (PARTICLE_BUFFER_MAX-sized) on every scan —
# no new allocation surface introduced. Cold writer remains OFF this
# scan list intentionally: it is a cold-path thread (OTHER, not FIFO),
# so its allocation footprint is judged at code review, not by this gate.
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
#
# Phase 4-2 D Wave A note: Live mode body adds zero std::mutex references.
# The gate stays narrow to cold_writer.cpp by design — Wave B's GPIO and
# UDS source files (src/gpio/, src/uds/) live in their own translation
# units and are NOT gated here. Both Wave B modules use single-thread
# accept/wait loops with no shared mutable state, so no mutex is required
# there either, but the gate's load-bearing target is the cold publish
# path on the AMCL → smoother seam.
#
# Test label inventory:
#   - hardware-free          — runs in CI / local without LiDAR or GPIO
#   - hardware-required      — runs only with RPLIDAR C1 attached
#   - hardware-required-gpio — (Wave B) runs only with /dev/gpiochip0
#   - python-required        — runs only when uv + Python prototype present
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
