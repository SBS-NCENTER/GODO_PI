#!/usr/bin/env bash
# Promote a smoke run (out/<ts>_<tag>/) into a named Test Session.
#
# The smoke area (out/*) is a bring-up archive — ad-hoc, not versioned as
# a TS<N>. When a run turns out to be the "reference" for a formal session,
# call this script to move and rename it:
#
#   scripts/promote_smoke_to_ts.sh <smoke-dir> TS7 "C1 first light"
#
# Arguments:
#   <smoke-dir>  path under out/ (absolute or relative to the RPi5 root)
#   TS<N>        target session name; must match the pattern TS<digit>+
#   <note>       free-form one-liner appended to the promoted session log
#
# Effect:
#   out/<smoke-dir>/              →  ../../<TS_ROOT>/TS<N>/
#   appends one line to the moved logs/*.txt: "promoted_from: <smoke-dir>"
#
# TS_ROOT defaults to `test_sessions` at the repo root; override with
# GODO_TS_ROOT=/some/path.
set -euo pipefail

if [[ $# -lt 3 ]]; then
    echo "usage: $0 <smoke-dir> <TS-name> <one-line-note>" >&2
    exit 2
fi
SMOKE="$1"
TS_NAME="$2"
NOTE="$3"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${ROOT_DIR}/../.." && pwd)"
TS_ROOT_DEFAULT="${REPO_ROOT}/test_sessions"
TS_ROOT="${GODO_TS_ROOT:-${TS_ROOT_DEFAULT}}"

# Resolve the smoke directory (accept absolute or relative-to-out/).
if [[ "${SMOKE}" != /* ]]; then
    if [[ -d "${ROOT_DIR}/out/${SMOKE}" ]]; then
        SMOKE_ABS="${ROOT_DIR}/out/${SMOKE}"
    else
        SMOKE_ABS="${ROOT_DIR}/${SMOKE}"
    fi
else
    SMOKE_ABS="${SMOKE}"
fi
if [[ ! -d "${SMOKE_ABS}" ]]; then
    echo "smoke directory not found: ${SMOKE_ABS}" >&2
    exit 1
fi

if ! [[ "${TS_NAME}" =~ ^TS[0-9]+$ ]]; then
    echo "invalid TS name: ${TS_NAME} (must match TS<digits>)" >&2
    exit 1
fi

DEST="${TS_ROOT}/${TS_NAME}"
if [[ -e "${DEST}" ]]; then
    echo "refusing to overwrite existing ${DEST}" >&2
    exit 1
fi

mkdir -p "${TS_ROOT}"
mv "${SMOKE_ABS}" "${DEST}"

# Annotate each session log inside the promoted directory.
SRC_REL="$(realpath --relative-to="${REPO_ROOT}" "${SMOKE_ABS}" 2>/dev/null || echo "${SMOKE_ABS}")"
while IFS= read -r -d '' log; do
    {
        echo
        echo "## Promotion"
        echo "promoted_from   : ${SRC_REL}"
        echo "promoted_as     : ${TS_NAME}"
        echo "promotion_note  : ${NOTE}"
    } >> "${log}"
done < <(find "${DEST}/logs" -type f -name '*.txt' -print0 2>/dev/null)

echo "promoted: ${SMOKE_ABS}  ->  ${DEST}"
