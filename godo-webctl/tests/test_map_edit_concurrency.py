"""issue#28.1 B1 — pin asyncio.Lock serialisation on `/api/map/edit/coord`.

The Map-Edit pipeline holds a per-app `asyncio.Lock` to ensure only one
Apply runs at a time (avoids second-resolution timestamp collisions and
derived-pair write races). Two test cases:

1. **Timeout path**: with the lock-acquire timeout forced to ~0, a
   second concurrent request observes HTTP 409 `pipeline_busy` while
   the first is in-flight. Pins the fail-fast contract.

2. **Serialisation path**: without timeout pressure, two interleaved
   requests both succeed and produce DIFFERENT `derived_name`s. Pins
   that the lock actually serialises (rather than letting both races
   write to the same derived path).
"""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from godo_webctl import app as app_mod
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


async def test_concurrent_apply_serialises_or_rejects_busy(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1 case 1 — timeout path. With the lock-acquire timeout forced
    near zero, a second concurrent Apply observes 409 `pipeline_busy`
    while the first one is in-flight."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )

    # Force the lock-acquire timeout to near-zero so the second request
    # cannot wait for the first to finish.
    monkeypatch.setattr(app_mod, "MAP_EDIT_PIPELINE_LOCK_TIMEOUT_S", 0.001)

    # Slow down the first request inside the lock so the second one
    # arrives while the lock is held. We monkeypatch
    # `maps_mod.read_active_name` (the first step inside the lock) to
    # sleep ~200 ms before returning the real value.
    real_read_active_name = app_mod.maps_mod.read_active_name

    def slow_read_active_name(maps_dir: Path) -> str | None:
        import time as _time

        _time.sleep(0.2)
        return real_read_active_name(maps_dir)

    monkeypatch.setattr(
        app_mod.maps_mod, "read_active_name", slow_read_active_name,
    )

    async with _client(s) as cl:
        token = await _login_admin(cl)
        body = {"x_m": 0.1, "y_m": 0.2, "theta_deg": 0.0, "memo": "concur1"}
        body2 = {"x_m": 0.2, "y_m": 0.3, "theta_deg": 0.0, "memo": "concur2"}

        async def post(b: dict[str, object]) -> httpx.Response:
            return await cl.post(
                "/api/map/edit/coord", json=b, headers=_auth(token),
            )

        # Fire both — first should win the lock; second should
        # observe `pipeline_busy` after the 1 ms timeout elapses
        # (the 200 ms sleep keeps the lock held).
        r1, r2 = await asyncio.gather(post(body), post(body2))

    statuses = sorted([r1.status_code, r2.status_code])
    # One success (200) and one busy (409).
    assert statuses == [HTTPStatus.OK, HTTPStatus.CONFLICT], (
        f"got statuses {statuses}: r1={r1.text!r}, r2={r2.text!r}"
    )
    # The 409 carries `pipeline_busy`.
    busy = r1 if r1.status_code == HTTPStatus.CONFLICT else r2
    assert busy.json() == {"ok": False, "err": "pipeline_busy"}


async def test_concurrent_apply_serialises(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1 case 2 — serialisation path. Two concurrent Applies under
    the default (60 s) lock-timeout MUST execute strictly sequentially
    — pinned by recording the entry/exit ordering of the slow first
    step. Distinct memos guarantee distinct `derived_name`s so a
    timestamp collision does not mask the test."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )

    # Trace lock holders: monkeypatch `read_active_name` to record
    # entry/exit and sleep ~50 ms so contention is observable. If the
    # lock serialises, the second entry happens AFTER the first exit;
    # if the lock leaks, entries interleave.
    real_read_active_name = app_mod.maps_mod.read_active_name
    events: list[tuple[str, float]] = []
    events_lock = asyncio.Lock()

    def traced_read_active_name(maps_dir: Path) -> str | None:
        import time as _time

        t0 = _time.monotonic()
        events.append(("enter", t0))
        _time.sleep(0.05)
        t1 = _time.monotonic()
        events.append(("exit", t1))
        return real_read_active_name(maps_dir)

    monkeypatch.setattr(
        app_mod.maps_mod, "read_active_name", traced_read_active_name,
    )
    del events_lock  # unused; events.append on a Python list is GIL-safe.

    async with _client(s) as cl:
        token = await _login_admin(cl)

        async def post(memo: str) -> httpx.Response:
            return await cl.post(
                "/api/map/edit/coord",
                json={"x_m": 0.1, "y_m": 0.2, "theta_deg": 0.0, "memo": memo},
                headers=_auth(token),
            )

        r1, r2 = await asyncio.gather(post("first"), post("second"))

    assert r1.status_code == HTTPStatus.OK, r1.text
    assert r2.status_code == HTTPStatus.OK, r2.text
    name1 = r1.json()["derived_name"]
    name2 = r2.json()["derived_name"]
    assert name1 != name2, f"derived_name collision: {name1!r} vs {name2!r}"

    # Strict serialisation pin: the events list is `[enter, exit, enter,
    # exit]` — never `[enter, enter, exit, exit]`. The latter would
    # mean the lock leaked and both requests ran the slow step in
    # parallel.
    kinds = [k for (k, _t) in events]
    assert kinds == ["enter", "exit", "enter", "exit"], (
        f"lock did not serialise: events={events!r}"
    )
