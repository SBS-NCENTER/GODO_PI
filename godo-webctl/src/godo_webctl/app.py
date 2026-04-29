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
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as FastApiPath
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import activity as activity_mod
from . import auth as auth_mod
from . import backup as backup_mod
from . import config_schema as config_schema_mod
from . import config_view as config_view_mod
from . import logs as logs_mod
from . import map_backup as map_backup_mod
from . import map_image as map_image_mod
from . import maps as maps_mod
from . import resources as resources_mod
from . import restart_pending as restart_pending_mod
from . import services as services_mod
from . import sse as sse_mod
from . import system_services as system_services_mod
from . import uds_client as uds_mod
from .config import Settings, load_settings
from .constants import (
    ACTIVITY_TAIL_DEFAULT_N,
    CONFIG_GET_UDS_TIMEOUT_S,
    CONFIG_PATCH_BODY_MAX_BYTES,
    CONFIG_SCHEMA_CACHE_TTL_S,
    CONFIG_SET_UDS_TIMEOUT_S,
    CONFIG_VALUE_TEXT_MAX_LEN,
    JOURNAL_TAIL_DEFAULT_N,
    LOGIN_PASSWORD_MAX_LEN,
    LOGIN_USERNAME_MAX_LEN,
    LOGS_TAIL_DEFAULT_N,
    LOGS_TAIL_MAX_N,
    MAPS_ACTIVE_BASENAME,
    SERVICE_TRANSITION_MESSAGES_KO,
)
from .local_only import loopback_only
from .protocol import (
    AMCL_RATE_FIELDS,
    ERR_BACKUP_NOT_FOUND,
    ERR_INVALID_MAP_NAME,
    ERR_MAP_IS_ACTIVE,
    ERR_MAP_NOT_FOUND,
    ERR_MAPS_DIR_MISSING,
    ERR_RESTORE_NAME_CONFLICT,
    ERR_SERVICE_STARTING,
    ERR_SERVICE_STOPPING,
    JITTER_FIELDS,
    LAST_POSE_FIELDS,
    LAST_SCAN_HEADER_FIELDS,
    MODE_IDLE,
    MODE_LIVE,
    MODE_ONESHOT,
    RESOURCES_FIELDS,
)

# Track B-BACKUP — `<ts>` path constraint for the restore route. Same
# canonical-UTC-stamp regex `map_backup._TS_REGEX` enforces internally;
# this is the FIRST defence layer (FastAPI returns 422 before the
# handler runs).
_BACKUP_TS_PATTERN = r"^[0-9]{8}T[0-9]{6}Z$"

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


class ConfigPatchBody(BaseModel):
    """`PATCH /api/config` body. Mode-A S4 fold: webctl pre-validation
    is body size + single-key shape + JSON well-formedness only — no
    ASCII / regex / range checks. The C++ tracker's `validate.cpp` is
    the canonical validator and emits typed `bad_key` / `bad_value` /
    `non_ascii_value` errors that webctl forwards verbatim.
    """

    key: str = Field(min_length=1, max_length=128)
    # `value` is forwarded as a string to the tracker's `set_config`
    # wire (the tracker re-parses per the schema's ValueType). We
    # accept Python int/float/bool here for SPA convenience and
    # str-coerce server-side to keep the wire shape canonical.
    value: str | int | float | bool = Field(...)


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


