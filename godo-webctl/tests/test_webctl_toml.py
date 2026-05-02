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


# ---- issue#14 — tracker-owned [serial] section reader -----------------


def test_tracker_serial_default_when_missing_file(tmp_path: Path) -> None:
    out = wt.read_tracker_serial_section(tmp_path / "no_such.toml")
    assert out.lidar_port == wt.TRACKER_SERIAL_LIDAR_PORT_DEFAULT
    # issue#10 — default flipped /dev/ttyUSB0 → /dev/rplidar.
    assert wt.TRACKER_SERIAL_LIDAR_PORT_DEFAULT == "/dev/rplidar"


def test_tracker_serial_default_when_section_missing(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[network]\nue_host = \"127.0.0.1\"\n")
    out = wt.read_tracker_serial_section(p)
    assert out.lidar_port == "/dev/rplidar"


def test_tracker_serial_reads_value_verbatim(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text('[serial]\nlidar_port = "/dev/ttyUSB1"\n')
    out = wt.read_tracker_serial_section(p)
    assert out.lidar_port == "/dev/ttyUSB1"


def test_tracker_serial_default_when_empty_string(tmp_path: Path) -> None:
    """Empty string from TOML falls back to default (defence-in-depth)."""
    p = tmp_path / "tracker.toml"
    p.write_text('[serial]\nlidar_port = ""\n')
    out = wt.read_tracker_serial_section(p)
    assert out.lidar_port == "/dev/rplidar"


def test_tracker_serial_rejects_non_string(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[serial]\nlidar_port = 1234\n")
    with pytest.raises(wt.WebctlTomlError):
        wt.read_tracker_serial_section(p)


def test_tracker_serial_rejects_table_section(tmp_path: Path) -> None:
    """If [serial] is given as an array of tables (operator typo), reject
    cleanly rather than silently use defaults."""
    p = tmp_path / "tracker.toml"
    p.write_text('[[serial]]\nlidar_port = "/dev/ttyUSB1"\n')
    with pytest.raises(wt.WebctlTomlError):
        wt.read_tracker_serial_section(p)


def test_tracker_serial_propagates_malformed_toml(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text("[serial\nlidar_port = bogus\n")
    with pytest.raises(wt.WebctlTomlError):
        wt.read_tracker_serial_section(p)


# ---- issue#14 Maj-1 — mapping-stop timing ladder ------------------------


def test_mapping_timing_defaults_when_section_missing(tmp_path: Path) -> None:
    """No [webctl] section → all 4 mapping_*_s fields fall to schema defaults."""
    section = wt.read_webctl_section(tmp_path / "no_such.toml", env={})
    assert section.mapping_docker_stop_grace_s == 30
    assert section.mapping_systemctl_subprocess_timeout_s == 45
    assert section.mapping_systemd_stop_timeout_s == 45
    assert section.mapping_webctl_stop_timeout_s == 50


def test_mapping_timing_reads_from_toml(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\n"
        "mapping_docker_stop_grace_s = 35\n"
        "mapping_systemctl_subprocess_timeout_s = 50\n"
        "mapping_systemd_stop_timeout_s = 55\n"
        "mapping_webctl_stop_timeout_s = 60\n",
    )
    section = wt.read_webctl_section(p, env={})
    assert section.mapping_docker_stop_grace_s == 35
    assert section.mapping_systemctl_subprocess_timeout_s == 50
    assert section.mapping_systemd_stop_timeout_s == 55
    assert section.mapping_webctl_stop_timeout_s == 60
    # systemctl_subprocess (50) < webctl (60) — quartet invariant holds.
    assert section.mapping_systemctl_subprocess_timeout_s < section.mapping_webctl_stop_timeout_s


def test_mapping_timing_env_overrides_toml(tmp_path: Path) -> None:
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\n"
        "mapping_docker_stop_grace_s = 35\n"
        "mapping_systemd_stop_timeout_s = 55\n"
        "mapping_webctl_stop_timeout_s = 60\n",
    )
    env = {"GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S": "70"}
    section = wt.read_webctl_section(p, env=env)
    assert section.mapping_webctl_stop_timeout_s == 70


@pytest.mark.parametrize("bad", [9, 5, 61, 100])
def test_mapping_docker_stop_grace_s_out_of_range_raises(tmp_path: Path, bad: int) -> None:
    """Range [10, 60] mirrors the C++ schema row."""
    p = tmp_path / "tracker.toml"
    p.write_text(f"[webctl]\nmapping_docker_stop_grace_s = {bad}\n")
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.mapping_docker_stop_grace_s" in str(ei.value)


@pytest.mark.parametrize("bad", [19, 0, 91, 200])
def test_mapping_systemd_stop_timeout_s_out_of_range_raises(tmp_path: Path, bad: int) -> None:
    """Range [20, 90] mirrors the C++ schema row."""
    p = tmp_path / "tracker.toml"
    # Pin docker stop grace below to isolate the systemd-key error.
    p.write_text(
        f"[webctl]\n"
        f"mapping_docker_stop_grace_s = 15\n"
        f"mapping_systemd_stop_timeout_s = {bad}\n",
    )
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.mapping_systemd_stop_timeout_s" in str(ei.value)


@pytest.mark.parametrize("bad", [24, 0, 121, 999])
def test_mapping_webctl_stop_timeout_s_out_of_range_raises(tmp_path: Path, bad: int) -> None:
    """Range [25, 120] mirrors the C++ schema row."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        f"[webctl]\n"
        f"mapping_docker_stop_grace_s = 15\n"
        f"mapping_systemd_stop_timeout_s = 22\n"
        f"mapping_webctl_stop_timeout_s = {bad}\n",
    )
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.mapping_webctl_stop_timeout_s" in str(ei.value)


@pytest.mark.parametrize("bad", [9, 5, 91, 200])
def test_mapping_systemctl_subprocess_timeout_s_out_of_range_raises(
    tmp_path: Path, bad: int,
) -> None:
    """issue#16.1 — range [10, 90] mirrors the C++ schema row."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        f"[webctl]\n"
        f"mapping_systemctl_subprocess_timeout_s = {bad}\n",
    )
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.mapping_systemctl_subprocess_timeout_s" in str(ei.value)


def test_mapping_systemctl_subprocess_timeout_default_when_section_missing(
    tmp_path: Path,
) -> None:
    """issue#16.1 — empty file → systemctl_subprocess key falls to 45."""
    section = wt.read_webctl_section(tmp_path / "no_such.toml", env={})
    assert (
        section.mapping_systemctl_subprocess_timeout_s
        == wt.WEBCTL_MAPPING_SYSTEMCTL_SUBPROCESS_TIMEOUT_S_DEFAULT
        == 45
    )


def test_mapping_systemctl_subprocess_timeout_from_toml(tmp_path: Path) -> None:
    """issue#16.1 — TOML override (40) propagates."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\nmapping_systemctl_subprocess_timeout_s = 40\n",
    )
    section = wt.read_webctl_section(p, env={})
    assert section.mapping_systemctl_subprocess_timeout_s == 40


def test_mapping_systemctl_subprocess_timeout_from_env(tmp_path: Path) -> None:
    """issue#16.1 — env wins over TOML."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\nmapping_systemctl_subprocess_timeout_s = 40\n",
    )
    env = {"GODO_WEBCTL_MAPPING_SYSTEMCTL_SUBPROCESS_TIMEOUT_S": "30"}
    section = wt.read_webctl_section(p, env=env)
    assert section.mapping_systemctl_subprocess_timeout_s == 30


