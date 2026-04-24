#!/usr/bin/env bash
# Launch the godo_jitter measurement binary.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN="${ROOT_DIR}/build/src/godo_jitter/godo_jitter"

if [[ ! -x "${BIN}" ]]; then
    echo "run-pi5-jitter: ${BIN} not found — run scripts/build.sh first." >&2
    exit 1
fi

exec "${BIN}" "$@"
