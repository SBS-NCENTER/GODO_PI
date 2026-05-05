"""
Track B-MAPEDIT-2 — `map_origin.apply_origin_edit` unit tests.

Sign convention is SUBTRACT (issue#27, operator-locked 2026-05-04 KST,
supersedes the 2026-04-30 ADD spec). PICK#2 / PICK#3 regression pins
encode the operator-supplied HIL data points.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from godo_webctl import map_origin
from godo_webctl.constants import ORIGIN_X_Y_ABS_MAX_M


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _write_yaml_bytes(path: Path, body: bytes) -> None:
    path.write_bytes(body)


# 1. absolute happy path — SUBTRACT sign convention pin (issue#27,
# operator-locked 2026-05-04 KST). Supersedes the 2026-04-30 ADD lock.
def test_apply_origin_edit_absolute_subtracts_typed(tmp_path: Path) -> None:
    """SUBTRACT semantic: typed (x_m, y_m) names the world coord that
    should become the new origin. So:
        new_yaml_origin = old_yaml_origin - typed
    """
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(
        yaml,
        "image: studio_v1.pgm\nresolution: 0.05\norigin: [-1.5, -2.0, 0.0]\n"
        "occupied_thresh: 0.65\n",
    )
    result = map_origin.apply_origin_edit(yaml, 0.32, -0.18, "absolute")
    assert result.prev_origin == (-1.5, -2.0, 0.0)
    # SUBTRACT: new_origin = old - typed = (-1.5 - 0.32, -2.0 - (-0.18))
    assert result.new_origin[0] == pytest.approx(-1.82)
    assert result.new_origin[1] == pytest.approx(-1.82)
    assert result.new_origin[2] == 0.0
    text = yaml.read_text("utf-8")
    assert "origin: [-1.82, -1.82, 0.0]" in text
    # Other lines unchanged.
    assert "image: studio_v1.pgm" in text
    assert "resolution: 0.05" in text
    assert "occupied_thresh: 0.65" in text


# 2. PICK#2 regression pin — operator HIL data point 2026-05-03 KST.
def test_apply_origin_edit_absolute_subtracts_pose_pick_2(tmp_path: Path) -> None:
    """PICK#2 historical data — operator HIL 2026-05-03 KST.

    Pre-state: old_origin=(2.01, 8.56), old_pose=(12.87, 15.49).
    Operator types absolute (7.86, 18.34).

    Backend produces:
      new_yaml_origin = old_yaml_origin - typed = (2.01 - 7.86, 8.56 - 18.34)
                     = (-5.85, -9.78)
    Resulting pose (computed by tracker after restart):
      new_pose = old_pose - typed = (12.87 - 7.86, 15.49 - 18.34)
              = (5.01, -2.85)
    """
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [2.01, 8.56, 0.0]\n")
    result = map_origin.apply_origin_edit(yaml, 7.86, 18.34, "absolute")
    # 5 mm tolerance accounts for AMCL noise (converge_xy_std_m default 0.015).
    expected_origin = (-5.85, -9.78)
    assert result.new_origin[0] == pytest.approx(expected_origin[0], abs=0.005)
    assert result.new_origin[1] == pytest.approx(expected_origin[1], abs=0.005)


# 3. PICK#3 regression pin — operator HIL data point 2026-05-03 KST.
def test_apply_origin_edit_absolute_subtracts_pose_pick_3(tmp_path: Path) -> None:
    """PICK#3 historical data — operator HIL 2026-05-03 KST.

    Pre-state: old_origin=(7.86, 18.34), old_pose=(18.72, 25.27).
    Operator types absolute (10.32, 28.86).

    Backend produces:
      new_yaml_origin = (7.86 - 10.32, 18.34 - 28.86) = (-2.46, -10.52)
    Resulting pose:
      new_pose = (18.72 - 10.32, 25.27 - 28.86) = (8.40, -3.59)
    """
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [7.86, 18.34, 0.0]\n")
    result = map_origin.apply_origin_edit(yaml, 10.32, 28.86, "absolute")
    expected_origin = (-2.46, -10.52)
    assert result.new_origin[0] == pytest.approx(expected_origin[0], abs=0.005)
    assert result.new_origin[1] == pytest.approx(expected_origin[1], abs=0.005)


# 3 (T2 fold) — theta passthrough byte-for-byte over a parametrized set of
# tricky theta tokens (raw Pi/2, scientific, signed zero, high-precision).
@pytest.mark.parametrize(
    "theta_str",
    [
        "0.0",
        "1.5707963267948966",
        "1.5e-3",
        "-0.0",
        "0.7853981633974483",
    ],
)
def test_apply_origin_edit_preserves_theta_byte_for_byte(tmp_path: Path, theta_str: str) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    body = f"image: x.pgm\norigin: [-1.5, -2.0, {theta_str}]\nfree_thresh: 0.196\n"
    _write_yaml(yaml, body)
    map_origin.apply_origin_edit(yaml, 0.32, -0.18, "absolute")
    new_text = yaml.read_text("utf-8")
    assert f", {theta_str}]" in new_text, f"theta drift: {new_text!r}"


# 4. all non-origin lines preserved byte-for-byte (diff is exactly 1 line)
def test_apply_origin_edit_preserves_other_yaml_keys_byte_for_byte(tmp_path: Path) -> None:
    """Use a non-zero typed value so the SUBTRACT-rewritten origin line
    actually differs from the original."""
    yaml = tmp_path / "studio_v1.yaml"
    original = (
        "# This is a comment line\n"
        "image: studio_v1.pgm\n"
        "resolution: 0.05\n"
        "origin: [-1.5, -2.0, 0.0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n"
        "mode: trinary\n"
        "\n"  # trailing blank
    )
    _write_yaml(yaml, original)
    map_origin.apply_origin_edit(yaml, 0.5, 0.5, "absolute")
    new_lines = yaml.read_text("utf-8").splitlines(keepends=True)
    old_lines = original.splitlines(keepends=True)
    diffs = [(i, o, n) for i, (o, n) in enumerate(zip(old_lines, new_lines, strict=True)) if o != n]
    assert len(diffs) == 1, f"expected exactly 1 differing line, got {diffs}"
    assert "origin:" in diffs[0][1]


# 5. inline comment after the bracket is preserved
def test_apply_origin_edit_origin_with_inline_comment(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [-1.5, -2.0, 0.0]  # studio_center\n")
    map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")
    text = yaml.read_text("utf-8")
    assert "# studio_center" in text


# 6. no origin: line → OriginYamlParseFailed
def test_apply_origin_edit_yaml_with_no_origin_line_raises(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "image: foo.pgm\nresolution: 0.05\n")
    with pytest.raises(map_origin.OriginYamlParseFailed):
        map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")


# 7. duplicate origin: lines → OriginYamlParseFailed("multiple_origin_lines")
def test_apply_origin_edit_yaml_with_two_origin_lines_raises(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [-1.5, -2.0, 0.0]\norigin: [0, 0, 0]\n")
    with pytest.raises(map_origin.OriginYamlParseFailed) as exc_info:
        map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")
    assert "multiple_origin_lines" in str(exc_info.value)


# 8. block-scalar form → OriginYamlParseFailed("flow_style_required")
def test_apply_origin_edit_block_scalar_origin_raises(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin:\n  - -1.5\n  - -2.0\n  - 0.0\n")
    with pytest.raises(map_origin.OriginYamlParseFailed) as exc_info:
        map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")
    assert "flow_style_required" in str(exc_info.value)


# 9. active YAML missing → ActiveYamlMissing
def test_apply_origin_edit_active_yaml_missing_raises(tmp_path: Path) -> None:
    ghost = tmp_path / "no_such.yaml"
    with pytest.raises(map_origin.ActiveYamlMissing):
        map_origin.apply_origin_edit(ghost, 0.0, 0.0, "absolute")


# 10 (S2 fold) — atomic write: os.replace failure leaves YAML untouched
# AND no .tmp leftover
def test_apply_origin_edit_atomic_write(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [-1.5, -2.0, 0.0]\n")
    original_bytes = yaml.read_bytes()

    real_replace = os.replace

    def boom(src: object, dst: object) -> None:
        del src, dst
        raise OSError("simulated_replace_failure")

    with (
        mock.patch.object(os, "replace", side_effect=boom),
        pytest.raises(OSError, match="simulated_replace_failure"),
    ):
        map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")

    # Original bytes preserved.
    assert yaml.read_bytes() == original_bytes
    # S2 fold: no leftover *.tmp after failure.
    assert not list(tmp_path.glob("*.tmp"))
    # Sanity: real os.replace still works post-test.
    assert real_replace is os.replace


# 11. bad mode → BadOriginValue (defence-in-depth; Pydantic should catch first)
def test_apply_origin_edit_bad_mode_raises(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [-1.5, -2.0, 0.0]\n")
    with pytest.raises(map_origin.BadOriginValue) as exc_info:
        map_origin.apply_origin_edit(yaml, 0.0, 0.0, "lol")  # type: ignore[arg-type]
    assert "bad_mode" in str(exc_info.value)


# 12. module-discipline pin: map_origin.py does NOT import maps.py
def test_module_does_not_import_maps() -> None:
    """`map_origin.py` MUST NOT import `maps.py` (Track E uncoupled-leaves
    pattern). Mirror of `test_map_edit.py::test_module_does_not_import_maps`.
    """
    src = Path(__file__).resolve().parents[1] / "src" / "godo_webctl" / "map_origin.py"
    text = src.read_text("utf-8")
    assert "from .maps" not in text
    assert "from godo_webctl.maps" not in text
    assert "import godo_webctl.maps" not in text


# 13. round-trip precision — high-precision input survives `repr()` format.
def test_apply_origin_edit_round_trip_precision(tmp_path: Path) -> None:
    """SUBTRACT semantic: new = old - typed. Pre-state old=(0, 0); typed
    high-precision values land on disk as their negatives."""
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [0.0, 0.0, 0.0]\n")
    high_precision_x = 1.234567890123
    high_precision_y = -2.345678901234
    map_origin.apply_origin_edit(yaml, high_precision_x, high_precision_y, "absolute")
    # Re-parse on-disk bytes.
    import re as _re

    text = yaml.read_text("utf-8")
    m = _re.search(r"origin: \[([^,]+), ([^,]+),", text)
    assert m is not None, f"no origin line: {text!r}"
    parsed_x = float(m.group(1))
    parsed_y = float(m.group(2))
    # SUBTRACT: new = 0 - typed = -typed. Round-trip via repr() must
    # preserve full mantissa.
    assert abs(parsed_x - (-high_precision_x)) < 1e-10
    assert abs(parsed_y - (-high_precision_y)) < 1e-10


# 14 (T3 fold) — origin line whitespace variants
@pytest.mark.parametrize(
    "origin_line",
    [
        "origin: [-1.5,-2.0,0.0]",  # no spaces
        "origin: [ -1.5 , -2.0 , 0.0 ]",  # extra spaces
        "origin:[-1.5, -2.0, 0.0]",  # no space after colon
        "origin:  [-1.5, -2.0, 0.0]",  # double space after colon
    ],
)
def test_apply_origin_edit_origin_line_whitespace_variants(
    tmp_path: Path, origin_line: str
) -> None:
    """SUBTRACT semantic: typed (0, 0) leaves the origin unchanged
    (`new = old - 0 = old`)."""
    yaml = tmp_path / "studio_v1.yaml"
    body = f"image: foo.pgm\nresolution: 0.05\n{origin_line}\nfree_thresh: 0.196\n"
    _write_yaml(yaml, body)
    result = map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")
    assert result.prev_origin == (-1.5, -2.0, 0.0)
    assert result.new_origin == (-1.5, -2.0, 0.0)
    new_text = yaml.read_text("utf-8")
    assert "image: foo.pgm" in new_text
    assert "free_thresh: 0.196" in new_text


# 15. CRLF line endings preserved per-line (R7 mitigation)
def test_apply_origin_edit_preserves_crlf_line_endings(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    body = b"image: foo.pgm\r\norigin: [-1.5, -2.0, 0.0]\r\nfree_thresh: 0.196\r\n"
    _write_yaml_bytes(yaml, body)
    # SUBTRACT semantic: typed (0, 0) leaves origin unchanged → bytes
    # equal modulo the origin line's exact rewrite shape.
    map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")
    new_bytes = yaml.read_bytes()
    # Other lines retain their CRLF endings.
    assert b"image: foo.pgm\r\n" in new_bytes
    assert b"free_thresh: 0.196\r\n" in new_bytes
    # Origin line also CRLF (we preserve the original line ending). With
    # typed=(0,0) under SUBTRACT, new_origin == prev_origin so the origin
    # line bytes are byte-identical post-rewrite.
    assert b"origin: [-1.5, -2.0, 0.0]\r\n" in new_bytes


# 16. SUBTRACT-computed value out of bound → BadOriginValue
def test_apply_origin_edit_subtract_overflow_raises(tmp_path: Path) -> None:
    """SUBTRACT semantic: new = old - typed. Pre-state old at the
    positive bound; subtracting a large negative typed pushes the new
    value over the positive bound."""
    yaml = tmp_path / "studio_v1.yaml"
    near_bound = ORIGIN_X_Y_ABS_MAX_M - 10.0
    _write_yaml(yaml, f"origin: [{near_bound}, 0.0, 0.0]\n")
    with pytest.raises(map_origin.BadOriginValue) as exc_info:
        # typed=-100 → new = (near_bound) - (-100) = near_bound + 100 → out of bound.
        map_origin.apply_origin_edit(yaml, -100.0, 0.0, "absolute")
    assert "abs_value_exceeds_bound" in str(exc_info.value)


# --- issue#27 — theta editing tests ---------------------------------------


def test_apply_origin_edit_theta_passthrough_byte_stable_when_theta_deg_none(
    tmp_path: Path,
) -> None:
    """Mode-A M3 fold pin: when ``theta_deg=None`` (existing callers,
    public /api/map/origin path before the SPA frontend lands), the
    theta token bytes are byte-identical pre/post."""
    yaml = tmp_path / "studio_v1.yaml"
    # 5° in radians at full f64 precision.
    theta_str = "0.087266462599716474"
    _write_yaml(yaml, f"origin: [0.0, 0.0, {theta_str}]\n")
    pre_bytes = yaml.read_bytes()
    map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute", theta_deg=None)
    # Origin line bytes byte-identical: typed=(0,0) leaves x/y same;
    # theta_deg=None preserves theta token verbatim.
    post_bytes = yaml.read_bytes()
    assert post_bytes == pre_bytes, (
        f"byte drift on theta passthrough: {pre_bytes!r} → {post_bytes!r}"
    )


def test_apply_origin_edit_theta_deg_writes_radians(tmp_path: Path) -> None:
    """When ``theta_deg`` is supplied, the theta token is replaced by
    `repr(theta_deg * pi / 180)` (radians). ROS map_server convention."""
    import math as _math
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [0.0, 0.0, 0.0]\n")
    map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute", theta_deg=5.0)
    text = yaml.read_text("utf-8")
    expected_rad = repr(5.0 * (_math.pi / 180.0))
    assert expected_rad in text


def test_apply_origin_edit_theta_deg_zero_writes_zero(tmp_path: Path) -> None:
    """0° → 0.0 rad. The exact serialised form is `repr(0.0)` = `'0.0'`,
    which collides with the original token — but we still write through
    the rewrite path (NOT the passthrough), so the operator's intent
    (`theta_deg=0`) is recorded."""
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [0.0, 0.0, 1.5707963267948966]\n")  # was 90°
    map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute", theta_deg=0.0)
    text = yaml.read_text("utf-8")
    # The 90°-rad token must be replaced by 0.0.
    assert "1.5707963267948966" not in text
    assert "origin: [0.0, 0.0, 0.0]" in text


def test_apply_origin_edit_theta_deg_non_finite_raises(tmp_path: Path) -> None:
    """NaN / Infinity in theta_deg → BadOriginValue."""
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [0.0, 0.0, 0.0]\n")
    with pytest.raises(map_origin.BadOriginValue) as ei:
        map_origin.apply_origin_edit(
            yaml, 0.0, 0.0, "absolute", theta_deg=float("nan"),
        )
    assert "non_finite_theta_deg" in str(ei.value)
    with pytest.raises(map_origin.BadOriginValue):
        map_origin.apply_origin_edit(
            yaml, 0.0, 0.0, "absolute", theta_deg=float("inf"),
        )


# --- issue#28 — wrap_yaw_deg ------------------------------------------


def test_wrap_yaw_deg_pass_through_in_range() -> None:
    assert map_origin.wrap_yaw_deg(0.0) == 0.0
    assert map_origin.wrap_yaw_deg(45.0) == 45.0
    assert map_origin.wrap_yaw_deg(-90.0) == -90.0
    assert map_origin.wrap_yaw_deg(180.0) == 180.0


def test_wrap_yaw_deg_wraps_overflow() -> None:
    assert map_origin.wrap_yaw_deg(190.0) == -170.0
    assert map_origin.wrap_yaw_deg(360.0) == 0.0
    assert map_origin.wrap_yaw_deg(540.0) == 180.0


def test_wrap_yaw_deg_wraps_underflow() -> None:
    # -180 reflects to +180 (half-open at the lower bound).
    assert map_origin.wrap_yaw_deg(-180.0) == 180.0
    assert map_origin.wrap_yaw_deg(-185.0) == 175.0
    assert map_origin.wrap_yaw_deg(-360.0) == 0.0


# --- issue#28 — apply_origin_edit_in_memory + theta SUBTRACT ----------


_PRISTINE_YAML = (
    "image: chroma.pgm\n"
    "resolution: 0.05\n"
    "origin: [1.5, -2.0, 0.08726646]\n"  # theta = 5° in radians
    "occupied_thresh: 0.65\n"
    "free_thresh: 0.196\n"
    "negate: 0\n"
)


def test_apply_origin_edit_in_memory_xy_subtract_basic() -> None:
    new_text, res = map_origin.apply_origin_edit_in_memory(
        _PRISTINE_YAML, 0.5, 1.0, "absolute", theta_deg=None,
    )
    assert res.prev_origin[0] == pytest.approx(1.5)
    assert res.new_origin[0] == pytest.approx(1.0)  # 1.5 - 0.5
    assert res.new_origin[1] == pytest.approx(-3.0)  # -2.0 - 1.0
    # Theta byte-identical when theta_deg is None.
    assert "0.08726646" in new_text


def test_apply_origin_edit_subtracts_theta_rotate_1() -> None:
    """Mode-A C6 lock — ROTATE#1: old=5°, typed=10° → new=-5°."""
    _, res = map_origin.apply_origin_edit_in_memory(
        _PRISTINE_YAML, 0.0, 0.0, "absolute", theta_deg=10.0,
    )
    new_yaw_deg = res.new_origin[2] * (180.0 / 3.141592653589793)
    assert new_yaw_deg == pytest.approx(-5.0, abs=1e-3)


