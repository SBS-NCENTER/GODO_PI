"""
Track B-MAPEDIT — pure-function PGM brush-erase transform.

`apply_edit(active_pgm, mask_png_bytes)` decodes a single-channel mask PNG
(or RGBA — alpha > 0 means paint), validates dimensions match the active
PGM, rewrites every painted cell to `MAP_EDIT_FREE_PIXEL_VALUE` (canonical
"free" = 254), and atomically replaces the on-disk PGM.

Module discipline (pinned by invariant, see CODEBASE.md):

- Sole owner of the mask→PGM transform. Does NOT import `maps.py`; the
  caller (app.py) resolves the active realpath via `maps.read_active_name`
  + `maps.pgm_for` and passes the `Path` in.
- Writes ONLY to the active PGM realpath. Never touches the active.pgm
  symlink, the YAML sibling, or any backup directory.
- Atomic-write pattern mirrors `auth.py::_write_atomic` (tmp file in same
  dir + `os.replace` + on-failure tmp cleanup, mode 0644). PGM is a
  publicly readable artifact (operators read via /api/map/image), so the
  mode is 0644 not 0600.

The decode uses `Pillow` (transitive dep through FastAPI/Starlette) — no
hand-rolled PNG parser. Decode failure raises `MaskDecodeFailed`; the
caller maps it to HTTP 400.

Pixel semantics (R8 mitigation):

- Greyscale (mode "L"): pixel value `>= 128` means paint.
- RGBA / LA (with alpha): alpha `> 0` means paint.
- Anything else is converted to "L" first via `Image.convert("L")`.

Threshold value 128 lives in `constants.py::MAP_EDIT_PAINT_THRESHOLD` so
a future writer cannot drift it without a visible diff.
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .constants import (
    MAP_EDIT_FREE_PIXEL_VALUE,
    MAP_EDIT_MASK_PNG_MAX_BYTES,
    MAP_EDIT_PAINT_THRESHOLD,
    PGM_HEADER_MAX_BYTES,
)

logger = logging.getLogger("godo_webctl.map_edit")

# Atomic-write file mode. PGM is operator-readable via /api/map/image, so
# 0644 (mirror of `map_backup.py`'s copied artifacts), NOT 0600 like
# `auth.py::_write_atomic`'s credential file.
_PGM_FILE_MODE = 0o644
_TMP_SUFFIX = ".tmp"


class MapEditError(Exception):
    """Base for map_edit-module exceptions."""


class ActiveMapMissing(MapEditError):
    """Active PGM file does not exist or is unreadable."""


class MaskDecodeFailed(MapEditError):
    """Mask bytes are not a parseable PNG."""


class MaskShapeMismatch(MapEditError):
    """Mask dimensions do not match the PGM dimensions."""


class MaskTooLarge(MapEditError):
    """Mask bytes exceed `MAP_EDIT_MASK_PNG_MAX_BYTES`."""


class EditFailed(MapEditError):
    """Underlying I/O failure during the atomic-write phase."""


@dataclass(frozen=True)
class EditResult:
    """Returned by `apply_edit` on success."""

    pixels_changed: int


# --- header parsing ----------------------------------------------------


def _parse_pgm_header(head: bytes) -> tuple[int, int, int, int]:
    """Return ``(width, height, maxval, header_byte_len)``.

    Mirror of `maps.read_pgm_dimensions` in shape, but extends to the
    `maxval` token AND returns where the binary pixel block starts. We
    cannot reuse `read_pgm_dimensions` because its public contract is
    `(width, height)` only — adding a third return value would change
    the wire of the maps module.
    """
    if not head.startswith(b"P5"):
        raise EditFailed("missing_p5_magic")
    rest = head[2:]
    tokens: list[bytes] = []
    token_end_offsets: list[int] = []
    i = 0
    while i < len(rest) and len(tokens) < 3:
        ch = rest[i : i + 1]
        if ch in (b" ", b"\t", b"\n", b"\r"):
            i += 1
            continue
        if ch == b"#":
            while i < len(rest) and rest[i : i + 1] not in (b"\n", b"\r"):
                i += 1
            continue
        start = i
        while i < len(rest) and rest[i : i + 1] not in (b" ", b"\t", b"\n", b"\r", b"#"):
            i += 1
        tokens.append(rest[start:i])
        token_end_offsets.append(i)
    if len(tokens) < 3:
        raise EditFailed("missing_header_tokens")
    try:
        width = int(tokens[0])
        height = int(tokens[1])
        maxval = int(tokens[2])
    except ValueError as e:
        raise EditFailed(f"non_numeric_header: {e}") from e
    if width <= 0 or height <= 0 or not (0 < maxval <= 255):
        raise EditFailed(f"invalid_header_values: {width}x{height} max={maxval}")
    # The header ends at the first whitespace byte AFTER the maxval token
    # (a single newline by netpbm convention; spec also tolerates a single
    # space, which we accept here).
    after_maxval = token_end_offsets[2]
    if after_maxval >= len(rest):
        raise EditFailed("missing_header_terminator")
    terminator = rest[after_maxval : after_maxval + 1]
    if terminator not in (b" ", b"\t", b"\n", b"\r"):
        raise EditFailed("missing_header_terminator")
    header_byte_len = 2 + after_maxval + 1  # 2 = len("P5")
    return width, height, maxval, header_byte_len


# --- mask decode -------------------------------------------------------


def _decode_mask_to_paint_array(
    mask_bytes: bytes,
    *,
    expected_width: int,
    expected_height: int,
) -> list[bool]:
    """Return a row-major flat list of `bool` whose `True` entries are
    cells the operator marked for paint.

    A list-of-bool keeps this module dependency-light (no `numpy` import).
    The 200×200 case is 40 000 bools which is ~40 KB of Python heap —
    negligible at the operating cadence of map_edit (one call per
    operator click).
    """
    try:
        img = Image.open(_BytesReader(mask_bytes))
        # Force decode now so format bugs raise here, not lazily later.
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise MaskDecodeFailed(f"png_decode_failed: {e}") from e

    if img.width != expected_width or img.height != expected_height:
        raise MaskShapeMismatch(
            f"mask {img.width}x{img.height} != pgm {expected_width}x{expected_height}",
        )

    has_alpha = img.mode in ("RGBA", "LA") or "A" in img.getbands()
    if has_alpha:
        # Alpha-as-paint (R8 case 2). Use the alpha channel directly.
        alpha = img.getchannel("A")
        a_bytes = alpha.tobytes()
        # `> 0` per the docstring: any non-zero alpha is "paint".
        return [b > 0 for b in a_bytes]
    # Greyscale-as-paint (R8 case 1). Convert anything else to "L" so the
    # threshold compare is well-defined.
    if img.mode != "L":
        img = img.convert("L")
    l_bytes = img.tobytes()
    return [b >= MAP_EDIT_PAINT_THRESHOLD for b in l_bytes]


class _BytesReader:
    """Minimal file-like wrapper Pillow accepts. Avoids `io.BytesIO`'s
    full feature surface so we never accidentally write back through
    the reader."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def seek(self, pos: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = pos
        elif whence == 1:
            self._pos += pos
        elif whence == 2:
            self._pos = len(self._data) + pos
        else:  # pragma: no cover — defensive
            raise ValueError(f"invalid whence: {whence}")
        return self._pos

    def tell(self) -> int:
        return self._pos


