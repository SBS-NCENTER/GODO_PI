"""
issue#14 — pgm_encoder unit tests (hardware-free).

These tests target the pure stdlib + numpy module ``pgm_encoder.py``
rather than the rclpy wrapper, so they run without ROS dependencies
under ``verify-no-hw.sh --quick``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Ensure the godo-mapping/ root is on sys.path so we can import
# `preview_node.pgm_encoder` without an installed package.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Skip the entire module if numpy is not available (e.g. system Python
# without it). godo-mapping's container always has numpy via apt.
pytest.importorskip("numpy")

from preview_node import pgm_encoder as E  # noqa: E402


def test_pgm_header_is_p5_with_dimensions_and_max() -> None:
    """First ASCII bytes are exactly ``P5\\n<W> <H>\\n255\\n``."""
    pixels = bytes(4 * 3)
    body = E.encode_pgm_p5(4, 3, pixels)
    assert body.startswith(b"P5\n4 3\n255\n")
    # Total length = header + W*H raw bytes.
    assert len(body) == len(b"P5\n4 3\n255\n") + 4 * 3


def test_pgm_pixel_mapping_unknown_205_free_254_occupied_0() -> None:
    """OccupancyGrid value mapping pin: -1→205, 0→254, ≥50→0."""
    # 1×4 row: unknown, free, threshold-1 (still unknown), occupied
    data = [-1, 0, 49, 100]
    pixels = E.occupancy_to_pixels(4, 1, data)
    # Y-flip: a 1-row grid is unchanged. pixel order is left-to-right.
    assert pixels[0] == E.PIXEL_UNKNOWN
    assert pixels[1] == E.PIXEL_FREE
    assert pixels[2] == E.PIXEL_UNKNOWN
    assert pixels[3] == E.PIXEL_OCCUPIED


def test_pgm_y_axis_flipped_to_top_down() -> None:
    """OccupancyGrid is row-major bottom-up in ROS. `occupancy_to_pixels`
    must Y-flip so the resulting top row of pixels is what was the
    BOTTOM row of the OccupancyGrid."""
    # 3×2: row0 (bottom) = [-1, -1], row1 (top) = [0, 0]
    data = [-1, -1, 0, 0]
    pixels = E.occupancy_to_pixels(2, 2, data)
    # Top row (PGM index 0..1) should be the OccupancyGrid's row1 → free.
    assert pixels[0] == E.PIXEL_FREE
    assert pixels[1] == E.PIXEL_FREE
    # Bottom row of PGM (index 2..3) should be OccupancyGrid's row0 → unknown.
    assert pixels[2] == E.PIXEL_UNKNOWN
    assert pixels[3] == E.PIXEL_UNKNOWN


def test_occupancy_to_pixels_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError):
        E.occupancy_to_pixels(2, 2, [1, 2, 3])  # 3 != 4


def test_occupancy_to_pixels_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError):
        E.occupancy_to_pixels(0, 5, [])
    with pytest.raises(ValueError):
        E.occupancy_to_pixels(5, -1, [])


def test_encode_pgm_p5_rejects_pixels_size_mismatch() -> None:
    with pytest.raises(ValueError):
        E.encode_pgm_p5(2, 2, b"\x00\x00\x00")  # 3 != 4


def test_encode_pgm_p5_handles_full_pipeline_byte_exact() -> None:
    """End-to-end: feed a tiny known OccupancyGrid → assert byte-exact PGM."""
    data = [-1, 0, 100, 0]  # row0 [unknown, free], row1 [occupied, free]
    pixels = E.occupancy_to_pixels(2, 2, data)
    body = E.encode_pgm_p5(2, 2, pixels)
    # Header byte-exact.
    expected_header = b"P5\n2 2\n255\n"
    assert body[: len(expected_header)] == expected_header
    # After Y-flip, top row of PGM = OccupancyGrid row1 → [occupied, free].
    raw = body[len(expected_header) :]
    assert raw[0] == E.PIXEL_OCCUPIED
    assert raw[1] == E.PIXEL_FREE
    # Bottom row of PGM = OccupancyGrid row0 → [unknown, free].
    assert raw[2] == E.PIXEL_UNKNOWN
    assert raw[3] == E.PIXEL_FREE


def test_constants_pinned() -> None:
    """Drift catch — pixel-value contract is operator-visible."""
    assert E.PIXEL_UNKNOWN == 205
    assert E.PIXEL_FREE == 254
    assert E.PIXEL_OCCUPIED == 0
    assert E.OCCUPIED_THRESHOLD_PERCENT == 50
    assert E.PREVIEW_DUMP_HZ == 1.0
    # 1 Hz = 1e9 ns interval.
    assert E.PREVIEW_DUMP_MIN_INTERVAL_NS == 10**9
