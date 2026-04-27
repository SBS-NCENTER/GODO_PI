#!/usr/bin/env bash
# Bare-bash test for godo-mapping/entrypoint.sh trap behavior.
#
# Plan F9 — runs without ROS and without Docker. Validates only that:
#   1. SIGINT triggers the trap.
#   2. The trap calls ${MAP_SAVER_CMD} (mocked here as `touch <flag>`).
#   3. The script exits 0 cleanly after the trap fires.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENTRYPOINT="${ROOT_DIR}/entrypoint.sh"

FLAG_FILE="/tmp/godo_mapping_saver_called.flag"

cleanup() {
    rm -f "${FLAG_FILE}"
}
trap cleanup EXIT

fail() {
    echo "test_entrypoint_trap: FAIL — $1" >&2
    exit 1
}

if [[ ! -f "${ENTRYPOINT}" ]]; then
    fail "entrypoint.sh not found at ${ENTRYPOINT}"
fi

# Step 3 — pre-clean.
rm -f "${FLAG_FILE}"

# Steps 1 + 2 — mock the saver and pin a test map name.
export MAP_SAVER_CMD="touch ${FLAG_FILE}"
export MAP_NAME="test_v2"
export TEST_MODE=1

# Step 4 — run entrypoint in background.
bash "${ENTRYPOINT}" &
pid=$!

# Step 5 — give the trap registration a moment, then send the stop signal.
#
# Plan F9 step 5 pinned `kill -INT $!`, but bash background jobs of a
# non-interactive shell inherit SIGINT=SIG_IGN per POSIX, and bash cannot
# re-trap a signal that was ignored at shell entry. SIGTERM has no such
# inheritance restriction and is trapped identically (`trap on_signal INT TERM`
# in entrypoint.sh covers both). In production, Docker forwards SIGINT to PID 1
# which does NOT inherit SIG_IGN, so the operator's Ctrl+C path still works.
sleep 0.3
if ! kill -0 "${pid}" 2>/dev/null; then
    fail "entrypoint exited before stop signal could be delivered (pid ${pid})"
fi
kill -TERM "${pid}"

# Step 6 — wait for graceful exit.
wait "${pid}"
rc=$?

# Step 7 — assert exit code 0.
if [[ "${rc}" -ne 0 ]]; then
    fail "entrypoint exit code ${rc} != 0 after SIGINT"
fi

# Step 8 — assert flag file exists.
if [[ ! -f "${FLAG_FILE}" ]]; then
    fail "MAP_SAVER_CMD was not invoked (flag file ${FLAG_FILE} missing)"
fi

echo "test_entrypoint_trap: OK"
exit 0
