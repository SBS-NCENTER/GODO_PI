"""
Track B-CONFIG (PR-CONFIG-β, TB1 fold) — cross-language schema parity.

Loads `production/RPi5/src/core/config_schema.hpp` BY REAL PATH (mirrors
`tests/test_protocol.py`'s LAST_POSE_FIELDS pattern) and asserts:

  - row count == 48 (issue#12 fold pin: 46 + 2 webctl.* rows),
  - every row's `reload_class` is one of the 3 known strings,
  - every row's `type` is one of the 3 known strings,
  - the default_repr is non-empty.

Also cross-checks that the schema's sorted name set matches the
section-prefix coverage operators expect (`amcl.* / gpio.* / ipc.* /
network.* / rt.* / serial.* / smoother.* / webctl.*`).

Drift between the C++ source and the Python parser fails this test;
the failure message names the diverged row.
"""

from __future__ import annotations

from pathlib import Path

from godo_webctl import config_schema as schema_mod
from godo_webctl import protocol as P

# Real-source path. If this changes, the regex parser path changes too.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CPP_SCHEMA_HPP = _REPO_ROOT / "production" / "RPi5" / "src" / "core" / "config_schema.hpp"


def test_real_source_exists() -> None:
    assert _CPP_SCHEMA_HPP.exists(), f"C++ schema source missing: {_CPP_SCHEMA_HPP}"


def test_row_count_pinned_at_48() -> None:
    """issue#12 fold pin: schema row count is 48 (46 + 2 webctl.* rows)."""
    rows = schema_mod.load_schema()
    assert len(rows) == 48


def test_static_assert_in_cpp_says_48_too() -> None:
    """Cross-pin: the C++ static_assert text contains the count."""
    text = _CPP_SCHEMA_HPP.read_text(encoding="utf-8")
    assert "CONFIG_SCHEMA.size() == 48" in text


def test_webctl_rows_present() -> None:
    """issue#12 — webctl.* rows must appear after the existing 46-row
    set; presence + reload_class pin."""
    rows = schema_mod.load_schema()
    by_name = {r.name: r for r in rows}
    pose = by_name.get("webctl.pose_stream_hz")
    scan = by_name.get("webctl.scan_stream_hz")
    assert pose is not None
    assert scan is not None
    assert pose.type == "int"
    assert scan.type == "int"
    assert pose.min_d == 1.0
    assert pose.max_d == 60.0
    assert pose.default_repr == "30"
    assert scan.default_repr == "30"
    assert pose.reload_class == "restart"
    assert scan.reload_class == "restart"


def test_every_reload_class_in_known_set() -> None:
    rows = schema_mod.load_schema()
    bad = [r.name for r in rows if r.reload_class not in P.VALID_RELOAD_CLASSES]
    assert bad == [], f"unknown reload_class on rows: {bad}"


def test_every_type_in_known_set() -> None:
    rows = schema_mod.load_schema()
    valid_types = {"int", "double", "string"}
    bad = [r.name for r in rows if r.type not in valid_types]
    assert bad == [], f"unknown type on rows: {bad}"


def test_every_default_non_empty() -> None:
    rows = schema_mod.load_schema()
    bad = [r.name for r in rows if not r.default_repr]
    assert bad == [], f"empty default on rows: {bad}"


def test_sections_match_design() -> None:
    """The 8 design-time sections all appear at least once (issue#12
    added webctl)."""
    rows = schema_mod.load_schema()
    sections = {r.name.split(".", 1)[0] for r in rows}
    expected = {
        "amcl",
        "gpio",
        "ipc",
        "network",
        "rt",
        "serial",
        "smoother",
        "webctl",
    }
    assert sections == expected, (
        f"section drift: extra={sections - expected} missing={expected - sections}"
    )


def test_alphabetical_ordering() -> None:
    """The C++ pin claims alphabetical-by-name; check the parsed view."""
    rows = schema_mod.load_schema()
    names = [r.name for r in rows]
    assert names == sorted(names)


def test_known_hot_keys_present() -> None:
    """The 3 hot-class keys read by cold_writer.cpp's per-iteration body
    MUST appear in the schema with reload_class='hot'. Any drift here
    means cold_writer would silently fall back to cfg.* on every read."""
    rows = schema_mod.load_schema()
    hot_keys = {r.name for r in rows if r.reload_class == "hot"}
    required = {
        "smoother.deadband_mm",
        "smoother.deadband_deg",
        "amcl.yaw_tripwire_deg",
    }
    assert required <= hot_keys, f"hot-class drift: missing {required - hot_keys}"
