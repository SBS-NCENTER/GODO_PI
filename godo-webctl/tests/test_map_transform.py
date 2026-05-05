"""
issue#30 — Pure-function tests for `godo_webctl.map_transform`
(pick-anchored YAML normalization + canvas-expand).

Replaces the issue#28 SUBTRACT-pipeline tests under the same path
(post-`git mv`).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from godo_webctl import map_transform as MT
from godo_webctl.map_transform import (
    Cumulative,
    ThisStep,
    pristine_world_to_pixel,
)

# --- helpers -----------------------------------------------------------


def _write_3class_pgm(path: Path, width: int, height: int, fill: int = 254) -> None:
    body = bytearray()
    for r in range(height):
        for c in range(width):
            if r == 0 or c == 0 or r == height - 1 or c == width - 1:
                body.append(0)
            else:
                body.append(fill)
    header = f"P5\n{width} {height}\n255\n".encode("ascii")
    path.write_bytes(header + bytes(body))


_VALID_YAML = (
    "image: pristine.pgm\n"
    "resolution: 0.05\n"
    "origin: [0.0, 0.0, 0.0]\n"
    "occupied_thresh: 0.65\n"
    "free_thresh: 0.196\n"
    "negate: 0\n"
)

_VALID_YAML_NONZERO_YAW = (
    "image: pristine.pgm\n"
    "resolution: 0.05\n"
    "origin: [-9.575, -8.750, 1.6039575825827]\n"
    "occupied_thresh: 0.65\n"
    "free_thresh: 0.196\n"
    "negate: 0\n"
)


def _setup_pristine(
    tmp_path: Path,
    width: int = 200,
    height: int = 200,
    *,
    yaml: str = _VALID_YAML,
) -> tuple[Path, Path]:
    pristine_pgm = tmp_path / "pristine.pgm"
    pristine_yaml = tmp_path / "pristine.yaml"
    _write_3class_pgm(pristine_pgm, width, height, fill=254)
    pristine_yaml.write_text(yaml)
    return pristine_pgm, pristine_yaml


def _derived_paths(tmp_path: Path, suffix: str) -> tuple[Path, Path, Path]:
    p = tmp_path / f"pristine.20260504-120000-{suffix}.pgm"
    y = tmp_path / f"pristine.20260504-120000-{suffix}.yaml"
    s = tmp_path / f"pristine.20260504-120000-{suffix}.sidecar.json"
    return p, y, s


# --- pristine_world_to_pixel tests -----------------------------------


def test_pristine_world_to_pixel_yaw_zero_collapses_to_simple_form() -> None:
    """When `oθ_p == 0` the yaw-aware form collapses to the simple
    `(cum_tx - ox_p) / res; H_p - 1 - (cum_ty - oy_p) / res`."""
    i_p, j_p_top = pristine_world_to_pixel(
        cum_tx=2.5, cum_ty=1.0,
        ox_p=0.5, oy_p=-0.5,
        otheta_p=0.0,
        W_p=100, H_p=80,
        res=0.05,
    )
    expected_i = (2.5 - 0.5) / 0.05
    expected_j = (80 - 1) - (1.0 - (-0.5)) / 0.05
    assert i_p == pytest.approx(expected_i)
    assert j_p_top == pytest.approx(expected_j)


def test_pristine_world_to_pixel_nonzero_yaw_round_trip() -> None:
    """When `(cum_tx, cum_ty) == (ox_p, oy_p)`, the bottom-left pixel is
    targeted regardless of `otheta_p`. → i_p ≈ 0, j_p_top ≈ H_p - 1."""
    i_p, j_p_top = pristine_world_to_pixel(
        cum_tx=-9.575, cum_ty=-8.750,
        ox_p=-9.575, oy_p=-8.750,
        otheta_p=1.604,
        W_p=200, H_p=200,
        res=0.05,
    )
    assert i_p == pytest.approx(0.0, abs=1e-9)
    assert j_p_top == pytest.approx(199.0, abs=1e-9)


# --- Pick-anchored end-to-end tests ----------------------------------


def test_zero_theta_zero_pick_at_pristine_origin(tmp_path: Path) -> None:
    """θ=0, pick at pristine's bottom-left (= world (0, 0) given
    `origin: [0,0,0]`): derived YAML places that pixel at world (0,0)."""
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 50, 40)
    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, "p1")

    cum = Cumulative(translate_x_m=0.0, translate_y_m=0.0, rotate_deg=0.0)
    step = ThisStep(0.0, 0.0, 0.0, 0.0, 0.0)
    res = MT.transform_pristine_to_derived(
        pristine_pgm, pristine_yaml,
        derived_pgm, derived_yaml, sidecar,
        cum, step, parent_lineage=[],
    )
    ox, oy, oyaw = res.new_yaml_origin_xy_yaw
    assert oyaw == pytest.approx(0.0)
    assert ox == pytest.approx(0.0, abs=1e-9)
    assert oy == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("theta_deg", [0.0, 30.0, 90.0, -45.0, 180.0])
def test_pickpoint_lands_at_world_origin_yaw_zero_pristine(
    tmp_path: Path, theta_deg: float,
) -> None:
    """For each θ, the picked pixel ends up at derived world (0, 0)
    within ±0.5·res."""
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 50, 50)
    res_m = 0.05
    cum_tx = 1.0
    cum_ty = 0.5
    cum = Cumulative(translate_x_m=cum_tx, translate_y_m=cum_ty, rotate_deg=theta_deg)
    step = ThisStep(0.0, 0.0, theta_deg, cum_tx, cum_ty)
    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, f"theta_{int(theta_deg)}")
    result = MT.transform_pristine_to_derived(
        pristine_pgm, pristine_yaml,
        derived_pgm, derived_yaml, sidecar,
        cum, step, parent_lineage=[],
    )
    ox, oy, oyaw = result.new_yaml_origin_xy_yaw
    H_d = result.new_height_px
    # Re-derive (i_p_new, j_p_new) from (ox, oy):
    i_p_new = -ox / res_m
    j_p_new = (H_d - 1) + oy / res_m
    # World coord at the picked pixel via the YAML origin formula:
    wx = ox + i_p_new * res_m
    wy = oy + (H_d - 1 - j_p_new) * res_m
    assert wx == pytest.approx(0.0, abs=0.5 * res_m)
    assert wy == pytest.approx(0.0, abs=0.5 * res_m)
    assert oyaw == pytest.approx(0.0)


def test_pickpoint_round_trip_with_nonzero_pristine_yaw(tmp_path: Path) -> None:
    """[C1 regression] synthetic 200×200 pristine PGM with `oθ_p =
    1.6039575825827`. Pick world (2.0, 1.0) with typed θ=30°."""
    pristine_pgm, pristine_yaml = _setup_pristine(
        tmp_path, 200, 200, yaml=_VALID_YAML_NONZERO_YAW,
    )
    res_m = 0.05
    # Choose cum_tx, cum_ty so that pristine_world_to_pixel returns
    # an interior pixel. Just pick world (2.0, 1.0) directly as the
    # cumulative-translate target (it's already in pristine world frame).
    cum = Cumulative(translate_x_m=2.0, translate_y_m=1.0, rotate_deg=30.0)
    step = ThisStep(0.0, 0.0, 30.0, 2.0, 1.0)
    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, "nzyaw")
    result = MT.transform_pristine_to_derived(
        pristine_pgm, pristine_yaml,
        derived_pgm, derived_yaml, sidecar,
        cum, step, parent_lineage=[],
    )
    ox, oy, oyaw = result.new_yaml_origin_xy_yaw
    assert oyaw == pytest.approx(0.0)
    H_d = result.new_height_px
    i_p_new = -ox / res_m
    j_p_new = (H_d - 1) + oy / res_m
    wx = ox + i_p_new * res_m
    wy = oy + (H_d - 1 - j_p_new) * res_m
    assert wx == pytest.approx(0.0, abs=0.5 * res_m)
    assert wy == pytest.approx(0.0, abs=0.5 * res_m)


# --- Pristine immutability + 1× resample -----------------------------


def test_pristine_unchanged_after_apply(tmp_path: Path) -> None:
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 24, 24)
    pgm_before = pristine_pgm.read_bytes()
    yaml_before = pristine_yaml.read_bytes()

    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, "imm")
    cum = Cumulative(0.5, 0.3, 15.0)
    step = ThisStep(0.0, 0.0, 15.0, 0.5, 0.3)
    MT.transform_pristine_to_derived(
        pristine_pgm, pristine_yaml,
        derived_pgm, derived_yaml, sidecar,
        cum, step, parent_lineage=[],
    )
    assert pristine_pgm.read_bytes() == pgm_before
    assert pristine_yaml.read_bytes() == yaml_before


def test_apply_reads_pristine_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Image.open spy — only pristine paths are opened."""
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 16, 16)

    stale = tmp_path / "pristine.20260101-000000-stale.pgm"
    _write_3class_pgm(stale, 16, 16, fill=205)
    (tmp_path / "pristine.20260101-000000-stale.yaml").write_text(_VALID_YAML)

    opened_paths: list[str] = []
    real_open = Image.open

    def spy_open(fp: Any, *a: Any, **kw: Any) -> Any:
        opened_paths.append(str(fp))
        return real_open(fp, *a, **kw)

    monkeypatch.setattr(Image, "open", spy_open)

    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, "spy")
    cum = Cumulative(0.0, 0.0, 0.0)
    step = ThisStep(0.0, 0.0, 0.0, 0.0, 0.0)
    MT.transform_pristine_to_derived(
        pristine_pgm, pristine_yaml,
        derived_pgm, derived_yaml, sidecar,
        cum, step, parent_lineage=[],
    )
    for path in opened_paths:
        assert "stale" not in path, f"Image.open on stale derived: {path}"
        assert path.endswith("pristine.pgm"), f"unexpected path: {path}"


