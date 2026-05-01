"""
issue#14 — pure-stdlib + numpy PGM (P5) encoder for the mapping preview.

Decoupled from rclpy so tests can run hardware-free under
``verify-no-hw.sh --quick``. The thin rclpy node ``preview_dumper.py``
sits on top and imports this module's ``encode_pgm_p5`` +
``occupancy_to_pixels`` functions.

Tier-1 constants are inline (no shared header — this surface lives
inside the container; webctl/RPi5 never import this file).
"""

from __future__ import annotations

import numpy as np

# --- Tier-1 ---------------------------------------------------------------
# Pixel mapping mirrors slam_toolbox's `map_saver_cli` convention so the
# canonical `<name>.pgm` and the `.preview/<name>.pgm` we publish look
# identical to operators flipping between Map > Overview and the live
# preview.
PIXEL_UNKNOWN = 205    # mid-grey
PIXEL_FREE = 254       # near-white; mirrors MAP_EDIT_FREE_PIXEL_VALUE
PIXEL_OCCUPIED = 0     # black

# nav_msgs/msg/OccupancyGrid encodes occupancy as int8 percent:
#   -1 = unknown
#   0..100 = occupancy probability percent
# slam_toolbox's map_saver_cli thresholds at 50% to discretise to PGM.
OCCUPIED_THRESHOLD_PERCENT = 50

PREVIEW_DUMP_HZ = 1.0
PREVIEW_DUMP_MIN_INTERVAL_NS = int(1e9 / PREVIEW_DUMP_HZ)


def occupancy_to_pixels(width: int, height: int, data: list[int]) -> bytes:
    """Map a flat OccupancyGrid `data` array into a top-down PGM byte
    string of length `width * height`.

    OccupancyGrid is row-major bottom-up in ROS; PGM is top-down. We
    flip Y so the PGM operators see is the same orientation as
    slam_toolbox's saved map.

    Args:
        width: PGM image width in pixels.
        height: PGM image height in pixels.
        data: flat int list of length `width * height`. Values:
            -1 = unknown, 0..100 = occupancy percent.

    Returns:
        Raw bytes of length `width * height`.

    Raises:
        ValueError on shape mismatch.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"non-positive dimensions: width={width} height={height}")
    if len(data) != width * height:
        raise ValueError(
            f"data length {len(data)} != width*height {width * height}",
        )
    arr = np.asarray(data, dtype=np.int8).reshape((height, width))[::-1, :]
    out = np.full((height, width), PIXEL_UNKNOWN, dtype=np.uint8)
    out[arr == 0] = PIXEL_FREE
    out[arr >= OCCUPIED_THRESHOLD_PERCENT] = PIXEL_OCCUPIED
    return bytes(out.tobytes())


def encode_pgm_p5(width: int, height: int, pixels: bytes) -> bytes:
    """Encode a (width, height) raw byte buffer as a netpbm P5 PGM.

    Header format: ``P5\\n<W> <H>\\n255\\n`` followed by `width * height`
    raw bytes. No comments. Caller is responsible for `pixels` being
    exactly `width * height` bytes (e.g. via ``occupancy_to_pixels``).

    Args:
        width / height: image dimensions.
        pixels: raw byte buffer.

    Returns:
        Complete PGM file body.

    Raises:
        ValueError on shape mismatch.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"non-positive dimensions: width={width} height={height}")
    expected = width * height
    if len(pixels) != expected:
        raise ValueError(
            f"pixels length {len(pixels)} != width*height {expected}",
        )
    header = f"P5\n{width} {height}\n255\n".encode("ascii")
    return header + pixels
