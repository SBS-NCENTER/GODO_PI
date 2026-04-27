#!/usr/bin/env bash
# Host-side wrapper for godo-mapping container.
#
# Usage:   bash scripts/run-mapping.sh <map_name>
# Example: bash scripts/run-mapping.sh control_room_v1
#
# Walk the LiDAR around the room for ~1 minute, then Ctrl+C. The trap inside
# entrypoint.sh writes maps/<map_name>.{pgm,yaml}.
#
# Env-var overrides:
#   LIDAR_DEV       LiDAR USB serial device  (default: /dev/ttyUSB0)
#   IMAGE_TAG       Docker image tag         (default: godo-mapping:dev)

set -euo pipefail

# Nit N7 — anchor cwd to the godo-mapping repo subdir so the bind mount
# (./maps:/maps) and the pre-flight collision check both resolve correctly
# regardless of the operator's invocation cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# Plan F12 — LIDAR_DEV is overridable for hosts where C1 enumerates as ttyUSB1.
LIDAR_DEV="${LIDAR_DEV:-/dev/ttyUSB0}"
IMAGE_TAG="${IMAGE_TAG:-godo-mapping:dev}"
CONTAINER_NAME="godo-mapping"

usage() {
    cat <<'EOF'
Usage: bash scripts/run-mapping.sh <map_name>

Runs the godo-mapping container, walks the LiDAR around the room while you
hold it, and on Ctrl+C writes maps/<map_name>.{pgm,yaml}.

Env-var overrides:
  LIDAR_DEV       LiDAR USB serial device  (default: /dev/ttyUSB0)
  IMAGE_TAG       Docker image tag         (default: godo-mapping:dev)
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi

MAP_NAME="$1"

# Map name sanity — keep filenames safe for shell, YAML, and Windows backups.
if [[ ! "${MAP_NAME}" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "godo-mapping: map name '${MAP_NAME}' contains invalid characters." >&2
    echo "  Allowed: letters, digits, '.', '_', '-'." >&2
    exit 2
fi

# Plan F6 — pinned filename-collision message (byte-exact).
if [[ -e "maps/${MAP_NAME}.pgm" ]]; then
    echo "godo-mapping: 'maps/${MAP_NAME}.pgm' already exists. Remove it first or pick a new name." >&2
    exit 1
fi

# Plan F6 — pinned stale-container message (byte-exact). Filter checks both
# running and stopped containers to catch operators who forgot --rm or whose
# previous run crashed before cleanup.
if docker ps -a --filter "name=^${CONTAINER_NAME}$" --format '{{.Names}}' | grep -q .; then
    echo "godo-mapping: container 'godo-mapping' is already running. Stop it first: docker stop godo-mapping" >&2
    exit 1
fi

# LiDAR device must exist on the host — surface the obvious failure early
# instead of letting docker run --device fail with a less helpful message.
if [[ ! -e "${LIDAR_DEV}" ]]; then
    echo "godo-mapping: LiDAR device '${LIDAR_DEV}' not found." >&2
    echo "  Plug in the C1 (USB CP2102 dongle) or set LIDAR_DEV=/dev/ttyUSBn." >&2
    exit 1
fi

# Image must be built — operators are pointed at verify-no-hw.sh --full or
# `docker build -t godo-mapping:dev .`.
if ! docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
    echo "godo-mapping: image '${IMAGE_TAG}' not found — build it first:" >&2
    echo "  docker build -t ${IMAGE_TAG} ." >&2
    echo "  (or run: bash scripts/verify-no-hw.sh --full)" >&2
    exit 1
fi

echo "godo-mapping: starting mapping run for '${MAP_NAME}'."
echo "  device: ${LIDAR_DEV}"
echo "  image:  ${IMAGE_TAG}"
echo "  output: maps/${MAP_NAME}.{pgm,yaml}"
echo "Walk the LiDAR around the room slowly (~30 cm/s). Ctrl+C to stop and save."

exec docker run --rm \
    --name "${CONTAINER_NAME}" \
    --network=host \
    --device="${LIDAR_DEV}" \
    -v "${ROOT_DIR}/maps:/maps" \
    -e "MAP_NAME=${MAP_NAME}" \
    "${IMAGE_TAG}"