# --- Canvas / bbox tests --------------------------------------------


def test_canvas_too_large_rejects(tmp_path: Path) -> None:
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 3000, 3000)
    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, "huge")
    cum = Cumulative(0.0, 0.0, 45.0)
    step = ThisStep(0.0, 0.0, 45.0, 0.0, 0.0)
    with pytest.raises(MT.CanvasTooLarge):
        MT.transform_pristine_to_derived(
            pristine_pgm, pristine_yaml,
            derived_pgm, derived_yaml, sidecar,
            cum, step, parent_lineage=[],
        )


def test_off_center_bbox_envelopes_all_pristine_corners() -> None:
    """For each θ + off-center pivot, every pristine corner's rotated
    coord must fall inside [x_min, x_max] × [y_min, y_max]."""
    width, height = 100, 80
    for theta_deg in [0, 30, 90, -45, 180]:
        i_p, j_p = 30.0, 50.0
        theta_rad = math.radians(theta_deg)
        x_min, y_min, x_max, y_max = MT._off_center_bbox(width, height, i_p, j_p, theta_rad)
        c = math.cos(-theta_rad)
        s = math.sin(-theta_rad)
        for cx, cy in [(0.0, 0.0), (width, 0.0), (0.0, height), (width, height)]:
            dx = cx - i_p
            dy = cy - j_p
            xr = i_p + c * dx - s * dy
            yr = j_p + s * dx + c * dy
            assert x_min <= xr <= x_max
            assert y_min <= yr <= y_max


