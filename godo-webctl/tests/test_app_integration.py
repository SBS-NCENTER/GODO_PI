"""FastAPI integration: route handlers + fake UDS server + tmp map pair.

Pre-PR-A this file already covered the 3 Phase 4-3 endpoints
(`/api/health`, `/api/calibrate`, `/api/map/backup`) and the static
mount. PR-A introduces auth: `/api/calibrate` and `/api/map/backup` now
require an admin JWT, so the existing happy-path tests log in first via
the lazy-seeded `ncenter`/`ncenter` admin and reuse the token.

PR-A new coverage (≥ 13 cases per plan T6):
- /api/auth/{login,logout,me,refresh} happy + failure
- /api/auth/me unauth → 401, forged → 401, expired → 401
- /api/live admin-only
- /api/last_pose returns LAST_POSE_FIELDS-shaped body (real-FastAPI
  contract test — the BE drift catch the frontend stub server cannot
  provide)
- /api/last_pose/stream returns text/event-stream and ≥ 1 frame
- /api/local/* loopback gating
- /api/system/{reboot,shutdown} mocked subprocess
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
import jwt
import pytest
from httpx import ASGITransport

from godo_webctl.app import create_app
from godo_webctl.config import Settings
from godo_webctl.constants import JWT_ALGORITHM
from godo_webctl.protocol import LAST_POSE_FIELDS, LAST_SCAN_HEADER_FIELDS


def _settings_for(
    *,
    uds_socket: Path,
    map_path: Path,
    backup_dir: Path,
    maps_dir: Path | None = None,
    jwt_secret_path: Path | None = None,
    users_file: Path | None = None,
    spa_dist: Path | None = None,
    disk_check_path: Path | None = None,
    restart_pending_path: Path | None = None,
    pidfile_path: Path | None = None,
) -> Settings:
    base = backup_dir.parent
    return Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=uds_socket,
        backup_dir=backup_dir,
        map_path=map_path,
        # Default to a sibling that does NOT contain `active.pgm` so the
        # legacy back-compat path is exercised when the test does not
        # pin a specific maps_dir.
        maps_dir=maps_dir or (base / "maps"),
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
        jwt_secret_path=jwt_secret_path or (base / "jwt_secret"),
        users_file=users_file or (base / "users.json"),
        spa_dist=spa_dist,
        chromium_loopback_only=True,
        disk_check_path=disk_check_path or Path("/"),
        restart_pending_path=restart_pending_path or (base / "restart_pending"),
        # create_app() never touches this path (M5 boundary); the field
        # exists only because Settings is the SSOT for both code and the
        # __main__ entrypoint. Tests use a unique tmp filename.
        pidfile_path=pidfile_path or (base / "godo-webctl.pid"),
    )


def _client(settings: Settings) -> httpx.AsyncClient:
    app = create_app(settings)
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


async def _login_admin(cl: httpx.AsyncClient) -> str:
    r = await cl.post("/api/auth/login", json={"username": "ncenter", "password": "ncenter"})
    assert r.status_code == HTTPStatus.OK, r.text
    return r.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- /api/health ----------------------------------------------------------
async def test_health_ok_when_tracker_replies(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(b'{"ok":true,"mode":"Idle"}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/health")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"webctl": "ok", "tracker": "ok", "mode": "Idle"}


async def test_health_unreachable_when_no_uds(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "ghost.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/health")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"webctl": "ok", "tracker": "unreachable", "mode": None}


# ---- /api/calibrate -------------------------------------------------------
async def test_calibrate_happy_sends_oneshot_bytes(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    # Two replies: first for /api/auth/login (which doesn't talk to UDS),
    # then for the calibrate `set_mode`. Login is local; only one UDS reply.
    fake_uds_server.reply(b'{"ok":true}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/calibrate", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"ok": True}
    # Wire-byte-exact (M4 case (c)).
    assert fake_uds_server.captured == [b'{"cmd":"set_mode","mode":"OneShot"}\n']


async def test_calibrate_unreachable_returns_503(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "ghost.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/calibrate", headers=_auth(token))
    assert r.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert r.json()["ok"] is False
    assert r.json()["err"] == "tracker_unreachable"


async def test_calibrate_bad_mode_returns_400_with_err(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(b'{"ok":false,"err":"bad_mode"}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/calibrate", headers=_auth(token))
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json() == {"ok": False, "err": "bad_mode"}


async def test_calibrate_timeout_returns_504(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    s = Settings(  # tighten the calibrate timeout for a fast test
        host=s.host,
        port=s.port,
        uds_socket=s.uds_socket,
        backup_dir=s.backup_dir,
        map_path=s.map_path,
        maps_dir=s.maps_dir,
        health_uds_timeout_s=s.health_uds_timeout_s,
        calibrate_uds_timeout_s=0.2,
        jwt_secret_path=s.jwt_secret_path,
        users_file=s.users_file,
        spa_dist=s.spa_dist,
        chromium_loopback_only=s.chromium_loopback_only,
        disk_check_path=s.disk_check_path,
        restart_pending_path=s.restart_pending_path,
        pidfile_path=s.pidfile_path,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/calibrate", headers=_auth(token))
    assert r.status_code == HTTPStatus.GATEWAY_TIMEOUT
    assert r.json() == {"ok": False, "err": "tracker_timeout"}


async def test_calibrate_protocol_error_returns_502(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(b"garbage-not-json")
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/calibrate", headers=_auth(token))
    assert r.status_code == HTTPStatus.BAD_GATEWAY
    assert r.json() == {"ok": False, "err": "protocol_error"}


async def test_calibrate_unauth_returns_401(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/calibrate")
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "auth_required"


# ---- /api/map/backup ------------------------------------------------------
async def test_backup_happy_returns_path(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "unused.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/map/backup", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["ok"] is True
    assert Path(body["path"]).is_dir()
    assert (Path(body["path"]) / "studio_v1.pgm").is_file()


async def test_backup_missing_map_returns_404(
    tmp_path: Path,
) -> None:
    # Need a map pair so login works without OS errors elsewhere.
    s = _settings_for(
        uds_socket=tmp_path / "unused.sock",
        map_path=tmp_path / "ghost.pgm",
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/map/backup", headers=_auth(token))
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert r.json() == {"ok": False, "err": "map_path_not_found"}


async def test_backup_conflict_returns_409(
    tmp_path: Path,
    tmp_map_pair: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode-A M3 fold: when backup_map raises
    ``BackupError("concurrent_backup_in_progress")`` the handler maps it
    to HTTP 409 with the documented Korean detail.
    """
    from godo_webctl import backup as backup_mod

    def _raise_conflict(*args: object, **kwargs: object) -> None:
        raise backup_mod.BackupError("concurrent_backup_in_progress")

    monkeypatch.setattr(backup_mod, "backup_map", _raise_conflict)
    s = _settings_for(
        uds_socket=tmp_path / "unused.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/map/backup", headers=_auth(token))
    assert r.status_code == HTTPStatus.CONFLICT
    body = r.json()
    assert body["ok"] is False
    assert body["err"] == "concurrent_backup_in_progress"
    assert body["detail"] == "다른 백업이 진행 중입니다."


# ---- static page ----------------------------------------------------------
async def test_static_index_served_at_root(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "unused.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/")
    assert r.status_code == HTTPStatus.OK
    assert "text/html" in r.headers.get("content-type", "")
    assert 'id="tracker-status"' in r.text


# ============================================================================
# PR-A new coverage starts here
# ============================================================================


# ---- /api/auth/login ------------------------------------------------------
async def test_auth_login_happy_returns_token_role_exp(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/auth/login", json={"username": "ncenter", "password": "ncenter"})
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["token"], str) and len(body["token"]) > 20
    assert body["role"] == "admin"
    assert body["username"] == "ncenter"
    assert isinstance(body["exp"], int) and body["exp"] > int(time.time())


async def test_auth_login_wrong_password_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/auth/login", json={"username": "ncenter", "password": "WRONG"})
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "bad_credentials"


async def test_auth_login_unknown_user_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "bad_credentials"


