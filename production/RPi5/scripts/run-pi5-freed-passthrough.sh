#!/usr/bin/env bash
# Launch the godo_freed_passthrough binary — minimal FreeD serial → UDP
# forwarder for wiring bring-up.
#
# Prerequisites:
#   - YL-128 wired per production/RPi5/doc/freed_wiring.md §A.
#   - Boot config from §B applied and Pi rebooted (so /dev/ttyAMA0 is the
#     PL011 UART0). On the stock Trixie image you may instead pass
#     --port /dev/serial0 (which symlinks to whichever ttyAMA<N> the
#     PL011 ended up as) without rebooting.
#   - Current user is in the `dialout` group (id | grep dialout).
#   - scripts/build.sh has produced
#     build/src/godo_freed_passthrough/godo_freed_passthrough.
#
# No sudo / setcap needed — this binary uses no RT privileges.
# All flags pass through unchanged. Defaults: 10.10.204.184:50002.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN="${ROOT_DIR}/build/src/godo_freed_passthrough/godo_freed_passthrough"

if [[ ! -x "${BIN}" ]]; then
    echo "run-pi5-freed-passthrough: ${BIN} not found — run scripts/build.sh first." >&2
    exit 1
fi

exec "${BIN}" "$@"