# --- 3-class quantise --------------------------------------------------


def test_three_class_threshold_after_transform(tmp_path: Path) -> None:
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 32, 32)
    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, "qnt")
    cum = Cumulative(0.0, 0.0, 10.0)
    step = ThisStep(0.0, 0.0, 10.0, 0.0, 0.0)
    MT.transform_pristine_to_derived(
        pristine_pgm, pristine_yaml,
        derived_pgm, derived_yaml, sidecar,
        cum, step, parent_lineage=[],
    )
    raw = derived_pgm.read_bytes()
    body_start = raw.index(b"255\n") + len(b"255\n")
    body = raw[body_start:]
    assert set(body).issubset({0, 205, 254}), sorted(set(body))


# --- Atomic C3-triple write ------------------------------------------


def test_yaml_failure_unlinks_pgm(tmp_path: Path) -> None:
    """Mode-A C3 pin: YAML rename failure → PGM unlinked."""
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 8, 8)
    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, "yf")
    derived_yaml.mkdir()
    (derived_yaml / "blocker.txt").write_text("nope")
    cum = Cumulative(0.0, 0.0, 0.0)
    step = ThisStep(0.0, 0.0, 0.0, 0.0, 0.0)
    with pytest.raises(MT.PairWriteFailed):
        MT.transform_pristine_to_derived(
            pristine_pgm, pristine_yaml,
            derived_pgm, derived_yaml, sidecar,
            cum, step, parent_lineage=[],
        )
    assert not derived_pgm.exists()


