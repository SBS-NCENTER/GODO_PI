#!/usr/bin/env bash
# godo-mapping container entrypoint.
#
# On SIGINT / SIGTERM, runs ${MAP_SAVER_CMD} to write /maps/${MAP_NAME}.{pgm,yaml}
# and exits 0. The map saver command is indirected through MAP_SAVER_CMD so the
# host-side test (tests/test_entrypoint_trap.sh) can mock it without ROS.

set -euo pipefail

# Nit N1 — --help shim. verify-no-hw.sh --full smokes this via
# `docker run --rm godo-mapping:dev --help`.
if [[ "${1:-}" == "--help" ]]; then
    echo "godo-mapping entrypoint — runs slam_toolbox + rplidar inside the container."
    echo "Usage: docker run ... -e MAP_NAME=<name> godo-mapping:dev"
    exit 0
fi

# MAP_NAME is mandatory — it determines the output filenames.
if [[ -z "${MAP_NAME:-}" ]]; then
    echo "godo-mapping: MAP_NAME env-var is required (e.g., -e MAP_NAME=control_room_v1)." >&2
    exit 2
fi

# Output paths inside the container. The host bind-mounts ./maps -> /maps.
MAP_OUT_DIR="/maps"
MAP_OUT_BASE="${MAP_OUT_DIR}/${MAP_NAME}"

# Plan F9 — map saver indirection. Default writes /maps/${MAP_NAME}.{pgm,yaml}
# (the bind-mounted host path). tests/test_entrypoint_trap.sh overrides this
# to a `touch <flag>` shim. Assignment is AFTER MAP_OUT_BASE so the default
# expansion sees a defined variable.
#
# 2026-04-28: --ros-args -p save_map_timeout:=10.0 raises map_saver_cli's
# default 2-second wait — slam_toolbox publishes /map at map_update_interval
# (configured in slam_toolbox_async.yaml). 10 s gives ample headroom.
MAP_SAVER_CMD="${MAP_SAVER_CMD:-ros2 run nav2_map_server map_saver_cli -f ${MAP_OUT_BASE} --ros-args -p save_map_timeout:=10.0}"

# Track the foreground PID so the trap can wait on it after signaling.
LAUNCH_PID=""

# Nit N2 — trap fires regardless of TEST_MODE. In TEST_MODE the foreground is
# `sleep infinity`; the trap calls MAP_SAVER_CMD (mocked to touch the flag) and
# exits 0. In production the foreground is `ros2 launch ...`; the trap stops
# the launch graph, then calls the production MAP_SAVER_CMD default (which
# includes `-f ${MAP_OUT_BASE}` to write /maps/${MAP_NAME}.{pgm,yaml}), then
# exits 0.
on_signal() {
    # CRITICAL ordering (2026-04-28 hotfix): map_saver_cli subscribes to the
    # /map topic; it can only see published data while slam_toolbox is alive.
    # Run the saver BEFORE tearing down the launch graph. If we kill the
    # launch graph first, slam_toolbox stops publishing and map_saver waits
    # for a topic that will never appear → 'Failed to spin map subscription'.
    # Word-split MAP_SAVER_CMD intentionally so callers can inject extra args.
    # shellcheck disable=SC2086
    saver_failed=0
    if ! ${MAP_SAVER_CMD}; then
        saver_failed=1
    fi
    # Now graceful shutdown of the launch graph.
    if [[ -n "${LAUNCH_PID}" ]] && kill -0 "${LAUNCH_PID}" 2>/dev/null; then
        # SIGTERM (not SIGINT) so test-mode `sleep infinity` actually dies.
        # Bash background jobs in a non-interactive shell ignore SIGINT, which
        # would hang the trap's `wait` indefinitely. SIGTERM works for both
        # `sleep infinity` (test) and `ros2 launch` (production) — ros2 launch
        # treats SIGTERM as a graceful shutdown of the launch graph.
        kill -TERM "${LAUNCH_PID}" 2>/dev/null || true
        wait "${LAUNCH_PID}" 2>/dev/null || true
    fi
    # Banner emitted AFTER teardown so the warning is the operator's last
    # visible output. Saver failure must not mask the intentional Ctrl+C —
    # we still exit 0 so the shutdown is clean even on a half-built map.
    if [[ "${saver_failed}" -eq 1 ]]; then
        echo "" >&2
        echo "================================================================" >&2
        echo "godo-mapping: WARNING — map saver returned non-zero." >&2
        echo "  /maps/${MAP_NAME}.{pgm,yaml} may be missing or partial." >&2
        echo "  Check with 'ls -la maps/' on the host before copying to" >&2
        echo "  /etc/godo/maps/." >&2
        echo "================================================================" >&2
    fi
    exit 0
}
trap on_signal INT TERM

if [[ -n "${TEST_MODE:-}" ]]; then
    # Test path — no ROS. Stay alive until the trap fires.
    sleep infinity &
else
    # Production path — launch slam_toolbox + rplidar.
    # `source` of the ROS overlay is required for `ros2` to resolve.
    # ROS Jazzy's setup.bash references unset vars (e.g. AMENT_TRACE_SETUP_FILES)
    # and trips `set -u`. Relax strict mode for the source line only — restore
    # immediately so the rest of the entrypoint keeps the strict guarantees.
    set +u
    # shellcheck disable=SC1091
    source /opt/ros/jazzy/setup.bash
    # Overlay holding the upstream rplidar_ros build (rplidar_node + C1
    # launch). The Jazzy Debian rplidar_ros 2.1.0 only ships the legacy
    # rplidar_composition binary, which fails on C1 with 0x80008002.
    # shellcheck disable=SC1091
    source /opt/ros_overlay/install/setup.bash
    set -u
    ros2 launch /godo-mapping/launch/map.launch.py &
fi
LAUNCH_PID=$!

# Wait without -e blowing up if the foreground exits non-zero on signal teardown.
wait "${LAUNCH_PID}" || true
