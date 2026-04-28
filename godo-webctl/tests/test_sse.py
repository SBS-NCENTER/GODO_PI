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


def _settings() -> Settings:
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


async def test_last_pose_stream_emits_5hz_sleep_sequence() -> None:
    """Sleep duration sequence is `[0.2, 0.2, ...]` → 5 Hz cadence by
    construction. No wall-clock involved."""
    sleep = RecordingSleep(max_calls=3)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    pose = {
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
    fake_client.get_last_pose.return_value = pose
    chunks = await _drain(sse.last_pose_stream(fake_client, _settings(), sleep=sleep))
    # 3 ticks attempted before recorder cancels the loop.
    assert sleep.calls == [SSE_TICK_S, SSE_TICK_S, SSE_TICK_S]
    # At least the first tick produced a data frame.
    assert any(c.startswith(b"data:") for c in chunks)


async def test_last_pose_stream_skips_frame_on_uds_error() -> None:
    """Tracker-down: get_last_pose raises → no frame emitted that tick,
    generator stays alive."""
    sleep = RecordingSleep(max_calls=2)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.side_effect = uds_client.UdsUnreachable("down")
    chunks = await _drain(sse.last_pose_stream(fake_client, _settings(), sleep=sleep))
    assert sleep.calls == [SSE_TICK_S, SSE_TICK_S]
    # No data frames emitted at all (only would-be-keepalives, but with
    # 2 ticks of 0.2 s = 0.4 s virtual elapsed we are well below 15 s).
    assert all(not c.startswith(b"data:") for c in chunks)


async def test_last_pose_stream_emits_keepalive_after_heartbeat_window() -> None:
    """Keepalive comment line must appear once virtual elapsed time
    crosses SSE_HEARTBEAT_S."""
    n_ticks_to_keepalive = int(SSE_HEARTBEAT_S / SSE_TICK_S) + 1
    sleep = RecordingSleep(max_calls=n_ticks_to_keepalive + 1)
    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = {"ok": True, "valid": 0}
    chunks = await _drain(sse.last_pose_stream(fake_client, _settings(), sleep=sleep))
    assert any(c == b": keepalive\n\n" for c in chunks)


async def test_last_pose_stream_cancellation_propagates() -> None:
    """Cancelling the injected sleep terminates the loop within one tick."""

    async def cancel_immediately(_d: float) -> None:
        raise asyncio.CancelledError()

    fake_client = mock.MagicMock(spec=uds_client.UdsClient)
    fake_client.get_last_pose.return_value = {"ok": True}
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


# ---- response headers ---------------------------------------------------


def test_sse_response_headers_pinned() -> None:
    """N5: defensive against a future reverse-proxy buffering SSE."""
    assert sse.SSE_RESPONSE_HEADERS["Cache-Control"] == "no-cache"
    assert sse.SSE_RESPONSE_HEADERS["X-Accel-Buffering"] == "no"
