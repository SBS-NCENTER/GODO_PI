"""
issue#12 — `webctl_toml.read_webctl_section` cases.

Coverage:
  (a) missing TOML file → defaults (30, 30).
  (b) TOML without `[webctl]` section → defaults.
  (c) one key set → other defaults.
  (d) both keys set → both honoured.
  (e) env var overrides TOML.
  (f) out-of-range value (0, 61, -1) raises ``WebctlTomlError``.
  (g) non-integer value raises ``WebctlTomlError``.
  (h) malformed TOML raises ``WebctlTomlError``.
  (i) tracker-unrelated keys in `[webctl]` are tolerated (forward-compat).

The tracker writes via atomic-rename so torn reads cannot occur (see
``webctl_toml.py`` docstring); race-window cases are not tested here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from godo_webctl import webctl_toml as wt

# ---- (a) missing TOML file -----------------------------------------------


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    """Operator boot before any tracker.toml exists must NOT crash."""
    section = wt.read_webctl_section(tmp_path / "no_such_file.toml", env={})
    assert section.pose_stream_hz == wt.WEBCTL_POSE_STREAM_HZ_DEFAULT
    assert section.scan_stream_hz == wt.WEBCTL_SCAN_STREAM_HZ_DEFAULT


# ---- (b) TOML without [webctl] section -----------------------------------


def test_toml_without_webctl_section_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[network]\nue_host = \"127.0.0.1\"\n")
    section = wt.read_webctl_section(p, env={})
    assert section.pose_stream_hz == wt.WEBCTL_POSE_STREAM_HZ_DEFAULT
    assert section.scan_stream_hz == wt.WEBCTL_SCAN_STREAM_HZ_DEFAULT


# ---- (c) one key set, other defaults -------------------------------------


def test_partial_section_only_pose(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\npose_stream_hz = 10\n")
    section = wt.read_webctl_section(p, env={})
    assert section.pose_stream_hz == 10
    assert section.scan_stream_hz == wt.WEBCTL_SCAN_STREAM_HZ_DEFAULT


def test_partial_section_only_scan(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\nscan_stream_hz = 15\n")
    section = wt.read_webctl_section(p, env={})
    assert section.pose_stream_hz == wt.WEBCTL_POSE_STREAM_HZ_DEFAULT
    assert section.scan_stream_hz == 15


# ---- (d) both keys set ---------------------------------------------------


def test_both_keys_set(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\npose_stream_hz = 25\nscan_stream_hz = 50\n")
    section = wt.read_webctl_section(p, env={})
    assert section.pose_stream_hz == 25
    assert section.scan_stream_hz == 50


# ---- (e) env var beats TOML ----------------------------------------------


def test_env_pose_overrides_toml(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\npose_stream_hz = 10\nscan_stream_hz = 20\n")
    env = {"GODO_WEBCTL_POSE_STREAM_HZ": "60"}
    section = wt.read_webctl_section(p, env=env)
    assert section.pose_stream_hz == 60  # env wins
    assert section.scan_stream_hz == 20  # TOML stands


def test_env_scan_overrides_toml(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\nscan_stream_hz = 5\n")
    env = {"GODO_WEBCTL_SCAN_STREAM_HZ": "45"}
    section = wt.read_webctl_section(p, env=env)
    assert section.pose_stream_hz == wt.WEBCTL_POSE_STREAM_HZ_DEFAULT
    assert section.scan_stream_hz == 45


def test_env_overrides_default_when_no_toml(tmp_path: Path) -> None:
    """Env applies even when no TOML file exists."""
    env = {
        "GODO_WEBCTL_POSE_STREAM_HZ": "1",
        "GODO_WEBCTL_SCAN_STREAM_HZ": "60",
    }
    section = wt.read_webctl_section(tmp_path / "missing.toml", env=env)
    assert section.pose_stream_hz == 1
    assert section.scan_stream_hz == 60


# ---- (f) out-of-range value ---------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, 61, 1000])
def test_toml_out_of_range_raises(tmp_path: Path, bad: int) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text(f"[webctl]\npose_stream_hz = {bad}\n")
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.pose_stream_hz" in str(ei.value)
    assert str(bad) in str(ei.value)


@pytest.mark.parametrize("bad", ["0", "-1", "61", "1000"])
def test_env_out_of_range_raises(tmp_path: Path, bad: str) -> None:
    env = {"GODO_WEBCTL_SCAN_STREAM_HZ": bad}
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(tmp_path / "missing.toml", env=env)
    assert "GODO_WEBCTL_SCAN_STREAM_HZ" in str(ei.value)


# ---- (g) non-integer value -----------------------------------------------


def test_toml_string_value_raises(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text('[webctl]\npose_stream_hz = "not-a-number"\n')
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.pose_stream_hz" in str(ei.value)


def test_toml_float_value_raises(tmp_path: Path) -> None:
    """TOML floats must NOT silently coerce to int — schema declares Int."""
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\npose_stream_hz = 30.5\n")
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.pose_stream_hz" in str(ei.value)


def test_toml_bool_value_raises(tmp_path: Path) -> None:
    """bool is a subclass of int; module rejects it explicitly so
    `pose_stream_hz = true` does not coerce to 1."""
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\nscan_stream_hz = true\n")
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.scan_stream_hz" in str(ei.value)


def test_env_non_integer_raises(tmp_path: Path) -> None:
    env = {"GODO_WEBCTL_POSE_STREAM_HZ": "fifteen"}
    with pytest.raises(wt.WebctlTomlError):
        wt.read_webctl_section(tmp_path / "missing.toml", env=env)


# ---- (h) malformed TOML --------------------------------------------------


def test_malformed_toml_raises(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\npose_stream_hz = = 30\n")  # syntax error
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "tracker.toml" in str(ei.value) or str(p) in str(ei.value)


def test_webctl_section_not_a_table_raises(tmp_path: Path) -> None:
    """`webctl = 30` (top-level scalar) must raise — it's a malformed
    schema layout, not a forward-compat extension."""
    p = tmp_path / "tracker.toml"
    p.write_text("webctl = 30\n")
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "[webctl]" in str(ei.value) or "table" in str(ei.value)


# ---- (i) forward-compat tolerance ---------------------------------------


def test_unknown_keys_in_webctl_section_tolerated(tmp_path: Path) -> None:
    """Future additions to the [webctl] section must NOT crash this
    reader — only the keys this module knows about are validated. The
    tracker enforces allowed_keys() rejection separately at the C++
    side; webctl is permissive here so an old webctl can boot against
    a new tracker.toml without a coordinated upgrade."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\n"
        "pose_stream_hz = 30\n"
        "future_unknown_key = 999\n"
    )
    section = wt.read_webctl_section(p, env={})
    assert section.pose_stream_hz == 30
    assert section.scan_stream_hz == wt.WEBCTL_SCAN_STREAM_HZ_DEFAULT


