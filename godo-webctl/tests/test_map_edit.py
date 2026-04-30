"""
Track B-MAPEDIT — `map_edit.apply_edit` unit tests.

13 backend unit cases per planner §5 (12 baseline + T1 grey threshold +
boundary-case + module-discipline pin).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from godo_webctl import map_edit
from godo_webctl.constants import (
    MAP_EDIT_FREE_PIXEL_VALUE,
    MAP_EDIT_MASK_PNG_MAX_BYTES,
    MAP_EDIT_PAINT_THRESHOLD,
)

# Local helpers; conftest's helpers are visible by name but mypy + ruff
# prefer explicit re-imports for test files. We import inline.


def _make_pgm(tmp_path: Path, width: int, height: int, fill: int = 0) -> Path:
    from tests.conftest import make_test_pgm_bytes

    pgm = tmp_path / "active.pgm"
    pgm.write_bytes(make_test_pgm_bytes(width, height, fill=fill))
    return pgm


def _make_mask(width: int, height: int, painted_indices: list[int]) -> bytes:
    from tests.conftest import make_test_mask_png

    return make_test_mask_png(width, height, painted_indices)


def _read_body(pgm: Path, width: int, height: int) -> bytes:
    """Return only the raw pixel bytes (header stripped)."""
    raw = pgm.read_bytes()
    # Trivial header: `P5\n<W> <H>\n255\n` (ASCII-decimal).
    header = f"P5\n{width} {height}\n255\n".encode("ascii")
    assert raw.startswith(header)
    return raw[len(header) : len(header) + width * height]


# 1. empty mask → no-op
def test_apply_edit_empty_mask_no_op(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    original = pgm.read_bytes()
    mask = _make_mask(4, 4, [])  # all-zero
    result = map_edit.apply_edit(pgm, mask)
    assert result.pixels_changed == 0
    assert pgm.read_bytes() == original


# 2. full mask → every cell becomes FREE
def test_apply_edit_full_mask_writes_free_value(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    mask = _make_mask(4, 4, list(range(16)))  # all painted
    result = map_edit.apply_edit(pgm, mask)
    assert result.pixels_changed == 16
    body = _read_body(pgm, 4, 4)
    assert all(b == MAP_EDIT_FREE_PIXEL_VALUE for b in body)


# 3. partial mask → exact cells flipped, others untouched
def test_apply_edit_partial_mask(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 8, 8, fill=100)
    painted = [0, 7, 9, 33, 63]  # five known indices in 8×8
    mask = _make_mask(8, 8, painted)
    result = map_edit.apply_edit(pgm, mask)
    assert result.pixels_changed == 5
    body = _read_body(pgm, 8, 8)
    for i in range(64):
        if i in painted:
            assert body[i] == MAP_EDIT_FREE_PIXEL_VALUE, f"i={i}"
        else:
            assert body[i] == 100, f"i={i}"


# 4. idempotent: paint over already-free cell does NOT count
def test_apply_edit_does_not_change_already_free(tmp_path: Path) -> None:
    # PGM pre-filled with FREE_PIXEL_VALUE in cells 0+1, fill=100 elsewhere.
    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    raw = bytearray(pgm.read_bytes())
    header_len = len(b"P5\n4 4\n255\n")
    raw[header_len + 0] = MAP_EDIT_FREE_PIXEL_VALUE
    raw[header_len + 1] = MAP_EDIT_FREE_PIXEL_VALUE
    pgm.write_bytes(bytes(raw))
    mask = _make_mask(4, 4, [0, 1, 2])  # paint 3 cells; 2 already free
    result = map_edit.apply_edit(pgm, mask)
    # Only cell 2 actually changed.
    assert result.pixels_changed == 1


# 5. dimensions mismatch raises
def test_apply_edit_dimensions_mismatch_raises(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    mask = _make_mask(8, 8, [])
    with pytest.raises(map_edit.MaskShapeMismatch):
        map_edit.apply_edit(pgm, mask)


# 6. non-PNG bytes → MaskDecodeFailed
def test_apply_edit_mask_decode_fails_raises(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    with pytest.raises(map_edit.MaskDecodeFailed):
        map_edit.apply_edit(pgm, b"not a png at all")


# 7. mask too large → MaskTooLarge raised at the module layer too
def test_apply_edit_mask_too_large_raises(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    oversize = b"x" * (MAP_EDIT_MASK_PNG_MAX_BYTES + 1)
    with pytest.raises(map_edit.MaskTooLarge):
        map_edit.apply_edit(pgm, oversize)


# 8. atomic write: os.replace failure leaves PGM untouched + no .tmp leftover
def test_apply_edit_atomic_write(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    original = pgm.read_bytes()
    mask = _make_mask(4, 4, list(range(16)))

    real_replace = os.replace

    def boom(src: object, dst: object) -> None:
        # Mimic the real syscall touching tmp first so the mocked
        # branch is realistic; raise BEFORE actually swapping.
        del src, dst
        raise OSError("simulated_replace_failure")

    with (
        mock.patch.object(os, "replace", side_effect=boom),
        pytest.raises(OSError, match="simulated_replace_failure"),
    ):
        map_edit.apply_edit(pgm, mask)

    # Original bytes preserved.
    assert pgm.read_bytes() == original
    # S3 fold: no leftover *.tmp after failure.
    assert not list(tmp_path.glob("*.tmp"))
    # Sanity: real os.replace still works post-test.
    assert real_replace is os.replace


# 9. active PGM missing → ActiveMapMissing
def test_apply_edit_active_pgm_missing_raises(tmp_path: Path) -> None:
    ghost = tmp_path / "no_such.pgm"
    mask = _make_mask(4, 4, [])
    with pytest.raises(map_edit.ActiveMapMissing):
        map_edit.apply_edit(ghost, mask)


# 10. header bytes preserved byte-for-byte
def test_apply_edit_preserves_pgm_header(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    header = b"P5\n4 4\n255\n"
    original = pgm.read_bytes()
    assert original.startswith(header)
    mask = _make_mask(4, 4, list(range(16)))
    map_edit.apply_edit(pgm, mask)
    new = pgm.read_bytes()
    assert new[: len(header)] == original[: len(header)]


# 11. RGBA: alpha > 0 means paint
def test_apply_edit_alpha_channel_marks_paint(tmp_path: Path) -> None:
    from io import BytesIO

    from PIL import Image

    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    # Make an RGBA mask: cells 0..7 alpha=255, cells 8..15 alpha=0.
    rgba = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    px = rgba.load()
    assert px is not None
    for i in range(8):
        px[i % 4, i // 4] = (0, 0, 0, 255)
    buf = BytesIO()
    rgba.save(buf, format="PNG")
    result = map_edit.apply_edit(pgm, buf.getvalue())
    assert result.pixels_changed == 8


# 12. drift catch: written value equals constants.MAP_EDIT_FREE_PIXEL_VALUE
def test_apply_edit_pixel_value_is_constants_constant(tmp_path: Path) -> None:
    pgm = _make_pgm(tmp_path, 2, 2, fill=10)
    mask = _make_mask(2, 2, [0])
    map_edit.apply_edit(pgm, mask)
    body = _read_body(pgm, 2, 2)
    assert body[0] == MAP_EDIT_FREE_PIXEL_VALUE


# 13 (T1 fold) — greyscale 128 threshold boundary
def test_apply_edit_grey_threshold_boundary(tmp_path: Path) -> None:
    """Pin the threshold = 128 invariant. A mask pixel at exactly 127
    must NOT paint; 128 must paint. 200 + 0 are positive/negative
    controls."""
    from io import BytesIO

    from PIL import Image

    pgm = _make_pgm(tmp_path, 4, 4, fill=100)
    # Row 0 holds the four boundary values; rows 1..3 are zero.
    pixels = bytearray(16)
    pixels[0] = 127  # just below threshold → NOT painted
    pixels[1] = MAP_EDIT_PAINT_THRESHOLD  # exactly 128 → painted
    pixels[2] = 200  # well above → painted
    pixels[3] = 0  # baseline 0 → NOT painted
    img = Image.frombytes("L", (4, 4), bytes(pixels))
    buf = BytesIO()
    img.save(buf, format="PNG")
    result = map_edit.apply_edit(pgm, buf.getvalue())
    body = _read_body(pgm, 4, 4)
    # Cells 1, 2 painted.
    assert body[0] == 100  # untouched
    assert body[1] == MAP_EDIT_FREE_PIXEL_VALUE
    assert body[2] == MAP_EDIT_FREE_PIXEL_VALUE
    assert body[3] == 100  # untouched
    assert result.pixels_changed == 2


# Module-boundary discipline pin
def test_module_does_not_import_maps() -> None:
    """`map_edit.py` MUST NOT import `maps.py` (Track E uncoupled-leaves
    pattern). Mirror of `test_map_backup.py::test_module_does_not_import_maps`.
    """
    src = Path(__file__).resolve().parents[1] / "src" / "godo_webctl" / "map_edit.py"
    text = src.read_text("utf-8")
    assert "from .maps" not in text
    assert "from godo_webctl.maps" not in text
    assert "import godo_webctl.maps" not in text
