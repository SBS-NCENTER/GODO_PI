"""issue#28.2 — End-to-end SSE producer-side pin for /api/map/edit/coord.

PR #93 (issue#28.1) added unit tests B2/B3/B4 covering the SSE
*broadcaster relay* (frame-inject → frame-relay round-trip). Those
tests publish frames to the broadcaster directly and assert the relay
forwards them — they do NOT exercise the actual handler's
frame-emission code.

This file pins the *producer* side: the real /api/map/edit/coord
handler, when driven through ASGI, emits a well-formed SSE frame
sequence that meets the SPA's UX contract (request_id consistent
across frames, monotonic progress, expected phase set, reason field
on rejection).

Cases:
  T1 — Happy path: coord apply with valid pristine map → frame
       sequence carries the same request_id as the HTTP response,
       includes 'starting' (progress=0.0) and 'done' (progress=1.0)
       markers, monotonic non-decreasing progress, 'done' frame
       carries `derived_name`.
  T2 — Reject path: coord apply against a maps_dir without active
       symlink → frame sequence emits 'starting' then 'rejected' with
       a non-empty `reason` field; request_id consistent across both
       frames.

Reviewer's M1 finding (PR #93 Mode-B): the original B2/B3/B4 tests pin
ONLY the relay, so a regression that drops `request_id`, omits
`reason`, or skips a phase frame on the producer side would slip
through. T1 + T2 here close that hole with one integration test per
direction.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from http import HTTPStatus
from pathlib import Path

import httpx
from httpx import ASGITransport

from godo_webctl import sse
from godo_webctl.app import create_app
from godo_webctl.config import Settings


def _settings_for(
    *,
    uds_socket: Path,
    map_path: Path,
    backup_dir: Path,
    maps_dir: Path,
) -> Settings:
    base = backup_dir.parent
    return Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=uds_socket,
        backup_dir=backup_dir,
        map_path=map_path,
        maps_dir=maps_dir,
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
        jwt_secret_path=base / "jwt_secret",
        users_file=base / "users.json",
        spa_dist=None,
        chromium_loopback_only=True,
        disk_check_path=Path("/"),
        restart_pending_path=base / "restart_pending",
        pidfile_path=base / "godo-webctl.pid",
        tracker_toml_path=base / "tracker.toml",
        mapping_runtime_dir=base / "mapping_rt",
        mapping_image_tag="godo-mapping:dev",
        docker_bin=Path("/usr/bin/docker"),
        mapping_webctl_stop_timeout_s=35.0,
        mapping_systemctl_subprocess_timeout_s=20.0,
        mapping_auto_recover_lidar=True,
    )


def _client(settings: Settings) -> httpx.AsyncClient:
    app = create_app(settings)
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


async def _login_admin(cl: httpx.AsyncClient) -> str:
    r = await cl.post(
        "/api/auth/login",
        json={"username": "ncenter", "password": "ncenter"},
    )
    assert r.status_code == HTTPStatus.OK, r.text
    return r.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _spawn_sse_consumer() -> tuple[asyncio.Task[None], list[dict[str, object]]]:
    """Spawn a background task subscribed to `map_edit_progress_stream()`
    that decodes each `data: <json>` chunk into a dict and appends it
    to the returned list. Caller is responsible for cancelling the
    task once the producing HTTP request has finished.
    """
    out: list[dict[str, object]] = []

    async def consume() -> None:
        async for chunk in sse.map_edit_progress_stream():
            # SSE chunks: `data: <json>\n\n` for frames; `: <hb>\n\n`
            # for heartbeats. Filter to data: payloads only.
            if not chunk.startswith(b"data:"):
                continue
            body = chunk.removeprefix(b"data: ").rstrip(b"\n")
            try:
                out.append(json.loads(body))
            except json.JSONDecodeError:
                # Surface non-JSON for the test to fail informatively.
                out.append({"_raw": body.decode("utf-8", errors="replace")})

    task = asyncio.create_task(consume())
    # Yield once so the consumer's queue is registered with the
    # broadcaster before any publish goes out (mirrors the existing
    # `_drain_progress_with_publishes` helper in test_sse.py).
    await asyncio.sleep(0)
    return task, out


async def _drain_and_cancel(
    task: asyncio.Task[None], frames_out: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Yield enough event-loop turns for the consumer to drain its
    queue, then cancel the task and return the collected frames."""
    # Yield generously — frames are still in the broadcaster's per-queue
    # asyncio.Queue at this point, even though publish_map_edit_progress
    # has returned. 16 yields is safely above the typical 5-7 frames /
    # Apply.
    for _ in range(16):
        await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return frames_out


