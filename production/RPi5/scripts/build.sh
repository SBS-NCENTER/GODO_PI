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
# issue#11 P4-2-11-1 note: src/parallel/ ships ParallelEvalPool, which DOES
# use std::mutex + std::condition_variable internally for fork-join
# dispatch. The gate stays scoped to cold_writer.cpp — the pool's mutex is
# pimpl-hidden inside parallel_eval_pool.cpp, never visible to
# cold_writer.cpp's source text. M1 *spirit* is preserved because cold
# writer is NOT the wait-free publisher (only Thread D is); the pool's
# dispatch+join completes BEFORE target_offset.store() fires. See
# CODEBASE.md invariant (s).
#
# Test label inventory:
#   - hardware-free          — runs in CI / local without LiDAR or GPIO
#   - hardware-required      — runs only with RPLIDAR C1 attached
#                              (ctest -L hardware-required)
#   - hardware-required-gpio — runs only with /dev/gpiochip0 + gpio group
#                              perms (ctest -L hardware-required-gpio).
#                              Manually invoked; not part of the default
#                              hardware-free gate. Asserts libgpiod can
#                              open the chip and request the configured
#                              pins; press path is exercised by the
#                              hardware-free test_gpio_source_fake target.
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

# -----------------------------------------------------------------------
# [scan-publisher-grep] — Track D invariant: at RUNTIME, only
# cold_writer.cpp's run_one_iteration / run_live_iteration may call
# last_scan_seq.store(). main.cpp is allowed exactly ONE store at
# startup — the sentinel-iterations init that mirrors LastPose's
# init pattern (uds_protocol.md §C.5 + main.cpp comments). The
# Seqlock single-writer contract is single-writer at runtime; the boot
# init runs before any thread spawn so it can't race.
# Hits outside the (cold_writer.cpp, main.cpp) allow-list FAIL the build.
# -----------------------------------------------------------------------
SCAN_PUBLISHER_PATTERN='last_scan_seq\.store\b'
SCAN_PUBLISHER_HITS="$(grep -rnE "${SCAN_PUBLISHER_PATTERN}" "${ROOT_DIR}/src" 2>/dev/null \
    | grep -v "${ROOT_DIR}/src/localization/cold_writer.cpp" \
    | grep -v "${ROOT_DIR}/src/godo_tracker_rt/main.cpp" || true)"
if [[ -n "${SCAN_PUBLISHER_HITS}" ]]; then
    echo "[scan-publisher-grep] FAIL — last_scan_seq.store called outside the allow-list:" >&2
    echo "${SCAN_PUBLISHER_HITS}" | sed 's/^/[scan-publisher-grep]   /' >&2
    exit 1
fi
# Pin: main.cpp must contain EXACTLY ONE store call (the boot sentinel).
# More than one would be a regression — runtime stores belong to the
# cold writer, not main.
MAIN_SCAN_STORES="$(grep -cE "${SCAN_PUBLISHER_PATTERN}" \
    "${ROOT_DIR}/src/godo_tracker_rt/main.cpp" 2>/dev/null || echo 0)"
if [[ "${MAIN_SCAN_STORES}" -gt 1 ]]; then
    echo "[scan-publisher-grep] FAIL — main.cpp has ${MAIN_SCAN_STORES} last_scan_seq.store calls; expected 1 (boot sentinel only)" >&2
    exit 1
fi
echo "[scan-publisher-grep] clean (last_scan_seq.store only in cold_writer.cpp + 1 boot init in main.cpp)"

