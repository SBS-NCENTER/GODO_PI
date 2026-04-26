"""
FastAPI app factory for godo-webctl.

Three routes (thin handlers, invariant (c) in CODEBASE.md):
  GET  /api/health       — liveness + tracker mode
  POST /api/calibrate    — latch OneShot mode on tracker (returns immediately)
  POST /api/map/backup   — atomic snapshot of the current .pgm + .yaml

Plus a static-file mount at ``/`` for ``static/index.html``.

All HTTP status codes go through ``http.HTTPStatus`` (S3); never integer
literals. Per N10, each handler does at most one ``call_uds`` /
``backup_map`` call plus shape mapping — no business logic.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import backup as backup_mod
from . import uds_client as uds_mod
from .config import Settings, load_settings
from .protocol import MODE_ONESHOT

_LOG_FORMAT = "%(asctime)s %(levelname)s [godo-webctl] %(message)s"

logger = logging.getLogger("godo_webctl")


def _ensure_logging_configured() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)


def create_app(settings: Settings | None = None) -> FastAPI:
    _ensure_logging_configured()
    cfg: Settings = settings if settings is not None else load_settings()
    client = uds_mod.UdsClient(cfg.uds_socket)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "starting; host=%s port=%d uds=%s map=%s backup_dir=%s",
            cfg.host,
            cfg.port,
            cfg.uds_socket,
            cfg.map_path,
            cfg.backup_dir,
        )
        yield
        logger.info("stopping")

    app = FastAPI(title="godo-webctl", version="0.1.0", lifespan=lifespan)

    # ---- /api/health -----------------------------------------------------
    @app.get("/api/health")
    async def health() -> JSONResponse:
        try:
            resp = await uds_mod.call_uds(client.get_mode, cfg.health_uds_timeout_s)
        except (uds_mod.UdsUnreachable, uds_mod.UdsTimeout, uds_mod.UdsProtocolError):
            return JSONResponse(
                {"webctl": "ok", "tracker": "unreachable", "mode": None},
                status_code=HTTPStatus.OK,
            )
        return JSONResponse(
            {"webctl": "ok", "tracker": "ok", "mode": resp.get("mode")},
            status_code=HTTPStatus.OK,
        )

    # ---- /api/calibrate --------------------------------------------------
    @app.post("/api/calibrate")
    async def calibrate() -> JSONResponse:
        try:
            await uds_mod.call_uds(
                client.set_mode,
                MODE_ONESHOT,
                cfg.calibrate_uds_timeout_s,
            )
        except uds_mod.UdsTimeout:
            return JSONResponse(
                {"ok": False, "err": "tracker_timeout"},
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
            )
        except uds_mod.UdsUnreachable:
            return JSONResponse(
                {"ok": False, "err": "tracker_unreachable"},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except uds_mod.UdsServerRejected as e:
            # Tracker replied ok=false → propagate err code with HTTP 400.
            return JSONResponse(
                {"ok": False, "err": e.err},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except uds_mod.UdsProtocolError:
            # Wire-level fault (malformed JSON / missing ok / oversized) →
            # HTTP 502 (Mode-B SHOULD-FIX S3 — exception class drives the
            # split, not string-prefix dispatch).
            return JSONResponse(
                {"ok": False, "err": "protocol_error"},
                status_code=HTTPStatus.BAD_GATEWAY,
            )
        return JSONResponse({"ok": True}, status_code=HTTPStatus.OK)

    # ---- /api/map/backup -------------------------------------------------
    @app.post("/api/map/backup")
    async def map_backup() -> JSONResponse:
        try:
            path = await asyncio.to_thread(
                backup_mod.backup_map,
                cfg.map_path,
                cfg.backup_dir,
            )
        except backup_mod.BackupError as e:
            err = str(e)
            if err == "map_path_not_found":
                return JSONResponse(
                    {"ok": False, "err": err},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            return JSONResponse(
                {"ok": False, "err": err},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return JSONResponse(
            {"ok": True, "path": str(path)},
            status_code=HTTPStatus.OK,
        )

    # ---- static page -----------------------------------------------------
    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