# --- public API --------------------------------------------------------


def apply_edit(active_pgm: Path, mask_png_bytes: bytes) -> EditResult:
    """Paint the active PGM through the mask. Returns ``EditResult``.

    Raises:
        ActiveMapMissing — `active_pgm` is missing or not a regular file.
        MaskTooLarge — mask exceeds `MAP_EDIT_MASK_PNG_MAX_BYTES`.
        MaskDecodeFailed — mask is not a valid PNG.
        MaskShapeMismatch — mask dimensions != PGM dimensions.
        EditFailed — atomic-write or header-parse failure.
    """
    if len(mask_png_bytes) > MAP_EDIT_MASK_PNG_MAX_BYTES:
        # Defence-in-depth: app.py also checks content-length BEFORE
        # buffering into memory. This path catches the
        # multipart-decoded-but-large case.
        raise MaskTooLarge(
            f"mask {len(mask_png_bytes)} bytes > {MAP_EDIT_MASK_PNG_MAX_BYTES}",
        )

    if not active_pgm.is_file():
        raise ActiveMapMissing(str(active_pgm))

    try:
        pgm_bytes = active_pgm.read_bytes()
    except OSError as e:
        raise ActiveMapMissing(str(e)) from e

    width, height, _maxval, header_len = _parse_pgm_header(pgm_bytes[:PGM_HEADER_MAX_BYTES])
    expected_pixel_bytes = width * height
    if len(pgm_bytes) - header_len < expected_pixel_bytes:
        raise EditFailed(
            f"truncated_pgm: header={header_len} body={len(pgm_bytes) - header_len} "
            f"expected={expected_pixel_bytes}",
        )

    paint = _decode_mask_to_paint_array(
        mask_png_bytes,
        expected_width=width,
        expected_height=height,
    )

    # Apply the mask. `bytearray` + slice rebuild is cheaper than a
    # per-cell loop for typical 200×200 maps; the slice copy walks all
    # 40 000 bytes once, the in-place loop walks the painted subset.
    body = bytearray(pgm_bytes[header_len : header_len + expected_pixel_bytes])
    pixels_changed = 0
    free = MAP_EDIT_FREE_PIXEL_VALUE
    for i, want_paint in enumerate(paint):
        if want_paint and body[i] != free:
            body[i] = free
            pixels_changed += 1

    tail = pgm_bytes[header_len + expected_pixel_bytes :]
    new_bytes = pgm_bytes[:header_len] + bytes(body) + tail

    _atomic_write(active_pgm, new_bytes)
    return EditResult(pixels_changed=pixels_changed)


def _atomic_write(target: Path, data: bytes) -> None:
    """Tmp file in same dir + ``os.replace`` + on-failure cleanup.

    Mirrors `auth.py::_write_atomic` (lines 267-295) but at mode
    `_PGM_FILE_MODE = 0o644` because the PGM is operator-readable.
    Pinned by `tests/test_map_edit.py::test_apply_edit_atomic_write`
    asserting no `*.tmp` survives a failed `os.replace`.
    """
    tmp = target.with_suffix(target.suffix + _TMP_SUFFIX)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PGM_FILE_MODE)
    try:
        try:
            with os.fdopen(fd, "wb", closefd=True) as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        try:
            os.replace(tmp, target)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except BaseException:
        # KeyboardInterrupt and friends must also leave no .tmp behind.
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
