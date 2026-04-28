"""
PGM → PNG renderer for B-MAP.

The tracker writes its occupancy grid as a netpbm `.pgm`. Browsers do not
render PGM natively; webctl converts on demand and caches the PNG bytes
in-process keyed by ``(path, mtime)``. TTL is `MAP_IMAGE_CACHE_TTL_S`.

A single cached entry is sufficient: there is exactly one active map per
deployment. The TTL exists only to bound a stale-cache window if the
operator hand-edits the .pgm without bumping mtime (rare; a deliberate
write rebuilds the timestamp).
"""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image

from .constants import MAP_IMAGE_CACHE_TTL_S


class MapImageError(Exception):
    """Base for module errors."""


class MapImageNotFound(MapImageError):
    """The .pgm path does not exist."""


class MapImageInvalid(MapImageError):
    """Pillow could not decode the file as a PGM."""


@dataclass(frozen=True)
class _CacheEntry:
    path: str
    mtime_ns: int
    cached_at: float
    png_bytes: bytes


_lock = threading.Lock()
_entry: _CacheEntry | None = None

_PNG_FORMAT: Final[str] = "PNG"


def _now() -> float:
    return time.monotonic()


def render_pgm_to_png(map_path: Path) -> bytes:
    """Return PNG bytes for the .pgm at ``map_path``. Cached by
    ``(path, mtime, cached_at)``; TTL ``MAP_IMAGE_CACHE_TTL_S``."""
    global _entry
    try:
        st = map_path.stat()
    except FileNotFoundError as e:
        raise MapImageNotFound(str(map_path)) from e

    key = (str(map_path), st.st_mtime_ns)
    with _lock:
        cached = _entry
        if (
            cached is not None
            and (cached.path, cached.mtime_ns) == key
            and (_now() - cached.cached_at) < MAP_IMAGE_CACHE_TTL_S
        ):
            return cached.png_bytes

    # Render outside the lock — Pillow decode is the dominant cost and we
    # do not want to serialise concurrent readers waiting on the cache.
    try:
        with Image.open(map_path) as img:
            img.load()
            buf = io.BytesIO()
            img.save(buf, format=_PNG_FORMAT)
            png = buf.getvalue()
    except Exception as e:  # noqa: BLE001 — Pillow raises a wide hierarchy
        raise MapImageInvalid(str(e)) from e

    with _lock:
        _entry = _CacheEntry(
            path=str(map_path),
            mtime_ns=st.st_mtime_ns,
            cached_at=_now(),
            png_bytes=png,
        )
    return png


def _reset_cache_for_tests() -> None:
    """Test-only hook to drop the singleton cache."""
    global _entry
    with _lock:
        _entry = None
