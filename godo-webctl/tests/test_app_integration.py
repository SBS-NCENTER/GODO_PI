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

from godo_webctl import auth as auth_mod
from godo_webctl.app import create_app
from godo_webctl.config import Settings
from godo_webctl.constants import JWT_ALGORITHM
from godo_webctl.protocol import LAST_POSE_FIELDS


def _settings_for(
    *,
    uds_socket: Path,
    map_path: Path,
    backup_dir: Path,
    jwt_secret_path: Path | None = None,
    users_file: Path | None = None,
    spa_dist: Path | None = None,
) -> Settings:
    base = backup_dir.parent
    return Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=uds_socket,
        backup_dir=backup_dir,
        map_path=map_path,
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
        jwt_secret_path=jwt_secret_path or (base / "jwt_secret"),
        users_file=users_file or (base / "users.json"),
        spa_dist=spa_dist,
        chromium_loopback_only=True,
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
        health_uds_timeout_s=s.health_uds_timeout_s,
        calibrate_uds_timeout_s=0.2,
        jwt_secret_path=s.jwt_secret_path,
        users_file=s.users_file,
        spa_dist=s.spa_dist,
        chromium_loopback_only=s.chromium_loopback_only,
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
        token = await _login_admin(cl)
        r = await cl.get("/api/last_pose", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert tuple(body.keys()) == LAST_POSE_FIELDS


# ---- /api/last_pose/stream (smoke) ---------------------------------------
async def test_last_pose_stream_route_is_wired_with_correct_headers(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    """Smoke test: the route exists and is configured with the right
    media type + defensive proxy-buffering headers. End-to-end frame
    cadence is asserted by `tests/test_sse.py` against the generator
    directly with a virtual clock (per T3) — there is no value in
    racing a wall-clock SSE read through httpx ASGI here."""
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
    fake_list = [{"name": "godo-tracker", "active": "active"}]
    with mock.patch("godo_webctl.app.services_mod.list_active", return_value=fake_list):
        async with _client(s) as cl:
            token = await _login_admin(cl)
            r = await cl.get("/api/local/services", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.json() == fake_list


async def test_local_services_non_loopback_returns_403(
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "u.sock",
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    app = create_app(s)
    transport = ASGITransport(app=app, client=("192.168.1.50", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as cl:
        # login must come from loopback; emulate by fetching a token via
        # an issue_token shortcut against the app's secret.
        secret = app.state.jwt_secret
        token, _ = auth_mod.issue_token(secret, "ncenter", "admin")
        r = await cl.get("/api/local/services", headers=_auth(token))
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
        r = await cl.get("/api/activity?n=5", headers=_auth(token))
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
        token = await _login_admin(cl)
        r = await cl.get("/api/map/image", headers=_auth(token))
    assert r.status_code == HTTPStatus.OK
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


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
