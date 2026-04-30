"""
Track B-MAPEDIT-2 — `map_origin.apply_origin_edit` unit tests.

12 baseline cases per planner §5.1 + T2 parametrized theta tokens + T3
parametrized whitespace variants. Sign convention is ADD (operator-locked
2026-04-30 KST).
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


# 1. absolute happy path — round-trip + on-disk byte change
def test_apply_origin_edit_absolute_happy_path(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(
        yaml,
        "image: studio_v1.pgm\nresolution: 0.05\norigin: [-1.5, -2.0, 0.0]\n"
        "occupied_thresh: 0.65\n",
    )
    result = map_origin.apply_origin_edit(yaml, 0.32, -0.18, "absolute")
    assert result.prev_origin == (-1.5, -2.0, 0.0)
    assert result.new_origin == (0.32, -0.18, 0.0)
    text = yaml.read_text("utf-8")
    assert "origin: [0.32, -0.18, 0.0]" in text
    # Other lines unchanged.
    assert "image: studio_v1.pgm" in text
    assert "resolution: 0.05" in text
    assert "occupied_thresh: 0.65" in text


# 2. delta happy path — ADD sign convention pin (operator-locked 2026-04-30 KST)
def test_apply_origin_edit_delta_happy_path(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    _write_yaml(yaml, "origin: [-1.5, -2.0, 0.0]\n")
    result = map_origin.apply_origin_edit(yaml, 0.32, -0.18, "delta")
    # ADD: new = prev + typed
    assert result.prev_origin == (-1.5, -2.0, 0.0)
    expected_x = -1.5 + 0.32
    expected_y = -2.0 + (-0.18)
    assert result.new_origin[0] == pytest.approx(expected_x)
    assert result.new_origin[1] == pytest.approx(expected_y)
    assert result.new_origin[2] == 0.0


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
    map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")
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


# 13. round-trip precision — high-precision input survives `.10g` format
def test_apply_origin_edit_round_trip_precision(tmp_path: Path) -> None:
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
    assert abs(parsed_x - high_precision_x) < 1e-10
    assert abs(parsed_y - high_precision_y) < 1e-10


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
    yaml = tmp_path / "studio_v1.yaml"
    body = f"image: foo.pgm\nresolution: 0.05\n{origin_line}\nfree_thresh: 0.196\n"
    _write_yaml(yaml, body)
    result = map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")
    assert result.prev_origin == (-1.5, -2.0, 0.0)
    assert result.new_origin == (0.0, 0.0, 0.0)
    new_text = yaml.read_text("utf-8")
    assert "image: foo.pgm" in new_text
    assert "free_thresh: 0.196" in new_text


# 15. CRLF line endings preserved per-line (R7 mitigation)
def test_apply_origin_edit_preserves_crlf_line_endings(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    body = b"image: foo.pgm\r\norigin: [-1.5, -2.0, 0.0]\r\nfree_thresh: 0.196\r\n"
    _write_yaml_bytes(yaml, body)
    map_origin.apply_origin_edit(yaml, 0.0, 0.0, "absolute")
    new_bytes = yaml.read_bytes()
    # Other lines retain their CRLF endings.
    assert b"image: foo.pgm\r\n" in new_bytes
    assert b"free_thresh: 0.196\r\n" in new_bytes
    # Origin line also CRLF (we preserve the original line ending).
    assert b"origin: [0.0, 0.0, 0.0]\r\n" in new_bytes


# 16. delta computed value out of bound → BadOriginValue
def test_apply_origin_edit_delta_overflow_raises(tmp_path: Path) -> None:
    yaml = tmp_path / "studio_v1.yaml"
    # prev origin is at the bound; adding a positive delta tips it over.
    near_bound = ORIGIN_X_Y_ABS_MAX_M - 10.0
    _write_yaml(yaml, f"origin: [{near_bound}, 0.0, 0.0]\n")
    with pytest.raises(map_origin.BadOriginValue) as exc_info:
        map_origin.apply_origin_edit(yaml, 100.0, 0.0, "delta")
    assert "abs_value_exceeds_bound" in str(exc_info.value)