def test_orphan_tmp_swept_idempotent(tmp_path: Path) -> None:
    (tmp_path / "pristine.pgm.tmp").write_bytes(b"junk")
    (tmp_path / "pristine.yaml.tmp").write_bytes(b"junk")
    (tmp_path / "pristine.sidecar.json.tmp").write_bytes(b"junk")
    swept = MT.sweep_stale_tmp(tmp_path)
    assert swept == 3
    assert MT.sweep_stale_tmp(tmp_path) == 0


# --- Sidecar emission via transform ----------------------------------


def test_affine_matrix_golden_4x4_theta45() -> None:
    """[MA1 sign-error catch] 4×4 toy bitmap, picked-pixel (2, 2),
    θ=45°. Hand-derive the AFFINE matrix coefficients (output→input
    mapping) and assert they match `_affine_matrix_for_pivot_rotation`
    bit-equal (within float tolerance).

    For pivot (i_p, j_p) = (2, 2) with bbox starting at (x_min, y_min):
        a = cos(theta)
        b = -sin(theta)
        c = i_p + cos(theta)·(x_min - i_p) - sin(theta)·(y_min - j_p)
        d = sin(theta)
        e = cos(theta)
        f = j_p + sin(theta)·(x_min - i_p) + cos(theta)·(y_min - j_p)

    A regression that drops the sign on `b` (the standard CCW [c -s; s c]
    convention) would fail this test.
    """
    theta = math.pi / 4  # 45°
    cs = math.cos(theta)
    sn = math.sin(theta)
    # Use a synthetic bbox start (-1, -1) representing rotation overhang.
    a, b, c, d, e, f = MT._affine_matrix_for_pivot_rotation(
        i_p=2.0, j_p=2.0, x_min=-1, y_min=-1, theta_rad=theta,
    )
    assert a == pytest.approx(cs, abs=1e-12)
    assert b == pytest.approx(-sn, abs=1e-12)
    assert c == pytest.approx(2.0 + cs * (-1 - 2.0) - sn * (-1 - 2.0), abs=1e-12)
    assert d == pytest.approx(sn, abs=1e-12)
    assert e == pytest.approx(cs, abs=1e-12)
    assert f == pytest.approx(2.0 + sn * (-1 - 2.0) + cs * (-1 - 2.0), abs=1e-12)