def test_mapping_timing_ordering_invariant_systemctl_ge_webctl_raises(
    tmp_path: Path,
) -> None:
    """issue#16.1 — systemctl_subprocess >= webctl_timeout must reject;
    the systemctl wrapper deadline cannot exceed the coordinator's."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\n"
        "mapping_docker_stop_grace_s = 30\n"
        "mapping_systemd_stop_timeout_s = 45\n"
        "mapping_systemctl_subprocess_timeout_s = 60\n"
        "mapping_webctl_stop_timeout_s = 50\n",
    )
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.mapping_systemctl_subprocess_timeout_s" in str(ei.value)
    assert "webctl.mapping_webctl_stop_timeout_s" in str(ei.value)


def test_mapping_timing_ordering_invariant_docker_ge_systemd_raises(
    tmp_path: Path,
) -> None:
    """If docker_grace >= systemd_timeout, reject — SIGKILL would
    fire while docker stop is still expecting to send TERM."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\n"
        "mapping_docker_stop_grace_s = 30\n"
        "mapping_systemd_stop_timeout_s = 30\n"
        "mapping_webctl_stop_timeout_s = 50\n",
    )
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    msg = str(ei.value)
    # Error message names the second key in the broken pair so the
    # operator sees the row to bump.
    assert "webctl.mapping_systemd_stop_timeout_s" in msg
    assert "must be >" in msg


