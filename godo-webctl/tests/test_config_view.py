"""
Track B-CONFIG (PR-CONFIG-β) — pure projection helpers.

`config_view` has no FastAPI / network dependencies, so the tests are
straight dict-in / dict-out comparisons.
"""

from __future__ import annotations

from godo_webctl import config_schema as schema_mod
from godo_webctl import config_view as view_mod


def test_project_config_view_unwraps_keys_envelope() -> None:
    """The C++ tracker emits ``{"ok":true,"keys":{...}}``; the projection
    must return the inner ``keys`` dict so the SPA receives a flat
    ``Record<string, ConfigValue>``."""
    resp = {
        "ok": True,
        "keys": {"smoother.deadband_mm": 12.5, "network.ue_port": 6666},
    }
    out = view_mod.project_config_view(resp)
    assert "ok" not in out
    assert "keys" not in out
    assert out == {"smoother.deadband_mm": 12.5, "network.ue_port": 6666}


def test_project_config_view_handles_empty() -> None:
    """Defensive paths — an empty response, an ok-only response (no
    keys envelope), and a malformed non-dict keys field all yield
    `{}` rather than crashing the handler."""
    assert view_mod.project_config_view({}) == {}
    assert view_mod.project_config_view({"ok": True}) == {}
    assert view_mod.project_config_view({"ok": True, "keys": None}) == {}
    assert view_mod.project_config_view({"ok": True, "keys": "not a dict"}) == {}


def test_project_config_view_preserves_value_types() -> None:
    """JSON int / float / string values pass through the unwrap with
    Python type identity preserved (the SPA renders per ConfigSchemaRow.type)."""
    resp = {
        "ok": True,
        "keys": {
            "an_int": 42,
            "a_double": 3.14,
            "a_string": "/dev/ttyUSB0",
        },
    }
    out = view_mod.project_config_view(resp)
    assert isinstance(out["an_int"], int)
    assert isinstance(out["a_double"], float)
    assert isinstance(out["a_string"], str)


def test_project_config_view_ignores_sibling_fields() -> None:
    """Any future protocol-level sibling fields (alongside `ok` + `keys`)
    must be invisible to the SPA. This pin guarantees the projection
    is keys-only, not "everything except ok"."""
    resp = {
        "ok": True,
        "keys": {"smoother.deadband_mm": 12.5},
        "future_field": "should_not_leak",
    }
    out = view_mod.project_config_view(resp)
    assert out == {"smoother.deadband_mm": 12.5}


def test_project_schema_view_real_source() -> None:
    rows = schema_mod.load_schema()
    out = view_mod.project_schema_view(rows)
    assert len(out) == 68
    # issue#12 — webctl.* rows surface in the projected view.
    names = [r["name"] for r in out]
    assert "webctl.pose_stream_hz" in names
    assert "webctl.scan_stream_hz" in names
    # issue#14 Maj-1 / issue#16.1 — webctl.mapping_* rows surface too.
    assert "webctl.mapping_docker_stop_grace_s" in names
    assert "webctl.mapping_systemctl_subprocess_timeout_s" in names
    assert "webctl.mapping_systemd_stop_timeout_s" in names
    assert "webctl.mapping_webctl_stop_timeout_s" in names
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
