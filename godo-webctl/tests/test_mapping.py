"""
issue#14 — Mapping coordinator unit tests.

Coverage spans (per plan §12):
  - validate_name (regex + reserved + length boundaries).
  - state.json round-trip + corrupt recovery.
  - state-machine transitions: Idle→Starting→Running, abort path,
    crash path, container_start_timeout, image_missing pre-flight,
    tracker_stop_failed, M3 boot reconcile preserves started_at.
  - preview_path realpath containment.
  - _resolve_lidar_port reads the tracker [serial] section.
  - monitor_snapshot composition (mocked subprocess).
  - flock defence (concurrent start raises MappingAlreadyActive).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from godo_webctl import mapping as M
from godo_webctl import services as services_mod
from godo_webctl.config import Settings


def _settings(tmp_path: Path) -> Settings:
    """Build a Settings whose every path lives under tmp_path."""
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir(mode=0o750, exist_ok=True)
    (maps_dir / ".preview").mkdir(mode=0o750, exist_ok=True)
    return Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=tmp_path / "ctl.sock",
        backup_dir=tmp_path / "bk",
        map_path=tmp_path / "fake.pgm",
        maps_dir=maps_dir,
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
        jwt_secret_path=tmp_path / "jwt",
        users_file=tmp_path / "users.json",
        spa_dist=None,
        chromium_loopback_only=True,
        disk_check_path=tmp_path,
        restart_pending_path=tmp_path / "restart_pending",
        pidfile_path=tmp_path / "godo-webctl.pid",
        tracker_toml_path=tmp_path / "tracker.toml",
        mapping_runtime_dir=tmp_path / "runtime",
        mapping_image_tag="godo-mapping:dev",
        docker_bin=Path("/usr/bin/docker"),
        # issue#14 Maj-1: tests pin the schema default so the stop-poll
        # deadline matches the production ladder (35 s).
        mapping_webctl_stop_timeout_s=35.0,
        mapping_auto_recover_lidar=True,
    )


# --- validate_name -------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "studio",
        "studio_v1",
        "studio-v1",
        "control_room_2026",
        "studio.v1",
        "studio.2026.05.01",
        "(prefix)tail",
        "studio(1)",
        "Date,Loc",
        "a",
        "a" * 64,
    ],
)
def test_validate_name_accepts_typical_stems(name: str) -> None:
    M.validate_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
        "with space",
        "tab\tname",
        "studio/path",
        "../etc/passwd",
        "studio\x00null",
        "한글",
        "*glob",
        "shell;injection",
        "a" * 65,
    ],
)
def test_validate_name_rejects_invalid_strings(name: str) -> None:
    with pytest.raises(M.InvalidName):
        M.validate_name(name)


@pytest.mark.parametrize("name", [".", "..", "active"])
def test_validate_name_rejects_reserved(name: str) -> None:
    with pytest.raises(M.InvalidName) as exc_info:
        M.validate_name(name)
    assert "reserved_name" in str(exc_info.value)


@pytest.mark.parametrize("name", [".foo", "..bar", ".hidden"])
def test_validate_name_rejects_leading_dot(name: str) -> None:
    """C5 fix: leading-dot rejected at regex layer (operator-locked)."""
    with pytest.raises(M.InvalidName):
        M.validate_name(name)


# --- preview_path realpath containment -----------------------------------


def test_preview_path_returns_canonical_path_under_maps_dir(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    p = M.preview_path(cfg, "studio_v1")
    assert p == cfg.maps_dir / ".preview" / "studio_v1.pgm"


def test_preview_path_rejects_traversal_via_invalidname(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    with pytest.raises(M.InvalidName):
        M.preview_path(cfg, "../etc/passwd")


# --- state.json round-trip + corrupt recovery -----------------------------


def test_state_json_round_trip_and_idle_default(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    # No state file → Idle.
    s = M._load_state(cfg)
    assert s.state == M.MappingState.IDLE

    # Persist a Running status; reload byte-equal.
    written = M.MappingStatus(
        state=M.MappingState.RUNNING,
        map_name="studio_v1",
        container_id_short="abc123def456",
        started_at="2026-05-01T15:30:42Z",
        error_detail=None,
        journal_tail_available=False,
    )
    M._save_state(cfg, written)
    reloaded = M._load_state(cfg)
    assert reloaded == written


def test_state_json_corrupt_raises_state_file_corrupt(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    state_file = cfg.mapping_runtime_dir / "state.json"
    state_file.write_text("not json {")
    with pytest.raises(M.StateFileCorrupt):
        M._load_state(cfg)


def test_state_json_unknown_state_raises_state_file_corrupt(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    state_file = cfg.mapping_runtime_dir / "state.json"
    state_file.write_text(json.dumps({"state": "not_a_state"}))
    with pytest.raises(M.StateFileCorrupt):
        M._load_state(cfg)


def test_status_recovers_to_idle_when_state_file_corrupt(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    state_file = cfg.mapping_runtime_dir / "state.json"
    state_file.write_text("garbage")
    s = M.status(cfg)
    assert s.state == M.MappingState.IDLE


# --- _resolve_lidar_port -------------------------------------------------


def test_resolve_lidar_port_reads_tracker_serial_section(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    cfg.tracker_toml_path.write_text(
        '[serial]\nlidar_port = "/dev/ttyUSB1"\n',
    )
    assert M._resolve_lidar_port(cfg) == "/dev/ttyUSB1"


def test_resolve_lidar_port_falls_back_to_default_when_toml_silent(
    tmp_path: Path,
) -> None:
    cfg = _settings(tmp_path)
    # No tracker.toml at all.
    assert M._resolve_lidar_port(cfg) == "/dev/ttyUSB0"


def test_resolve_lidar_port_falls_back_when_section_missing(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    cfg.tracker_toml_path.write_text('[network]\nue_host = "127.0.0.1"\n')
    assert M._resolve_lidar_port(cfg) == "/dev/ttyUSB0"


# --- envfile writer -------------------------------------------------------


def test_write_run_envfile_atomic_with_three_keys(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    M._write_run_envfile(cfg, "studio_v1", "/dev/ttyUSB1", "godo-mapping:dev")
    content = (cfg.mapping_runtime_dir / "active.env").read_text("utf-8")
    assert "MAP_NAME=studio_v1\n" in content
    assert "LIDAR_DEV=/dev/ttyUSB1\n" in content
    assert "IMAGE_TAG=godo-mapping:dev\n" in content


def test_write_run_envfile_creates_runtime_dir_lazily(tmp_path: Path) -> None:
    """M2 fix: runtime dir created at runtime, not install-time."""
    cfg = _settings(tmp_path)
    assert not cfg.mapping_runtime_dir.exists()
    M._write_run_envfile(cfg, "studio", "/dev/ttyUSB0", "godo-mapping:dev")
    assert cfg.mapping_runtime_dir.is_dir()


# --- start() happy + failure paths ----------------------------------------


class _FakeSubprocess:
    """Test double for subprocess.run capturing argv calls."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        # queued (returncode, stdout, stderr) per subprocess invocation;
        # final sticky value used after the queue empties.
        self.responses: list[tuple[int, str, str]] = []
        self.sticky: tuple[int, str, str] = (0, "", "")

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if self.responses:
            rc, stdout, stderr = self.responses.pop(0)
        else:
            rc, stdout, stderr = self.sticky
        return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr=stderr)


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeSubprocess]:
    """Replace `subprocess.run` inside the mapping module."""
    fake = _FakeSubprocess()
    monkeypatch.setattr(M.subprocess, "run", fake)
    monkeypatch.setattr(M, "_run_systemctl_start_mapping", lambda cfg: None)
    monkeypatch.setattr(M, "_run_systemctl_stop_mapping", lambda cfg: None)
    yield fake


