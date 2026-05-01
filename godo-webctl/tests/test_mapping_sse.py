"""
issue#14 — Mapping monitor SSE producer (singleton ticker).

Coverage (per plan §12):
  - Single tick → single frame.
  - Self-terminate when state is `no_active`.
  - Self-terminate when container exits mid-stream.
  - Multi-subscriber: ONE snapshot invocation per tick regardless of N.
  - Cancel-safe (CancelledError out of sleep).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from godo_webctl import mapping_sse as MS
from godo_webctl.config import Settings


def _settings(tmp_path: Path) -> Settings:
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir(mode=0o750, exist_ok=True)
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
    )


@pytest.fixture(autouse=True)
def _reset_singleton() -> Iterator[None]:
    MS.reset_for_test()
    yield
    MS.reset_for_test()


async def test_stream_emits_one_frame_per_tick(tmp_path: Path) -> None:
    """One snapshot = one frame, then no_active = close."""
    cfg = _settings(tmp_path)
    snaps = [
        {"valid": True, "container_state": "running", "container_cpu_pct": 10.0},
        {"valid": True, "container_state": "no_active"},
    ]
    call_count = 0

    def fake_snap(_cfg: Settings) -> dict[str, Any]:
        nonlocal call_count
        out = snaps[call_count] if call_count < len(snaps) else snaps[-1]
        call_count += 1
        return out

    sleep_calls: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleep_calls.append(s)

    frames: list[bytes] = []
    gen = MS.mapping_monitor_stream(cfg, sleep=fake_sleep, snapshot_fn=fake_snap)
    async for frame in gen:
        frames.append(frame)

    # First snap is "running" → emitted; loop sleeps; second snap is
    # "no_active" → emitted then close.
    assert len(frames) == 2
    body0 = frames[0].decode("utf-8")
    assert body0.startswith("data: ")
    payload0 = json.loads(body0[len("data: ") :].strip())
    assert payload0["container_state"] == "running"
    payload1 = json.loads(frames[1].decode("utf-8")[len("data: ") :].strip())
    assert payload1["container_state"] == "no_active"


async def test_stream_self_terminates_when_state_idle(tmp_path: Path) -> None:
    """Initial Idle → first frame is no_active + immediate close."""
    cfg = _settings(tmp_path)

    def snap_idle(_cfg: Settings) -> dict[str, Any]:
        return {"valid": True, "container_state": "no_active"}

    async def fake_sleep(_s: float) -> None:
        pass

    frames: list[bytes] = []
    async for frame in MS.mapping_monitor_stream(cfg, sleep=fake_sleep, snapshot_fn=snap_idle):
        frames.append(frame)
    assert len(frames) == 1
    assert b"no_active" in frames[0]


async def test_stream_self_terminates_when_container_exits_mid_stream(
    tmp_path: Path,
) -> None:
    cfg = _settings(tmp_path)
    snaps = [
        {"valid": True, "container_state": "running"},
        {"valid": True, "container_state": "exited"},
    ]
    counter = 0

    def fake_snap(_cfg: Settings) -> dict[str, Any]:
        nonlocal counter
        out = snaps[counter] if counter < len(snaps) else snaps[-1]
        counter += 1
        return out

    async def fake_sleep(_s: float) -> None:
        pass

    frames: list[bytes] = []
    async for frame in MS.mapping_monitor_stream(cfg, sleep=fake_sleep, snapshot_fn=fake_snap):
        frames.append(frame)
    assert len(frames) == 2
    assert b'"container_state":"exited"' in frames[1]


async def test_singleton_ticker_one_snapshot_per_tick_regardless_of_subscriber_count(
    tmp_path: Path,
) -> None:
    """M4 critical assertion: 5 concurrent subscribers × 3 ticks → exactly
    3 snapshot invocations (not 15). Singleton ticker fans out one frame
    to all queues."""
    cfg = _settings(tmp_path)
    invocations = 0

    def fake_snap(_cfg: Settings) -> dict[str, Any]:
        nonlocal invocations
        invocations += 1
        if invocations >= 4:
            return {"valid": True, "container_state": "no_active"}
        return {"valid": True, "container_state": "running"}

    sleep_count = 0

    async def fake_sleep(_s: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        # Yield once so other subscribers' awaits can interleave.
        await asyncio.sleep(0)

    # Start N subscribers.
    n_subs = 5
    counts: list[int] = [0] * n_subs

    async def consume(idx: int) -> None:
        async for _frame in MS.mapping_monitor_stream(
            cfg, sleep=fake_sleep, snapshot_fn=fake_snap,
        ):
            counts[idx] += 1

    tasks = [asyncio.create_task(consume(i)) for i in range(n_subs)]
    # Wait for them to finish (the snapshot fn returns no_active on 4th
    # call which closes the stream).
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=2.0)

    # Critical: total snapshot invocations is N_TICKS, not N_TICKS * N_SUBS.
    assert invocations == 4
    # Every subscriber received both running frames + the no_active close
    # frame. Order within frames is identical (broadcast).
    for c in counts:
        assert c == 4


async def test_stream_cancel_safe_emits_close_to_subscribers(tmp_path: Path) -> None:
    """When the ticker is cancelled (e.g. server shutdown), every
    subscriber's stream closes cleanly within one tick — no unbounded
    hang. Subscribers see ZERO or ONE frame before close depending on
    the cancel timing; the contract is bounded liveness, not a specific
    frame count."""
    cfg = _settings(tmp_path)
    snap_count = 0

    def fake_snap(_cfg: Settings) -> dict[str, Any]:
        nonlocal snap_count
        snap_count += 1
        return {"valid": True, "container_state": "running"}

    async def cancelling_sleep(_s: float) -> None:
        raise asyncio.CancelledError()

    frames: list[bytes] = []
    # Subscriber sees the first running frame, then the ticker's
    # CancelledError triggers its `finally` to broadcast __close__,
    # which terminates the consumer cleanly.
    async for frame in MS.mapping_monitor_stream(
        cfg, sleep=cancelling_sleep, snapshot_fn=fake_snap,
    ):
        frames.append(frame)
    # First frame emitted before cancel; no second frame.
    assert len(frames) == 1
    assert b'"container_state":"running"' in frames[0]