def test_mapping_timing_ordering_invariant_systemd_ge_webctl_raises(
    tmp_path: Path,
) -> None:
    """If systemd_timeout >= webctl_timeout, webctl's poll deadline
    fires before systemd has a chance to clean-stop the unit."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\n"
        "mapping_docker_stop_grace_s = 15\n"
        "mapping_systemd_stop_timeout_s = 50\n"
        "mapping_webctl_stop_timeout_s = 50\n",
    )
    with pytest.raises(wt.WebctlTomlError) as ei:
        wt.read_webctl_section(p, env={})
    assert "webctl.mapping_webctl_stop_timeout_s" in str(ei.value)
    assert "must be >" in str(ei.value)


def test_mapping_timing_ordering_invariant_docker_gt_systemd_raises(
    tmp_path: Path,
) -> None:
    """Strict-greater check (not just != ) — docker_grace > systemd
    flips the ladder upside down."""
    p = tmp_path / "tracker.toml"
    p.write_text(
        "[webctl]\n"
        "mapping_docker_stop_grace_s = 50\n"
        "mapping_systemd_stop_timeout_s = 30\n"
        "mapping_webctl_stop_timeout_s = 60\n",
    )
    with pytest.raises(wt.WebctlTomlError):
        wt.read_webctl_section(p, env={})


def test_mapping_timing_defaults_satisfy_ordering_invariant() -> None:
    """Schema defaults pinned in webctl_toml.py MUST satisfy the
    cross-quartet invariant — otherwise a fresh deploy with no
    [webctl] overrides would crash at first `read_webctl_section`
    call."""
    docker = wt.WEBCTL_MAPPING_DOCKER_STOP_GRACE_S_DEFAULT
    systemctl = wt.WEBCTL_MAPPING_SYSTEMCTL_SUBPROCESS_TIMEOUT_S_DEFAULT
    systemd = wt.WEBCTL_MAPPING_SYSTEMD_STOP_TIMEOUT_S_DEFAULT
    webctl = wt.WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S_DEFAULT
    assert docker < systemd < webctl
    assert systemctl < webctl
    # issue#16.1 — operator-locked 30/45/45/50 quartet.
    assert docker == 30
    assert systemctl == 45
    assert systemd == 45
    assert webctl == 50


def test_mapping_timing_partial_section_uses_defaults_for_missing(
    tmp_path: Path,
) -> None:
    """If only one key is set, the others default to the schema."""
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\nmapping_docker_stop_grace_s = 35\n")
    section = wt.read_webctl_section(p, env={})
    assert section.mapping_docker_stop_grace_s == 35
    assert section.mapping_systemctl_subprocess_timeout_s == 45  # default
    assert section.mapping_systemd_stop_timeout_s == 45  # default
    assert section.mapping_webctl_stop_timeout_s == 50  # default


def test_mapping_timing_partial_violating_ordering_still_rejected(
    tmp_path: Path,
) -> None:
    """If a partial override breaks the ladder against defaults
    (e.g. docker=46 against systemd_default=45), reject — the
    invariant must hold against the EFFECTIVE values, not just the
    operator-supplied ones."""
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\nmapping_docker_stop_grace_s = 46\n")
    with pytest.raises(wt.WebctlTomlError):
        wt.read_webctl_section(p, env={})
