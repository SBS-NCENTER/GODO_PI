"""FastAPI integration: route handlers + fake UDS server + tmp map pair."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

import httpx
from httpx import ASGITransport

from godo_webctl.app import create_app
from godo_webctl.config import Settings


def _settings_for(
    *,
    uds_socket: Path,
    map_path: Path,
    backup_dir: Path,
) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=0,
        uds_socket=uds_socket,
        backup_dir=backup_dir,
        map_path=map_path,
        health_uds_timeout_s=1.0,
        calibrate_uds_timeout_s=1.0,
    )


def _client(settings: Settings) -> httpx.AsyncClient:
    app = create_app(settings)
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


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
    fake_uds_server.reply(b'{"ok":true}')
    s = _settings_for(
        uds_socket=fake_uds_server.path,
        map_path=tmp_map_pair,
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/calibrate")
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
        r = await cl.post("/api/calibrate")
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
        r = await cl.post("/api/calibrate")
    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert r.json() == {"ok": False, "err": "bad_mode"}


async def test_calibrate_timeout_returns_504(
    fake_uds_server,
    tmp_path: Path,
    tmp_map_pair: Path,
) -> None:
    # Server accepts but never replies → client times out → 504.
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
    )
    async with _client(s) as cl:
        r = await cl.post("/api/calibrate")
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
        r = await cl.post("/api/calibrate")
    assert r.status_code == HTTPStatus.BAD_GATEWAY
    assert r.json() == {"ok": False, "err": "protocol_error"}


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
        r = await cl.post("/api/map/backup")
    assert r.status_code == HTTPStatus.OK
    body = r.json()
    assert body["ok"] is True
    assert Path(body["path"]).is_dir()
    assert (Path(body["path"]) / "studio_v1.pgm").is_file()


async def test_backup_missing_map_returns_404(
    tmp_path: Path,
) -> None:
    s = _settings_for(
        uds_socket=tmp_path / "unused.sock",
        map_path=tmp_path / "ghost.pgm",
        backup_dir=tmp_path / "bk",
    )
    async with _client(s) as cl:
        r = await cl.post("/api/map/backup")
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