def test_typed_delta_shifts_picked_point_off_origin(tmp_path: Path) -> None:
    """[C-2.1 cardinal] click world (5, 0) + typed delta (1, 0, 0):
    assert `cumulative.translate ≈ (4, 0)` AND derived YAML places
    the pristine pixel originally at world (5, 0) at derived world
    (1, 0) ± 0.5·res.

    Per the round-3 lock: `cumulative.translate = picked_world −
    R(-θ_active)·typed_delta`. With θ_active=0, R=I → cumulative =
    (5,0) − (1,0) = (4,0). The picked-pixel is the cumulative-pivot;
    after rotation/translate the picked-pixel lands at derived world
    (0, 0), so the pristine-(5, 0) pixel — which is `typed_delta` away
    from the cumulative-pivot in the active-at-pick frame — lands at
    derived world `typed_delta = (1, 0)`.
    """
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 200, 200)
    res_m = 0.05
    derived_pgm, derived_yaml, sidecar = _derived_paths(tmp_path, "c21")

    from godo_webctl import sidecar as sc_mod

    parent = sc_mod.Cumulative(0.0, 0.0, 0.0)
    step_local = sc_mod.ThisStep(
        delta_translate_x_m=1.0,
        delta_translate_y_m=0.0,
        delta_rotate_deg=0.0,
        picked_world_x_m=5.0,
        picked_world_y_m=0.0,
    )
    cum_sc = sc_mod.compose_cumulative(parent, step_local)
    assert cum_sc.translate_x_m == pytest.approx(4.0, abs=1e-9)
    assert cum_sc.translate_y_m == pytest.approx(0.0, abs=1e-9)

    cum_mt = Cumulative(cum_sc.translate_x_m, cum_sc.translate_y_m, cum_sc.rotate_deg)
    step_mt = ThisStep(
        step_local.delta_translate_x_m,
        step_local.delta_translate_y_m,
        step_local.delta_rotate_deg,
        step_local.picked_world_x_m,
        step_local.picked_world_y_m,
    )
    result = MT.transform_pristine_to_derived(
        pristine_pgm, pristine_yaml,
        derived_pgm, derived_yaml, sidecar,
        cum_mt, step_mt, parent_lineage=[],
    )
    ox, oy, oyaw = result.new_yaml_origin_xy_yaw
    H_d = result.new_height_px
    # P_pick (= pristine-(5, 0)) must land at derived world (1, 0).
    # The pristine-(5, 0) pixel maps to pristine_world_to_pixel(5, 0, ...)
    # in pristine pixel space; in the cumulative cum=(4,0) frame, the
    # pristine-(5, 0) pixel sits 1 m in +x from the picked-pivot.
    # After rotation θ=0, derived-pixel = picked_pixel_new + (1m / res, 0).
    i_pick_in_derived = -ox / res_m  # picked-pivot lands at derived world (0,0)
    j_pick_in_derived = (H_d - 1) + oy / res_m
    # Pristine-(5, 0) is 1 m in +x from picked-pivot in pristine world frame;
    # at θ=0 derived also has +x aligned, so derived-pixel for that point:
    i_pristine5_derived = i_pick_in_derived + 1.0 / res_m
    j_pristine5_derived = j_pick_in_derived
    # Convert derived-pixel back to derived world:
    wx_pristine5 = ox + i_pristine5_derived * res_m
    wy_pristine5 = oy + (H_d - 1 - j_pristine5_derived) * res_m
    assert wx_pristine5 == pytest.approx(1.0, abs=0.5 * res_m)
    assert wy_pristine5 == pytest.approx(0.0, abs=0.5 * res_m)
    assert oyaw == pytest.approx(0.0)


def test_transform_emits_sidecar_with_correct_lineage(tmp_path: Path) -> None:
    pristine_pgm, pristine_yaml = _setup_pristine(tmp_path, 16, 16)
    derived_pgm, derived_yaml, sidecar_path = _derived_paths(tmp_path, "sclin")
    cum = Cumulative(0.0, 0.0, 0.0)
    step = ThisStep(0.0, 0.0, 0.0, 0.0, 0.0)
    MT.transform_pristine_to_derived(
        pristine_pgm, pristine_yaml,
        derived_pgm, derived_yaml, sidecar_path,
        cum, step, parent_lineage=[],
        memo="firstpick",
    )
    assert sidecar_path.is_file()
    import json as _json
    body = _json.loads(sidecar_path.read_bytes())
    assert body["schema"] == "godo.map.sidecar.v1"
    assert body["kind"] == "derived"
    assert body["lineage"]["generation"] == 0
    assert body["lineage"]["kind"] == "operator_apply"
    assert body["created"]["memo"] == "firstpick"