def test_apply_origin_edit_subtracts_theta_rotate_2() -> None:
    """Mode-A C6 lock — ROTATE#2: old=-5°, typed=20° → new=-25°. Drift
    catch — mirrors PICK#2/#3."""
    yaml_neg5 = _PRISTINE_YAML.replace("0.08726646", "-0.08726646")
    _, res = map_origin.apply_origin_edit_in_memory(
        yaml_neg5, 0.0, 0.0, "absolute", theta_deg=20.0,
    )
    new_yaw_deg = res.new_origin[2] * (180.0 / 3.141592653589793)
    assert new_yaw_deg == pytest.approx(-25.0, abs=1e-3)


def test_apply_origin_edit_subtracts_theta_wraps_at_180() -> None:
    """Mode-A C5 pin — wrap-around: old=170°, typed=−20° → −170° (not
    +190°)."""
    yaml_170 = _PRISTINE_YAML.replace("0.08726646", "2.96705973")  # 170° rad
    _, res = map_origin.apply_origin_edit_in_memory(
        yaml_170, 0.0, 0.0, "absolute", theta_deg=-20.0,
    )
    new_yaw_deg = res.new_origin[2] * (180.0 / 3.141592653589793)
    # 170 - (-20) = 190 → wrap → -170
    assert new_yaw_deg == pytest.approx(-170.0, abs=1e-3)


def test_apply_origin_edit_in_memory_does_not_touch_disk(tmp_path: Path) -> None:
    """The in-memory variant returns a string and never writes; the
    pristine YAML on disk is byte-identical after the call."""
    pristine = tmp_path / "chroma.yaml"
    pristine.write_text(_PRISTINE_YAML)
    before = pristine.read_bytes()
    map_origin.apply_origin_edit_in_memory(
        pristine.read_text(), 0.5, 1.0, "absolute", theta_deg=10.0,
    )
    assert pristine.read_bytes() == before
