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


# --- Track E (PR-C) — cache-key migration to realpath -------------------


def test_cache_invalidates_on_symlink_target_change_same_mtime(
    tmp_path: Path,
) -> None:
    """Mode-A TB2: pin the realpath cache-key contract directly.

    The pre-PR-C cache key was ``(str(map_path), st.st_mtime_ns)`` —
    when a symlink swap pointed at a NEW target whose mtime happened to
    equal the old target's, the cache hit fired and stale bytes were
    served. The fix is to key on ``os.path.realpath(map_path)``.

    This test forces equal mtimes via ``os.utime`` so byte-comparing
    PNGs would not be enough on its own (a future Pillow optimisation
    could produce identical output for both 1×1 PGMs and silently pass
    the test); we instead pin ``_entry.path == realpath(target)``.
    """
    M._reset_cache_for_tests()
    pgm_a = tmp_path / "studio_v1.pgm"
    pgm_b = tmp_path / "studio_v2.pgm"
    _write_pgm(pgm_a, 4, 4, fill=0)
    _write_pgm(pgm_b, 4, 4, fill=255)
    forced_mtime = 12345.6789
    os.utime(pgm_a, (forced_mtime, forced_mtime))
    os.utime(pgm_b, (forced_mtime, forced_mtime))

    active = tmp_path / "active.pgm"
    active.symlink_to(pgm_a.name)

    png_a = M.render_pgm_to_png(active)
    entry_a = M._inspect_cache_for_tests()
    assert entry_a is not None
    assert entry_a.path == os.path.realpath(pgm_a)

    # Swap symlink to pgm_b (M2 pattern: secrets-named tmp + replace).
    tmp_link = tmp_path / ".swap.pgm.tmp"
    os.symlink(pgm_b.name, tmp_link)
    os.replace(tmp_link, active)

    png_b = M.render_pgm_to_png(active)
    entry_b = M._inspect_cache_for_tests()
    assert entry_b is not None
    assert entry_b.path == os.path.realpath(pgm_b)
    assert entry_a.path != entry_b.path
    # Sanity belt: the PNG bytes also differ (will fail if Pillow ever
    # normalises the two 1×1 grayscales to identical output, in which
    # case the realpath assert above is the contract that still holds).
    assert png_a != png_b


def test_cache_invalidates_on_symlink_target_path_change(tmp_path: Path) -> None:
    """Sanity case: different mtimes (the easy half). Without the
    realpath migration this passed pre-PR-C; we keep it to catch a
    regression that regresses past both halves of the bug."""
    M._reset_cache_for_tests()
    pgm_a = tmp_path / "studio_v1.pgm"
    pgm_b = tmp_path / "studio_v2.pgm"
    _write_pgm(pgm_a, 4, 4, fill=10)
    time.sleep(0.01)
    _write_pgm(pgm_b, 4, 4, fill=240)

    active = tmp_path / "active.pgm"
    active.symlink_to(pgm_a.name)
    a = M.render_pgm_to_png(active)

    tmp_link = tmp_path / ".swap.pgm.tmp"
    os.symlink(pgm_b.name, tmp_link)
    os.replace(tmp_link, active)
    b = M.render_pgm_to_png(active)
    assert a != b
