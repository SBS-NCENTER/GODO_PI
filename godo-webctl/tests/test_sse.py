"""
T3: SSE generators driven by virtual sleep.

Both generators take an injected `sleep` callable so we can record the
sequence of sleep durations and assert the cadence WITHOUT any
wall-clock waits.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest import mock

import pytest

from godo_webctl import sse, uds_client
from godo_webctl.config import Settings
from godo_webctl.constants import (
    SSE_HEARTBEAT_S,
    SSE_SERVICES_TICK_S,
    SSE_TICK_S,
)


def _settings(tracker_toml_path: Path | None = None) -> Settings:
    """Test fixture Settings.

    `tracker_toml_path` defaults to a non-existent path so
    ``webctl_toml.read_webctl_section`` returns the schema defaults
    (30 Hz pose, 30 Hz scan) without requiring a fixture file. Tests
    that pin a specific cadence pass an explicit path.
    """
    return Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=Path("/tmp/x"),
        backup_dir=Path("/tmp/bk"),
        map_path=Path("/tmp/m.pgm"),
        maps_dir=Path("/tmp/maps"),
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
        jwt_secret_path=Path("/tmp/j"),
        users_file=Path("/tmp/u.json"),
        spa_dist=None,
        chromium_loopback_only=True,
        disk_check_path=Path("/"),
        restart_pending_path=Path("/tmp/rp"),
        pidfile_path=Path("/tmp/pid"),
        tracker_toml_path=tracker_toml_path
        if tracker_toml_path is not None
        else Path("/tmp/no_such_tracker.toml"),
        mapping_runtime_dir=Path("/tmp/mapping_rt"),
        mapping_image_tag="godo-mapping:dev",
        docker_bin=Path("/usr/bin/docker"),
        mapping_webctl_stop_timeout_s=35.0,
        mapping_systemctl_subprocess_timeout_s=20.0,
        mapping_auto_recover_lidar=True,
    )


class RecordingSleep:
    """Async sleep substitute that records call durations and returns
    immediately. Tests poll `.calls` to assert cadence sequence."""

    def __init__(self, *, max_calls: int) -> None:
        self.calls: list[float] = []
        self._max = max_calls

    async def __call__(self, duration: float) -> None:
        self.calls.append(duration)
        if len(self.calls) >= self._max:
            raise asyncio.CancelledError("recorder budget exhausted")


async def _drain(stream: AsyncIterator[bytes]) -> list[bytes]:
    out: list[bytes] = []
    try:
        async for chunk in stream:
            out.append(chunk)
    except asyncio.CancelledError:
        pass
    return out


# ---- last_pose_stream ---------------------------------------------------


_DEFAULT_POSE_TICK_S = 1.0 / 30  # webctl_toml.WEBCTL_POSE_STREAM_HZ_DEFAULT
_DEFAULT_SCAN_TICK_S = 1.0 / 30  # webctl_toml.WEBCTL_SCAN_STREAM_HZ_DEFAULT


def _canned_pose() -> dict[str, object]:
    return {
        "ok": True,
        "valid": 1,
        "x_m": 0.0,
        "y_m": 0.0,
        "yaw_deg": 0.0,
        "xy_std_m": 0.0,
        "yaw_std_deg": 0.0,
        "iterations": 0,
        "converged": 0,
        "forced": 0,
        "published_mono_ns": 0,
    }


def _canned_output() -> dict[str, object]:
    """issue#27 — minimal valid LastOutputFrame-shape dict for SSE tests."""
    return {
        "ok": True,
        "valid": 1,
        "x_m": 0.0,
        "y_m": 0.0,
        "z_m": 0.0,
        "pan_deg": 0.0,
        "tilt_deg": 0.0,
        "roll_deg": 0.0,
        "zoom": 0.0,
        "focus": 0.0,
        "published_mono_ns": 0,
    }


