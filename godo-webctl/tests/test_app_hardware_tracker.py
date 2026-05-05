"""
Hardware-required smoke test. Runs ONLY on a host with a live
``/run/godo/ctl.sock`` (i.e. ``godo_tracker_rt`` is up). Run manually:

    uv run pytest -m hardware_tracker

Strategy (S9): after ``POST /api/calibrate``, poll ``GET /api/health`` every
200 ms for up to 5 s. We MUST observe at least one ``OneShot`` reading
(the latch took effect) AND a subsequent ``Idle`` (converge() returned).

Note (issue#28.2 cleanup, 2026-05-05): /api/calibrate is admin-protected;
the test logs in via /api/auth/login and attaches the Bearer token. The
production host's seeded admin (`ncenter`/`ncenter`, FRONT_DESIGN §3.F)
is the credential. The marker is auto-excluded from the default
`pytest` run (see `pyproject.toml addopts`), so the live-tracker
side-effect (Live→OneShot→Idle transition) only fires when the
operator explicitly invokes `-m hardware_tracker`.
"""

from __future__ import annotations

import asyncio
import time
from http import HTTPStatus
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from godo_webctl.app import create_app
from godo_webctl.config import load_settings

UDS_PATH = Path("/run/godo/ctl.sock")


pytestmark = pytest.mark.hardware_tracker


@pytest.fixture
def hardware_client():
    if not UDS_PATH.exists():
        pytest.skip(f"{UDS_PATH} not present — godo_tracker_rt must be up")
    settings = load_settings()
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


async def test_calibrate_round_trip_observes_oneshot_then_idle(
    hardware_client,
) -> None:
    async with hardware_client as cl:
        # Sanity: health says tracker is reachable before we begin.
        h = await cl.get("/api/health")
        assert h.status_code == HTTPStatus.OK
        assert h.json()["tracker"] == "ok", h.json()

        token = await _login_admin(cl)
        auth = {"Authorization": f"Bearer {token}"}

        # Latch OneShot.
        c = await cl.post("/api/calibrate", headers=auth)
        assert c.status_code == HTTPStatus.OK, c.text
        assert c.json() == {"ok": True}

        # Poll for the sequence: OneShot must appear, then Idle.
        observed: list[str | None] = []
        saw_oneshot = False
        saw_idle_after_oneshot = False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            h = await cl.get("/api/health")
            mode = h.json().get("mode")
            observed.append(mode)
            if mode == "OneShot":
                saw_oneshot = True
            elif mode == "Idle" and saw_oneshot:
                saw_idle_after_oneshot = True
                break
            await asyncio.sleep(0.2)

        assert saw_oneshot and saw_idle_after_oneshot, (
            f"did not observe OneShot→Idle within 5 s; observed sequence: {observed!r}"
        )