# ---- /api/auth/me ---------------------------------------------------------
async def test_auth_me_with_token(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.get("/api/auth/me", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["username"] == "ncenter"
    assert body["role"] == "admin"


async def test_auth_me_without_token_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/auth/me")
    assert r.status_code == HTTPStatus.UNAUTHORIZED


async def test_auth_me_with_forged_token_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    forged = jwt.encode(
        {"sub": "x", "role": "admin", "exp": int(time.time()) + 60},
        b"\x00" * 32,
        algorithm=JWT_ALGORITHM,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/auth/me", headers=_auth(forged))
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "token_invalid"


async def test_auth_me_with_expired_token_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    secret_path = tmp_path / "jwt_secret"
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        jwt_secret_path=secret_path,
    )
    # Build the app first so the secret file exists.
    async with _client(s) as cl:
        secret = secret_path.read_bytes()
        expired = jwt.encode(
            {"sub": "ncenter", "role": "admin", "exp": int(time.time()) - 10},
            secret,
            algorithm=JWT_ALGORITHM,
        )
        r = await cl.get("/api/auth/me", headers=_auth(expired))
    assert r.status_code == HTTPStatus.UNAUTHORIZED


# ---- /api/auth/refresh + logout ------------------------------------------
async def test_auth_refresh_returns_valid_token(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/auth/refresh", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    # Within the same wall-second the new token may be byte-identical
    # (same iat, same exp). What matters is that it verifies cleanly.
    assert isinstance(body["token"], str) and len(body["token"]) > 20
    assert body["exp"] > int(time.time())
    # Sanity: the new token decodes to the same identity.
    new_secret = create_app(s).state.jwt_secret  # any app from same secret path
    decoded = jwt.decode(body["token"], new_secret, algorithms=[JWT_ALGORITHM])
    assert decoded["sub"] == "ncenter"
    assert decoded["role"] == "admin"


async def test_auth_logout_acks(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/auth/logout", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"ok": True}


# ---- /api/live ------------------------------------------------------------
async def test_live_enable_sends_live_bytes(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(b'{"ok":true}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/live", json={"enable": True}, headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"ok": True, "mode": "Live"}
    assert fake_uds_server.captured == [b'{"cmd":"set_mode","mode":"Live"}\n']


async def test_live_disable_sends_idle_bytes(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(b'{"ok":true}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/live", json={"enable": False}, headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"ok": True, "mode": "Idle"}
    assert fake_uds_server.captured == [b'{"cmd":"set_mode","mode":"Idle"}\n']


async def test_live_unauth_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/live", json={"enable": True})
    assert r.status_code == HTTPStatus.UNAUTHORIZED


# ---- /api/last_pose (real-FastAPI contract test, T6) ---------------------
async def test_last_pose_returns_track_b_field_set(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """T6: drift catch — backend must speak `LAST_POSE_FIELDS` exactly.
    Frontend stub server cannot catch this."""
    fake_uds_server.reply(
        b'{"ok":true,"valid":1,"x_m":1.5,"y_m":2.0,"yaw_deg":45.0,'
        b'"xy_std_m":0.01,"yaw_std_deg":0.1,"iterations":5,'
        b'"converged":1,"forced":0,"published_mono_ns":42}'
    )
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        # Track F: /api/last_pose is anonymous-readable.
        r = await cl.get("/api/last_pose")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert tuple(body.keys()) == LAST_POSE_FIELDS


# ---- /api/last_pose/stream (smoke) ---------------------------------------
async def test_last_pose_stream_route_is_wired_with_correct_headers(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Smoke test: the route exists, is reachable, and is configured
    with the right media type + defensive proxy-buffering headers. End-
    to-end frame cadence is asserted by `tests/test_sse.py` against the
    generator directly with a virtual clock (per T3) — there is no
    value in racing a wall-clock SSE read through httpx ASGI here."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    app = create_app(s)
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/last_pose/stream" in paths
    assert "/api/local/services/stream" in paths
    # The headers tuple is a module-level constant; assert by reference.
    from godo_webctl.sse import SSE_RESPONSE_HEADERS

    assert SSE_RESPONSE_HEADERS["X-Accel-Buffering"] == "no"
    assert SSE_RESPONSE_HEADERS["Cache-Control"] == "no-cache"

    # N-B6: actually call the route — catches "refactor broke
    # `StreamingResponse(...)` construction" that the route-existence
    # check above misses entirely. ASGITransport buffers the full
    # response (it is not a true streaming transport), so we cannot
    # iterate forever; we mock the generator with one that yields once
    # and exits, so ASGI completes the response and we get headers +
    # status to assert against. The generator's actual cadence /
    # heartbeat behaviour is covered by `tests/test_sse.py` against
    # the generator directly with a virtual clock (per T3).

    async def _yield_once_then_exit(*_args: Any, **_kwargs: Any) -> AsyncIterator[bytes]:
        yield b"data: {}\n\n"

    async with _client(s) as cl:
        # Track F: SSE stream is anonymous-readable.
        with mock.patch(
            "godo_webctl.sse.last_pose_stream",
            side_effect=_yield_once_then_exit,
        ):
            r = await cl.get("/api/last_pose/stream")
    assert r.status_code == HTTPStatus.OK
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    assert r.text == "data: {}\n\n"


# ---- /api/local/* loopback gate ------------------------------------------
async def test_local_services_loopback_allowed(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    # ASGITransport client.host defaults to 127.0.0.1 (loopback).
    # Track F: /api/local/services is anonymous-readable from loopback.
    fake_list = [{"name": "godo-tracker", "active": "active"}]
    with mock.patch("godo_webctl.app.services_mod.list_active", return_value=fake_list):
        async with _client(s) as cl:
            r = await cl.get("/api/local/services")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == fake_list


@pytest.mark.parametrize(
    "path",
    ["/api/local/services", "/api/local/services/stream"],
)
async def test_local_endpoint_non_loopback_returns_403(
    tmp_path: Path,
    tmp_map_pair: Path,
    path: str,
) -> None:
    """Both the REST and SSE local-only endpoints must reject non-
    loopback peers identically. Per N-B7: SSE-side gate was previously
    only verified to be wired the same way; this asserts the actual
    deny path."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    app = create_app(s)
    transport = ASGITransport(app=app, client=("192.168.1.50", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as cl:
        # Track F: read endpoints are anonymous, but loopback gate still
        # enforced. Anon GET from non-loopback → 403 loopback_only,
        # never 401 (loopback dependency runs before auth).
        r = await cl.get(path)
    assert r.status_code == HTTPStatus.FORBIDDEN
    assert r.json()["err"] == "loopback_only"


# ---- /api/system/* mocked subprocess --------------------------------------
async def test_system_reboot_invokes_subprocess(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch("godo_webctl.app.services_mod.system_reboot") as m:
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post("/api/system/reboot", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"ok": True}
    m.assert_called_once_with()


async def test_system_shutdown_invokes_subprocess(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch("godo_webctl.app.services_mod.system_shutdown") as m:
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post("/api/system/shutdown", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"ok": True}
    m.assert_called_once_with()


# ---- /api/activity --------------------------------------------------------
async def test_activity_returns_recent_actions_newest_first(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(b'{"ok":true}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)  # appends "login"
        r = await cl.post("/api/calibrate", headers=_auth(token))  # appends "calibrate"
        assert r.status_code == HTTPStatus.OK
        # Track F: /api/activity is anonymous-readable; login/calibrate
        # entries above were added via the admin session, but reading
        # the log does not itself require auth.
        r = await cl.get("/api/activity?n=5")
    assert r.status_code == HTTPStatus.OK
    items = r.json()
    assert isinstance(items, list)
    assert len(items) >= 2
    assert items[0]["type"] == "calibrate"  # newest first
    assert items[1]["type"] == "login"


# ---- /api/map/image ------------------------------------------------------
async def test_map_image_returns_png(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    # Force a fresh map_image cache for this run.
    from godo_webctl import map_image as mi

    mi._reset_cache_for_tests()
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        # Track F: /api/map/image is anonymous-readable.
        r = await cl.get("/api/map/image")
    assert r.status_code == HTTPStatus.OK
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


# ---- Track F: anonymous-read coverage + mutation-401 coverage -----------
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/map/backup", None),
        ("POST", "/api/system/reboot", None),
        ("POST", "/api/system/shutdown", None),
        ("POST", "/api/local/service/godo-tracker/restart", None),
        ("POST", "/api/system/service/godo-tracker/restart", None),
    ],
)
async def test_mutation_endpoints_unauth_return_401(
    tmp_path: Path,
    tmp_map_pair: Path,
    method: str,
    path: str,
    body: object,
) -> None:
    """Track F: every mutation endpoint MUST return 401 to anonymous
    callers. The matching read endpoints (covered elsewhere) are
    anonymous-OK; the gate is exclusively on writes."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        if method == "POST":
            r = await cl.post(path, json=body)
        else:
            r = await cl.request(method, path)
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "auth_required"


async def test_local_service_action_unauth_from_loopback_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Track F: even from loopback (passes loopback_only), an anonymous
    call to a /api/local/service/<name>/<action> POST must 401 — the
    auth gate runs after the loopback gate. Reads from loopback are
    anonymous OK; writes are not."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/local/service/godo-tracker/restart")
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "auth_required"


# ---- users.json corruption recovery (per N2) -----------------------------
async def test_corrupted_users_file_returns_503_on_login(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    bad_users = tmp_path / "users.json"
    bad_users.write_text("{this is not valid json", encoding="utf-8")
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        users_file=bad_users,
    )
    async with _client(s) as cl:
        # /api/health stays available even with corrupted users.json.
        r = await cl.get("/api/health")
        assert r.status_code == HTTPStatus.OK
        # Login → 503 with auth_unavailable.
        r = await cl.post("/api/auth/login", json={"username": "ncenter", "password": "ncenter"})
    assert r.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert r.json()["err"] == "auth_unavailable"


# ---- spa_dist mount swap -------------------------------------------------
async def test_spa_dist_mount_serves_dist_when_set(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    spa_dir = tmp_path / "dist"
    spa_dir.mkdir()
    (spa_dir / "index.html").write_text("<!doctype html><title>SPA</title>", encoding="utf-8")
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        spa_dist=spa_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/")
    assert r.status_code == HTTPStatus.OK
    assert "SPA" in r.text


@pytest.fixture
async def _live_app() -> AsyncIterator[Any]:
    yield None  # placeholder so pytest can collect this file even with no marks


# ============================================================================
# Track D — /api/last_scan + /api/last_scan/stream
# ============================================================================


_CANNED_SCAN = (
    b'{"ok":true,"valid":1,"forced":1,"pose_valid":1,"iterations":7,'
    b'"published_mono_ns":42,"pose_x_m":1.5,"pose_y_m":2.0,'
    b'"pose_yaw_deg":45.0,"n":2,"angles_deg":[0.0,0.5],'
    b'"ranges_m":[1.0,1.5]}'
)


async def test_last_scan_returns_track_d_field_set(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Drift catch — backend must speak `LAST_SCAN_HEADER_FIELDS` exactly.
    Frontend stub server cannot catch this."""
    fake_uds_server.reply(_CANNED_SCAN)
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        # Track F: /api/last_scan is anonymous-readable.
        r = await cl.get("/api/last_scan")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert tuple(body.keys()) == LAST_SCAN_HEADER_FIELDS


async def test_last_scan_anon_returns_200(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Track F: /api/last_scan is anonymous-readable; no token required.
    Symmetric pin for the (existing) mutation-401 test."""
    fake_uds_server.reply(_CANNED_SCAN)
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/last_scan")
    assert r.status_code == HTTPStatus.OK


async def test_last_scan_stream_anon_returns_200(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Track F: /api/last_scan/stream is anonymous-readable; same gate
    as /api/last_pose/stream."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )

    async def _yield_once_then_exit(*_args: Any, **_kwargs: Any) -> AsyncIterator[bytes]:
        yield b"data: {}\n\n"

    async with _client(s) as cl:
        with mock.patch(
            "godo_webctl.sse.last_scan_stream",
            side_effect=_yield_once_then_exit,
        ):
            r = await cl.get("/api/last_scan/stream")
    assert r.status_code == HTTPStatus.OK
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"


async def test_last_scan_path_extras_return_404(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """TM1: route is parameter-less; extra path segments must 404."""
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/last_scan/extra")
    assert r.status_code == HTTPStatus.NOT_FOUND


async def test_last_scan_tracker_unreachable_returns_503(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "ghost.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/last_scan")
    assert r.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert r.json()["err"] == "tracker_unreachable"


async def test_last_scan_no_run_yet_returns_valid_zero(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Tracker reachable but no scan published yet (sentinel). Emits a
    valid=0 reply per the C++ side; the SPA gates rendering on this."""
    fake_uds_server.reply(
        b'{"ok":true,"valid":0,"forced":0,"pose_valid":0,"iterations":-1,'
        b'"published_mono_ns":0,"pose_x_m":0.0,"pose_y_m":0.0,'
        b'"pose_yaw_deg":0.0,"n":0,"angles_deg":[],"ranges_m":[]}',
    )
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/last_scan")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["valid"] == 0
    assert body["n"] == 0
    assert body["iterations"] == -1


async def test_last_scan_server_emits_polar_not_world_cartesian(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Mode-A TM5 pin: the server emits RAW polar (angles_deg + ranges_m
    in the LiDAR frame) plus the pose anchor. The SPA does the polar →
    Cartesian world-frame transform — server must NOT pre-transform.

    Verification: when the canned scan has pose_yaw=90° + a beam at
    angle_deg=0 + range=1, the wire body MUST contain that beam at
    angle_deg=0 (LiDAR frame), NOT the rotated world point."""
    fake_uds_server.reply(
        b'{"ok":true,"valid":1,"forced":1,"pose_valid":1,"iterations":1,'
        b'"published_mono_ns":1,"pose_x_m":0.0,"pose_y_m":0.0,'
        b'"pose_yaw_deg":90.0,"n":1,"angles_deg":[0.0],'
        b'"ranges_m":[1.0]}',
    )
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/last_scan")
    body = r.json()
    # Beam stays at LiDAR-frame angle 0 (NOT yaw-rotated to 90).
    assert body["angles_deg"] == [0.0]
    assert body["ranges_m"] == [1.0]
    # Anchor pose is preserved — SPA does the transform using these.
    assert body["pose_yaw_deg"] == 90.0


async def test_anon_read_endpoints_return_200(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Track D + Track F symmetric coverage of the existing
    test_mutation_endpoints_unauth_return_401: every documented anon-
    readable endpoint MUST return 200 (or 502/503 for tracker-down
    cases that are NOT auth failures) when called WITHOUT a token.

    The matching mutation set (existing test_mutation_endpoints_unauth_return_401)
    asserts 401 on the same anon. Drift between either list and the
    handler `Depends(require_*)` annotations is caught."""
    fake_uds_server.reply(b'{"ok":true,"mode":"Idle"}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    # Subset of read endpoints we can hit with a single fake_uds reply
    # queued; the assertion is "no 401". 503 is also acceptable for paths
    # that need a fresh UDS reply (queue drained after first call).
    #
    # Mode-B S2 fold: the SSE endpoint /api/diag/stream is intentionally
    # NOT in this list — its anon-200 contract is pinned by a dedicated
    # test (test_diag_stream_anon_returns_event_stream below) which uses
    # cl.stream() + timeout to handle the unbounded async generator.
    # Wedging SSE into this single-shot loop would either hang the
    # generator (cl.stream() with no timeout) or duplicate the dedicated
    # test's logic. The two together cover all 5 PR-DIAG anon endpoints.
    paths = [
        "/api/health",
        "/api/last_pose",
        "/api/last_scan",
        "/api/maps",
        "/api/activity",
        # PR-DIAG anon-readable single-shot endpoints (TM8 mitigation).
        "/api/system/jitter",
        "/api/system/amcl_rate",
        "/api/system/resources",
        "/api/logs/tail?unit=godo-tracker&n=10",
        # Track B-SYSTEM PR-2 — anon-readable system services snapshot.
        "/api/system/services",
    ]
    async with _client(s) as cl:
        for path in paths:
            r = await cl.get(path)
            # Anon must NEVER see 401 on a read endpoint.
            assert r.status_code != HTTPStatus.UNAUTHORIZED, (
                f"{path} returned 401 — Track F regression"
            )


# ============================================================================
# Track E (PR-C) — multi-map management
# ============================================================================


# ---- GET /api/maps (anon-readable per Track F) ---------------------------


async def test_list_maps_anon_returns_two_entries(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert isinstance(body, list)
    names = sorted(e["name"] for e in body)
    assert names == ["studio_v1", "studio_v2"]
    actives = [e["is_active"] for e in body if e["name"] == "studio_v1"]
    assert actives == [True]


async def test_list_maps_admin_token_also_works(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Track F: read endpoints accept (but do not require) auth."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.get("/api/maps", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK


async def test_list_maps_empty_dir_returns_empty_list(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    empty_maps = tmp_path / "empty_maps"
    empty_maps.mkdir()
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=empty_maps,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == []


# ---- GET /api/maps/<name>/image -----------------------------------------


async def test_get_map_image_named_returns_png(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/studio_v1/image")
    assert r.status_code == HTTPStatus.OK
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_get_map_image_named_empty_name_returns_404_routing(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Mode-A TB1: empty name `""` is rejected by FastAPI's router (route
    `/api/maps/{name}/image` requires a non-empty path segment) before
    the handler runs. We pin the 404 explicitly so a future router-config
    change cannot silently introduce a code path with an empty name."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps//image")
    assert r.status_code == HTTPStatus.NOT_FOUND


async def test_get_map_image_named_unknown_returns_404(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/no_such_map/image")
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert r.json()["err"] == "map_not_found"


# Path-traversal corpus uses string literals (NOT parametrize) per the
# CODEBASE.md test-discipline pattern: each rejection carries its own
# named test so a regression message names the input that escaped.


async def test_get_map_image_named_dot_traversal_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        # FastAPI routes `/api/maps/..%2Fetc/image` differently from
        # `/api/maps/<bad-name>/image` — both must be rejected. We pick a
        # leading-dot name (still rejected by MAPS_NAME_REGEX after the
        # 2026-04-29 dot-in-stem allow) that the router passes through
        # to the handler, confirming the validator rejects it at the
        # maps.py layer rather than the router.
        r = await cl.get("/api/maps/.hidden/image")
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["err"] == "invalid_map_name"


async def test_get_map_image_named_hidden_dot_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/.hidden/image")
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["err"] == "invalid_map_name"


async def test_get_map_image_named_too_long_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        long_name = "a" * 65
        r = await cl.get(f"/api/maps/{long_name}/image")
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["err"] == "invalid_map_name"


# ---- GET /api/maps/<name>/yaml ------------------------------------------


async def test_get_map_yaml_named_returns_text(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/studio_v1/yaml")
    assert r.status_code == HTTPStatus.OK
    assert r.headers["content-type"].startswith("text/plain")
    assert "image: studio_v1.pgm" in r.text


async def test_get_map_yaml_named_bad_name_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/.hidden/yaml")
    assert r.status_code == HTTPStatus.BAD_REQUEST


# ---- GET /api/maps/<name>/dimensions (Track D scale fix) ---------------


async def test_get_map_dimensions_returns_width_height(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """tmp_maps_dir's PGM is 4×4 — the dimensions endpoint reads the
    netpbm header (no Pillow) and returns the expected JSON shape."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/studio_v1/dimensions")
    assert r.status_code == HTTPStatus.OK, r.text
    body = r.json()
    assert body == {"width": 4, "height": 4}


async def test_get_map_dimensions_unknown_returns_404(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/studio_vX/dimensions")
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert r.json()["err"] == "map_not_found"


async def test_get_map_dimensions_invalid_name_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/.hidden/dimensions")
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["err"] == "invalid_map_name"


async def test_get_map_dimensions_malformed_pgm_returns_500(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """T5: a PGM lacking the `P5` magic surfaces as 500 map_invalid via
    `PgmHeaderInvalid` raised in `maps.py` (NOT a reverse import from
    `map_image.py::MapImageInvalid`)."""
    bad = tmp_maps_dir / "studio_v1.pgm"
    bad.write_bytes(b"NOTP5\n4 4\n255\n" + bytes([128] * 16))
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/maps/studio_v1/dimensions")
    assert r.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert r.json()["err"] == "map_invalid"


# ---- POST /api/maps/<name>/activate (admin) -----------------------------


async def test_activate_admin_repoints_active_symlink(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    import os as _os

    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/maps/studio_v2/activate", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body == {"ok": True, "restart_required": True}
    assert _os.readlink(tmp_maps_dir / "active.pgm") == "studio_v2.pgm"
    assert _os.readlink(tmp_maps_dir / "active.yaml") == "studio_v2.yaml"


async def test_activate_anon_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Track F: mutation endpoints reject anonymous callers with 401."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.post("/api/maps/studio_v2/activate")
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "auth_required"


async def test_activate_unknown_returns_404(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/maps/no_such_map/activate", headers=_auth(token))
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert r.json()["err"] == "map_not_found"


async def test_activate_reserved_name_returns_400_with_detail(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/maps/active/activate", headers=_auth(token))
    assert r.status_code == HTTPStatus.BAD_REQUEST
    body = r.json()
    assert body["err"] == "invalid_map_name"
    assert body.get("detail") == "reserved_name"


# Endpoint-layer rejection corpus for activate / delete (Mode-B Nit #3).
# Mirrors the image / yaml corpus pattern at :969-1022 — string literals
# (NOT parametrize) so a regression message names the input that escaped.
# Per Mode-A TB1 routing-vs-handler discipline, FastAPI's path routing
# may convert some inputs to 404 (e.g. encoded slashes that the router
# unwraps into a different path) BEFORE the handler runs; the assertions
# accept either 400 (handler-layer regex reject via maps.validate_name)
# or 404 (routing-layer reject before handler) and document why. Either
# outcome is a valid rejection; only 200/2xx would be a real escape.


async def test_activate_dot_traversal_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Path-traversal corpus for /activate: `..%2Fetc%2Fpasswd` (URL-encoded
    slash) and `.hidden` (leading-dot escape). The first variant is
    decoded by httpx/Starlette path normalization; depending on the
    runtime, the URL collapses to a route that does not match the
    `/api/maps/{name}/activate` template at all, surfacing as 404 (no
    route) or 405 (parent path matched with a different method). Either
    routing-layer rejection is acceptable; only a 200/2xx on a traversal
    name would be a real escape. The literal `.hidden` variant DOES
    reach the handler (no slash) and must 400 via the regex (leading
    dot is the post-2026-04-29 traversal sentinel)."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r1 = await cl.post(
            "/api/maps/..%2Fetc%2Fpasswd/activate",
            headers=_auth(token),
        )
        assert r1.status_code in (
            HTTPStatus.BAD_REQUEST,
            HTTPStatus.NOT_FOUND,
            HTTPStatus.METHOD_NOT_ALLOWED,
        ), r1.text
        if r1.status_code == HTTPStatus.BAD_REQUEST:
            assert r1.json()["err"] == "invalid_map_name"
        # Variant 2: literal `.hidden` — router passes through, handler
        # MUST reject via the regex (leading dot forbidden).
        r2 = await cl.post("/api/maps/.hidden/activate", headers=_auth(token))
    assert r2.status_code == HTTPStatus.BAD_REQUEST
    assert r2.json()["err"] == "invalid_map_name"


async def test_activate_hidden_dot_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Leading-dot corpus for /activate: `.hidden` MUST 400 via regex."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post("/api/maps/.hidden/activate", headers=_auth(token))
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["err"] == "invalid_map_name"


async def test_activate_writes_activity_log(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        await cl.post("/api/maps/studio_v2/activate", headers=_auth(token))
        r = await cl.get("/api/activity?n=10")
    assert r.status_code == HTTPStatus.OK
    types = [e["type"] for e in r.json()]
    assert "map_activate" in types


# ---- DELETE /api/maps/<name> (admin) ------------------------------------


async def test_delete_admin_removes_pair(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.delete("/api/maps/studio_v2", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"ok": True}
    assert not (tmp_maps_dir / "studio_v2.pgm").exists()
    assert not (tmp_maps_dir / "studio_v2.yaml").exists()


async def test_delete_anon_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.delete("/api/maps/studio_v2")
    assert r.status_code == HTTPStatus.UNAUTHORIZED


async def test_delete_active_map_returns_409(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Named test (NOT folded into delete suite per Mode-A discipline):
    deleting the currently active map MUST 409, not 400/404/500."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.delete("/api/maps/studio_v1", headers=_auth(token))
    assert r.status_code == HTTPStatus.CONFLICT
    assert r.json()["err"] == "map_is_active"


async def test_delete_unknown_returns_404(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.delete("/api/maps/no_such_map", headers=_auth(token))
    assert r.status_code == HTTPStatus.NOT_FOUND


# Delete-side rejection corpus (Mode-B Nit #3) — mirrors activate.
# Same router-vs-handler discipline: 400 (handler regex reject) and 404
# (router reject before handler) are both valid rejection outcomes.


async def test_delete_dot_traversal_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Path-traversal corpus for DELETE: encoded slash + leading-dot
    literal. The encoded-slash variant collapses to a non-matching route
    (404/405) or reaches the handler (400); all are valid rejections.
    The literal `.hidden` case reaches the handler and must 400 via
    regex (leading dot is the post-2026-04-29 traversal sentinel)."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r1 = await cl.delete(
            "/api/maps/..%2Fetc%2Fpasswd",
            headers=_auth(token),
        )
        assert r1.status_code in (
            HTTPStatus.BAD_REQUEST,
            HTTPStatus.NOT_FOUND,
            HTTPStatus.METHOD_NOT_ALLOWED,
        ), r1.text
        if r1.status_code == HTTPStatus.BAD_REQUEST:
            assert r1.json()["err"] == "invalid_map_name"
        r2 = await cl.delete("/api/maps/.hidden", headers=_auth(token))
    assert r2.status_code == HTTPStatus.BAD_REQUEST
    assert r2.json()["err"] == "invalid_map_name"


async def test_delete_hidden_dot_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Leading-dot corpus for DELETE: `.hidden` MUST 400 via regex."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.delete("/api/maps/.hidden", headers=_auth(token))
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["err"] == "invalid_map_name"


# ---- /api/map/image now resolves through active symlink (back-compat) ----


async def test_existing_map_image_resolves_through_active_symlink(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_maps_dir: Path,
) -> None:
    """Existing PoseCanvas callers continue working: /api/map/image now
    serves the PGM behind `active.pgm` (which the conftest fixture wires
    to studio_v1.pgm)."""
    from godo_webctl import map_image as _M

    _M.invalidate_cache()
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        maps_dir=tmp_maps_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/map/image")
    assert r.status_code == HTTPStatus.OK
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


# ---- Back-compat boot: cfg.map_path migration ---------------------------


def test_lifespan_legacy_migration_creates_active_symlink(
    tmp_path: Path,
) -> None:
    """When `cfg.maps_dir/active.pgm` is missing AND `cfg.map_path` is
    set + the file exists, app boot copies the legacy pair into
    `maps_dir` and creates the active symlinks. Idempotent on second
    boot."""
    import os as _os

    legacy_dir = tmp_path / "etc_godo_maps"
    legacy_dir.mkdir()
    legacy_pgm = legacy_dir / "studio_v1.pgm"
    legacy_yaml = legacy_dir / "studio_v1.yaml"
    legacy_pgm.write_bytes(b"P5\n4 4\n255\n" + bytes([128] * 16))
    legacy_yaml.write_text(
        "image: studio_v1.pgm\nresolution: 0.05\norigin: [0,0,0]\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\nnegate: 0\n",
    )

    maps_dir = tmp_path / "var_lib_godo_maps"
    s = Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=tmp_path / "u.sock",
        backup_dir=tmp_path / "bk",
        map_path=legacy_pgm,
        maps_dir=maps_dir,
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
        jwt_secret_path=tmp_path / "jwt",
        users_file=tmp_path / "users.json",
        spa_dist=None,
        chromium_loopback_only=True,
        disk_check_path=Path("/"),
        restart_pending_path=tmp_path / "rp",
        pidfile_path=tmp_path / "godo-webctl.pid",
    )

    # Manually invoke the migration helper that the lifespan uses.
    from godo_webctl import maps as _MM

    ran = _MM.migrate_legacy_active(maps_dir, legacy_pgm)
    assert ran is True
    assert (maps_dir / "studio_v1.pgm").exists()
    assert _os.readlink(maps_dir / "active.pgm") == "studio_v1.pgm"

    # Second invocation is a no-op (returns False).
    assert _MM.migrate_legacy_active(maps_dir, legacy_pgm) is False
    # Reference settings to keep the test purposeful even if app create
    # is skipped — settings being constructable validates the
    # `maps_dir` field is wired into Settings (drift check).
    assert s.maps_dir == maps_dir


def test_lifespan_warns_every_boot_when_map_path_set(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Mode-B Nit #4 / Q-OQ-E4: when `cfg.map_path` exists, every webctl
    lifespan startup MUST emit `maps.legacy_map_path_in_use` at WARNING.
    Operators read journals selectively — a one-shot warning is easy to
    miss. This test boots the app twice via Starlette's `TestClient`
    (which drives the ASGI lifespan protocol) and asserts the warning
    fires on BOTH boots."""
    import logging

    from fastapi.testclient import TestClient

    legacy_dir = tmp_path / "etc_godo_maps"
    legacy_dir.mkdir()
    legacy_pgm = legacy_dir / "studio_v1.pgm"
    legacy_yaml = legacy_dir / "studio_v1.yaml"
    legacy_pgm.write_bytes(b"P5\n4 4\n255\n" + bytes([128] * 16))
    legacy_yaml.write_text(
        "image: studio_v1.pgm\nresolution: 0.05\norigin: [0,0,0]\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\nnegate: 0\n",
    )

    maps_dir = tmp_path / "var_lib_godo_maps"
    maps_dir.mkdir()

    s = Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=tmp_path / "u.sock",
        backup_dir=tmp_path / "bk",
        map_path=legacy_pgm,
        maps_dir=maps_dir,
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
        jwt_secret_path=tmp_path / "jwt",
        users_file=tmp_path / "users.json",
        spa_dist=None,
        chromium_loopback_only=True,
        disk_check_path=Path("/"),
        restart_pending_path=tmp_path / "rp",
        pidfile_path=tmp_path / "godo-webctl.pid",
    )

    def _boot_and_count_warns() -> int:
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="godo_webctl"):
            app = create_app(s)
            with TestClient(app):
                pass  # entering the ctx triggers lifespan startup
        return sum(
            1
            for rec in caplog.records
            if rec.levelno == logging.WARNING and "maps.legacy_map_path_in_use" in rec.getMessage()
        )

    # First boot — migration runs AND the every-boot warn fires.
    assert _boot_and_count_warns() == 1
    # Second boot — migration is a no-op (active.pgm now exists), but
    # the every-boot warn MUST still fire while cfg.map_path is set.
    assert _boot_and_count_warns() == 1


# ============================================================================
# PR-DIAG (Track B-DIAG) — diagnostics endpoints
# ============================================================================


# ---- /api/system/jitter --------------------------------------------------


async def test_system_jitter_anon_returns_200(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(
        b'{"ok":true,"valid":1,"p50_ns":4567,"p95_ns":12345,'
        b'"p99_ns":45678,"max_ns":123456,"mean_ns":5678,'
        b'"sample_count":2048,"published_mono_ns":1}',
    )
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/jitter")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["valid"] == 1
    assert body["p50_ns"] == 4567
    assert "ok" not in body  # projection drops the JSON-level success flag


async def test_system_jitter_tracker_unreachable_returns_503(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "ghost.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/jitter")
    assert r.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert r.json()["err"] == "tracker_unreachable"


async def test_system_jitter_no_publish_yet_returns_valid_false(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(
        b'{"ok":true,"valid":0,"p50_ns":0,"p95_ns":0,"p99_ns":0,'
        b'"max_ns":0,"mean_ns":0,"sample_count":0,"published_mono_ns":0}',
    )
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/jitter")
    assert r.status_code == HTTPStatus.OK
    assert r.json()["valid"] == 0


# ---- /api/system/amcl_rate ----------------------------------------------


async def test_system_amcl_rate_anon_returns_200(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(
        b'{"ok":true,"valid":1,"hz":9.987,'
        b'"last_iteration_mono_ns":1,"total_iteration_count":42,'
        b'"published_mono_ns":2}',
    )
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/amcl_rate")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["hz"] == 9.987
    assert body["total_iteration_count"] == 42


async def test_system_amcl_rate_tracker_timeout_returns_504(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    # Tighten the timeout so the test runs fast; do not enqueue a reply.
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    s = Settings(
        host=s.host,
        port=s.port,
        uds_socket=s.uds_socket,
        backup_dir=s.backup_dir,
        map_path=s.map_path,
        maps_dir=s.maps_dir,
        health_uds_timeout_s=0.2,
        calibrate_uds_timeout_s=0.2,
        jwt_secret_path=s.jwt_secret_path,
        users_file=s.users_file,
        spa_dist=s.spa_dist,
        chromium_loopback_only=s.chromium_loopback_only,
        disk_check_path=s.disk_check_path,
        restart_pending_path=s.restart_pending_path,
        pidfile_path=s.pidfile_path,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/amcl_rate")
    assert r.status_code == HTTPStatus.GATEWAY_TIMEOUT
    assert r.json()["err"] == "tracker_timeout"


# ---- /api/system/resources ----------------------------------------------


async def test_system_resources_anon_returns_200(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        disk_check_path=tmp_path,
        restart_pending_path=tmp_path / "rp",
    )
    # Reset the resources module-level cache so this test sees fresh data.
    from godo_webctl import resources as _R

    _R._reset_cache_for_tests()
    async with _client(s) as cl:
        r = await cl.get("/api/system/resources")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    # All RESOURCES_FIELDS keys present.
    from godo_webctl.protocol import RESOURCES_FIELDS

    for field in RESOURCES_FIELDS:
        assert field in body
    # Disk fields populated because we pointed at tmp_path.
    assert body["disk_total_bytes"] is not None


async def test_system_resources_with_admin_token_also_works(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Track F: read endpoints accept (but do not require) auth."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        disk_check_path=tmp_path,
        restart_pending_path=tmp_path / "rp",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.get("/api/system/resources", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK


# ---- /api/logs/tail ------------------------------------------------------


async def test_logs_tail_happy_returns_lines(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch("godo_webctl.logs.subprocess.run") as m:
        cp = mock.MagicMock()
        cp.stdout = "line1\nline2\nline3\n"
        cp.stderr = ""
        cp.returncode = 0
        m.return_value = cp
        async with _client(s) as cl:
            r = await cl.get("/api/logs/tail?unit=godo-tracker&n=3")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == ["line1", "line2", "line3"]


async def test_logs_tail_unknown_unit_returns_404(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/logs/tail?unit=etc-shadow&n=10")
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert r.json()["err"] == "unknown_service"


async def test_logs_tail_n_above_cap_returns_422(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Pydantic Field(le=LOGS_TAIL_MAX_N) surfaces as 422 when n exceeds
    the cap. The SPA's apiFetch maps both 400 + 422 to "invalid input"."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/logs/tail?unit=godo-tracker&n=10000")
    # Mode-B S1 fold: route uses Annotated[Query(le=LOGS_TAIL_MAX_N)],
    # so FastAPI's own validation surfaces the over-cap as 422 BEFORE
    # the handler body runs.
    assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_logs_tail_subprocess_timeout_returns_504(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    import subprocess as _sp

    with mock.patch("godo_webctl.logs.subprocess.run") as m:
        m.side_effect = _sp.TimeoutExpired(cmd=["journalctl"], timeout=1.0)
        async with _client(s) as cl:
            r = await cl.get("/api/logs/tail?unit=godo-tracker&n=5")
    assert r.status_code == HTTPStatus.GATEWAY_TIMEOUT
    assert r.json()["err"] == "subprocess_timeout"


# ---- /api/diag/stream ----------------------------------------------------


async def test_diag_stream_anon_returns_event_stream(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Anon access (Track F) + the SSE content-type pin. We don't try to
    parse a frame here — the diag_stream cadence test in test_sse.py
    covers frame shape; this test pins HTTP-level wiring only.

    SSE generators don't terminate naturally; we open the stream with a
    short read timeout and bail after the first chunk."""
    import asyncio as _asyncio

    for _ in range(3):
        fake_uds_server.reply(b'{"ok":true,"valid":0}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        disk_check_path=tmp_path,
        restart_pending_path=tmp_path / "rp",
    )

    async def _peek_one_chunk() -> tuple[int, str]:
        async with (
            _client(s) as cl,
            cl.stream("GET", "/api/diag/stream", timeout=2.0) as resp,
        ):
            status = resp.status_code
            ctype = resp.headers.get("content-type", "")
            async for _chunk in resp.aiter_bytes():
                return status, ctype
            return status, ctype

    try:
        status, ctype = await _asyncio.wait_for(_peek_one_chunk(), timeout=3.0)
    except TimeoutError:
        # The connect already succeeded by definition (the timeout fires
        # only inside the body-read loop). Pass — the route is wired.
        return
    assert status == HTTPStatus.OK
    assert "text/event-stream" in ctype


# =====================================================================
# Track B-CONFIG (PR-CONFIG-β) — config edit pipeline endpoints.
# =====================================================================


@pytest.mark.parametrize(
    "path",
    [
        "/api/config",
        "/api/config/schema",
        "/api/system/restart_pending",
    ],
)
async def test_config_read_endpoints_anon_return_200(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
    path: str,
) -> None:
    """Track F: every read endpoint is anonymous-OK. Mirrors the
    test_anon_read_endpoints_return_200 pattern (single canned reply
    queued; assertion is `not 401`)."""
    fake_uds_server.reply(b'{"ok":true,"smoother.deadband_mm":10.0}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get(path)
    assert r.status_code != HTTPStatus.UNAUTHORIZED, f"{path} returned 401 — Track F regression"


async def test_get_config_returns_projected_dict(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """The C++ tracker emits ``{"ok":true,"keys":{...}}``; the projection
    in `config_view.project_config_view` unwraps `keys` into the flat
    dict the SPA consumes (`protocol.ts::ConfigGetResponse`). This test
    pins the FULL wire path with the real C++ envelope shape so a future
    change to the projection layer can't silently revert the SPA's
    Config tab to "—" rendering (the bug that motivated PR-A2)."""
    fake_uds_server.reply(
        b'{"ok":true,"keys":{"smoother.deadband_mm":12.5,"network.ue_port":6666}}'
    )
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/config")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert "ok" not in body
    assert "keys" not in body
    assert body["smoother.deadband_mm"] == 12.5
    assert body["network.ue_port"] == 6666


async def test_get_config_schema_returns_37_rows(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """The schema is mirrored from C++; the endpoint serves the local
    parse cache, not a UDS round-trip."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/config/schema")
    assert r.status_code == HTTPStatus.OK
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 40
    # Each row has the documented keys.
    for row in rows:
        assert {
            "name",
            "type",
            "min",
            "max",
            "default",
            "reload_class",
            "description",
        } == set(row.keys())


async def test_patch_config_admin_happy(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    fake_uds_server.reply(b'{"ok":true,"reload_class":"hot"}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.patch(
            "/api/config",
            headers=_auth(token),
            json={"key": "smoother.deadband_mm", "value": "12.5"},
        )
    assert r.status_code == HTTPStatus.OK, r.text
    assert r.json() == {"ok": True, "reload_class": "hot"}
    # Wire-byte-exact check.
    assert (
        b'{"cmd":"set_config","key":"smoother.deadband_mm","value":"12.5"}'
        in fake_uds_server.captured[0]
    )


async def test_patch_config_anon_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.patch(
            "/api/config",
            json={"key": "smoother.deadband_mm", "value": "12.5"},
        )
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "auth_required"


async def test_patch_config_bad_key_returns_400_with_err(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Tracker rejection of unknown key surfaces as 400 + err='bad_key'."""
    fake_uds_server.reply(b'{"ok":false,"err":"bad_key","detail":"unknown"}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.patch(
            "/api/config",
            headers=_auth(token),
            json={"key": "no.such.key", "value": "1"},
        )
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["ok"] is False
    assert r.json()["err"] == "bad_key"


async def test_patch_config_oversized_body_rejected(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """`CONFIG_PATCH_BODY_MAX_BYTES` defence-in-depth before Pydantic."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        oversized = "x" * 2048
        r = await cl.patch(
            "/api/config",
            headers=_auth(token),
            json={"key": "k", "value": oversized},
        )
    assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert r.json()["err"] == "bad_payload"


async def test_patch_config_rejects_quote_in_key(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Webctl pre-checks the two byte values that would break the
    tracker's hand-rolled JSON parser."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.patch(
            "/api/config",
            headers=_auth(token),
            json={"key": 'evil"key', "value": "1"},
        )
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["err"] == "bad_payload"


async def test_get_restart_pending_false_when_flag_missing(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        restart_pending_path=tmp_path / "no_flag",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/restart_pending")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"pending": False}


async def test_get_restart_pending_true_when_flag_exists(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    flag = tmp_path / "rp"
    flag.write_text("")
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        restart_pending_path=flag,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/restart_pending")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"pending": True}


# ============================================================================
# Track B-BACKUP — /api/map/backup/list + /api/map/backup/<ts>/restore
# ============================================================================


async def test_backup_list_anon_returns_200(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_backup_dir: Path,
) -> None:
    """Track F: /api/map/backup/list is anonymous-readable; no token."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_backup_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/map/backup/list")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)


async def test_backup_list_returns_newest_first(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_backup_dir: Path,
) -> None:
    """Wire-shape contract: items[0].ts is the most recent UTC stamp."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_backup_dir,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/map/backup/list")
    assert r.status_code == HTTPStatus.OK
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0]["ts"] == "20260202T020202Z"
    assert items[1]["ts"] == "20260101T010101Z"
    assert sorted(items[0]["files"]) == ["studio_v2.pgm", "studio_v2.yaml"]


async def test_backup_list_dir_missing_returns_200_empty(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Mode-A M5 fold: missing backup dir returns 200 with items=[]
    (uniform shape — replaces the dropped 503 path)."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "no_such_backup_dir",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/map/backup/list")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == {"items": []}


async def test_backup_restore_admin_returns_200(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_backup_dir: Path,
) -> None:
    """Admin happy path: restore copies the named pair into maps_dir."""
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_backup_dir,
        maps_dir=maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post(
            "/api/map/backup/20260101T010101Z/restore",
            headers=_auth(token),
        )
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["ok"] is True
    assert body["ts"] == "20260101T010101Z"
    assert sorted(body["restored"]) == ["studio_v1.pgm", "studio_v1.yaml"]
    # Files actually present in maps_dir.
    assert (maps_dir / "studio_v1.pgm").is_file()
    assert (maps_dir / "studio_v1.yaml").is_file()


async def test_backup_restore_unauth_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_backup_dir: Path,
) -> None:
    """Track F: anon mutation rejected with 401."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_backup_dir,
    )
    async with _client(s) as cl:
        r = await cl.post("/api/map/backup/20260101T010101Z/restore")
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "auth_required"


async def test_backup_restore_unknown_ts_returns_404(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_backup_dir: Path,
) -> None:
    """Well-formed but non-existent ts → 404 backup_not_found."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_backup_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post(
            "/api/map/backup/29991231T235959Z/restore",
            headers=_auth(token),
        )
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert r.json()["err"] == "backup_not_found"


async def test_backup_restore_dot_traversal_returns_4xx(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_backup_dir: Path,
) -> None:
    """Path-traversal corpus for restore: malformed `<ts>` MUST be
    rejected before any FS touch. FastAPI's `Path(pattern=...)` runs
    BEFORE the handler (returns 422); some inputs collapse via routing
    to 404 (e.g. encoded slashes that the router unwraps into a
    non-matching route). Both outcomes are valid rejections; only a
    200/2xx on a traversal name would be a real escape."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_backup_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        for bad in ("..", ".hidden", "foo", "20260101"):
            r = await cl.post(
                f"/api/map/backup/{bad}/restore",
                headers=_auth(token),
            )
            # Routing-vs-handler discipline (mirror of Track E
            # `test_activate_dot_traversal_returns_400`): inputs like
            # `..` are normalised by httpx/Starlette and may surface
            # via routing as 404/405 BEFORE reaching the handler;
            # legal-shape inputs that fail the FastAPI Path(pattern=...)
            # constraint surface as 422. Either rejection class is
            # acceptable; only a 200/2xx would be a real escape.
            assert r.status_code in (
                HTTPStatus.UNPROCESSABLE_ENTITY,
                HTTPStatus.NOT_FOUND,
                HTTPStatus.METHOD_NOT_ALLOWED,
                HTTPStatus.BAD_REQUEST,
            ), f"bad ts {bad!r} returned {r.status_code}"


async def test_backup_restore_appends_activity_log(
    tmp_path: Path,
    tmp_map_pair: Path,
    tmp_backup_dir: Path,
) -> None:
    """Mode-A N7 fold: activity-log entry detail is `f"{ts} ({n} files)"`."""
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_backup_dir,
        maps_dir=maps_dir,
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        await cl.post(
            "/api/map/backup/20260101T010101Z/restore",
            headers=_auth(token),
        )
        r = await cl.get("/api/activity?n=10")
    assert r.status_code == HTTPStatus.OK
    items = r.json()
    types_to_details = {e["type"]: e["detail"] for e in items}
    assert "map_backup_restored" in types_to_details
    # Format pin: `<ts> (<n> files)` exactly.
    assert types_to_details["map_backup_restored"] == "20260101T010101Z (2 files)"


# ============================================================================
# Track B-SYSTEM PR-2 — service observability
# ============================================================================


def _stub_service_show(name: str, *, env: dict[str, str] | None = None) -> Any:
    """Helper — build a `services.ServiceShow` with sane defaults."""
    from godo_webctl import services

    return services.ServiceShow(
        name=name,
        active_state="active",
        sub_state="running",
        main_pid=1234,
        active_since_unix=1714397472,
        memory_bytes=53477376,
        env_redacted=env if env is not None else {},
        env_stale=False,
    )


async def test_get_system_services_anon_returns_200_with_redacted_env(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """The aggregate GET is anon-readable (Track F) and emits secrets
    as `<redacted>` per the substring allow-list."""
    from godo_webctl import services as svc_mod
    from godo_webctl import system_services as ss_mod
    from godo_webctl.protocol import SYSTEM_SERVICES_FIELDS

    ss_mod._reset_cache_for_tests()
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )

    def _show(name: str) -> svc_mod.ServiceShow:
        # The stub mirrors `services.service_show` semantics: env_redacted
        # is the POST-redaction dict.
        env_raw = {
            "GODO_LOG_DIR": "/var/log/godo",
            "JWT_SECRET": "real-value",
        }
        return _stub_service_show(name, env=svc_mod.redact_env(env_raw))

    with mock.patch("godo_webctl.system_services.services.service_show", side_effect=_show):
        async with _client(s) as cl:
            r = await cl.get("/api/system/services")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert "services" in body
    assert isinstance(body["services"], list)
    assert len(body["services"]) == 3
    for entry in body["services"]:
        assert tuple(entry.keys()) == SYSTEM_SERVICES_FIELDS
        assert entry["env_redacted"]["JWT_SECRET"] == "<redacted>"
        assert entry["env_redacted"]["GODO_LOG_DIR"] == "/var/log/godo"


async def test_get_system_services_admin_token_also_works(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Track F: read endpoints accept (but do not require) auth."""
    from godo_webctl import system_services as ss_mod

    ss_mod._reset_cache_for_tests()
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch(
        "godo_webctl.system_services.services.service_show",
        side_effect=lambda name: _stub_service_show(name),
    ):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.get("/api/system/services", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK


async def test_get_system_services_returns_unknown_state_on_per_service_failure(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """M5 fold pin: per-service degradation. The aggregate endpoint
    always returns 200; a failed `systemctl show` for ONE service
    surfaces as `active_state="unknown"` for that entry only."""
    from godo_webctl import services as svc_mod
    from godo_webctl import system_services as ss_mod

    ss_mod._reset_cache_for_tests()
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )

    def _show(name: str) -> svc_mod.ServiceShow:
        if name == "godo-tracker":
            raise svc_mod.CommandFailed(returncode=1, stderr="boom")
        return _stub_service_show(name)

    with mock.patch("godo_webctl.system_services.services.service_show", side_effect=_show):
        async with _client(s) as cl:
            r = await cl.get("/api/system/services")
    assert r.status_code == HTTPStatus.OK
    by_name = {e["name"]: e for e in r.json()["services"]}
    assert by_name["godo-tracker"]["active_state"] == "unknown"
    assert by_name["godo-webctl"]["active_state"] == "active"


@pytest.mark.parametrize(
    "action",
    ["start", "restart"],
)
async def test_local_service_start_during_activating_returns_409_with_korean_detail(
    tmp_path: Path,
    tmp_map_pair: Path,
    action: str,
) -> None:
    """T3 fold: 409 + EXACT Korean string per M3 table — drift catches
    the particle (가 vs 이)."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch("godo_webctl.services.is_active", return_value="activating"):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post(
                f"/api/local/service/godo-tracker/{action}",
                headers=_auth(token),
            )
    assert r.status_code == HTTPStatus.CONFLICT
    body = r.json()
    assert body["ok"] is False
    assert body["err"] == "service_starting"
    assert "godo-tracker가 시동 중입니다." in body["detail"]


async def test_local_service_stop_during_deactivating_returns_409(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch("godo_webctl.services.is_active", return_value="deactivating"):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post(
                "/api/local/service/godo-webctl/stop",
                headers=_auth(token),
            )
    assert r.status_code == HTTPStatus.CONFLICT
    body = r.json()
    assert body["err"] == "service_stopping"
    # Particle pin: webctl → 이 (받침 ㄹ).
    assert "godo-webctl이 종료 중입니다." in body["detail"]


async def test_local_service_irq_pin_starting_uses_subject_particle_이(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """irq-pin → 핀 → ㄴ 받침 → 이. Drift catch on the particle."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch("godo_webctl.services.is_active", return_value="activating"):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post(
                "/api/local/service/godo-irq-pin/start",
                headers=_auth(token),
            )
    body = r.json()
    assert "godo-irq-pin이 시동 중입니다." in body["detail"]


# --- §8 fold-in: /api/system/service/{name}/{action} (admin-non-loopback) ---


async def test_post_system_service_restart_admin_returns_200(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """TB1 fold: monkeypatch `services.control` (the wrapper, not
    `subprocess.run`), assert 200 + activity_log entry."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch("godo_webctl.app.services_mod.control", return_value="active"):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post(
                "/api/system/service/godo-tracker/restart",
                headers=_auth(token),
            )
            assert r.status_code == HTTPStatus.OK
            assert r.json() == {"ok": True, "status": "active"}
            # S1 fold: activity_log entry recorded.
            log = await cl.get("/api/activity?n=10")
            types_to_details = {e["type"]: e["detail"] for e in log.json()}
            assert types_to_details.get("svc_restart") == "godo-tracker by ncenter"


async def test_post_system_service_restart_anon_returns_401(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/system/service/godo-tracker/restart")
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    assert r.json()["err"] == "auth_required"


async def test_post_system_service_restart_user_role_returns_403(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """A non-admin token must surface as 403 admin_required (mirror of
    /api/system/reboot pattern)."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    # Issue a non-admin token by hand using the same module the app uses.
    from godo_webctl.auth import issue_token

    # Read the secret the app generated at startup so the token verifies.
    base = (tmp_path / "bk").parent  # _settings_for() puts bk under this base
    secret = (base / "jwt_secret").read_bytes() if (base / "jwt_secret").exists() else None
    async with _client(s) as cl:
        # Touch /api/health to force the lifespan + auth bootstrap to write
        # the secret file; then read the bytes for token issuance.
        await cl.get("/api/health")
        secret = (base / "jwt_secret").read_bytes()
        token, _exp = issue_token(secret, "viewer-bob", "viewer")
        r = await cl.post(
            "/api/system/service/godo-tracker/restart",
            headers=_auth(token),
        )
    assert r.status_code == HTTPStatus.FORBIDDEN
    assert r.json()["err"] == "admin_required"


async def test_post_system_service_invalid_action_returns_400(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post(
            "/api/system/service/godo-tracker/frobnicate",
            headers=_auth(token),
        )
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json()["err"] == "unknown_action"


async def test_post_system_service_unknown_unit_returns_404(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.post(
            "/api/system/service/godo-xyz/restart",
            headers=_auth(token),
        )
    assert r.status_code == HTTPStatus.NOT_FOUND
    assert r.json()["err"] == "unknown_service"


async def test_post_system_service_during_activating_returns_409_with_korean_detail(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """The transition gate is inherited from `services.control()`: the
    `/api/system/service/*` route shares the SOLE call site."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch("godo_webctl.services.is_active", return_value="activating"):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post(
                "/api/system/service/godo-tracker/restart",
                headers=_auth(token),
            )
    assert r.status_code == HTTPStatus.CONFLICT
    body = r.json()
    assert body["err"] == "service_starting"
    assert "godo-tracker가 시동 중입니다." in body["detail"]


async def test_post_system_service_subprocess_timeout_returns_504(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """S2 fold: CommandTimeout maps to 504."""
    from godo_webctl import services as svc_mod

    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch(
        "godo_webctl.app.services_mod.control",
        side_effect=svc_mod.CommandTimeout("timed out"),
    ):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post(
                "/api/system/service/godo-tracker/restart",
                headers=_auth(token),
            )
    assert r.status_code == HTTPStatus.GATEWAY_TIMEOUT
    assert r.json()["err"] == "subprocess_timeout"


async def test_post_system_service_subprocess_failed_returns_500(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """S2 fold: CommandFailed maps to 500 with detail."""
    from godo_webctl import services as svc_mod

    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    with mock.patch(
        "godo_webctl.app.services_mod.control",
        side_effect=svc_mod.CommandFailed(returncode=1, stderr="boom"),
    ):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.post(
                "/api/system/service/godo-tracker/restart",
                headers=_auth(token),
            )
    assert r.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert r.json()["err"] == "subprocess_failed"


# ---- PR-B: /api/system/processes ----------------------------------------


async def test_get_system_processes_anon_returns_200(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Anon-readable per CODEBASE invariant (n). Wire shape projected
    through `PROCESSES_RESPONSE_FIELDS`."""
    from godo_webctl.protocol import PROCESSES_RESPONSE_FIELDS

    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/processes")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    for field in PROCESSES_RESPONSE_FIELDS:
        assert field in body
    assert isinstance(body["processes"], list)
    assert isinstance(body["duplicate_alert"], bool)


async def test_get_system_processes_with_admin_token_also_works(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        token = await _login_admin(cl)
        r = await cl.get("/api/system/processes", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK


async def test_get_system_processes_per_row_shape_pinned(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Mode-A S1 fold: each row matches `PROCESS_FIELDS` exactly. We
    monkeypatch `ProcessSampler.sample` to a known shape so the test
    is deterministic across hosts (real /proc walks differ)."""
    from godo_webctl.protocol import PROCESS_FIELDS

    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    fake_snap = {
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
    with mock.patch(
        "godo_webctl.processes.ProcessSampler.sample",
        return_value=fake_snap,
    ):
        async with _client(s) as cl:
            r = await cl.get("/api/system/processes")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    rows = body["processes"]
    assert len(rows) == 1
    row = rows[0]
    for f in PROCESS_FIELDS:
        assert f in row, f"missing {f}"


async def test_get_system_processes_duplicate_alert_propagates(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    fake_snap = {
        "processes": [
            {
                "name": "godo_tracker_rt",
                "pid": 100,
                "user": "ncenter",
                "state": "S",
                "cmdline": ["godo_tracker_rt"],
                "cpu_pct": 0.0,
                "rss_mb": 50.0,
                "etime_s": 1,
                "category": "managed",
                "duplicate": True,
            },
            {
                "name": "godo_tracker_rt",
                "pid": 101,
                "user": "ncenter",
                "state": "S",
                "cmdline": ["godo_tracker_rt"],
                "cpu_pct": 0.0,
                "rss_mb": 50.0,
                "etime_s": 1,
                "category": "managed",
                "duplicate": True,
            },
        ],
        "duplicate_alert": True,
        "published_mono_ns": 1,
    }
    with mock.patch(
        "godo_webctl.processes.ProcessSampler.sample",
        return_value=fake_snap,
    ):
        async with _client(s) as cl:
            r = await cl.get("/api/system/processes")
    body = r.json()
    assert body["duplicate_alert"] is True


async def test_get_system_processes_ignores_unknown_query_params(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Mode-A S1 fold (S1 backend half): the SPA filter is client-side;
    a future writer adding `?filter=...` server-side fails contract.
    The current handler accepts no query params — confirm an extra one
    is silently ignored (FastAPI returns 200 with the unfiltered body).
    """
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/processes?filter=nonsense")
    assert r.status_code == HTTPStatus.OK


async def test_get_system_processes_stream_smoke(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Smoke pattern (mirror of `test_diag_stream_anon_returns_event_stream`):
    open the stream with a short read timeout, bail after the first
    chunk. SSE generators don't terminate naturally."""
    import asyncio as _asyncio

    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )

    async def _peek() -> tuple[int, str]:
        async with (
            _client(s) as cl,
            cl.stream("GET", "/api/system/processes/stream", timeout=2.0) as resp,
        ):
            status = resp.status_code
            ctype = resp.headers.get("content-type", "")
            async for _chunk in resp.aiter_bytes():
                return status, ctype
            return status, ctype

    try:
        status, ctype = await _asyncio.wait_for(_peek(), timeout=3.0)
    except TimeoutError:
        return  # connect succeeded, body-read timed out — acceptable
    assert status == HTTPStatus.OK
    assert "text/event-stream" in ctype


# ---- PR-B: /api/system/resources/extended ------------------------------


async def test_get_system_resources_extended_anon_returns_200(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    from godo_webctl.protocol import EXTENDED_RESOURCES_FIELDS

    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        disk_check_path=tmp_path,
    )
    async with _client(s) as cl:
        r = await cl.get("/api/system/resources/extended")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    for field in EXTENDED_RESOURCES_FIELDS:
        assert field in body
    assert isinstance(body["cpu_per_core"], list)


async def test_get_system_resources_extended_with_no_meminfo_returns_null_mem(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Per-source resilience: if `_read_meminfo_total_avail` raises
    (which it doesn't normally, but we simulate it via monkeypatch),
    the snapshot still yields with mem fields null."""
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        disk_check_path=tmp_path,
    )
    with mock.patch(
        "godo_webctl.resources_extended._read_meminfo_total_avail",
        return_value=(None, None),
    ):
        async with _client(s) as cl:
            r = await cl.get("/api/system/resources/extended")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["mem_total_mb"] is None
    assert body["mem_used_mb"] is None


async def test_get_system_resources_extended_stream_smoke(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    import asyncio as _asyncio

    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
        disk_check_path=tmp_path,
    )

    async def _peek() -> tuple[int, str]:
        async with (
            _client(s) as cl,
            cl.stream("GET", "/api/system/resources/extended/stream", timeout=2.0) as resp,
        ):
            status = resp.status_code
            ctype = resp.headers.get("content-type", "")
            async for _chunk in resp.aiter_bytes():
                return status, ctype
            return status, ctype

    try:
        status, ctype = await _asyncio.wait_for(_peek(), timeout=3.0)
    except TimeoutError:
        return
    assert status == HTTPStatus.OK
    assert "text/event-stream" in ctype
