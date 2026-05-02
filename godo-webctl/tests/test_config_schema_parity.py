"""
Track B-CONFIG (PR-CONFIG-β, TB1 fold) — cross-language schema parity.

Loads `production/RPi5/src/core/config_schema.hpp` BY REAL PATH (mirrors
`tests/test_protocol.py`'s LAST_POSE_FIELDS pattern) and asserts:

  - row count == 53 (issue#10.1 pin: 52 + 1 serial.lidar_udev_serial row),
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


def test_row_count_pinned_at_53() -> None:
    """issue#10.1 pin: schema row count is 53 (52 + 1 serial.lidar_udev_serial row)."""
    rows = schema_mod.load_schema()
    assert len(rows) == 53


def test_static_assert_in_cpp_says_53_too() -> None:
    """Cross-pin: the C++ static_assert text contains the count."""
    text = _CPP_SCHEMA_HPP.read_text(encoding="utf-8")
    assert "CONFIG_SCHEMA.size() == 53" in text


def test_lidar_udev_serial_row_present() -> None:
    """issue#10.1 — serial.lidar_udev_serial row exposes the cp210x
    factory serial used by 99-rplidar.rules.template. install.sh is
    the sole consumer (sed-substitutes into the rendered rule);
    tracker stores verbatim through apply / render_toml round-trip.
    Default pins the studio's specific serial so an out-of-the-box
    install on the production host matches the existing /dev/rplidar
    udev contract."""
    rows = schema_mod.load_schema()
    by_name = {r.name: r for r in rows}
    row = by_name.get("serial.lidar_udev_serial")
    assert row is not None
    assert row.type == "string"
    assert row.reload_class == "restart"
    assert row.default_repr == "2eca2bbb4d6eef1182aae9c2c169b110"
    # Description must mention install.sh consumer so an operator
    # reading the Config tab tooltip understands the round-trip path.
    assert "install.sh" in row.description


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


def test_webctl_mapping_timing_rows_present() -> None:
    """issue#14 Maj-1 / issue#16.1 — four webctl-owned mapping-stop
    timing rows. All Restart-class; defaults pin the SIGTERM→SIGKILL
    grace ladder (docker=30 < systemd=45 < webctl=50; systemctl=45
    nested under webctl)."""
    rows = schema_mod.load_schema()
    by_name = {r.name: r for r in rows}
    docker    = by_name.get("webctl.mapping_docker_stop_grace_s")
    systemctl = by_name.get("webctl.mapping_systemctl_subprocess_timeout_s")
    systemd   = by_name.get("webctl.mapping_systemd_stop_timeout_s")
    webctl    = by_name.get("webctl.mapping_webctl_stop_timeout_s")
    assert docker    is not None
    assert systemctl is not None
    assert systemd   is not None
    assert webctl    is not None
    assert docker.type    == "int"
    assert systemctl.type == "int"
    assert systemd.type   == "int"
    assert webctl.type    == "int"
    assert docker.min_d    == 10.0
    assert docker.max_d    == 60.0
    assert systemctl.min_d == 10.0
    assert systemctl.max_d == 90.0
    assert systemd.min_d   == 20.0
    assert systemd.max_d   == 90.0
    assert webctl.min_d    == 25.0
    assert webctl.max_d    == 120.0
    assert docker.default_repr    == "30"
    assert systemctl.default_repr == "45"
    assert systemd.default_repr   == "45"
    assert webctl.default_repr    == "50"
    assert docker.reload_class    == "restart"
    assert systemctl.reload_class == "restart"
    assert systemd.reload_class   == "restart"
    assert webctl.reload_class    == "restart"


def test_constants_mapping_stop_timeout_matches_schema_default_repr() -> None:
    """issue#14 Mode-B Mn2 fix (2026-05-02 KST) / issue#16.1: pin
    `MAPPING_CONTAINER_STOP_TIMEOUT_S` (the Settings fallback default)
    against the schema's `webctl.mapping_webctl_stop_timeout_s`
    `default_repr`. Three layers carry "50" today (constants.py,
    config_defaults.hpp, schema row); without this parity test, a
    drift between Python constant and C++ schema row would silently
    pass CI and only surface at the operator's first install."""
    from godo_webctl.constants import MAPPING_CONTAINER_STOP_TIMEOUT_S

    rows = schema_mod.load_schema()
    by_name = {r.name: r for r in rows}
    webctl = by_name["webctl.mapping_webctl_stop_timeout_s"]
    assert MAPPING_CONTAINER_STOP_TIMEOUT_S == float(webctl.default_repr), (
        f"drift: constants.py MAPPING_CONTAINER_STOP_TIMEOUT_S = "
        f"{MAPPING_CONTAINER_STOP_TIMEOUT_S} but schema default_repr = "
        f"{webctl.default_repr!r}"
    )


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