def _map_backup_exc_to_response(exc: Exception) -> JSONResponse:
    """Local error mapper for `map_backup.*` exceptions. Kept separate
    from `_map_maps_exc_to_response` because the two error families do
    not overlap (CODEBASE.md invariant (c))."""
    if isinstance(exc, map_backup_mod.BackupNotFound):
        return JSONResponse(
            {"ok": False, "err": ERR_BACKUP_NOT_FOUND},
            status_code=HTTPStatus.NOT_FOUND,
        )
    if isinstance(exc, map_backup_mod.RestoreNameConflict):
        return JSONResponse(
            {"ok": False, "err": ERR_RESTORE_NAME_CONFLICT},
            status_code=HTTPStatus.CONFLICT,
        )
    if isinstance(exc, OSError):
        return JSONResponse(
            {"ok": False, "err": "restore_failed", "detail": str(exc)},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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


def _jitter_view(resp: dict[str, object]) -> dict[str, object]:
    """PR-DIAG — project the UDS reply down to the documented JitterSnapshot
    schema. Same shape as `_last_pose_view`."""
    return {field: resp.get(field) for field in JITTER_FIELDS}


def _amcl_rate_view(resp: dict[str, object]) -> dict[str, object]:
    """PR-DIAG (Mode-A M2 fold) — projection through AMCL_RATE_FIELDS."""
    return {field: resp.get(field) for field in AMCL_RATE_FIELDS}


def _resources_view(snap: dict[str, object]) -> dict[str, object]:
    """PR-DIAG — webctl-only Resources schema; pure projection through
    RESOURCES_FIELDS so the wire shape is byte-stable across calls."""
    return {field: snap.get(field) for field in RESOURCES_FIELDS}


def _service_transition_response(exc: services_mod.ServiceTransitionInProgress) -> JSONResponse:
    """Translate a `ServiceTransitionInProgress` into the 409 wire shape.

    Body: `{ok: False, err: "service_starting"|"service_stopping",
    detail: "<Korean string>"}`. The Korean strings come from
    `SERVICE_TRANSITION_MESSAGES_KO` keyed by `(svc, transition)`. An
    out-of-table key falls back to a generic Korean string so a future
    service added to ALLOWED_SERVICES without a message entry still
    surfaces as 409 (not 500)."""
    err = ERR_SERVICE_STARTING if exc.transition == "starting" else ERR_SERVICE_STOPPING
    detail = SERVICE_TRANSITION_MESSAGES_KO.get(
        (exc.svc, exc.transition),
        f"{exc.svc} 전환 중입니다. 잠시 후 다시 시도해주세요.",
    )
    return JSONResponse(
        {"ok": False, "err": err, "detail": detail},
        status_code=HTTPStatus.CONFLICT,
    )


def _map_logs_exc_to_response(exc: Exception) -> JSONResponse:
    """Local error mapper for `logs.tail` exceptions. Mirrors the
    `_map_uds_exc_to_response` shape (HTTPStatus + ok/err body)."""
    if isinstance(exc, logs_mod.UnknownService):
        return JSONResponse(
            {"ok": False, "err": "unknown_service"},
            status_code=HTTPStatus.NOT_FOUND,
        )
    if isinstance(exc, logs_mod.CommandTimeout):
        return JSONResponse(
            {"ok": False, "err": "subprocess_timeout"},
            status_code=HTTPStatus.GATEWAY_TIMEOUT,
        )
    if isinstance(exc, logs_mod.CommandFailed):
        return JSONResponse(
            {"ok": False, "err": "subprocess_failed", "detail": str(exc)},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    return JSONResponse(
        {"ok": False, "err": "internal_error"},
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


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
            if err == "concurrent_backup_in_progress":
                return JSONResponse(
                    {
                        "ok": False,
                        "err": err,
                        "detail": "다른 백업이 진행 중입니다.",
                    },
                    status_code=HTTPStatus.CONFLICT,
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

    # ---- /api/map/backup/list (Track B-BACKUP, anon read) --------------
    # Track F: anonymous-readable. Mode-A M5 fold: returns 200 with
    # items=[] when the backup dir is missing OR empty (uniform shape).
    @app.get("/api/map/backup/list")
    async def map_backup_list() -> JSONResponse:
        entries = await asyncio.to_thread(map_backup_mod.list_backups, cfg.backup_dir)
        return JSONResponse(
            {"items": [e.to_dict() for e in entries]},
            status_code=HTTPStatus.OK,
        )

    # ---- /api/map/backup/<ts>/restore (Track B-BACKUP, admin) ----------
    # Mode-A N6 fold: FastAPI `Path(pattern=...)` is the FIRST defence
    # layer against malformed `<ts>` (returns 422 BEFORE handler runs);
    # `restore_backup`'s internal regex is the second layer.
    @app.post("/api/map/backup/{ts}/restore")
    async def map_backup_restore(
        ts: Annotated[str, FastApiPath(pattern=_BACKUP_TS_PATTERN)],
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            restored = await asyncio.to_thread(
                map_backup_mod.restore_backup,
                cfg.backup_dir,
                ts,
                cfg.maps_dir,
            )
        except (
            map_backup_mod.BackupNotFound,
            map_backup_mod.RestoreNameConflict,
            OSError,
        ) as e:
            return _map_backup_exc_to_response(e)
        # Mode-A N7 fold: detail is `f"{ts} ({n} files)"`.
        activity_log.append(
            "map_backup_restored",
            f"{ts} ({len(restored)} files)",
        )
        return JSONResponse(
            {"ok": True, "ts": ts, "restored": restored},
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

    # ---- /api/system/jitter (PR-DIAG, anon read) ------------------------
    @app.get("/api/system/jitter")
    async def system_jitter() -> JSONResponse:
        try:
            resp = await uds_mod.call_uds(client.get_jitter, cfg.health_uds_timeout_s)
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        return JSONResponse(_jitter_view(resp), status_code=HTTPStatus.OK)

    # ---- /api/system/amcl_rate (PR-DIAG, anon read) ---------------------
    # Mode-A M2 fold: endpoint is /api/system/amcl_rate (NOT scan_rate).
    @app.get("/api/system/amcl_rate")
    async def system_amcl_rate() -> JSONResponse:
        try:
            resp = await uds_mod.call_uds(client.get_amcl_rate, cfg.health_uds_timeout_s)
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        return JSONResponse(_amcl_rate_view(resp), status_code=HTTPStatus.OK)

    # ---- /api/system/resources (PR-DIAG, anon read) ---------------------
    @app.get("/api/system/resources")
    async def system_resources() -> JSONResponse:
        snap = await asyncio.to_thread(
            resources_mod.snapshot,
            disk_check_path=cfg.disk_check_path,
        )
        return JSONResponse(_resources_view(snap), status_code=HTTPStatus.OK)

    # ---- /api/config (Track B-CONFIG, anon read) ------------------------
    # Track F: anonymous-readable. The schema is C++ Tier-1 + the
    # current values are not credentials. Mutations stay admin-gated
    # below.
    @app.get("/api/config")
    async def get_config_endpoint() -> JSONResponse:
        try:
            resp = await uds_mod.call_uds(client.get_config, CONFIG_GET_UDS_TIMEOUT_S)
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        return JSONResponse(
            config_view_mod.project_config_view(resp),
            status_code=HTTPStatus.OK,
        )

    # ---- /api/config/schema (Track B-CONFIG, anon read) -----------------
    # The schema is constexpr in the tracker; serve from the Python
    # mirror cache (parse-once, hold-for-process). The tracker's
    # `get_config_schema` UDS handler exists for completeness +
    # cross-language parity tests, but webctl never calls it: the
    # local mirror is byte-equivalent and survives a tracker outage.
    _schema_cache: dict[str, object] = {"value": None, "ts": 0.0}

    @app.get("/api/config/schema")
    async def get_config_schema_endpoint() -> JSONResponse:
        import time

        now = time.monotonic()
        cached_ts = _schema_cache.get("ts")
        if (
            _schema_cache.get("value") is not None
            and isinstance(cached_ts, float)
            and now - cached_ts < CONFIG_SCHEMA_CACHE_TTL_S
        ):
            return JSONResponse(_schema_cache["value"], status_code=HTTPStatus.OK)
        try:
            rows = await asyncio.to_thread(config_schema_mod.load_schema)
        except config_schema_mod.ConfigSchemaError as e:
            return JSONResponse(
                {"ok": False, "err": "schema_unavailable", "detail": str(e)},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        body = config_view_mod.project_schema_view(rows)
        _schema_cache["value"] = body
        _schema_cache["ts"] = now
        return JSONResponse(body, status_code=HTTPStatus.OK)

    # ---- PATCH /api/config (Track B-CONFIG, admin) ----------------------
    @app.patch("/api/config")
    async def patch_config_endpoint(
        request: Request,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        # Defence-in-depth: enforce the body-size cap BEFORE Pydantic
        # parsing so a malicious 100 MiB upload cannot consume CPU.
        raw = await request.body()
        if len(raw) > CONFIG_PATCH_BODY_MAX_BYTES:
            return JSONResponse(
                {"ok": False, "err": "bad_payload", "detail": "body_too_large"},
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        try:
            body = ConfigPatchBody.model_validate_json(raw)
        except ValueError as e:
            return JSONResponse(
                {"ok": False, "err": "bad_payload", "detail": str(e)},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        # Mode-A S4: webctl validates body size + single-key shape +
        # JSON well-formedness only. NO ASCII check (defer to tracker).
        # The Pydantic model already pinned single-key + 1..128 byte
        # key + value type as one of {str,int,float,bool}.
        value_str = (
            "true" if body.value is True else "false" if body.value is False else str(body.value)
        )
        if len(value_str) > CONFIG_VALUE_TEXT_MAX_LEN:
            return JSONResponse(
                {"ok": False, "err": "bad_payload", "detail": "value_too_long"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        # Reject characters that would break the hand-rolled tracker
        # JSON parser (json_mini.cpp tolerates ASCII + no \" / \\ / \n
        # in field values).
        if any(c in body.key for c in ('"', "\\", "\n")):
            return JSONResponse(
                {"ok": False, "err": "bad_payload", "detail": "key_has_special_char"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if any(c in value_str for c in ('"', "\\", "\n")):
            return JSONResponse(
                {"ok": False, "err": "bad_payload", "detail": "value_has_special_char"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        try:
            resp = await uds_mod.call_uds(
                client.set_config,
                body.key,
                value_str,
                CONFIG_SET_UDS_TIMEOUT_S,
            )
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        activity_log.append("config_set", f"{body.key} by {claims.username}")
        return JSONResponse(
            {
                "ok": True,
                "reload_class": resp.get("reload_class", "hot"),
            },
            status_code=HTTPStatus.OK,
        )

    # ---- /api/system/restart_pending (Track B-CONFIG, anon read) --------
    @app.get("/api/system/restart_pending")
    async def get_restart_pending_endpoint() -> JSONResponse:
        pending = await asyncio.to_thread(
            restart_pending_mod.is_pending,
            cfg.restart_pending_path,
        )
        return JSONResponse({"pending": pending}, status_code=HTTPStatus.OK)

    # ---- /api/logs/tail (PR-DIAG, anon read) ----------------------------
    @app.get("/api/logs/tail")
    async def logs_tail(
        unit: Annotated[str, Query(min_length=1, max_length=64)],
        n: Annotated[int, Query(ge=1, le=LOGS_TAIL_MAX_N)] = LOGS_TAIL_DEFAULT_N,
    ) -> JSONResponse:
        # FastAPI's own Annotated[Query(...)] validation runs BEFORE the
        # handler body, so out-of-range `n` and missing `unit` surface as
        # native 422 (Mode-B S1 fold). Inside the handler we still rely
        # on logs.tail() for defence-in-depth (n>cap clamp + WARN, allow-
        # list lookup).
        try:
            lines = await asyncio.to_thread(logs_mod.tail, unit, n)
        except logs_mod.UnknownService as e:
            return _map_logs_exc_to_response(e)
        except logs_mod.CommandTimeout as e:
            return _map_logs_exc_to_response(e)
        except logs_mod.CommandFailed as e:
            return _map_logs_exc_to_response(e)
        return JSONResponse(lines, status_code=HTTPStatus.OK)

    # ---- /api/diag/stream (PR-DIAG, anon read SSE) ----------------------
    @app.get("/api/diag/stream")
    async def diag_stream() -> StreamingResponse:
        # Each subscriber owns its own UDS client (mirrors last_pose_stream
        # / last_scan_stream pattern). Multiplexed frame: pose + jitter +
        # amcl_rate + resources, 5 Hz cadence.
        sub_client = uds_mod.UdsClient(cfg.uds_socket)
        return StreamingResponse(
            sse_mod.diag_stream(sub_client, cfg),
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
        except services_mod.ServiceTransitionInProgress as e:
            return _service_transition_response(e)
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

    # ---- /api/system/services (Track B-SYSTEM PR-2, anon read) ----------
    @app.get("/api/system/services")
    async def system_services_endpoint() -> JSONResponse:
        items = await asyncio.to_thread(system_services_mod.snapshot)
        return JSONResponse({"services": items}, status_code=HTTPStatus.OK)

    # ---- /api/system/service/{name}/{action} (Track B-SYSTEM PR-2, admin) -
    # Mirrors `/api/system/reboot`'s admin-non-loopback pattern: JWT-authed
    # admin user from any origin (Tailscale, LAN, localhost). Shares
    # `services.control()` with `/api/local/service/*` so the transition
    # gate (HTTP 409) is inherited.
    @app.post("/api/system/service/{name}/{action}")
    async def system_service_action(
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
        except services_mod.ServiceTransitionInProgress as e:
            return _service_transition_response(e)
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
