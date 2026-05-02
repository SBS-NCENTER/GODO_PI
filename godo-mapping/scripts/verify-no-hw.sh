#!/usr/bin/env bash
# Hardware-free verification for godo-mapping.
#
# --quick (default, ~1 s, no Docker daemon needed):
#     bash -n on every shell script
#     python3 ast.parse on launch/map.launch.py
#     tests/test_entrypoint_trap.sh (mock-driven SIGINT trap)
#     run-mapping.sh --help parses without error
#
# --full (~5 min, ~800 MB pull, Docker daemon needed; LiDAR not needed):
#     everything in --quick
#     docker build -t godo-mapping:dev .
#     docker run --rm godo-mapping:dev --help

set -euo pipefail

# Nit N7 — anchor cwd to godo-mapping/ so relative paths in --quick resolve
# regardless of the operator's invocation cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

MODE="${1:-}"

usage() {
    cat <<'EOF'
Usage: bash scripts/verify-no-hw.sh [--quick | --full | --help]

Hardware-free verification for godo-mapping.

Modes:
  --quick   (default) ~1 s. bash -n + ast parse + trap test + --help smoke.
            No Docker daemon needed. Run on every commit.
  --full    ~5 min, ~800 MB pull. --quick + docker build + container --help
            smoke. Docker daemon needed. Run before LiDAR reconnect dress
            rehearsal.
  --help    Show this message.
EOF
}

case "${MODE}" in
    "" | --quick) MODE="--quick" ;;
    --full)       ;;
    --help | -h)  usage; exit 0 ;;
    *)            echo "verify-no-hw: unknown mode '${MODE}'." >&2; usage >&2; exit 2 ;;
esac

step() { echo "verify-no-hw: $*"; }
fail() { echo "verify-no-hw: FAIL — $*" >&2; exit 1; }

# ── Quick checks ─────────────────────────────────────────────────────────

step "bash -n: shell scripts"
shell_files=(
    "entrypoint.sh"
    "scripts/run-mapping.sh"
    "scripts/verify-no-hw.sh"
    "tests/test_entrypoint_trap.sh"
)
for f in "${shell_files[@]}"; do
    if [[ ! -f "${f}" ]]; then
        fail "shell file '${f}' not found (cwd=${PWD})"
    fi
    bash -n "${f}" || fail "syntax error in '${f}'"
done

step "python3 ast.parse: launch/map.launch.py"
if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not on PATH (required for launch-file syntax check)"
fi
python3 -c "import ast; ast.parse(open('launch/map.launch.py').read())" \
    || fail "launch/map.launch.py is not valid Python"

step "tests/test_entrypoint_trap.sh"
bash tests/test_entrypoint_trap.sh \
    || fail "trap test failed (see output above)"

step "scripts/run-mapping.sh --help"
bash scripts/run-mapping.sh --help >/dev/null \
    || fail "run-mapping.sh --help did not exit 0"

# Track B (F20): collect both Python test files. Prefer system python3 +
# pytest; fall back to `uv run --project ../godo-webctl` so dev boxes
# without `apt install python3-pytest` still pass. The error path emits a
# pinned English message naming both install routes.
PYTEST_RUNNER=()
if python3 -c "import pytest" >/dev/null 2>&1; then
    step "python3 -c 'import pytest' (pre-flight: system pytest available)"
    PYTEST_RUNNER=(python3 -m pytest)
elif command -v uv >/dev/null 2>&1; then
    step "uv-managed pytest (pre-flight: falling back to godo-webctl uv env)"
    # godo-webctl ships pytest in its dev group; we reuse its venv so
    # godo-mapping does not need its own UV project.
    PYTEST_RUNNER=(uv run --project "${ROOT_DIR}/../godo-webctl" -- python -m pytest)
else
    fail "pytest not available — install via apt (python3-pytest) or uv (cd ../godo-webctl && uv sync)"
fi

step "pytest godo-mapping/scripts/ (test_repeatability.py + test_pose_watch.py)"
"${PYTEST_RUNNER[@]}" "${ROOT_DIR}/scripts/" -q \
    || fail "pytest under godo-mapping/scripts/ failed"

# issue#14 — preview node pgm_encoder unit tests. Hardware-free
# (pure stdlib + numpy; no rclpy).
step "pytest godo-mapping/tests/ (test_preview_dumper_pgm_encoder.py)"
"${PYTEST_RUNNER[@]}" "${ROOT_DIR}/tests/" -q \
    || fail "pytest under godo-mapping/tests/ failed"

if [[ "${MODE}" == "--quick" ]]; then
    step "OK (--quick)"
    # F11 audit reminder for operators (no-op in --quick — pinned visible).
    echo
    echo "Reminder: after the FIRST mapping run on real hardware, audit the"
    echo "  generated YAML keys against occupancy_grid.cpp:148-154. See"
    echo "  godo-mapping/README.md '첫 매핑 후 검증' section."
    exit 0
fi

# ── Full checks ──────────────────────────────────────────────────────────

step "docker build -t godo-mapping:dev ."
if ! command -v docker >/dev/null 2>&1; then
    fail "docker not on PATH (required for --full)"
fi
docker build -t godo-mapping:dev . \
    || fail "docker build failed"

step "docker run --rm godo-mapping:dev --help"
docker run --rm godo-mapping:dev --help >/dev/null \
    || fail "container --help smoke failed"

# rf2o reachability smoke (S4 fold, 2026-04-29). Must list
# `rf2o_laser_odometry_node` so the launch file can spawn it.
step "docker exec rf2o overlay smoke (ros2 pkg executables rf2o_laser_odometry)"
rf2o_smoke_out="$(docker run --rm --entrypoint bash godo-mapping:dev -c \
    'source /opt/ros/jazzy/setup.bash && source /opt/ros_overlay/install/setup.bash && ros2 pkg executables rf2o_laser_odometry')" \
    || fail "rf2o overlay smoke command failed inside the image"
if [[ "${rf2o_smoke_out}" != *"rf2o_laser_odometry_node"* ]]; then
    fail "rf2o overlay smoke did not list rf2o_laser_odometry_node (output: ${rf2o_smoke_out})"
fi

step "OK (--full)"
echo
echo "Reminder: after the FIRST mapping run on real hardware, audit the"
echo "  generated YAML keys against occupancy_grid.cpp:148-154. See"
echo "  godo-mapping/README.md '첫 매핑 후 검증' section."
