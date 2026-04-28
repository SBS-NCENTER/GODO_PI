"""PGM → PNG renderer + cache."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from godo_webctl import map_image as M


def _write_pgm(p: Path, w: int, h: int, fill: int = 128) -> None:
    """Write a tiny binary PGM (P5)."""
    header = f"P5\n{w} {h}\n255\n".encode("ascii")
    body = bytes([fill] * (w * h))
    p.write_bytes(header + body)


def test_pgm_to_png_round_trip(tmp_path: Path) -> None:
    M._reset_cache_for_tests()
    pgm = tmp_path / "m.pgm"
    _write_pgm(pgm, 4, 4, fill=200)
    png = M.render_pgm_to_png(pgm)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_cache_hit_returns_same_bytes_object(tmp_path: Path) -> None:
    M._reset_cache_for_tests()
    pgm = tmp_path / "m.pgm"
    _write_pgm(pgm, 4, 4)
    a = M.render_pgm_to_png(pgm)
    b = M.render_pgm_to_png(pgm)
    # Same `bytes` object identity — cache hit, no re-render.
    assert a is b


def test_mtime_change_invalidates_cache(tmp_path: Path) -> None:
    M._reset_cache_for_tests()
    pgm = tmp_path / "m.pgm"
    _write_pgm(pgm, 4, 4, fill=10)
    a = M.render_pgm_to_png(pgm)
    # Mutate + bump mtime explicitly so the test does not race the
    # filesystem timestamp granularity.
    time.sleep(0.01)
    _write_pgm(pgm, 4, 4, fill=240)
    new_mtime = pgm.stat().st_mtime + 1
    os.utime(pgm, (new_mtime, new_mtime))
    b = M.render_pgm_to_png(pgm)
    assert a is not b


def test_missing_file_raises_not_found(tmp_path: Path) -> None:
    M._reset_cache_for_tests()
    with pytest.raises(M.MapImageNotFound):
        M.render_pgm_to_png(tmp_path / "does-not-exist.pgm")


def test_invalid_pgm_raises_invalid(tmp_path: Path) -> None:
    M._reset_cache_for_tests()
    bad = tmp_path / "bad.pgm"
    bad.write_bytes(b"this is not a netpbm file at all")
    with pytest.raises(M.MapImageInvalid):
        M.render_pgm_to_png(bad)