# -----------------------------------------------------------------------
# [hot-path-isolation-grep] — Track D invariant: Thread D
# (thread_d_rt in main.cpp) MUST NOT reference last_scan_seq. The 59.94 Hz
# UDP send loop runs at SCHED_FIFO; touching the cold-writer's scan
# seqlock from there would couple the hot path to a 11 KiB seqlock copy.
# Hits FAIL the build.
# -----------------------------------------------------------------------
HOT_PATH_TARGET="${ROOT_DIR}/src/godo_tracker_rt/main.cpp"
HOT_PATH_PATTERN='last_scan_seq'
# Extract the body of `void thread_d_rt(...)` once; reused by
# [hot-path-isolation-grep] (Track D) and [hot-path-jitter-grep] (PR-DIAG).
if [[ -f "${HOT_PATH_TARGET}" ]]; then
    HOT_BODY="$(awk '
        /^void thread_d_rt\(/ { in_fn=1 }
        in_fn { print; for (i=1; i<=length($0); ++i) {
                    c = substr($0, i, 1);
                    if (c == "{") depth++;
                    else if (c == "}") { depth--; if (depth == 0 && in_fn) { in_fn=0; exit } }
                } }
    ' "${HOT_PATH_TARGET}")"
    HOT_HITS="$(echo "${HOT_BODY}" | grep -nE "${HOT_PATH_PATTERN}" || true)"
    if [[ -n "${HOT_HITS}" ]]; then
        echo "[hot-path-isolation-grep] FAIL — last_scan_seq referenced inside thread_d_rt:" >&2
        echo "${HOT_HITS}" | sed 's/^/[hot-path-isolation-grep]   /' >&2
        exit 1
    fi
    echo "[hot-path-isolation-grep] clean (thread_d_rt does not reference last_scan_seq)"
fi

# -----------------------------------------------------------------------
# [hot-path-jitter-grep] — PR-DIAG invariant: Thread D records jitter into
# `jitter_ring` once per tick via `jitter_ring.record(...)`, NEVER calls
# `jitter_ring.snapshot(...)` (reader-side; lives in diag_publisher), and
# NEVER touches the published seqlock or percentile/sort code.
#
# Mode-A M3 fold pinned the symmetric contract: exactly one
# `jitter_ring\.` reference total AND zero `jitter_ring\.snapshot`
# references. Future read of the snapshot from Thread D would otherwise
# escape a named-symbols list.
# -----------------------------------------------------------------------
if [[ -f "${HOT_PATH_TARGET}" ]]; then
    JITTER_RING_TOTAL=$(echo "${HOT_BODY}" | grep -cE 'jitter_ring\.' || true)
    JITTER_RING_SNAPSHOT=$(echo "${HOT_BODY}" | grep -cE 'jitter_ring\.snapshot' || true)
    if [[ "${JITTER_RING_TOTAL}" -ne 1 ]]; then
        echo "[hot-path-jitter-grep] FAIL — thread_d_rt has ${JITTER_RING_TOTAL} 'jitter_ring.' references; expected exactly 1 (single record() call)" >&2
        echo "${HOT_BODY}" | grep -nE 'jitter_ring\.' | sed 's/^/[hot-path-jitter-grep]   /' >&2 || true
        exit 1
    fi
    if [[ "${JITTER_RING_SNAPSHOT}" -ne 0 ]]; then
        echo "[hot-path-jitter-grep] FAIL — thread_d_rt has ${JITTER_RING_SNAPSHOT} 'jitter_ring.snapshot' references; reader-side belongs in diag_publisher only" >&2
        exit 1
    fi
    JITTER_FORBIDDEN_PATTERN='\bstd::sort\b|\bcompute_percentile\b|\bcompute_summary\b|\bformat_ok_jitter\b|\bjitter_seq\b'
    JITTER_FORBIDDEN="$(echo "${HOT_BODY}" | grep -nE "${JITTER_FORBIDDEN_PATTERN}" || true)"
    if [[ -n "${JITTER_FORBIDDEN}" ]]; then
        echo "[hot-path-jitter-grep] FAIL — thread_d_rt references percentile/seqlock-store machinery:" >&2
        echo "${JITTER_FORBIDDEN}" | sed 's/^/[hot-path-jitter-grep]   /' >&2
        exit 1
    fi
    echo "[hot-path-jitter-grep] clean (thread_d_rt has 1 jitter_ring. call, 0 snapshot/sort/seqlock-store references)"
fi

# -----------------------------------------------------------------------
# [jitter-publisher-grep] — PR-DIAG invariant: only rt/diag_publisher.cpp
# may call `jitter_seq.store(...)` or `amcl_rate_seq.store(...)`. main.cpp
# does NOT seed these (default-constructed payload is the sentinel valid=0,
# so no boot init is needed — different from last_pose_seq/last_scan_seq
# where iterations=-1 is the operator-visible distinction).
#
# Tests are explicitly allow-listed because they construct seqlocks
# directly to drive percentile/store assertions.
# -----------------------------------------------------------------------
JITTER_STORE_PATTERN='(jitter_seq|amcl_rate_seq)\.store\b'
JITTER_STORE_HITS="$(grep -rnE "${JITTER_STORE_PATTERN}" "${ROOT_DIR}/src" 2>/dev/null \
    | grep -v "${ROOT_DIR}/src/rt/diag_publisher.cpp" || true)"
if [[ -n "${JITTER_STORE_HITS}" ]]; then
    echo "[jitter-publisher-grep] FAIL — jitter_seq.store / amcl_rate_seq.store called outside diag_publisher.cpp:" >&2
    echo "${JITTER_STORE_HITS}" | sed 's/^/[jitter-publisher-grep]   /' >&2
    exit 1
fi
echo "[jitter-publisher-grep] clean (jitter_seq.store / amcl_rate_seq.store only in rt/diag_publisher.cpp)"

# -----------------------------------------------------------------------
# [amcl-rate-publisher-grep] — PR-DIAG invariant (Mode-A M2): only
# cold_writer.cpp's run_one_iteration / run_live_iteration may call
# `amcl_rate_accum.record(...)`. Mirrors [scan-publisher-grep] precedent.
# Mode-A N3 note: `amcl_rate_seq` reader-only (diag_publisher reads
# the accumulator directly via snapshot()) — pinned by code review,
# not by build grep here.
# -----------------------------------------------------------------------
AMCL_RATE_RECORD_PATTERN='amcl_rate_accum\.record\b'
AMCL_RATE_RECORD_HITS="$(grep -rnE "${AMCL_RATE_RECORD_PATTERN}" "${ROOT_DIR}/src" 2>/dev/null \
    | grep -v "${ROOT_DIR}/src/localization/cold_writer.cpp" || true)"
if [[ -n "${AMCL_RATE_RECORD_HITS}" ]]; then
    echo "[amcl-rate-publisher-grep] FAIL — amcl_rate_accum.record called outside cold_writer.cpp:" >&2
    echo "${AMCL_RATE_RECORD_HITS}" | sed 's/^/[amcl-rate-publisher-grep]   /' >&2
    exit 1
fi
echo "[amcl-rate-publisher-grep] clean (amcl_rate_accum.record only in cold_writer.cpp)"

# -----------------------------------------------------------------------
# [hot-path-config-grep] — Track B-CONFIG (PR-CONFIG-α) invariant: the
# while-loop body of `void thread_d_rt(...)` MUST NOT reference `cfg.`,
# `live_cfg`, `hot_cfg_seq`, or `HotConfig`. Setup BEFORE the while loop
# is allowed to read `cfg.rt_cpu` / `cfg.rt_priority` / `cfg.ue_host` /
# `cfg.ue_port` / `cfg.t_ramp_ns` ONCE — those are restart-class fields,
# captured at thread start.
#
# Implementation: extract the body BETWEEN the line containing
# "while (godo::rt::g_running.load" and the matching closing brace.
# That subset must contain ZERO references to cfg / HotConfig / hot_cfg_seq.
# -----------------------------------------------------------------------
if [[ -f "${HOT_PATH_TARGET}" ]]; then
    HOT_LOOP_BODY="$(awk '
        /^void thread_d_rt\(/ { in_fn=1 }
        in_fn && /while \(godo::rt::g_running.load/ { in_loop=1 }
        in_loop { print; for (i=1; i<=length($0); ++i) {
                    c = substr($0, i, 1);
                    if (c == "{") loop_depth++;
                    else if (c == "}") { loop_depth--;
                        if (loop_depth == 0 && in_loop) { in_loop=0; in_fn=0; exit }
                    }
                } }
    ' "${HOT_PATH_TARGET}")"
    HOT_CFG_PATTERN='\bcfg\.|\blive_cfg\b|\bhot_cfg_seq\b|\bHotConfig\b'
    HOT_CFG_HITS="$(echo "${HOT_LOOP_BODY}" | grep -nE "${HOT_CFG_PATTERN}" || true)"
    if [[ -n "${HOT_CFG_HITS}" ]]; then
        echo "[hot-path-config-grep] FAIL — thread_d_rt loop body references cfg/live_cfg/hot_cfg_seq/HotConfig:" >&2
        echo "${HOT_CFG_HITS}" | sed 's/^/[hot-path-config-grep]   /' >&2
        exit 1
    fi
    echo "[hot-path-config-grep] clean (thread_d_rt loop body has no cfg/live_cfg/hot_cfg_seq/HotConfig references)"
fi

# -----------------------------------------------------------------------
# [hot-config-publisher-grep] — Track B-CONFIG (PR-CONFIG-α) invariant:
# only `src/config/apply.cpp` (production runtime) and
# `src/godo_tracker_rt/main.cpp` (boot init) may store into `hot_cfg_seq`.
# Tests construct seqlocks under their own names, so this grep is scoped
# to `src/`.
# -----------------------------------------------------------------------
HOT_CFG_STORE_PATTERN='hot_cfg_seq\.store\b'
HOT_CFG_STORE_HITS="$(grep -rnE --include='*.cpp' "${HOT_CFG_STORE_PATTERN}" "${ROOT_DIR}/src" 2>/dev/null \
    | grep -v "${ROOT_DIR}/src/config/apply.cpp" \
    | grep -v "${ROOT_DIR}/src/godo_tracker_rt/main.cpp" || true)"
if [[ -n "${HOT_CFG_STORE_HITS}" ]]; then
    echo "[hot-config-publisher-grep] FAIL — hot_cfg_seq.store called outside the allow-list:" >&2
    echo "${HOT_CFG_STORE_HITS}" | sed 's/^/[hot-config-publisher-grep]   /' >&2
    exit 1
fi
echo "[hot-config-publisher-grep] clean (hot_cfg_seq.store only in config/apply.cpp + main.cpp boot init)"

# -----------------------------------------------------------------------
# [atomic-toml-write-grep] — Track B-CONFIG (PR-CONFIG-α) invariant:
# only `src/config/atomic_toml_writer.cpp` may issue `::rename(`,
# `::mkstemp(`, or `std::filesystem::rename` against TOML paths. Other
# producers writing tracker.toml directly would bypass the atomic-write
# protocol (TM3 in plan).
#
# Allow-list: `src/uds/uds_server.cpp` legitimately uses ::rename for
# atomic-rename UDS bind (issue#10.1 PR #73 + issue#18). The UDS rename
# operates on `/run/godo/ctl.sock`, not on TOML — different invariant
# surface; both producers may safely co-exist.
# -----------------------------------------------------------------------
ATOMIC_TOML_PATTERN='::mkstemp\(|::rename\(|std::filesystem::rename'
ATOMIC_TOML_HITS="$(grep -rnE --include='*.cpp' "${ATOMIC_TOML_PATTERN}" "${ROOT_DIR}/src" 2>/dev/null \
    | grep -v "${ROOT_DIR}/src/config/atomic_toml_writer.cpp" \
    | grep -v "${ROOT_DIR}/src/uds/uds_server.cpp" || true)"
if [[ -n "${ATOMIC_TOML_HITS}" ]]; then
    echo "[atomic-toml-write-grep] FAIL — mkstemp/rename called outside atomic_toml_writer.cpp / uds_server.cpp:" >&2
    echo "${ATOMIC_TOML_HITS}" | sed 's/^/[atomic-toml-write-grep]   /' >&2
    exit 1
fi
echo "[atomic-toml-write-grep] clean (mkstemp/rename only in config/atomic_toml_writer.cpp + uds/uds_server.cpp)"

# -----------------------------------------------------------------------
# [edt-scratch-asserted] — issue#19 invariant: the type-erased EDT scratch
# dispatcher in parallel_eval_pool.cpp MUST trip a size-mismatch guard in
# BOTH debug AND release builds. D1 (operator-locked 2026-05-06) bans the
# NDEBUG-conditional `assert(...)` macro for this guard because under
# release builds it would compile out and a caller bug would silently
# produce OOB / UB on uninitialised scratch.
#
# The grep targets the dispatcher's function definition in
# parallel_eval_pool.cpp:
#   - REQUIRES at least one `std::abort` OR `fprintf(stderr).*scratch`
#     (the pair the runtime guard emits before aborting).
#   - REJECTS any `assert(.*per_worker` / `assert(.*scratch` (NDEBUG-
#     conditional macro path is forbidden).
#   - REJECTS any `#ifdef NDEBUG` / `#ifndef NDEBUG` near the guard
#     (would gate the abort on build flavour).
# Mode-A n4 fold: target the .cpp function body, not the call sites,
# because call sites belong to caller modules (likelihood_field.cpp +
# future EDT users) and would drift on refactor.
# -----------------------------------------------------------------------
EDT_SCRATCH_TARGET="${ROOT_DIR}/src/parallel/parallel_eval_pool.cpp"
if [[ -f "${EDT_SCRATCH_TARGET}" ]]; then
    EDT_ABORT_HITS=$(grep -cE 'std::abort\b' "${EDT_SCRATCH_TARGET}" || true)
    EDT_FPRINTF_HITS=$(grep -cE 'fprintf.*scratch|edt-scratch-asserted' \
        "${EDT_SCRATCH_TARGET}" || true)
    if [[ "${EDT_ABORT_HITS}" -lt 1 || "${EDT_FPRINTF_HITS}" -lt 1 ]]; then
        echo "[edt-scratch-asserted] FAIL — parallel_eval_pool.cpp is missing the unconditional size-mismatch guard (std::abort + fprintf(stderr)). D1 requires the guard trip in both debug and release; assert(...) is banned." >&2
        exit 1
    fi
    EDT_ASSERT_HITS=$(grep -cE 'assert\(.*per_worker|assert\(.*scratch' \
        "${EDT_SCRATCH_TARGET}" || true)
    if [[ "${EDT_ASSERT_HITS}" -gt 0 ]]; then
        echo "[edt-scratch-asserted] FAIL — parallel_eval_pool.cpp uses assert() macro for the per_worker / scratch size guard; assert is NDEBUG-conditional and compiles out under release. Use 'if (size != expected) { fprintf + std::abort(); }' instead." >&2
        grep -nE 'assert\(.*per_worker|assert\(.*scratch' \
            "${EDT_SCRATCH_TARGET}" | sed 's/^/[edt-scratch-asserted]   /' >&2
        exit 1
    fi
    EDT_NDEBUG_HITS=$(grep -cE '#if(n)?def\s+NDEBUG' "${EDT_SCRATCH_TARGET}" || true)
    if [[ "${EDT_NDEBUG_HITS}" -gt 0 ]]; then
        echo "[edt-scratch-asserted] FAIL — parallel_eval_pool.cpp gates code on NDEBUG; the size guard MUST be unconditional." >&2
        exit 1
    fi
    echo "[edt-scratch-asserted] clean (parallel_eval_pool.cpp dispatcher emits unconditional fprintf+std::abort; no assert(per_worker/scratch); no NDEBUG gating)"
fi
