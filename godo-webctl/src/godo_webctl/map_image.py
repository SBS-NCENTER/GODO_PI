"""
PGM → PNG renderer for B-MAP.

The tracker writes its occupancy grid as a netpbm `.pgm`. Browsers do not
render PGM natively; webctl converts on demand and caches the PNG bytes
in-process keyed by ``(realpath, target_mtime_ns)``. TTL is
`MAP_IMAGE_CACHE_TTL_S`.

A single cached entry is sufficient: there is exactly one active map per
deployment. The TTL exists only to bound a stale-cache window if the
operator hand-edits the .pgm without bumping mtime (rare; a deliberate
write rebuilds the timestamp).

Track E (PR-C) cache-key migration: the key uses ``os.path.realpath`` on
the symlink target rather than the raw path string. This closes a
cross-symlink bug where an operator activates a different map AND the
new target's mtime happens to match the old (e.g. backup-restore that
preserves mtime): without the realpath swap, the cache hit fires on
``(str(active.pgm), same_mtime)`` and the stale PNG is served. Pinned
by ``test_cache_invalidates_on_symlink_target_change_same_mtime``.
"""

from __future__ import annotations

import io
import os
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
    ``(realpath, target_mtime_ns, cached_at)``; TTL
    ``MAP_IMAGE_CACHE_TTL_S``. The realpath resolution closes the
    symlink-swap-with-same-mtime cache bug (Track E PR-C)."""
    global _entry
    if not map_path.exists():
        raise MapImageNotFound(str(map_path))
    try:
        real = os.path.realpath(map_path)
        st = os.stat(real)
    except FileNotFoundError as e:
        raise MapImageNotFound(str(map_path)) from e

    key = (real, st.st_mtime_ns)
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
        with Image.open(real) as img:
            img.load()
            buf = io.BytesIO()
            img.save(buf, format=_PNG_FORMAT)
            png = buf.getvalue()
    except Exception as e:  # noqa: BLE001 — Pillow raises a wide hierarchy
        raise MapImageInvalid(str(e)) from e

    with _lock:
        _entry = _CacheEntry(
            path=real,
            mtime_ns=st.st_mtime_ns,
            cached_at=_now(),
            png_bytes=png,
        )
    return png


def invalidate_cache() -> None:
    """Drop the singleton cache. Called by `app.py` after a Track E
    activate so the next `/api/map/image` GET re-renders even if the
    swap landed within the realpath/mtime cache-key window."""
    global _entry
    with _lock:
        _entry = None


def _reset_cache_for_tests() -> None:
    """Test-only alias kept for back-compat with existing test imports."""
    invalidate_cache()


def _inspect_cache_for_tests() -> _CacheEntry | None:
    """Test-only hook returning the live cache entry (or None). Used by
    `test_cache_invalidates_on_symlink_target_change_same_mtime` to pin
    the realpath cache-key contract directly (per Mode-A TB2)."""
    with _lock:
        return _entry
