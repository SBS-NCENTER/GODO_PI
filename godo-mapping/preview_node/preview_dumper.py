#!/usr/bin/env python3
"""
issue#14 — ROS2 preview PGM dumper.

Subscribes ``/map`` (``nav_msgs/msg/OccupancyGrid``), throttles to 1 Hz,
and atomic-writes a PGM to ``/maps/.preview/${MAP_NAME}.pgm``.

The pure encoder lives in ``pgm_encoder.py`` so unit tests can run
without rclpy (verify-no-hw.sh --quick path). This file is the thin
rclpy wrapper.

Single-writer / single-instance discipline: this node is the SOLE
writer to ``/maps/.preview/<name>.pgm``. The atomic write
(``tmp + os.replace``) means the SPA never sees a half-written PGM.
"""

from __future__ import annotations

import os
from pathlib import Path

import rclpy  # type: ignore[import-not-found]
from nav_msgs.msg import OccupancyGrid  # type: ignore[import-not-found]
from rclpy.node import Node  # type: ignore[import-not-found]

from .pgm_encoder import (
    PREVIEW_DUMP_MIN_INTERVAL_NS,
    encode_pgm_p5,
    occupancy_to_pixels,
)


class PreviewDumper(Node):  # type: ignore[misc]
    """rclpy node that publishes 1 Hz PGM previews of the in-progress map."""

    def __init__(self) -> None:
        super().__init__("godo_mapping_preview_dumper")
        self._map_name = os.environ["MAP_NAME"]  # entrypoint enforces presence
        self._out_dir = Path("/maps/.preview")
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._out_path = self._out_dir / f"{self._map_name}.pgm"
        self._last_emit_ns = 0
        self._sub = self.create_subscription(
            OccupancyGrid, "/map", self._on_map, 1,
        )

    def _on_map(self, msg: OccupancyGrid) -> None:
        now_ns = self.get_clock().now().nanoseconds
        if now_ns - self._last_emit_ns < PREVIEW_DUMP_MIN_INTERVAL_NS:
            return
        self._last_emit_ns = now_ns
        self._write_pgm(msg)

    def _write_pgm(self, msg: OccupancyGrid) -> None:
        w = msg.info.width
        h = msg.info.height
        pixels = occupancy_to_pixels(w, h, list(msg.data))
        body = encode_pgm_p5(w, h, pixels)
        tmp = self._out_path.with_suffix(".pgm.tmp")
        with open(tmp, "wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._out_path)


def main() -> None:
    rclpy.init()
    node = PreviewDumper()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
