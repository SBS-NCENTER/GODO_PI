#!/usr/bin/env bash
# Convenience wrapper to run godo_smoke on the RPi 5 with sensible defaults.
#
# Usage:
#   scripts/run-pi5-smoke.sh [--port /dev/ttyUSB0] [--frames 10] [--tag smoke]
#
# Pre-requirement: scripts/build.sh must have been run so build/godo_smoke
# exists. The artefacts land under out/<ts>_<tag>/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN="${ROOT_DIR}/build/src/godo_smoke/godo_smoke"

if [[ ! -x "${BIN}" ]]; then
    echo "godo_smoke binary not found at ${BIN}" >&2
    echo "run scripts/build.sh first." >&2
    exit 1
fi

exec "${BIN}" --out-dir "${ROOT_DIR}/out" "$@"