async def test_coord_happy_path_emits_consistent_frame_sequence(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """T1 — coord apply succeeds → frame sequence pin.

    Pins (the gaps the relay tests B2/B3/B4 don't cover):
      - Every frame carries `request_id` matching the HTTP response.
      - First frame is 'starting' (progress=0.0).
      - Last frame is 'done' (progress=1.0).
      - `progress` is monotonic non-decreasing across the sequence.
      - 'done' frame carries `derived_name` matching HTTP response.
    """
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )

    consumer_task, frames_out = await _spawn_sse_consumer()

    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post(
            "/api/map/edit/coord",
            json={
                "x_m": 0.1,
                "y_m": 0.2,
                "theta_deg": 0.0,
                "memo": "issue28_2_t1",
                "picked_world_x_m": 0.0,
                "picked_world_y_m": 0.0,
            },
            headers=_auth(token),
        )

    assert r.status_code == HTTPStatus.OK, r.text
    rj = r.json()
    assert rj["ok"] is True
    expected_rid = rj["request_id"]
    expected_derived = rj["derived_name"]

    frames = await _drain_and_cancel(consumer_task, frames_out)

    assert frames, "no SSE frames emitted; producer side broken"

    # Every frame carries request_id matching the HTTP response.
    for f in frames:
        assert f.get("request_id") == expected_rid, (
            f"request_id mismatch in frame={f!r}; expected={expected_rid!r}"
        )

    phases = [f.get("phase") for f in frames]
    assert phases[0] == "starting", f"first frame is not 'starting': {phases!r}"
    assert phases[-1] == "done", f"last frame is not 'done': {phases!r}"

    progresses = [float(f.get("progress", -1.0)) for f in frames]
    assert progresses[0] == 0.0, f"starting.progress != 0.0: {progresses!r}"
    assert progresses[-1] == 1.0, f"done.progress != 1.0: {progresses!r}"
    for i in range(1, len(progresses)):
        assert progresses[i] >= progresses[i - 1], (
            f"non-monotonic progress at frame {i}: "
            f"{progresses[i - 1]} -> {progresses[i]}; full={progresses!r}"
        )

    done_frame = frames[-1]
    assert done_frame.get("derived_name") == expected_derived, (
        f"done.derived_name mismatch: frame={done_frame!r} resp={expected_derived!r}"
    )


async def test_coord_reject_active_map_missing_emits_reason(
    tmp_path: Path,
) -> None:
    """T2 — coord apply with no active map → 'rejected' frame carries
    `reason` field.

    Reproduces the reviewer's "rejection without reason" silent-regression
    vector. A maps_dir without `active.{pgm,yaml}` symlinks (and a
    map_path that does NOT exist so auto-migration cannot synthesize
    them on first call) triggers `read_active_name → None →
    publish('rejected', reason='active_map_missing')`.
    """
    empty_maps_dir = tmp_path / "empty_maps"
    empty_maps_dir.mkdir(mode=0o750)
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_path / "nonexistent.pgm",
        backup_dir=tmp_path / "bk",
        maps_dir=empty_maps_dir,
    )

    consumer_task, frames_out = await _spawn_sse_consumer()

    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post(
            "/api/map/edit/coord",
            json={
                "x_m": 0.1,
                "y_m": 0.2,
                "theta_deg": 0.0,
                "memo": "issue28_2_t2",
                "picked_world_x_m": 0.0,
                "picked_world_y_m": 0.0,
            },
            headers=_auth(token),
        )

    assert r.status_code == HTTPStatus.SERVICE_UNAVAILABLE, r.text
    rj = r.json()
    assert rj["ok"] is False

    frames = await _drain_and_cancel(consumer_task, frames_out)

    assert frames, "no SSE frames emitted; producer side broken"

    # request_id consistent within this Apply (single non-None value).
    rids = {f.get("request_id") for f in frames}
    assert len(rids) == 1, f"request_id not consistent across frames: {rids!r}"
    rid = next(iter(rids))
    assert rid is not None and isinstance(rid, str) and len(rid) > 0, (
        f"request_id missing or empty: {rid!r}"
    )

    phases = [f.get("phase") for f in frames]
    assert phases[0] == "starting", f"first frame is not 'starting': {phases!r}"
    assert "rejected" in phases, f"no 'rejected' frame in sequence: {phases!r}"

    reject_frame = next(f for f in frames if f.get("phase") == "rejected")
    reason = reject_frame.get("reason")
    assert reason and isinstance(reason, str), (
        f"'rejected' frame missing or has empty 'reason': {reject_frame!r}"
    )
    # Specific scenario pin — reason must match the handler's branch label.
    assert reason == "active_map_missing", (
        f"unexpected reject reason: got={reason!r} expected='active_map_missing'; "
        f"frame={reject_frame!r}"
    )