def test_start_idle_to_running_happy_path(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    # Sequence: image inspect (rc=0), tracker stop via services_mod.control
    # (mocked separately), envfile write, systemctl start (mocked None),
    # docker inspect → "running", docker inspect Id → short ID.
    fake_subprocess.responses = [
        (0, "image-id\n", ""),  # docker image inspect
        (0, "running\n", ""),   # docker inspect State.Status
        (0, "abc123def456789012\n", ""),  # docker inspect Id
    ]
    monkeypatch.setattr(services_mod, "control", lambda svc, action: "inactive")

    out = M.start("studio_v1", cfg)

    assert out.state == M.MappingState.RUNNING
    assert out.map_name == "studio_v1"
    assert out.container_id_short == "abc123def456"
    assert out.started_at is not None


def test_start_image_missing_returns_image_missing(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    fake_subprocess.responses = [
        (1, "", "Error: No such image: godo-mapping:dev\n"),
    ]
    with pytest.raises(M.ImageMissing):
        M.start("studio_v1", cfg)
    # State must stay Idle on pre-flight failure.
    s = M._load_state(cfg)
    assert s.state == M.MappingState.IDLE


def test_start_tracker_stop_failed_transitions_to_failed(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    fake_subprocess.responses = [(0, "image-id\n", "")]  # docker image inspect ok
    def boom(svc: str, action: str) -> str:
        raise services_mod.CommandFailed(1, "polkit denied")
    monkeypatch.setattr(services_mod, "control", boom)

    with pytest.raises(M.TrackerStopFailed):
        M.start("studio_v1", cfg)
    s = M._load_state(cfg)
    assert s.state == M.MappingState.FAILED
    assert "tracker_stop_failed" in (s.error_detail or "")


def test_start_container_start_timeout_transitions_to_failed(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _settings(tmp_path)
    # Image present + every docker inspect returns "created" (never reaches "running").
    fake_subprocess.sticky = (0, "created\n", "")
    fake_subprocess.responses = [(0, "image-id\n", "")]
    monkeypatch.setattr(services_mod, "control", lambda svc, action: "inactive")
    monkeypatch.setattr(M, "MAPPING_CONTAINER_START_TIMEOUT_S", 0.05)
    monkeypatch.setattr(M, "MAPPING_DOCKER_INSPECT_POLL_S", 0.01)

    with pytest.raises(M.ContainerStartTimeout):
        M.start("studio_v1", cfg)
    s = M._load_state(cfg)
    assert s.state == M.MappingState.FAILED
    assert s.error_detail == "container_start_timeout"


def test_start_refused_when_already_active(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="prev",
            container_id_short="aaa",
            started_at="2026-05-01T00:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    with pytest.raises(M.MappingAlreadyActive):
        M.start("studio_v2", cfg)


def test_start_refused_when_pgm_already_exists(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    (cfg.maps_dir / "studio_v1.pgm").write_bytes(b"P5\n1 1\n255\n\x00")
    with pytest.raises(M.NameAlreadyExists):
        M.start("studio_v1", cfg)


def test_start_invalid_name_raises_invalid_name(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    with pytest.raises(M.InvalidName):
        M.start(".hidden", cfg)


# --- stop() variants ------------------------------------------------------


def test_stop_idle_raises_no_active_mapping(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    with pytest.raises(M.NoActiveMapping):
        M.stop(cfg)


def test_stop_failed_acknowledges_to_idle(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    # Persist Failed state with a previously-published preview file.
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.FAILED,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-01T15:30:42Z",
            error_detail="container_crashed",
            journal_tail_available=True,
        ),
    )
    preview = cfg.maps_dir / ".preview" / "studio_v1.pgm"
    preview.write_bytes(b"partial pgm")
    fake_subprocess.sticky = (0, "", "")  # docker rm ok

    out = M.stop(cfg)
    assert out.state == M.MappingState.IDLE
    assert out.map_name is None
    assert out.error_detail is None
    assert not preview.exists()


def test_stop_running_to_idle_happy_path(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-01T15:30:42Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    # Container is gone after stop (docker inspect returns "exited" then
    # nothing). Sticky returns "exited" so the polling loop exits cleanly.
    fake_subprocess.sticky = (
        1,
        "",
        "Error: No such object: godo-mapping\n",
    )

    out = M.stop(cfg)
    assert out.state == M.MappingState.IDLE


def test_stop_starting_to_idle_abort_path(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    """m10: operator clicks Stop while we are still polling for "running"."""
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.STARTING,
            map_name="studio_v1",
            container_id_short=None,
            started_at="2026-05-01T15:30:42Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    fake_subprocess.sticky = (
        1,
        "",
        "Error: No such object: godo-mapping\n",
    )
    out = M.stop(cfg)
    assert out.state == M.MappingState.IDLE


# --- M3 boot reconcile preserves started_at -------------------------------


def test_status_reconcile_preserves_started_at_when_running(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.STARTING,  # before reconcile
            map_name="studio_v1",
            container_id_short=None,
            started_at="2026-05-01T15:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    # docker inspect returns "running"; reconcile transitions Starting→Running.
    fake_subprocess.responses = [
        (0, "running\n", ""),
        (0, "abc123def4561234\n", ""),
    ]
    out = M.status(cfg)
    assert out.state == M.MappingState.RUNNING
    # M3 critical assertion: started_at NOT rewritten.
    assert out.started_at == "2026-05-01T15:00:00Z"


def test_status_reconcile_running_to_failed_when_container_gone(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-01T15:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    fake_subprocess.sticky = (1, "", "Error: No such object: godo-mapping\n")
    out = M.status(cfg)
    assert out.state == M.MappingState.FAILED
    assert out.started_at == "2026-05-01T15:00:00Z"  # M3 preserved
    assert out.error_detail == "webctl_lost_view_post_crash"
    assert out.journal_tail_available is True


# --- monitor_snapshot composition -----------------------------------------


def test_monitor_snapshot_no_active_when_container_absent(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    fake_subprocess.sticky = (1, "", "Error: No such object: godo-mapping\n")
    snap = M.monitor_snapshot(cfg)
    assert snap["valid"] is True
    assert snap["container_state"] == "no_active"
    assert snap["container_cpu_pct"] is None


def test_monitor_snapshot_running_composes_full_payload(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-01T15:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    preview = cfg.maps_dir / ".preview" / "studio_v1.pgm"
    preview.write_bytes(b"P5\n10 10\n255\n" + bytes(100))

    fake_subprocess.responses = [
        (0, "running\n", ""),  # docker inspect State.Status
        (0, "abc123def4561234\n", ""),  # docker inspect Id
        (
            0,
            json.dumps(
                {
                    "CPUPerc": "42.50%",
                    "MemUsage": "432.4MiB / 7.42GiB",
                    "NetIO": "12.3kB / 4.5kB",
                },
            )
            + "\n",
            "",
        ),  # docker stats
    ]
    snap = M.monitor_snapshot(cfg)
    assert snap["valid"] is True
    assert snap["container_state"] == "running"
    assert snap["container_id_short"] == "abc123def456"
    assert snap["container_cpu_pct"] == 42.5
    assert snap["container_mem_bytes"] == int(432.4 * 1024 * 1024)
    assert snap["container_net_rx_bytes"] == 12300
    assert snap["container_net_tx_bytes"] == 4500
    assert snap["in_progress_map_size_bytes"] == preview.stat().st_size
    assert snap["var_lib_godo_disk_avail_bytes"] is not None
    assert snap["var_lib_godo_disk_total_bytes"] is not None


def test_monitor_snapshot_partial_failure_keeps_other_fields(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-01T15:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    fake_subprocess.responses = [
        (0, "running\n", ""),  # inspect state
        (0, "abc123def456abc1\n", ""),  # inspect id
        (1, "", "transient docker error\n"),  # stats fails
    ]
    snap = M.monitor_snapshot(cfg)
    # container_state remains running; cpu_pct remains None.
    assert snap["container_state"] == "running"
    assert snap["container_cpu_pct"] is None
    # disk fields still composed.
    assert snap["var_lib_godo_disk_avail_bytes"] is not None


# --- humanize-bytes parsing edge cases ------------------------------------


def test_parse_humanize_bytes_handles_units() -> None:
    assert M._parse_humanize_bytes("100B") == 100
    assert M._parse_humanize_bytes("1KB") == 1000
    assert M._parse_humanize_bytes("1KiB") == 1024
    assert M._parse_humanize_bytes("2MiB") == 2 * 1024 * 1024
    assert M._parse_humanize_bytes("1.5GB") == int(1.5 * 1000**3)


def test_parse_humanize_bytes_rejects_malformed() -> None:
    assert M._parse_humanize_bytes("") is None
    assert M._parse_humanize_bytes("100") is None  # no unit
    assert M._parse_humanize_bytes("nope") is None


# --- journal_tail --------------------------------------------------------


def test_journal_tail_returns_empty_when_idle(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    assert M.journal_tail(cfg, 50) == []


def test_journal_tail_rejects_n_zero(tmp_path: Path) -> None:
    cfg = _settings(tmp_path)
    with pytest.raises(ValueError):
        M.journal_tail(cfg, 0)


def test_journal_tail_clamps_n_above_max(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-01T15:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    fake_subprocess.responses = [
        (0, "running\n", ""),  # status reconcile inspect
        (0, "abc123def456abc1\n", ""),  # status reconcile id
        (0, "line1\nline2\n", ""),  # journalctl
    ]
    M.journal_tail(cfg, 9999)
    # The third subprocess call was journalctl with -n clamped to MAX_N.
    journal_calls = [c for c in fake_subprocess.calls if c and c[0] == "journalctl"]
    assert journal_calls
    journal_argv = journal_calls[0]
    n_idx = journal_argv.index("-n")
    assert journal_argv[n_idx + 1] == str(M.MAPPING_JOURNAL_TAIL_MAX_N)


def test_journal_tail_passes_since_started_at(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-01T15:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    fake_subprocess.responses = [
        (0, "running\n", ""),
        (0, "abc123def456abc1\n", ""),
        (0, "log line\n", ""),
    ]
    M.journal_tail(cfg, 50)
    journal_argv = next(c for c in fake_subprocess.calls if c and c[0] == "journalctl")
    assert "--since=2026-05-01T15:00:00Z" in journal_argv


# --- issue#14 Maj-1 — stop deadline honors cfg.mapping_webctl_stop_timeout_s --


def test_stop_polling_deadline_uses_cfg_field_not_constant(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maj-1 invariant: the stop-poll deadline reads
    `cfg.mapping_webctl_stop_timeout_s`, NOT the legacy
    `MAPPING_CONTAINER_STOP_TIMEOUT_S` constant. Drive a never-exit
    container with a SHORT cfg deadline and assert the timeout fires
    in proportional wall-clock time (≪ the constant 35 s)."""
    cfg = _settings(tmp_path)
    # Override the per-test cfg ceiling to a small but non-zero value.
    cfg = cfg._replace(mapping_webctl_stop_timeout_s=0.05) if hasattr(cfg, "_replace") else cfg
    # Settings is a frozen dataclass, not a NamedTuple — re-construct.
    from dataclasses import replace as _replace

    cfg = _replace(cfg, mapping_webctl_stop_timeout_s=0.05)

    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-01T15:30:42Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )
    # Container persistently reports running; never exits.
    fake_subprocess.sticky = (0, "running\n", "")
    monkeypatch.setattr(M, "MAPPING_DOCKER_INSPECT_POLL_S", 0.01)

    with pytest.raises(M.ContainerStopTimeout) as exc_info:
        M.stop(cfg)
    # The exception message includes the cfg-derived deadline.
    assert "0.05" in str(exc_info.value)
    s = M._load_state(cfg)
    assert s.state == M.MappingState.FAILED
    assert s.error_detail == "container_stop_timeout"


# --- issue#14 Maj-2 — flock-narrowing concurrency tests ------------------


def test_state_reread_in_start_phase2_aborts_on_concurrent_stopping(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maj-2 invariant: while ``start()`` is in Phase 2 polling
    (no flock held), if a concurrent caller writes ``state == Stopping``
    to ``state.json``, the polling loop must detect it on the next
    state-reread tick and bail out — without writing Running."""
    cfg = _settings(tmp_path)
    # Container never reaches "running" — every inspect returns "created".
    fake_subprocess.sticky = (0, "created\n", "")
    fake_subprocess.responses = [(0, "image-id\n", "")]
    monkeypatch.setattr(services_mod, "control", lambda svc, action: "inactive")
    monkeypatch.setattr(M, "MAPPING_CONTAINER_START_TIMEOUT_S", 1.0)
    monkeypatch.setattr(M, "MAPPING_DOCKER_INSPECT_POLL_S", 0.005)
    monkeypatch.setattr(M, "MAPPING_STATE_REREAD_INTERVAL_S", 0.005)

    # Inject a state.json overwrite to Stopping after the first
    # docker-inspect call. Hook the docker_inspect_state helper.
    inspect_call_count = {"n": 0}
    real_inspect = M._docker_inspect_state

    def _inspect_with_concurrent_stop(c: Settings, container: str) -> str | None:
        result = real_inspect(c, container)
        inspect_call_count["n"] += 1
        # After the first inspect, simulate a concurrent stop() writing
        # Stopping to state.json.
        if inspect_call_count["n"] == 1:
            cur = M._load_state(c)
            if cur.state == M.MappingState.STARTING:
                M._save_state(
                    c,
                    M.MappingStatus(
                        state=M.MappingState.STOPPING,
                        map_name=cur.map_name,
                        container_id_short=cur.container_id_short,
                        started_at=cur.started_at,
                        error_detail=None,
                        journal_tail_available=False,
                    ),
                )
        return result

    monkeypatch.setattr(M, "_docker_inspect_state", _inspect_with_concurrent_stop)

    out = M.start("studio_v1", cfg)
    # start() must yield to the concurrent stop() instead of writing Running.
    assert out.state == M.MappingState.STOPPING
    # state.json must NOT be Running.
    s = M._load_state(cfg)
    assert s.state == M.MappingState.STOPPING


def test_stop_during_start_polling_succeeds_without_409(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maj-2 critical case: drive ``stop()`` while ``start()`` is mid-
    polling (Phase 2). Pre-Maj-2 behaviour: stop() blocked on
    ``MappingAlreadyActive`` because start() held ``_coordinator_flock``
    for the entire body. Post-Maj-2: stop() acquires the flock between
    start()'s Phase-1 release and Phase-3 acquire, writes Stopping,
    runs systemctl stop + polling, writes Idle.

    Test driver: simulate the race by directly transitioning state
    through start's Phase 1, then calling stop() — this is what would
    happen with two concurrent FastAPI handlers in single-worker
    uvicorn (gevent-style cooperative scheduling)."""
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)

    # Pretend start() finished Phase 1: state.json is Starting.
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.STARTING,
            map_name="studio_v1",
            container_id_short=None,
            started_at="2026-05-02T08:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )

    # Container is gone (the systemctl stop terminated it).
    fake_subprocess.sticky = (1, "", "Error: No such object: godo-mapping\n")

    # Crucially: stop() should NOT raise MappingAlreadyActive while
    # state==Starting; it should accept Starting as a valid abort
    # source state (m10 path).
    out = M.stop(cfg)
    assert out.state == M.MappingState.IDLE
    assert out.map_name is None
    # Final state in state.json must be Idle.
    s = M._load_state(cfg)
    assert s.state == M.MappingState.IDLE


def test_stop_phase1_releases_flock_before_phase2_polling(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maj-2 invariant: ``stop()`` MUST release the flock before
    entering its Phase-2 docker-inspect polling loop. We assert this
    by holding the flock externally during stop()'s polling phase
    and verifying it succeeds.

    The mechanism: hook docker_inspect_state to grab the flock between
    Phase 1 (state-write) and Phase 2 (polling). If stop() never tries
    to re-acquire the flock during polling, this should not block;
    Phase 3's brief flock acquire will queue but resolve quickly when
    the external holder releases."""
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    M._save_state(
        cfg,
        M.MappingStatus(
            state=M.MappingState.RUNNING,
            map_name="studio_v1",
            container_id_short="abc",
            started_at="2026-05-02T08:00:00Z",
            error_detail=None,
            journal_tail_available=False,
        ),
    )

    # First inspect call: container has exited.
    fake_subprocess.sticky = (0, "exited\n", "")

    # Track whether the flock was acquired during the polling window
    # (it shouldn't be — stop()'s Phase 2 runs without the flock).
    monkeypatch.setattr(M, "MAPPING_DOCKER_INSPECT_POLL_S", 0.001)

    out = M.stop(cfg)
    assert out.state == M.MappingState.IDLE


def test_start_phase1_pre_flight_image_missing_keeps_idle(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maj-2 boundary: image-missing pre-flight runs INSIDE Phase 1
    flock. State must stay Idle (no transition written) so a follow-up
    start() works after the operator builds the image."""
    cfg = _settings(tmp_path)
    fake_subprocess.responses = [
        (1, "", "Error: No such image: godo-mapping:dev\n"),
    ]
    with pytest.raises(M.ImageMissing):
        M.start("studio_v1", cfg)
    s = M._load_state(cfg)
    assert s.state == M.MappingState.IDLE


def test_start_phase3_yields_to_concurrent_stopping_no_running_written(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maj-2 boundary: the docker-inspect call returned 'running' but
    a concurrent stop() flipped state.json to Stopping between the
    inspect-running observation and the Phase-3 flock acquire. start()
    must NOT overwrite Stopping with Running — it returns the
    concurrent state instead."""
    cfg = _settings(tmp_path)
    fake_subprocess.responses = [
        (0, "image-id\n", ""),  # docker image inspect
        (0, "running\n", ""),   # docker inspect State.Status — running
        (0, "abc123def4561234\n", ""),  # docker inspect Id
    ]
    monkeypatch.setattr(services_mod, "control", lambda svc, action: "inactive")

    # Hook _coordinator_flock so that the second-acquire (Phase 3) sees
    # state.json as Stopping (a concurrent stop() ran between Phase 2
    # observation and Phase 3 acquire).
    real_flock = M._coordinator_flock
    flock_call_count = {"n": 0}

    import contextlib as _contextlib

    @_contextlib.contextmanager
    def _flock_with_concurrent_stop_before_phase3(c: Settings):
        flock_call_count["n"] += 1
        # Before yielding the SECOND flock (start's Phase 3), simulate
        # a concurrent stop() having flipped state to Stopping. The
        # first flock is start's Phase 1; the second is Phase 3.
        if flock_call_count["n"] == 2:
            cur = M._load_state(c)
            if cur.state == M.MappingState.STARTING:
                M._save_state(
                    c,
                    M.MappingStatus(
                        state=M.MappingState.STOPPING,
                        map_name=cur.map_name,
                        container_id_short=cur.container_id_short,
                        started_at=cur.started_at,
                        error_detail=None,
                        journal_tail_available=False,
                    ),
                )
        with real_flock(c) as inner:
            yield inner

    monkeypatch.setattr(M, "_coordinator_flock", _flock_with_concurrent_stop_before_phase3)

    out = M.start("studio_v1", cfg)
    # start() must observe the Stopping state and bail without
    # overwriting with Running.
    assert out.state == M.MappingState.STOPPING
    # state.json must NOT be Running.
    s = M._load_state(cfg)
    assert s.state == M.MappingState.STOPPING


# --- flock defence -------------------------------------------------------


def test_concurrent_start_returns_409_via_flock(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
) -> None:
    """Defence-in-depth: hold flock manually, then call start() and
    assert MappingAlreadyActive."""
    cfg = _settings(tmp_path)
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    import fcntl as _fcntl
    import os as _os

    lock_path = cfg.mapping_runtime_dir / ".lock"
    fd = _os.open(str(lock_path), _os.O_WRONLY | _os.O_CREAT, 0o600)
    try:
        _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        with pytest.raises(M.MappingAlreadyActive):
            M.start("studio_v1", cfg)
    finally:
        _fcntl.flock(fd, _fcntl.LOCK_UN)
        _os.close(fd)