# ---- boundary values -----------------------------------------------------


@pytest.mark.parametrize("ok", [1, 30, 60])
def test_boundary_values_accepted(tmp_path: Path, ok: int) -> None:
    """Min, default, and max all accepted at both layers."""
    p = tmp_path / "tracker.toml"
    p.write_text(f"[webctl]\npose_stream_hz = {ok}\nscan_stream_hz = {ok}\n")
    section = wt.read_webctl_section(p, env={})
    assert section.pose_stream_hz == ok
    assert section.scan_stream_hz == ok


# ---- precedence ladder (env > TOML > default) ---------------------------


def test_precedence_env_over_toml_over_default(tmp_path: Path) -> None:
    """Locks the documented precedence ladder."""
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\npose_stream_hz = 10\n")
    # No env, no scan in TOML → scan is default.
    section = wt.read_webctl_section(p, env={})
    assert section.pose_stream_hz == 10
    assert section.scan_stream_hz == wt.WEBCTL_SCAN_STREAM_HZ_DEFAULT
    # Env overrides pose.
    section = wt.read_webctl_section(p, env={"GODO_WEBCTL_POSE_STREAM_HZ": "5"})
    assert section.pose_stream_hz == 5
    assert section.scan_stream_hz == wt.WEBCTL_SCAN_STREAM_HZ_DEFAULT


# ---- public surface pin --------------------------------------------------


def test_public_constants_pinned() -> None:
    """Pin the documented Tier-1 constants — drift here means defaults
    drifted between tracker schema (default_repr) and webctl reader."""
    assert wt.WEBCTL_POSE_STREAM_HZ_DEFAULT == 30
    assert wt.WEBCTL_SCAN_STREAM_HZ_DEFAULT == 30
    assert wt.WEBCTL_STREAM_HZ_MIN == 1
    assert wt.WEBCTL_STREAM_HZ_MAX == 60
