"""
Track B-CONFIG (PR-CONFIG-β) — pure projection helpers.

`config_view` has no FastAPI / network dependencies, so the tests are
straight dict-in / dict-out comparisons.
"""

from __future__ import annotations

from godo_webctl import config_schema as schema_mod
from godo_webctl import config_view as view_mod


def test_project_config_view_strips_ok_field() -> None:
    resp = {"ok": True, "smoother.deadband_mm": 12.5, "network.ue_port": 6666}
    out = view_mod.project_config_view(resp)
    assert "ok" not in out
    assert out == {"smoother.deadband_mm": 12.5, "network.ue_port": 6666}


def test_project_config_view_handles_empty() -> None:
    assert view_mod.project_config_view({}) == {}
    assert view_mod.project_config_view({"ok": True}) == {}


def test_project_config_view_preserves_value_types() -> None:
    resp = {
        "ok": True,
        "an_int": 42,
        "a_double": 3.14,
        "a_string": "/dev/ttyUSB0",
    }
    out = view_mod.project_config_view(resp)
    assert isinstance(out["an_int"], int)
    assert isinstance(out["a_double"], float)
    assert isinstance(out["a_string"], str)


def test_project_schema_view_real_source() -> None:
    rows = schema_mod.load_schema()
    out = view_mod.project_schema_view(rows)
    assert len(out) == 40
    assert all(isinstance(r, dict) for r in out)
    # Required keys per CONFIG_SCHEMA_ROW_FIELDS.
    for r in out:
        assert set(r.keys()) == {
            "name",
            "type",
            "min",
            "max",
            "default",
            "reload_class",
            "description",
        }
