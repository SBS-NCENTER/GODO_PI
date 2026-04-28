"""
FastAPI app factory for godo-webctl.

Phase 4-3 baseline: `/api/health`, `/api/calibrate`, `/api/map/backup`,
static page at `/`.

PR-A (P0 frontend backend) extension: 14 new endpoints + 2 SSE streams.
Layout per FRONT_DESIGN §7:

  Auth (4):
    POST /api/auth/login     POST /api/auth/logout
    GET  /api/auth/me        POST /api/auth/refresh

  Live mode (1):
    POST /api/live           — toggle Idle <-> Live

  Last-pose (1 SSE + 1 GET piggybacking on Track B):
    GET  /api/last_pose/stream  (SSE)
    GET  /api/last_pose         (one-shot, also exists pre-PR-A via Track B)

  Map image (1):
    GET  /api/map/image

  Activity (1):
    GET  /api/activity?n=<int>

  Local-only services (4 + 1 SSE):
    GET  /api/local/services
    POST /api/local/service/<name>/<action>
    GET  /api/local/journal/<name>?n=<int>
    GET  /api/local/services/stream    (SSE)

  System (2):
    POST /api/system/reboot
    POST /api/system/shutdown

All status codes go through `http.HTTPStatus` (S3); never integer
literals. Per N10, each handler does at most one work call plus shape
mapping — no business logic.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import activity as activity_mod
from . import auth as auth_mod
from . import backup as backup_mod
from . import map_image as map_image_mod
from . import maps as maps_mod
from . import services as services_mod
from . import sse as sse_mod
from . import uds_client as uds_mod
from .config import Settings, load_settings
from .constants import (
    ACTIVITY_TAIL_DEFAULT_N,
    JOURNAL_TAIL_DEFAULT_N,
    LOGIN_PASSWORD_MAX_LEN,
    LOGIN_USERNAME_MAX_LEN,
    MAPS_ACTIVE_BASENAME,
)
from .local_only import loopback_only
from .protocol import (
    ERR_INVALID_MAP_NAME,
    ERR_MAP_IS_ACTIVE,
    ERR_MAP_NOT_FOUND,
    ERR_MAPS_DIR_MISSING,
    LAST_POSE_FIELDS,
    LAST_SCAN_HEADER_FIELDS,
    MODE_IDLE,
    MODE_LIVE,
    MODE_ONESHOT,
)

_LOG_FORMAT = "%(asctime)s %(levelname)s [godo-webctl] %(message)s"
_SSE_MEDIA_TYPE = "text/event-stream"
_PNG_MEDIA_TYPE = "image/png"
_YAML_MEDIA_TYPE = "text/plain; charset=utf-8"

logger = logging.getLogger("godo_webctl")


def _ensure_logging_configured() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)


# --- request bodies (Pydantic) -----------------------------------------


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=LOGIN_USERNAME_MAX_LEN)
    password: str = Field(min_length=1, max_length=LOGIN_PASSWORD_MAX_LEN)


class LiveBody(BaseModel):
    enable: bool


# --- helpers -----------------------------------------------------------


def _map_uds_exc_to_response(exc: uds_mod.UdsError) -> JSONResponse:
    """Shared error mapping for endpoints that issue exactly one UDS call."""
    if isinstance(exc, uds_mod.UdsTimeout):
        return JSONResponse(
            {"ok": False, "err": "tracker_timeout"},
            status_code=HTTPStatus.GATEWAY_TIMEOUT,
        )
    if isinstance(exc, uds_mod.UdsUnreachable):
        return JSONResponse(
            {"ok": False, "err": "tracker_unreachable"},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, uds_mod.UdsServerRejected):
        return JSONResponse(
            {"ok": False, "err": exc.err},
            status_code=HTTPStatus.BAD_REQUEST,
        )
    return JSONResponse(
        {"ok": False, "err": "protocol_error"},
        status_code=HTTPStatus.BAD_GATEWAY,
    )


def _map_maps_exc_to_response(exc: Exception) -> JSONResponse:
    """Local error mapper for `maps.*` exceptions. Kept separate from
    `_map_uds_exc_to_response` because the two error families do not
    overlap (CODEBASE.md invariant (c)).

    Track E (PR-C): the reserved-name path (`InvalidName("reserved_name")`)
    surfaces as `400 invalid_map_name` with `detail="reserved_name"` so
    the SPA can show a more specific tooltip if it wants to.
    """
    if isinstance(exc, maps_mod.InvalidName):
        body: dict[str, object] = {"ok": False, "err": ERR_INVALID_MAP_NAME}
        # Pull the bare reason out of the exception args (e.g.
        # "reserved_name", "path_outside_maps_dir") so the SPA can
        # disambiguate.
        if exc.args:
            body["detail"] = str(exc.args[0])
        return JSONResponse(body, status_code=HTTPStatus.BAD_REQUEST)
    if isinstance(exc, maps_mod.MapNotFound):
        return JSONResponse(
            {"ok": False, "err": ERR_MAP_NOT_FOUND},
            status_code=HTTPStatus.NOT_FOUND,
        )
    if isinstance(exc, maps_mod.MapIsActive):
        return JSONResponse(
            {"ok": False, "err": ERR_MAP_IS_ACTIVE},
            status_code=HTTPStatus.CONFLICT,
        )
    if isinstance(exc, maps_mod.MapsDirMissing):
        return JSONResponse(
            {"ok": False, "err": ERR_MAPS_DIR_MISSING},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    return JSONResponse(
        {"ok": False, "err": "internal_error"},
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


def _last_pose_view(resp: dict[str, object]) -> dict[str, object]:
    """Project the UDS reply down to the documented `LastPose` schema.
    Drops `ok` (HTTP-level success); preserves field order via
    LAST_POSE_FIELDS."""
    return {field: resp.get(field) for field in LAST_POSE_FIELDS}


def _last_scan_view(resp: dict[str, object]) -> dict[str, object]:
    """Track D — project the UDS reply down to the documented `LastScan`
    schema. Drops `ok` (HTTP-level success); preserves field order via
    LAST_SCAN_HEADER_FIELDS so the SPA can iterate the tuple if it wants
    the canonical ordering."""
    return {field: resp.get(field) for field in LAST_SCAN_HEADER_FIELDS}


def create_app(settings: Settings | None = None) -> FastAPI:
    _ensure_logging_configured()
    cfg: Settings = settings if settings is not None else load_settings()
    client = uds_mod.UdsClient(cfg.uds_socket)
    activity_log = activity_mod.ActivityLog()

    # --- auth bootstrap ---------------------------------------------------
    # Secret read once at startup; rotation = `systemctl restart`.
    jwt_secret, user_store = auth_mod.bootstrap(cfg.jwt_secret_path, cfg.users_file)

    # Track E (PR-C): one-shot soft migration from cfg.map_path to
    # cfg.maps_dir/active.pgm. Idempotent — second boot is a no-op for
    # the migration but still warns if cfg.map_path is set (per Q-OQ-E4).
    def _run_legacy_migration() -> None:
        active_pgm = cfg.maps_dir / f"{MAPS_ACTIVE_BASENAME}.pgm"
        if active_pgm.exists() or active_pgm.is_symlink():
            return
        if cfg.map_path is None or not cfg.map_path.exists():
            return
        try:
            maps_mod.migrate_legacy_active(cfg.maps_dir, cfg.map_path)
        except (maps_mod.InvalidName, maps_mod.MapNotFound, OSError) as e:
            logger.error(
                "maps.legacy_migration_failed: source=%s target=%s err=%s",
                cfg.map_path,
                cfg.maps_dir,
                e,
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.jwt_secret = jwt_secret
        app.state.user_store = user_store
        app.state.activity_log = activity_log
        spa_label = "spa_dist" if cfg.spa_dist is not None else "legacy_static"
        logger.info(
            "starting; host=%s port=%d uds=%s maps_dir=%s map=%s backup_dir=%s spa=%s",
            cfg.host,
            cfg.port,
            cfg.uds_socket,
            cfg.maps_dir,
            cfg.map_path,
            cfg.backup_dir,
            spa_label,
        )
        _run_legacy_migration()
        # Per Q-OQ-E4: warn EVERY boot until GODO_WEBCTL_MAP_PATH is
        # unset. Operators read journals selectively; one-shot warnings
        # are easy to miss.
        if cfg.map_path is not None and cfg.map_path.exists():
            logger.warning(
                "maps.legacy_map_path_in_use: source=%s target=%s; "
                "remove GODO_WEBCTL_MAP_PATH env var or run scripts/godo-maps-migrate to clean up",
                cfg.map_path,
                cfg.maps_dir,
            )
        yield
        logger.info("stopping")

    app = FastAPI(title="godo-webctl", version="0.1.0", lifespan=lifespan)
    # Eagerly mirror state onto the app object so dependencies that read
    # `request.app.state.<x>` work even before the lifespan startup hook
    # has run (test clients sometimes skip `lifespan`).
    app.state.jwt_secret = jwt_secret
    app.state.user_store = user_store
    app.state.activity_log = activity_log

    # ---- /api/health ----------------------------------------------------
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

    # ---- /api/calibrate -------------------------------------------------
    @app.post("/api/calibrate")
    async def calibrate(
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            await uds_mod.call_uds(
                client.set_mode,
                MODE_ONESHOT,
                cfg.calibrate_uds_timeout_s,
            )
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        activity_log.append("calibrate", claims.username)
        return JSONResponse({"ok": True}, status_code=HTTPStatus.OK)

    # ---- /api/live ------------------------------------------------------
    @app.post("/api/live")
    async def live(
        body: LiveBody,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        target = MODE_LIVE if body.enable else MODE_IDLE
        try:
            await uds_mod.call_uds(client.set_mode, target, cfg.calibrate_uds_timeout_s)
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        activity_log.append("live_on" if body.enable else "live_off", claims.username)
        return JSONResponse({"ok": True, "mode": target}, status_code=HTTPStatus.OK)

    # ---- /api/map/backup ------------------------------------------------
    @app.post("/api/map/backup")
    async def map_backup(
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
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
        activity_log.append("map_backup", claims.username)
        return JSONResponse(
            {"ok": True, "path": str(path)},
            status_code=HTTPStatus.OK,
        )

    # ---- /api/last_pose -------------------------------------------------
    @app.get("/api/last_pose")
    async def last_pose() -> JSONResponse:
        # Anonymous read OK (Track F): viewers monitor without login.
        # Mutations stay admin-gated.
        try:
            resp = await uds_mod.call_uds(client.get_last_pose, cfg.health_uds_timeout_s)
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        return JSONResponse(_last_pose_view(resp), status_code=HTTPStatus.OK)

    # ---- /api/last_pose/stream -----------------------------------------
    @app.get("/api/last_pose/stream")
    async def last_pose_stream() -> StreamingResponse:
        # Each subscriber gets its OWN UDS client (per Risks table —
        # avoids holding the shared client open).
        sub_client = uds_mod.UdsClient(cfg.uds_socket)
        return StreamingResponse(
            sse_mod.last_pose_stream(sub_client, cfg),
            media_type=_SSE_MEDIA_TYPE,
            headers=sse_mod.SSE_RESPONSE_HEADERS,
        )

    # ---- /api/last_scan -------------------------------------------------
    # Track D: live LIDAR overlay data source. Anonymous read (Track F);
    # mutations are out of scope (read-only endpoint).
    @app.get("/api/last_scan")
    async def last_scan() -> JSONResponse:
        try:
            resp = await uds_mod.call_uds(client.get_last_scan, cfg.health_uds_timeout_s)
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        return JSONResponse(_last_scan_view(resp), status_code=HTTPStatus.OK)

    # ---- /api/last_scan/stream -----------------------------------------
    @app.get("/api/last_scan/stream")
    async def last_scan_stream() -> StreamingResponse:
        # Each subscriber gets its OWN UDS client (mirror of
        # /api/last_pose/stream — per-subscriber isolation).
        sub_client = uds_mod.UdsClient(cfg.uds_socket)
        return StreamingResponse(
            sse_mod.last_scan_stream(sub_client, cfg),
            media_type=_SSE_MEDIA_TYPE,
            headers=sse_mod.SSE_RESPONSE_HEADERS,
        )

    # ---- /api/map/image -------------------------------------------------
    # Track E (PR-C): resolves through `cfg.maps_dir/active.pgm`. If no
    # active symlink yet exists, fall back to the legacy `cfg.map_path`
    # for a one-release deprecation window so existing PoseCanvas calls
    # do not break on a fresh dev machine.
    def _resolve_active_pgm() -> Path:
        active = cfg.maps_dir / f"{MAPS_ACTIVE_BASENAME}.pgm"
        if active.exists() or active.is_symlink():
            return active
        return cfg.map_path

    @app.get("/api/map/image")
    async def map_image() -> Response:
        try:
            png = await asyncio.to_thread(
                map_image_mod.render_pgm_to_png,
                _resolve_active_pgm(),
            )
        except map_image_mod.MapImageNotFound:
            return JSONResponse(
                {"ok": False, "err": "map_path_not_found"},
                status_code=HTTPStatus.NOT_FOUND,
            )
        except map_image_mod.MapImageInvalid:
            return JSONResponse(
                {"ok": False, "err": "map_invalid"},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return Response(content=png, media_type=_PNG_MEDIA_TYPE)

    # ---- /api/maps (Track E, PR-C) -------------------------------------
    # Anonymous-readable per Track F (read endpoints are anon, mutations
    # are admin-gated).
    @app.get("/api/maps")
    async def list_maps() -> JSONResponse:
        try:
            entries = await asyncio.to_thread(maps_mod.list_pairs, cfg.maps_dir)
        except maps_mod.MapsDirMissing as e:
            return _map_maps_exc_to_response(e)
        return JSONResponse(
            [e.to_dict() for e in entries],
            status_code=HTTPStatus.OK,
        )

    @app.get("/api/maps/{name}/image")
    async def map_image_named(name: str) -> Response:
        try:
            pgm = maps_mod.pgm_for(cfg.maps_dir, name)
        except maps_mod.InvalidName as e:
            return _map_maps_exc_to_response(e)
        if not maps_mod.is_pair_present(cfg.maps_dir, name):
            return _map_maps_exc_to_response(maps_mod.MapNotFound(name))
        try:
            png = await asyncio.to_thread(map_image_mod.render_pgm_to_png, pgm)
        except map_image_mod.MapImageNotFound:
            return _map_maps_exc_to_response(maps_mod.MapNotFound(name))
        except map_image_mod.MapImageInvalid:
            return JSONResponse(
                {"ok": False, "err": "map_invalid"},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return Response(content=png, media_type=_PNG_MEDIA_TYPE)

    @app.get("/api/maps/{name}/yaml")
    async def map_yaml_named(name: str) -> Response:
        try:
            yaml_path = maps_mod.yaml_for(cfg.maps_dir, name)
        except maps_mod.InvalidName as e:
            return _map_maps_exc_to_response(e)
        if not maps_mod.is_pair_present(cfg.maps_dir, name):
            return _map_maps_exc_to_response(maps_mod.MapNotFound(name))
        try:
            text = await asyncio.to_thread(yaml_path.read_text, "utf-8")
        except OSError:
            return _map_maps_exc_to_response(maps_mod.MapNotFound(name))
        return Response(content=text, media_type=_YAML_MEDIA_TYPE)

    @app.post("/api/maps/{name}/activate")
    async def activate_map(
        name: str,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            await asyncio.to_thread(maps_mod.set_active, cfg.maps_dir, name)
        except (
            maps_mod.InvalidName,
            maps_mod.MapNotFound,
            maps_mod.MapsDirMissing,
        ) as e:
            return _map_maps_exc_to_response(e)
        # Drop any cached PNG bytes pointing at the previous target so
        # the next /api/map/image GET re-renders. The realpath cache
        # key (Track E PR-C cache fix) would also catch this on the
        # next call, but explicit invalidation is faster + clearer.
        map_image_mod.invalidate_cache()
        activity_log.append("map_activate", f"{name} by {claims.username}")
        return JSONResponse(
            {"ok": True, "restart_required": True},
            status_code=HTTPStatus.OK,
        )

    @app.delete("/api/maps/{name}")
    async def delete_map(
        name: str,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            await asyncio.to_thread(maps_mod.delete_pair, cfg.maps_dir, name)
        except (
            maps_mod.InvalidName,
            maps_mod.MapNotFound,
            maps_mod.MapIsActive,
        ) as e:
            return _map_maps_exc_to_response(e)
        activity_log.append("map_delete", f"{name} by {claims.username}")
        return JSONResponse({"ok": True}, status_code=HTTPStatus.OK)

    # ---- /api/activity --------------------------------------------------
    @app.get("/api/activity")
    async def get_activity(n: int = ACTIVITY_TAIL_DEFAULT_N) -> JSONResponse:
        return JSONResponse(activity_log.tail(n), status_code=HTTPStatus.OK)

    # ---- /api/auth/* ----------------------------------------------------
    @app.post("/api/auth/login")
    async def auth_login(body: LoginBody) -> JSONResponse:
        try:
            role = await asyncio.to_thread(user_store.lookup_role, body.username, body.password)
        except auth_mod.AuthUnavailable as e:
            return JSONResponse(
                {"ok": False, "err": "auth_unavailable", "detail": str(e)},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except auth_mod.InvalidCredentials:
            # Always 401 with a generic body — do not leak whether the
            # username exists.
            return JSONResponse(
                {"ok": False, "err": "bad_credentials"},
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        token, exp = auth_mod.issue_token(jwt_secret, body.username, role)
        activity_log.append("login", body.username)
        return JSONResponse(
            {"ok": True, "token": token, "exp": exp, "role": role, "username": body.username},
            status_code=HTTPStatus.OK,
        )

    @app.post("/api/auth/logout")
    async def auth_logout(
        _: auth_mod.Claims = Depends(auth_mod.require_user),
    ) -> JSONResponse:
        # Stateless JWT — server has no session to invalidate. The frontend
        # drops the token from localStorage; we just acknowledge.
        return JSONResponse({"ok": True}, status_code=HTTPStatus.OK)

    @app.get("/api/auth/me")
    async def auth_me(
        claims: auth_mod.Claims = Depends(auth_mod.require_user),
    ) -> JSONResponse:
        return JSONResponse(
            {"ok": True, "username": claims.username, "role": claims.role, "exp": claims.exp},
            status_code=HTTPStatus.OK,
        )

    @app.post("/api/auth/refresh")
    async def auth_refresh(
        claims: auth_mod.Claims = Depends(auth_mod.require_user),
    ) -> JSONResponse:
        token, exp = auth_mod.issue_token(jwt_secret, claims.username, claims.role)
        return JSONResponse(
            {"ok": True, "token": token, "exp": exp},
            status_code=HTTPStatus.OK,
        )

    # ---- /api/local/* (loopback-only + admin) --------------------------
    @app.get(
        "/api/local/services",
        dependencies=[Depends(loopback_only)],
    )
    async def local_services() -> JSONResponse:
        # Anonymous read OK from loopback (Track F): kiosk operator can
        # see service status without login. Mutations stay admin-gated.
        items = await asyncio.to_thread(services_mod.list_active)
        return JSONResponse(items, status_code=HTTPStatus.OK)

    @app.post(
        "/api/local/service/{name}/{action}",
        dependencies=[Depends(loopback_only)],
    )
    async def local_service_action(
        name: str,
        action: str,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            status = await asyncio.to_thread(services_mod.control, name, action)
        except services_mod.UnknownService:
            return JSONResponse(
                {"ok": False, "err": "unknown_service"},
                status_code=HTTPStatus.NOT_FOUND,
            )
        except services_mod.UnknownAction:
            return JSONResponse(
                {"ok": False, "err": "unknown_action"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except services_mod.CommandTimeout:
            return JSONResponse(
                {"ok": False, "err": "subprocess_timeout"},
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
            )
        except services_mod.CommandFailed as e:
            return JSONResponse(
                {"ok": False, "err": "subprocess_failed", "detail": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        activity_log.append(f"svc_{action}", f"{name} by {claims.username}")
        return JSONResponse({"ok": True, "status": status}, status_code=HTTPStatus.OK)

    @app.get(
        "/api/local/journal/{name}",
        dependencies=[Depends(loopback_only)],
    )
    async def local_journal(
        name: str,
        n: int = JOURNAL_TAIL_DEFAULT_N,
    ) -> JSONResponse:
        try:
            lines = await asyncio.to_thread(services_mod.journal_tail, name, n)
        except services_mod.UnknownService:
            return JSONResponse(
                {"ok": False, "err": "unknown_service"},
                status_code=HTTPStatus.NOT_FOUND,
            )
        except ValueError:
            return JSONResponse(
                {"ok": False, "err": "bad_n"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except services_mod.CommandTimeout:
            return JSONResponse(
                {"ok": False, "err": "subprocess_timeout"},
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
            )
        except services_mod.CommandFailed as e:
            return JSONResponse(
                {"ok": False, "err": "subprocess_failed", "detail": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return JSONResponse(lines, status_code=HTTPStatus.OK)

    @app.get(
        "/api/local/services/stream",
        dependencies=[Depends(loopback_only)],
    )
    async def local_services_stream() -> StreamingResponse:
        return StreamingResponse(
            sse_mod.services_stream(cfg),
            media_type=_SSE_MEDIA_TYPE,
            headers=sse_mod.SSE_RESPONSE_HEADERS,
        )

    # ---- /api/system/* --------------------------------------------------
    @app.post("/api/system/reboot")
    async def system_reboot(
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            await asyncio.to_thread(services_mod.system_reboot)
        except services_mod.CommandTimeout:
            return JSONResponse(
                {"ok": False, "err": "subprocess_timeout"},
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
            )
        except services_mod.CommandFailed as e:
            return JSONResponse(
                {"ok": False, "err": "subprocess_failed", "detail": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        activity_log.append("reboot", claims.username)
        return JSONResponse({"ok": True}, status_code=HTTPStatus.OK)

    @app.post("/api/system/shutdown")
    async def system_shutdown(
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            await asyncio.to_thread(services_mod.system_shutdown)
        except services_mod.CommandTimeout:
            return JSONResponse(
                {"ok": False, "err": "subprocess_timeout"},
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
            )
        except services_mod.CommandFailed as e:
            return JSONResponse(
                {"ok": False, "err": "subprocess_failed", "detail": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        activity_log.append("shutdown", claims.username)
        return JSONResponse({"ok": True}, status_code=HTTPStatus.OK)

    # Keep FastAPI happy: it will reject 404s on unknown /api/* — but make
    # the dependency-side HTTPException flow uniform for SSE token paths.
    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        # Default FastAPI handler returns {"detail": ...}; we keep the
        # dependency-supplied dict body so frontend sees the documented
        # `{"ok": false, "err": "..."}` shape.
        if isinstance(exc.detail, dict):
            return JSONResponse(exc.detail, status_code=exc.status_code)
        return JSONResponse(
            {"ok": False, "err": str(exc.detail)},
            status_code=exc.status_code,
        )

    # ---- static / SPA mount ---------------------------------------------
    # PR-A keeps the legacy vanilla page available; PR-B will set
    # `spa_dist` to the built `godo-frontend/dist/`.
    if cfg.spa_dist is not None and cfg.spa_dist.is_dir():
        app.mount("/", StaticFiles(directory=cfg.spa_dist, html=True), name="spa")
    else:
        static_dir = Path(__file__).parent / "static"
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
