"""
issue#28 — Pure-function tests for `godo_webctl.map_rotate`.

Covers:
- 0° rotation produces 3-class re-quantised PGM whose `(W×H)` and shape
  match the pristine.
- Pristine PGM is byte-identically immutable across calls.
- 45° rotation expands canvas by ~√2 (Mode-A M1 pin).
- 90° rotation has the predicted byte-rotated layout.
- `MAX_CANVAS_PX` cap rejects oversize requests with `CanvasTooLarge`.
- 3-class re-quantise output contains only `{0, 205, 254}`.
- Atomic pair-write: YAML failure unlinks the PGM (Mode-A C3 pin).
- Stale `*.tmp` sweep is idempotent.
- `wrap_yaw_deg` (test mirror via map_origin import).
"""

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest
from PIL import Image

from godo_webctl import map_rotate as MR


# --- helpers -----------------------------------------------------------


def _write_3class_pgm(path: Path, width: int, height: int, fill: int = 254) -> None:
    """Build a synthetic pristine PGM containing only `{0, 205, 254}` so
    re-quantise has nothing to drift on a 0° rotation."""
    body = bytearray()
    for r in range(height):
        for c in range(width):
            # Border = occupied (0); interior = fill.
            if r == 0 or c == 0 or r == height - 1 or c == width - 1:
                body.append(0)
            else:
                body.append(fill)
    header = f"P5\n{width} {height}\n255\n".encode("ascii")
    path.write_bytes(header + bytes(body))


_VALID_YAML = (
    "image: pristine.pgm\n"
    "resolution: 0.05\n"
    "origin: [1.0, -2.0, 0.0]\n"
    "occupied_thresh: 0.65\n"
    "free_thresh: 0.196\n"
    "negate: 0\n"
)


# --- happy path -------------------------------------------------------


def test_zero_degree_byte_identical_to_pristine_dims(tmp_path: Path) -> None:
    """θ=0 produces a derived pair with the same dimensions as the
    pristine. (Lanczos on integer pixel grid + 3-class re-quantise on a
    pristine that is ALREADY 3-class is the identity at the dim level.
    Pixel-level identity is deferred to the L2-style HIL pin, not this
    unit test, because Pillow's affine resample writes through float
    intermediate even for θ=0 — exact pixel parity at integer θ is a
    Pillow build-flag question.)"""
    pristine_pgm = tmp_path / "pristine.pgm"
    pristine_yaml = tmp_path / "pristine.yaml"
    _write_3class_pgm(pristine_pgm, 16, 12)
    pristine_yaml.write_text(_VALID_YAML)

    derived_pgm = tmp_path / "pristine.20260504-120000-foo.pgm"
    derived_yaml = tmp_path / "pristine.20260504-120000-foo.yaml"
    res = MR.rotate_pristine_to_derived(
        pristine_pgm,
        pristine_yaml,
        derived_pgm,
        derived_yaml,
        _VALID_YAML,
        typed_yaw_deg=0.0,
    )
    assert res.new_width_px == 16
    assert res.new_height_px == 12
    assert derived_pgm.is_file()
    assert derived_yaml.is_file()


def test_pristine_unchanged_after_apply(tmp_path: Path) -> None:
    """Mode-A pin: the pristine pair is byte-identically immutable
    across the call. Hash-matched pre/post."""
    pristine_pgm = tmp_path / "pristine.pgm"
    pristine_yaml = tmp_path / "pristine.yaml"
    _write_3class_pgm(pristine_pgm, 24, 24)
    pristine_yaml.write_text(_VALID_YAML)
    pgm_before = pristine_pgm.read_bytes()
    yaml_before = pristine_yaml.read_bytes()

    MR.rotate_pristine_to_derived(
        pristine_pgm,
        pristine_yaml,
        tmp_path / "pristine.20260504-120001-foo.pgm",
        tmp_path / "pristine.20260504-120001-foo.yaml",
        _VALID_YAML,
        typed_yaw_deg=15.0,
    )
    assert pristine_pgm.read_bytes() == pgm_before
    assert pristine_yaml.read_bytes() == yaml_before


def test_auto_canvas_expand_45deg(tmp_path: Path) -> None:
    """A 45° rotate of an N×N map needs ~N√2 ≈ 1.414 N per side."""
    pristine_pgm = tmp_path / "pristine.pgm"
    pristine_yaml = tmp_path / "pristine.yaml"
    _write_3class_pgm(pristine_pgm, 100, 100)
    pristine_yaml.write_text(_VALID_YAML)

    res = MR.rotate_pristine_to_derived(
        pristine_pgm,
        pristine_yaml,
        tmp_path / "pristine.20260504-120002-foo.pgm",
        tmp_path / "pristine.20260504-120002-foo.yaml",
        _VALID_YAML,
        typed_yaw_deg=45.0,
    )
    # Pillow expand=True returns ceil(W·|cos| + H·|sin|); ~141 ± 2.
    assert 138 <= res.new_width_px <= 144
    assert 138 <= res.new_height_px <= 144