async def test_last_pose_stream_emits_default_30hz_sleep_sequence() -> None:
    """Sleep duration sequence is `[1/30, 1/30, ...]` → 30 Hz cadence
    when no tracker.toml override is present (issue#12 default).
    No wall-clock involved."""
    sleep = RecordingSleep(max_calls=3)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose()
    fake_client.get_last_output.return_value = _canned_output()
    chunks = await _drain(sse.last_pose_stream(fake_client, _settings(), sleep=sleep))
    # 3 ticks attempted before recorder cancels the loop.
    assert sleep.calls == [
        _DEFAULT_POSE_TICK_S,
        _DEFAULT_POSE_TICK_S,
        _DEFAULT_POSE_TICK_S,
    ]
    # At least the first tick produced a data frame.
    assert any(c.startswith(b"data:") for c in chunks)


async def test_last_pose_stream_emits_pose_and_output_wrap() -> None:
    """issue#27 wrap-and-version: each frame is
    {"pose": {...}, "output": {...}}."""
    import json as _json
    sleep = RecordingSleep(max_calls=1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose()
    fake_client.get_last_output.return_value = _canned_output()
    chunks = await _drain(sse.last_pose_stream(fake_client, _settings(), sleep=sleep))
    data_frames = [c for c in chunks if c.startswith(b"data:")]
    assert len(data_frames) >= 1
    body = data_frames[0].removeprefix(b"data: ").rstrip(b"\n")
    obj = _json.loads(body)
    assert "pose" in obj
    assert "output" in obj
    assert obj["pose"]["valid"] == 1
    assert obj["output"]["valid"] == 1


async def test_last_pose_stream_pose_unavailable_emits_sentinel() -> None:
    """issue#27 degraded-graceful: get_last_pose fails, get_last_output
    succeeds → frame still emitted with pose sentinel + output payload.
    SPA renders the pose card as 'unavailable' but keeps the output card."""
    import json as _json
    sleep = RecordingSleep(max_calls=1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.side_effect = uds_client.UdsUnreachable("down")
    fake_client.get_last_output.return_value = _canned_output()
    chunks = await _drain(sse.last_pose_stream(fake_client, _settings(), sleep=sleep))
    data_frames = [c for c in chunks if c.startswith(b"data:")]
    assert len(data_frames) >= 1
    body = data_frames[0].removeprefix(b"data: ").rstrip(b"\n")
    obj = _json.loads(body)
    # Pose sentinel: valid=0 + err=<exception class name>.
    assert obj["pose"]["valid"] == 0
    assert obj["pose"]["err"] == "UdsUnreachable"
    # Output is real.
    assert obj["output"]["valid"] == 1


async def test_last_pose_stream_output_unavailable_emits_sentinel() -> None:
    """Mirror: get_last_output fails, get_last_pose succeeds → frame
    emitted with output sentinel."""
    import json as _json
    sleep = RecordingSleep(max_calls=1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose()
    fake_client.get_last_output.side_effect = uds_client.UdsUnreachable("down")
    chunks = await _drain(sse.last_pose_stream(fake_client, _settings(), sleep=sleep))
    data_frames = [c for c in chunks if c.startswith(b"data:")]
    assert len(data_frames) >= 1
    body = data_frames[0].removeprefix(b"data: ").rstrip(b"\n")
    obj = _json.loads(body)
    assert obj["pose"]["valid"] == 1
    assert obj["output"]["valid"] == 0
    assert obj["output"]["err"] == "UdsUnreachable"


async def test_last_pose_stream_emits_keepalive_after_heartbeat_window() -> None:
    """Keepalive comment line must appear once virtual elapsed time
    crosses SSE_HEARTBEAT_S."""
    n_ticks_to_keepalive = int(SSE_HEARTBEAT_S / _DEFAULT_POSE_TICK_S) + 1
    sleep = RecordingSleep(max_calls=n_ticks_to_keepalive + 1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose()
    fake_client.get_last_output.return_value = _canned_output()
    chunks = await _drain(sse.last_pose_stream(fake_client, _settings(), sleep=sleep))
    assert any(c == b": keepalive\n\n" for c in chunks)


async def test_last_pose_stream_cancellation_propagates() -> None:
    """Cancelling the injected sleep terminates the loop within one tick."""

    async def cancel_immediately(_d: float) -> None:
        raise asyncio.CancelledError()

    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose()
    fake_client.get_last_output.return_value = _canned_output()
    with pytest.raises(asyncio.CancelledError):
        async for _ in sse.last_pose_stream(fake_client, _settings(), sleep=cancel_immediately):
            pass


# ---- services_stream ----------------------------------------------------


async def test_services_stream_emits_1hz_sleep_sequence() -> None:
    sleep = RecordingSleep(max_calls=3)
    with mock.patch("godo_webctl.sse.services_mod.list_active") as m:
        m.return_value = [{"name": "godo-tracker", "active": "active"}]
        chunks = await _drain(sse.services_stream(_settings(), sleep=sleep))
    assert sleep.calls == [SSE_SERVICES_TICK_S, SSE_SERVICES_TICK_S, SSE_SERVICES_TICK_S]
    assert any(c.startswith(b"data:") and b"services" in c for c in chunks)


async def test_services_stream_keepalive_after_heartbeat_window() -> None:
    n_ticks = int(SSE_HEARTBEAT_S / SSE_SERVICES_TICK_S) + 1
    sleep = RecordingSleep(max_calls=n_ticks + 1)
    with mock.patch("godo_webctl.sse.services_mod.list_active") as m:
        m.return_value = []
        chunks = await _drain(sse.services_stream(_settings(), sleep=sleep))
    assert any(c == b": keepalive\n\n" for c in chunks)


# ---- last_scan_stream (Track D) -----------------------------------------


def _canned_scan() -> dict[str, object]:
    """Minimal valid LastScan-shape dict the SSE test pumps through."""
    return {
        "ok": True,
        "valid": 1,
        "forced": 0,
        "pose_valid": 1,
        "iterations": 7,
        "published_mono_ns": 1_000_000_000,
        "pose_x_m": 1.5,
        "pose_y_m": 2.0,
        "pose_yaw_deg": 45.0,
        "n": 2,
        "angles_deg": [0.0, 0.5],
        "ranges_m": [1.0, 1.5],
    }


async def test_last_scan_stream_emits_default_30hz_sleep_sequence() -> None:
    """Sleep sequence is `[1/30, 1/30, 1/30]` → 30 Hz cadence by
    construction (issue#12 default)."""
    sleep = RecordingSleep(max_calls=3)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_scan.return_value = _canned_scan()
    chunks = await _drain(sse.last_scan_stream(fake_client, _settings(), sleep=sleep))
    assert sleep.calls == [
        _DEFAULT_SCAN_TICK_S,
        _DEFAULT_SCAN_TICK_S,
        _DEFAULT_SCAN_TICK_S,
    ]
    assert any(c.startswith(b"data:") for c in chunks)


async def test_last_scan_stream_skips_frame_on_uds_error() -> None:
    """Tracker-down: get_last_scan raises → no frame emitted that tick,
    generator stays alive."""
    sleep = RecordingSleep(max_calls=2)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_scan.side_effect = uds_client.UdsUnreachable("down")
    chunks = await _drain(sse.last_scan_stream(fake_client, _settings(), sleep=sleep))
    assert sleep.calls == [_DEFAULT_SCAN_TICK_S, _DEFAULT_SCAN_TICK_S]
    assert all(not c.startswith(b"data:") for c in chunks)


async def test_last_scan_stream_emits_keepalive_after_heartbeat_window() -> None:
    """Keepalive comment line must appear once virtual elapsed time
    crosses SSE_HEARTBEAT_S."""
    n_ticks_to_keepalive = int(SSE_HEARTBEAT_S / _DEFAULT_SCAN_TICK_S) + 1
    sleep = RecordingSleep(max_calls=n_ticks_to_keepalive + 1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_scan.return_value = _canned_scan()
    chunks = await _drain(sse.last_scan_stream(fake_client, _settings(), sleep=sleep))
    assert any(c == b": keepalive\n\n" for c in chunks)


async def test_last_scan_stream_cancellation_propagates() -> None:
    """Cancelling the injected sleep terminates the loop within one tick."""

    async def cancel_immediately(_d: float) -> None:
        raise asyncio.CancelledError()

    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_scan.return_value = _canned_scan()
    with pytest.raises(asyncio.CancelledError):
        async for _ in sse.last_scan_stream(fake_client, _settings(), sleep=cancel_immediately):
            pass


# ---- issue#12: tracker.toml [webctl] cadence injection -----------------


async def test_last_pose_stream_honours_toml_pose_stream_hz(tmp_path: Path) -> None:
    """When tracker.toml carries `[webctl] pose_stream_hz = 10`, the
    `last_pose_stream` loop sleeps for 1/10 = 0.1 s per tick (issue#12
    config-driven cadence)."""
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\npose_stream_hz = 10\n")
    sleep = RecordingSleep(max_calls=2)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose()
    fake_client.get_last_output.return_value = _canned_output()
    chunks = await _drain(
        sse.last_pose_stream(
            fake_client,
            _settings(tracker_toml_path=p),
            sleep=sleep,
        ),
    )
    assert sleep.calls == [pytest.approx(0.1), pytest.approx(0.1)]
    assert any(c.startswith(b"data:") for c in chunks)


async def test_last_scan_stream_honours_toml_scan_stream_hz(tmp_path: Path) -> None:
    """Twin of `test_last_pose_stream_honours_toml_pose_stream_hz` for
    the scan stream."""
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\nscan_stream_hz = 20\n")
    sleep = RecordingSleep(max_calls=2)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_scan.return_value = _canned_scan()
    chunks = await _drain(
        sse.last_scan_stream(
            fake_client,
            _settings(tracker_toml_path=p),
            sleep=sleep,
        ),
    )
    assert sleep.calls == [pytest.approx(0.05), pytest.approx(0.05)]
    assert any(c.startswith(b"data:") for c in chunks)


async def test_last_pose_stream_env_var_overrides_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GODO_WEBCTL_POSE_STREAM_HZ=60` in the environment beats the
    tracker.toml value (precedence: env > TOML > default)."""
    p = tmp_path / "tracker.toml"
    p.write_text("[webctl]\npose_stream_hz = 10\n")
    monkeypatch.setenv("GODO_WEBCTL_POSE_STREAM_HZ", "60")
    sleep = RecordingSleep(max_calls=2)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose()
    fake_client.get_last_output.return_value = _canned_output()
    await _drain(
        sse.last_pose_stream(
            fake_client,
            _settings(tracker_toml_path=p),
            sleep=sleep,
        ),
    )
    assert sleep.calls == [pytest.approx(1 / 60), pytest.approx(1 / 60)]


async def test_last_pose_stream_falls_back_on_toml_error(tmp_path: Path) -> None:
    """Mode-A M6 (Parent A6) — malformed tracker.toml does NOT crash
    the stream; it falls back to the default 30 Hz cadence."""
    p = tmp_path / "tracker.toml"
    # Out-of-range value would raise WebctlTomlError if the SSE loop
    # called read_webctl_section directly; the `_resolve_pose_tick_s`
    # wrapper catches and returns the default tick instead.
    p.write_text("[webctl]\npose_stream_hz = 9999\n")
    sleep = RecordingSleep(max_calls=2)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose()
    fake_client.get_last_output.return_value = _canned_output()
    await _drain(
        sse.last_pose_stream(
            fake_client,
            _settings(tracker_toml_path=p),
            sleep=sleep,
        ),
    )
    assert sleep.calls == [_DEFAULT_POSE_TICK_S, _DEFAULT_POSE_TICK_S]


# ---- diag_stream (PR-DIAG) ---------------------------------------------


def _canned_jitter() -> dict[str, object]:
    return {
        "ok": True,
        "valid": 1,
        "p50_ns": 4567,
        "p95_ns": 12345,
        "p99_ns": 45678,
        "max_ns": 123456,
        "mean_ns": 5678,
        "sample_count": 2048,
        "published_mono_ns": 1_000_000_000,
    }


def _canned_amcl_rate() -> dict[str, object]:
    return {
        "ok": True,
        "valid": 1,
        "hz": 9.987,
        "last_iteration_mono_ns": 1_000_000_000,
        "total_iteration_count": 42,
        "published_mono_ns": 1_000_000_001,
    }


def _canned_pose_dict() -> dict[str, object]:
    return {
        "ok": True,
        "valid": 1,
        "x_m": 0.0,
        "y_m": 0.0,
        "yaw_deg": 0.0,
        "xy_std_m": 0.0,
        "yaw_std_deg": 0.0,
        "iterations": 5,
        "converged": 1,
        "forced": 0,
        "published_mono_ns": 1_000_000_000,
    }


def _canned_resources() -> dict[str, object]:
    return {
        "cpu_temp_c": 50.0,
        "mem_used_pct": 25.0,
        "mem_total_bytes": 1 << 32,
        "mem_avail_bytes": 1 << 30,
        "disk_used_pct": 41.5,
        "disk_total_bytes": 1 << 35,
        "disk_avail_bytes": 1 << 33,
        "published_mono_ns": 0,
    }


async def test_diag_stream_emits_one_frame_per_tick() -> None:
    sleep = RecordingSleep(max_calls=3)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose_dict()
    fake_client.get_jitter.return_value = _canned_jitter()
    fake_client.get_amcl_rate.return_value = _canned_amcl_rate()
    with mock.patch(
        "godo_webctl.sse.resources_mod.snapshot",
        return_value=_canned_resources(),
    ):
        chunks = await _drain(sse.diag_stream(fake_client, _settings(), sleep=sleep))
    # issue#12 regression pin (operator-locked "지도 부분에만 적용"):
    # diag_stream still uses SSE_TICK_S (5 Hz / 0.2 s per tick),
    # NOT the new webctl.* config-driven cadence — only pose+scan
    # streams pick up the new rate.
    assert sleep.calls == [SSE_TICK_S, SSE_TICK_S, SSE_TICK_S]
    # One emit per tick.
    data_chunks = [c for c in chunks if c.startswith(b"data:")]
    assert len(data_chunks) == 3
    # Each frame contains all four top-level keys.
    import json

    body = json.loads(data_chunks[0][len(b"data: ") :].decode().rstrip("\n"))
    assert set(body.keys()) == {"pose", "jitter", "amcl_rate", "resources"}


async def test_diag_stream_skip_pose_error_keeps_other_panels() -> None:
    sleep = RecordingSleep(max_calls=1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.side_effect = uds_client.UdsUnreachable("down")
    fake_client.get_jitter.return_value = _canned_jitter()
    fake_client.get_amcl_rate.return_value = _canned_amcl_rate()
    with mock.patch(
        "godo_webctl.sse.resources_mod.snapshot",
        return_value=_canned_resources(),
    ):
        chunks = await _drain(sse.diag_stream(fake_client, _settings(), sleep=sleep))
    data = [c for c in chunks if c.startswith(b"data:")]
    assert len(data) == 1
    import json

    body = json.loads(data[0][len(b"data: ") :].decode().rstrip("\n"))
    # Pose became sentinel; jitter + amcl_rate populated.
    assert body["pose"]["valid"] == 0
    assert body["jitter"]["valid"] == 1
    assert body["amcl_rate"]["valid"] == 1


async def test_diag_stream_skip_resources_error_keeps_three_uds_panels() -> None:
    sleep = RecordingSleep(max_calls=1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose_dict()
    fake_client.get_jitter.return_value = _canned_jitter()
    fake_client.get_amcl_rate.return_value = _canned_amcl_rate()
    with mock.patch(
        "godo_webctl.sse.resources_mod.snapshot",
        side_effect=RuntimeError("kaboom"),
    ):
        chunks = await _drain(sse.diag_stream(fake_client, _settings(), sleep=sleep))
    data = [c for c in chunks if c.startswith(b"data:")]
    assert len(data) == 1
    import json

    body = json.loads(data[0][len(b"data: ") :].decode().rstrip("\n"))
    assert body["pose"]["valid"] == 1
    assert body["jitter"]["valid"] == 1
    assert body["amcl_rate"]["valid"] == 1
    assert body["resources"]["valid"] == 0


async def test_diag_stream_keepalive_after_heartbeat_window() -> None:
    n_ticks = int(SSE_HEARTBEAT_S / SSE_TICK_S) + 1
    sleep = RecordingSleep(max_calls=n_ticks + 1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose_dict()
    fake_client.get_jitter.return_value = _canned_jitter()
    fake_client.get_amcl_rate.return_value = _canned_amcl_rate()
    with mock.patch(
        "godo_webctl.sse.resources_mod.snapshot",
        return_value=_canned_resources(),
    ):
        chunks = await _drain(sse.diag_stream(fake_client, _settings(), sleep=sleep))
    assert any(c == b": keepalive\n\n" for c in chunks)


async def test_diag_stream_cancellation_propagates() -> None:
    async def cancel_immediately(_d: float) -> None:
        raise asyncio.CancelledError()

    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = _canned_pose_dict()
    fake_client.get_jitter.return_value = _canned_jitter()
    fake_client.get_amcl_rate.return_value = _canned_amcl_rate()
    with (
        mock.patch(
            "godo_webctl.sse.resources_mod.snapshot",
            return_value=_canned_resources(),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        async for _ in sse.diag_stream(
            fake_client,
            _settings(),
            sleep=cancel_immediately,
        ):
            pass


async def test_diag_stream_all_four_fail_emits_all_sentinel_frame() -> None:
    sleep = RecordingSleep(max_calls=1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.side_effect = uds_client.UdsUnreachable("p")
    fake_client.get_jitter.side_effect = uds_client.UdsUnreachable("j")
    fake_client.get_amcl_rate.side_effect = uds_client.UdsUnreachable("r")
    with mock.patch(
        "godo_webctl.sse.resources_mod.snapshot",
        side_effect=RuntimeError("res"),
    ):
        chunks = await _drain(sse.diag_stream(fake_client, _settings(), sleep=sleep))
    data = [c for c in chunks if c.startswith(b"data:")]
    assert len(data) == 1
    import json

    body = json.loads(data[0][len(b"data: ") :].decode().rstrip("\n"))
    for key in ("pose", "jitter", "amcl_rate", "resources"):
        assert body[key]["valid"] == 0


# ---- response headers ---------------------------------------------------


def test_sse_response_headers_pinned() -> None:
    """N5: defensive against a future reverse-proxy buffering SSE."""
    assert sse.SSE_RESPONSE_HEADERS["Cache-Control"] == "no-cache"
    assert sse.SSE_RESPONSE_HEADERS["X-Accel-Buffering"] == "no"


# ---- PR-B: processes_stream ----------------------------------------------


def _fake_process_sample() -> dict[str, object]:
    return {
        "processes": [
            {
                "name": "godo_smoke",
                "pid": 100,
                "user": "ncenter",
                "state": "S",
                "cmdline": ["godo_smoke"],
                "cpu_pct": 0.0,
                "rss_mb": 2.0,
                "etime_s": 5,
                "category": "godo",
                "duplicate": False,
            },
        ],
        "duplicate_alert": False,
        "published_mono_ns": 1,
    }


async def test_processes_stream_emits_1hz_sleep_sequence() -> None:
    from godo_webctl import processes
    from godo_webctl.constants import SSE_PROCESSES_TICK_S

    sleep = RecordingSleep(max_calls=3)
    sampler = mock.MagicMock(spec=processes.ProcessSampler)
    sampler.sample.return_value = _fake_process_sample()
    chunks = await _drain(
        sse.processes_stream(_settings(), sampler=sampler, sleep=sleep),
    )
    assert sleep.calls == [SSE_PROCESSES_TICK_S, SSE_PROCESSES_TICK_S, SSE_PROCESSES_TICK_S]
    assert any(c.startswith(b"data:") and b"duplicate_alert" in c for c in chunks)


async def test_processes_stream_skips_frame_on_sample_error() -> None:
    from godo_webctl import processes
    from godo_webctl.constants import SSE_PROCESSES_TICK_S

    sleep = RecordingSleep(max_calls=2)
    sampler = mock.MagicMock(spec=processes.ProcessSampler)
    sampler.sample.side_effect = OSError("proc gone")
    chunks = await _drain(
        sse.processes_stream(_settings(), sampler=sampler, sleep=sleep),
    )
    assert sleep.calls == [SSE_PROCESSES_TICK_S, SSE_PROCESSES_TICK_S]
    assert all(not c.startswith(b"data:") for c in chunks)


async def test_processes_stream_cancellation_propagates() -> None:
    from godo_webctl import processes

    async def cancel_immediately(_d: float) -> None:
        raise asyncio.CancelledError()

    sampler = mock.MagicMock(spec=processes.ProcessSampler)
    sampler.sample.return_value = _fake_process_sample()
    with pytest.raises(asyncio.CancelledError):
        async for _ in sse.processes_stream(_settings(), sampler=sampler, sleep=cancel_immediately):
            pass


# ---- PR-B: resources_extended_stream -------------------------------------


def _fake_extended_sample() -> dict[str, object]:
    return {
        "cpu_per_core": [10.0, 20.0, 30.0, 40.0],
        "cpu_aggregate_pct": 25.0,
        "mem_total_mb": 8000.0,
        "mem_used_mb": 2000.0,
        "disk_pct": 50.0,
        "published_mono_ns": 1,
    }


async def test_resources_extended_stream_emits_per_core_list() -> None:
    from godo_webctl import resources_extended
    from godo_webctl.constants import SSE_RESOURCES_EXTENDED_TICK_S

    sleep = RecordingSleep(max_calls=2)
    sampler = mock.MagicMock(spec=resources_extended.ResourcesExtendedSampler)
    sampler.sample.return_value = _fake_extended_sample()
    chunks = await _drain(
        sse.resources_extended_stream(_settings(), sampler=sampler, sleep=sleep),
    )
    assert sleep.calls == [SSE_RESOURCES_EXTENDED_TICK_S, SSE_RESOURCES_EXTENDED_TICK_S]
    data = [c for c in chunks if c.startswith(b"data:")]
    assert len(data) >= 1
    import json

    body = json.loads(data[0][len(b"data: ") :].decode().rstrip("\n"))
    assert isinstance(body["cpu_per_core"], list)
    assert len(body["cpu_per_core"]) == 4


async def test_resources_extended_stream_skips_on_partial_failure() -> None:
    from godo_webctl import resources_extended

    sleep = RecordingSleep(max_calls=1)
    sampler = mock.MagicMock(spec=resources_extended.ResourcesExtendedSampler)
    sampler.sample.side_effect = OSError("boom")
    chunks = await _drain(
        sse.resources_extended_stream(_settings(), sampler=sampler, sleep=sleep),
    )
    # No frames emitted; loop continues for one tick before recorder cancels.
    assert all(not c.startswith(b"data:") for c in chunks)


async def test_resources_extended_stream_cancellation_propagates() -> None:
    from godo_webctl import resources_extended

    async def cancel_immediately(_d: float) -> None:
        raise asyncio.CancelledError()

    sampler = mock.MagicMock(spec=resources_extended.ResourcesExtendedSampler)
    sampler.sample.return_value = _fake_extended_sample()
    with pytest.raises(asyncio.CancelledError):
        async for _ in sse.resources_extended_stream(
            _settings(),
            sampler=sampler,
            sleep=cancel_immediately,
        ):
            pass


# ---- issue#28.1 — map_edit_progress_stream invariants -------------------
# Pins for the shared broadcaster channel that drives the SPA's
# <ApplyMemoModal> progress indicator. Each frame carries
# `{"phase", "progress", "request_id"}`; SPA filters by `request_id` so
# stale connections from a previous Apply ignore foreign frames.


async def _drain_progress_with_publishes(
    frames: list[dict[str, object]],
) -> list[bytes]:
    """Spawn `map_edit_progress_stream`, publish a sequence of frames,
    then cancel. Returns every emitted byte chunk in order."""
    out: list[bytes] = []

    async def consume() -> None:
        async for chunk in sse.map_edit_progress_stream():
            out.append(chunk)

    task = asyncio.create_task(consume())
    # Yield once so the consumer's queue is registered with the
    # broadcaster before publishes go out.
    await asyncio.sleep(0)
    for frame in frames:
        await sse.publish_map_edit_progress(frame)
    # Yield enough times for the consumer to drain its queue.
    for _ in range(len(frames) + 2):
        await asyncio.sleep(0)
    task.cancel()
    import contextlib

    with contextlib.suppress(asyncio.CancelledError):
        await task
    return out


async def test_sse_progress_emits_monotonic_floats() -> None:
    """B2 — `progress` field is a float in [0.0, 1.0] and never
    decreases across a single request_id's frame sequence."""
    import json as _json

    rid = "abc12345"
    frames = [
        {"phase": "starting", "progress": 0.0, "request_id": rid},
        {"phase": "yaml_rewrite", "progress": 0.2, "request_id": rid},
        {"phase": "rotate", "progress": 0.5, "request_id": rid},
        {"phase": "restart_pending", "progress": 0.95, "request_id": rid},
        {"phase": "done", "progress": 1.0, "request_id": rid},
    ]
    chunks = await _drain_progress_with_publishes(frames)
    data_chunks = [c for c in chunks if c.startswith(b"data:")]
    assert len(data_chunks) == len(frames)
    progresses: list[float] = []
    for chunk in data_chunks:
        body = _json.loads(chunk.removeprefix(b"data: ").rstrip(b"\n"))
        assert isinstance(body["progress"], float), body
        assert 0.0 <= body["progress"] <= 1.0, body
        assert body["request_id"] == rid
        progresses.append(body["progress"])
    # Monotonically non-decreasing — strictly increasing in this trace.
    assert progresses == sorted(progresses)
    assert progresses[0] == 0.0 and progresses[-1] == 1.0


async def test_sse_emits_rejected_on_canvas_overflow() -> None:
    """B3 — when the pipeline rejects with `canvas_too_large`, the
    last frame carries `phase: "rejected"`, `progress: 1.0`, and a
    `reason: "canvas_too_large"` tag for the SPA to surface."""
    import json as _json

    rid = "rej00001"
    frames = [
        {"phase": "starting", "progress": 0.0, "request_id": rid},
        {"phase": "yaml_rewrite", "progress": 0.2, "request_id": rid},
        {
            "phase": "rejected",
            "progress": 1.0,
            "request_id": rid,
            "reason": "canvas_too_large",
        },
    ]
    chunks = await _drain_progress_with_publishes(frames)
    data_chunks = [c for c in chunks if c.startswith(b"data:")]
    assert len(data_chunks) == 3
    last = _json.loads(data_chunks[-1].removeprefix(b"data: ").rstrip(b"\n"))
    assert last["phase"] == "rejected"
    assert last["progress"] == 1.0
    assert last["reason"] == "canvas_too_large"
    assert last["request_id"] == rid


async def test_sse_progress_frames_carry_request_id() -> None:
    """B4 — every emitted frame carries the `request_id` tag (M9 lock).
    The SPA uses this to discard frames from a stale prior Apply."""
    import json as _json

    rid = "deadbeef"
    frames = [
        {"phase": "starting", "progress": 0.0, "request_id": rid},
        {"phase": "rotate", "progress": 0.5, "request_id": rid},
        {
            "phase": "done",
            "progress": 1.0,
            "request_id": rid,
            "derived_name": "studio_v1.20260505-141500-abc",
        },
    ]
    chunks = await _drain_progress_with_publishes(frames)
    data_chunks = [c for c in chunks if c.startswith(b"data:")]
    assert len(data_chunks) == 3
    for chunk in data_chunks:
        body = _json.loads(chunk.removeprefix(b"data: ").rstrip(b"\n"))
        assert "request_id" in body, body
        assert body["request_id"] == rid
