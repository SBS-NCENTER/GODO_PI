#!/usr/bin/env bash
# One-time RT privileges bring-up for the godo-tracker RPi 5 host.
#
# This script is run ONCE, as root, before the first `run-pi5-tracker-rt.sh`
# invocation on a given machine. It does three things:
#   1. Grant cap_sys_nice + cap_ipc_lock to the built tracker binary (so
#      the binary itself can call mlockall and SCHED_FIFO without sudo).
#   2. Append rtprio / memlock rlimit entries for the 'godo' user to
#      /etc/security/limits.conf (idempotent).
#   3. Check /dev/ttyAMA0 ownership so FreeD reads will succeed.
#
# It is NOT called from run-pi5-tracker-rt.sh. The run script runs without
# sudo; privileges live on the binary itself via setcap.
#
# Usage:
#   sudo production/RPi5/scripts/setup-pi5-rt.sh [path-to-tracker-binary]

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "setup-pi5-rt: must run as root (try 'sudo')." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TRACKER_BIN="${1:-${ROOT_DIR}/build/src/godo_tracker_rt/godo_tracker_rt}"

echo "[1/3] grant cap_sys_nice,cap_ipc_lock on ${TRACKER_BIN}"
if [[ ! -x "${TRACKER_BIN}" ]]; then
    echo "  WARN: ${TRACKER_BIN} does not exist yet — run scripts/build.sh first." >&2
else
    setcap 'cap_sys_nice,cap_ipc_lock+ep' "${TRACKER_BIN}"
    getcap "${TRACKER_BIN}"
fi

echo "[2/3] rtprio / memlock rlimit for user 'godo' in /etc/security/limits.conf"
LIMITS_FILE="/etc/security/limits.conf"
for line in \
    "@godo - rtprio 99" \
    "@godo - memlock unlimited" \
; do
    if ! grep -Fqx "${line}" "${LIMITS_FILE}"; then
        echo "${line}" >> "${LIMITS_FILE}"
        echo "  added: ${line}"
    else
        echo "  present: ${line}"
    fi
done

echo "[3/3] /dev/ttyAMA0 ownership"
if [[ -e /dev/ttyAMA0 ]]; then
    ls -l /dev/ttyAMA0
    echo "  note: the tracker user must be in the 'dialout' group;"
    echo "        check with 'id <user>' and 'sudo usermod -aG dialout <user>'."
else
    echo "  /dev/ttyAMA0 not present yet. Apply the boot-config changes in"
    echo "  production/RPi5/doc/freed_wiring.md §B and reboot."
fi

echo "setup-pi5-rt: done."
