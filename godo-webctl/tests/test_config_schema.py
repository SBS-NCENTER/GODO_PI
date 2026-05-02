"""
Track B-CONFIG (PR-CONFIG-β) — Python schema-mirror parser tests.

Two sets:
  (a) Synthetic — fixtures with crafted ConfigSchemaRow blocks that
      exercise the regex's parse paths in isolation. Useful for CI
      that does not have the full repo checked out.
  (b) Real-source — load `production/RPi5/src/core/config_schema.hpp`
      by real path and assert the parsed shape matches the C++ pin
      (42 rows; per-field types). Mirrors test_protocol.py's
      LAST_POSE_FIELDS pin pattern.

`test_config_schema_parity.py` (separate file) is the cross-language
parity catch — this file tests the parser correctness in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from godo_webctl import config_schema as schema_mod


def _make_synthetic_source(rows_text: str, expected: int = 40) -> str:
    """Wrap a row-text block in a minimal C++ source that the parser
    accepts. We do NOT need the real header structure — only the
    `{"...", ValueType::..., ...}` initializers."""
    return f"""
// fake header
inline constexpr std::array<ConfigSchemaRow, {expected}> CONFIG_SCHEMA = {{{{
{rows_text}
}}}};
"""


def test_parse_single_int_row() -> None:
    src = _make_synthetic_source(
        '{"network.ue_port", ValueType::Int, 1.0, 65535.0, "6666", '
        'ReloadClass::Restart, "UE port."},',
        expected=1,
    )
    rows = schema_mod._parse_source(src)
    assert len(rows) == 1
    r = rows[0]
    assert r.name == "network.ue_port"
    assert r.type == "int"
    assert r.min_d == 1.0
    assert r.max_d == 65535.0
    assert r.default_repr == "6666"
    assert r.reload_class == "restart"
    assert r.description == "UE port."


def test_parse_double_row() -> None:
    src = _make_synthetic_source(
        '{"smoother.deadband_mm", ValueType::Double, 0.0, 200.0, "10.0", '
        'ReloadClass::Hot, "Deadband on translation (mm)."},',
        expected=1,
    )
    rows = schema_mod._parse_source(src)
    assert len(rows) == 1
    assert rows[0].type == "double"
    assert rows[0].reload_class == "hot"
    assert rows[0].min_d == 0.0
    assert rows[0].max_d == 200.0


def test_parse_string_row_with_path_default() -> None:
    src = _make_synthetic_source(
        '{"amcl.map_path", ValueType::String, 0.0, 0.0, '
        '"/etc/godo/maps/studio_v1.pgm", ReloadClass::Recalibrate, '
        '"PGM map path."},',
        expected=1,
    )
    rows = schema_mod._parse_source(src)
    assert rows[0].type == "string"
    assert rows[0].default_repr == "/etc/godo/maps/studio_v1.pgm"
    assert rows[0].reload_class == "recalibrate"


def test_parse_three_rows_preserves_order() -> None:
    src = _make_synthetic_source(
        '{"a.x", ValueType::Int, 0.0, 10.0, "1", ReloadClass::Hot, "first"},\n'
        '{"a.y", ValueType::Int, 0.0, 10.0, "2", ReloadClass::Restart, "second"},\n'
        '{"a.z", ValueType::Int, 0.0, 10.0, "3", ReloadClass::Recalibrate, "third"},',
        expected=3,
    )
    rows = schema_mod._parse_source(src)
    names = [r.name for r in rows]
    assert names == ["a.x", "a.y", "a.z"]


def test_parse_rejects_short_row_count(tmp_path: Path) -> None:
    """The default `EXPECTED_ROW_COUNT` is 52; a 1-row file via the
    public path raises."""
    src = _make_synthetic_source(
        '{"a.x", ValueType::Int, 0.0, 10.0, "1", ReloadClass::Hot, "f"},',
        expected=52,  # the wrapper claims 52, but only 1 row in body
    )
    src_path = tmp_path / "config_schema.hpp"
    src_path.write_text(src)
    with pytest.raises(schema_mod.ConfigSchemaError) as ei:
        schema_mod.load_schema(source_path=src_path)
    assert "1" in str(ei.value)
    assert "52" in str(ei.value)


def test_load_schema_real_source_returns_52_rows() -> None:
    """TB1 fold: load by real path; pin row count + alphabetical sort.
    issue#16.1 fold: 51 → 52 (added webctl.mapping_systemctl_subprocess_timeout_s)."""
    rows = schema_mod.load_schema()
    assert len(rows) == 52
    # Alphabetical (matches the C++ pin in config_schema.hpp).
    names = [r.name for r in rows]
    assert names == sorted(names)
    # issue#12 — webctl.* rows present.
    assert "webctl.pose_stream_hz" in names
    assert "webctl.scan_stream_hz" in names
    # issue#14 Maj-1 — webctl.mapping_* rows present.
    assert "webctl.mapping_docker_stop_grace_s" in names
    assert "webctl.mapping_systemd_stop_timeout_s" in names
    assert "webctl.mapping_webctl_stop_timeout_s" in names


def test_load_schema_caches_parse() -> None:
    """Second call returns the same tuple instance."""
    schema_mod.reset_cache_for_tests()
    a = schema_mod.load_schema()
    b = schema_mod.load_schema()
    assert a is b


def test_schema_to_json_shape() -> None:
    """Project a small schema into the wire shape."""
    src = _make_synthetic_source(
        '{"a.x", ValueType::Int, 0.0, 10.0, "1", ReloadClass::Hot, "first"},',
        expected=1,
    )
    rows = schema_mod._parse_source(src)
    out = schema_mod.schema_to_json(rows)
    assert isinstance(out, list)
    assert len(out) == 1
    obj = out[0]
    assert obj == {
        "name": "a.x",
        "type": "int",
        "min": 0.0,
        "max": 10.0,
        "default": "1",
        "reload_class": "hot",
        "description": "first",
    }