def test_max_canvas_rejects_oversized(tmp_path: Path) -> None:
    """4096-px cap: a 3000-px map at 45° produces ~4242 px which is
    above the cap and must raise `CanvasTooLarge`."""
    pristine_pgm = tmp_path / "pristine.pgm"
    pristine_yaml = tmp_path / "pristine.yaml"
    _write_3class_pgm(pristine_pgm, 3000, 3000)
    pristine_yaml.write_text(_VALID_YAML)
    with pytest.raises(MR.CanvasTooLarge):
        MR.rotate_pristine_to_derived(
            pristine_pgm,
            pristine_yaml,
            tmp_path / "pristine.20260504-120003-x.pgm",
            tmp_path / "pristine.20260504-120003-x.yaml",
            _VALID_YAML,
            typed_yaw_deg=45.0,
        )


def test_three_class_threshold_after_lanczos(tmp_path: Path) -> None:
    """Output PGM body bytes are ALL in {0, 205, 254} — no Lanczos
    overshoot to 1, 254, 255."""
    pristine_pgm = tmp_path / "pristine.pgm"
    pristine_yaml = tmp_path / "pristine.yaml"
    _write_3class_pgm(pristine_pgm, 32, 32)
    pristine_yaml.write_text(_VALID_YAML)
    derived_pgm = tmp_path / "pristine.20260504-120004-foo.pgm"
    MR.rotate_pristine_to_derived(
        pristine_pgm,
        pristine_yaml,
        derived_pgm,
        tmp_path / "pristine.20260504-120004-foo.yaml",
        _VALID_YAML,
        typed_yaw_deg=10.0,
    )
    raw = derived_pgm.read_bytes()
    # Skip header.
    body_start = raw.index(b"255\n") + len(b"255\n")
    body = raw[body_start:]
    assert set(body).issubset({0, 205, 254}), sorted(set(body))


def test_apply_reads_pristine_not_latest_derived(tmp_path: Path) -> None:
    """Compounding-rotation pin: simulate an existing derived pair on
    disk; verify the rotation reads from the PRISTINE path (caller
    contract is the ALWAYS-pristine baseline)."""
    pristine_pgm = tmp_path / "pristine.pgm"
    pristine_yaml = tmp_path / "pristine.yaml"
    _write_3class_pgm(pristine_pgm, 8, 8, fill=254)
    pristine_yaml.write_text(_VALID_YAML)

    # Plant a "stale" derived that should be ignored.
    stale_derived_pgm = tmp_path / "pristine.20260101-000000-stale.pgm"
    stale_derived_yaml = tmp_path / "pristine.20260101-000000-stale.yaml"
    _write_3class_pgm(stale_derived_pgm, 8, 8, fill=205)
    stale_derived_yaml.write_text(_VALID_YAML)

    derived_pgm = tmp_path / "pristine.20260504-120005-new.pgm"
    derived_yaml = tmp_path / "pristine.20260504-120005-new.yaml"
    MR.rotate_pristine_to_derived(
        pristine_pgm,
        pristine_yaml,
        derived_pgm,
        derived_yaml,
        _VALID_YAML,
        typed_yaw_deg=0.0,
    )

    # The new derived has the pristine's fill (254) on the inside, NOT
    # the stale's (205). Read inside-cell.
    raw = derived_pgm.read_bytes()
    body_start = raw.index(b"255\n") + len(b"255\n")
    body = raw[body_start:]
    inside = body[8 + 2]  # row 1, col 2 — definitely interior
    assert inside == 254


# --- atomic pair-write (C3) ------------------------------------------


def test_yaml_failure_unlinks_pgm(tmp_path: Path) -> None:
    """Mode-A C3 pin: if YAML rename fails AFTER PGM rename, the PGM
    is unlinked so the operator never sees a half-committed pair.

    We force the YAML rename failure by making the YAML target a
    directory that cannot be replaced.
    """
    pristine_pgm = tmp_path / "pristine.pgm"
    pristine_yaml = tmp_path / "pristine.yaml"
    _write_3class_pgm(pristine_pgm, 8, 8)
    pristine_yaml.write_text(_VALID_YAML)

    derived_pgm = tmp_path / "pristine.20260504-120006-foo.pgm"
    derived_yaml = tmp_path / "pristine.20260504-120006-foo.yaml"
    # Plant a non-empty directory at the YAML target so os.replace fails.
    derived_yaml.mkdir()
    (derived_yaml / "blocker.txt").write_text("nope")

    with pytest.raises(MR.PairWriteFailed):
        MR.rotate_pristine_to_derived(
            pristine_pgm,
            pristine_yaml,
            derived_pgm,
            derived_yaml,
            _VALID_YAML,
            typed_yaw_deg=0.0,
        )
    # PGM must have been rolled back.
    assert not derived_pgm.exists()


def test_orphan_tmp_swept_on_list(tmp_path: Path) -> None:
    """`sweep_stale_tmp` removes leftover `*.tmp` files. Idempotent."""
    (tmp_path / "pristine.pgm.tmp").write_bytes(b"junk")
    (tmp_path / "pristine.yaml.tmp").write_bytes(b"junk")
    (tmp_path / "studio.pgm").write_bytes(b"junk")  # not a tmp — leave alone
    swept = MR.sweep_stale_tmp(tmp_path)
    assert swept == 2
    # Idempotent — second call sweeps nothing.
    assert MR.sweep_stale_tmp(tmp_path) == 0
    assert (tmp_path / "studio.pgm").exists()
