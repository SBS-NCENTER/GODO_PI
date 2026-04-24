#!/usr/bin/env bash
# Launch the godo_tracker_rt binary.
#
# Prerequisites:
#   - `scripts/setup-pi5-rt.sh` has been run ONCE as root on this host.
#   - `doc/freed_wiring.md` boot-config changes applied and the Pi rebooted.
#   - `scripts/build.sh` has produced build/src/godo_tracker_rt/godo_tracker_rt.
#
# No sudo needed — cap_sys_nice + cap_ipc_lock live on the binary itself.
# All flags (--ue-host, --freed-port, ...) pass through unchanged.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN="${ROOT_DIR}/build/src/godo_tracker_rt/godo_tracker_rt"

if [[ ! -x "${BIN}" ]]; then
    echo "run-pi5-tracker-rt: ${BIN} not found — run scripts/build.sh first." >&2
    exit 1
fi

exec "${BIN}" "$@"
