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
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as FastApiPath
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from . import activity as activity_mod
from . import auth as auth_mod
from . import backup as backup_mod
from . import config_schema as config_schema_mod
from . import config_view as config_view_mod
from . import logs as logs_mod
from . import map_backup as map_backup_mod
from . import map_edit as map_edit_mod
from . import map_image as map_image_mod
from . import map_origin as map_origin_mod
from . import map_transform as map_transform_mod
from . import mapping as mapping_mod
from . import mapping_sse as mapping_sse_mod
from . import maps as maps_mod
from . import processes as processes_mod
from . import resources as resources_mod
from . import resources_extended as resources_extended_mod
from . import restart_pending as restart_pending_mod
from . import services as services_mod
from . import sidecar as sidecar_mod
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
    MAP_EDIT_MASK_PNG_MAX_BYTES,
    MAP_EDIT_PIPELINE_LOCK_TIMEOUT_S,
    MAPPING_JOURNAL_TAIL_DEFAULT_N,
    MAPPING_JOURNAL_TAIL_MAX_N,
    MAPPING_NAME_MAX_LEN,
    MAPPING_UNIT_NAME,
    MAPS_ACTIVE_BASENAME,
    ORIGIN_BODY_MAX_BYTES,
    ORIGIN_X_Y_ABS_MAX_M,
    SERVICE_TRANSITION_MESSAGES_KO,
)
from .local_only import loopback_only
from .protocol import (
    AMCL_RATE_FIELDS,
    ERR_ACTIVE_MAP_MISSING,
    ERR_ACTIVE_YAML_MISSING,
    ERR_BACKUP_NOT_FOUND,
    ERR_BAD_N,
    ERR_CONTAINER_START_TIMEOUT,
    ERR_CONTAINER_STOP_TIMEOUT,
    ERR_CP210X_RECOVERY_FAILED,
    ERR_DOCKER_UNAVAILABLE,
    ERR_EDIT_FAILED,
    ERR_IMAGE_MISSING,
    ERR_INVALID_MAP_NAME,
    ERR_INVALID_MAPPING_NAME,
    ERR_LIDAR_PORT_NOT_RESOLVABLE,
    ERR_MAP_IS_ACTIVE,
    ERR_MAP_NOT_FOUND,
    ERR_MAPPING_ACTIVE,
    ERR_MAPPING_ALREADY_ACTIVE,
    ERR_MAPS_DIR_MISSING,
    ERR_MASK_DECODE_FAILED,
    ERR_MASK_SHAPE_MISMATCH,
    ERR_MASK_TOO_LARGE,
    ERR_NAME_EXISTS,
    ERR_NO_ACTIVE_MAPPING,
    ERR_ORIGIN_BAD_VALUE,
    ERR_ORIGIN_EDIT_FAILED,
    ERR_ORIGIN_YAML_PARSE_FAILED,
    ERR_PREVIEW_NOT_YET_PUBLISHED,
    ERR_RESTORE_NAME_CONFLICT,
    ERR_SERVICE_STARTING,
    ERR_SERVICE_STOPPING,
    ERR_STATE_FILE_CORRUPT,
    ERR_TRACKER_STOP_FAILED,
    EXTENDED_RESOURCES_FIELDS,
    JITTER_FIELDS,
    LAST_OUTPUT_FIELDS,
    LAST_POSE_FIELDS,
    LAST_SCAN_HEADER_FIELDS,
    MAPPING_STATUS_FIELDS,
    MODE_IDLE,
    MODE_LIVE,
    MODE_ONESHOT,
    PROCESS_FIELDS,
    RESOURCES_FIELDS,
)

# Track B-BACKUP — `<ts>` path constraint for the restore route.
# Mirrors `map_backup._TS_REGEX` (the second defence layer) which
# accepts both legacy UTC-stamp form (`...Z` suffix) and the
# post-PR #83 KST-stamp form (no suffix). FastAPI returns 422 BEFORE
# the handler runs when the path doesn't match. issue#32: prior
# pattern was `Z$` (UTC-only), which 422'd every backup created after
# the PR #83 KST timestamp lock.
_BACKUP_TS_PATTERN = r"^[0-9]{8}T[0-9]{6}Z?$"

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


class CalibrateBody(BaseModel):
    """`POST /api/calibrate` body (issue#3 — initial pose hint UI).

    All five fields are optional. When the operator places a hint via
    the SPA, the seed triple `(seed_x_m, seed_y_m, seed_yaw_deg)` is
    all-or-none — partial submissions are 422'd here BEFORE reaching
    UDS. σ overrides are independent of each other but require the
    seed triple to be present (operators cannot tune σ without
    placing a hint).

    Bounds match production/RPi5/src/uds/uds_server.cpp::hint_within_bounds
    byte-exactly and the schema row constraints in
    config_schema.hpp::CONFIG_SCHEMA. Drift is a CODEBASE invariant
    violation.

    Mode-A M4 — uses `model_validator(mode='after')` for the
    cross-field shape check; per-field bounds use Pydantic v2 `Field`
    constraints so a typo lands as 422 BEFORE the validator runs.
    """

    seed_x_m:      float | None = Field(default=None, ge=-100.0, le=100.0)
    seed_y_m:      float | None = Field(default=None, ge=-100.0, le=100.0)
    seed_yaw_deg:  float | None = Field(default=None, ge=0.0,    lt=360.0)
    sigma_xy_m:    float | None = Field(default=None, ge=0.05,   le=5.0)
    sigma_yaw_deg: float | None = Field(default=None, ge=1.0,    le=90.0)

    @model_validator(mode="after")
    def all_or_none_seed(self) -> CalibrateBody:
        triple = (self.seed_x_m, self.seed_y_m, self.seed_yaw_deg)
        n_present = sum(v is not None for v in triple)
        if n_present not in (0, 3):
            raise ValueError(
                "seed_x_m, seed_y_m, seed_yaw_deg must all be present "
                "or all absent",
            )
        if n_present == 0 and (
            self.sigma_xy_m is not None or self.sigma_yaw_deg is not None
        ):
            raise ValueError(
                "sigma overrides require seed_* to be present",
            )
        return self


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


class OriginPatchBody(BaseModel):
    """`POST /api/map/origin` body (Track B-MAPEDIT-2 + issue#27 theta).

    `mode` is a Pydantic `Literal` so a typo lands as 422 BEFORE the
    handler runs. NaN / ±Inf are guarded by the explicit `math.isfinite`
    check inside `apply_origin_edit` (S5 fold: `math.isfinite` is the
    load-bearing check; Pydantic's `allow_inf_nan` is best-effort
    defence-in-depth).

    issue#27 — `theta_deg` is optional. When omitted the YAML theta token
    is preserved byte-for-byte (existing contract). When supplied the
    value is converted to radians and written via `repr(theta_rad)`.
    """

    x_m: float = Field(...)
    y_m: float = Field(...)
    mode: Literal["absolute", "delta"] = Field(...)
    theta_deg: float | None = Field(default=None)


class MapEditCoordBody(BaseModel):
    """`POST /api/map/edit/coord` body.

    issue#30 wire shape — pick-anchored + delta-on-top semantics:
    - `x_m` / `y_m`: operator's typed delta (world-frame meters, in the
      active-at-pick frame). Empty / 0 = "no further nudge". These are
      `delta_translate_x_m` / `delta_translate_y_m` in `sidecar.ThisStep`.
    - `theta_deg`: operator's typed rotation delta (degrees, optional).
    - `picked_world_x_m` / `picked_world_y_m`: the world-frame coord of
      the operator's canvas click at time of click. The click defines
      the new origin baseline (= world (0, 0)) before the typed delta
      is applied on top. When omitted we treat the body as legacy
      pre-issue#30 (round-1 wire shape) and set
      `picked_world_* = x_m / y_m` — round-trip equivalent to the
      pre-issue#30 collapse, so a stale SPA bundle does not silently
      regress; the response carries the
      `X-GODO-Deprecation: picked_world_missing` header so HIL can
      spot regressions immediately.
    """

    x_m: float = Field(...)
    y_m: float = Field(...)
    theta_deg: float | None = Field(default=None)
    memo: str = Field(min_length=1, max_length=32)
    picked_world_x_m: float | None = Field(default=None)
    picked_world_y_m: float | None = Field(default=None)


class MappingStartBody(BaseModel):
    """`POST /api/mapping/start` body (issue#14)."""

    name: str = Field(min_length=1, max_length=MAPPING_NAME_MAX_LEN)


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
    if isinstance(exc, maps_mod.PgmHeaderInvalid):
        # Track D scale fix: a malformed PGM surfaces as 500 map_invalid,
        # mirroring `map_image_mod.MapImageInvalid`'s shape (the SPA
        # already handles this code).
        return JSONResponse(
            {"ok": False, "err": "map_invalid"},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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


def _map_edit_exc_to_response(exc: Exception) -> JSONResponse:
    """Local error mapper for `map_edit.*` exceptions. Kept separate from
    `_map_maps_exc_to_response` and `_map_backup_exc_to_response` because
    the three error families do not overlap (CODEBASE.md invariant (c)).

    Status mapping (Track B-MAPEDIT, see CODEBASE.md invariant (aa)):
      - `MaskTooLarge` → 413 (`mask_too_large`)
      - `MaskDecodeFailed` → 400 (`mask_decode_failed`)
      - `MaskShapeMismatch` → 400 (`mask_shape_mismatch`)
      - `ActiveMapMissing` → 503 (`active_map_missing`)
      - `EditFailed` (atomic-write or header-parse) → 500 (`edit_failed`)
    """
    if isinstance(exc, map_edit_mod.MaskTooLarge):
        return JSONResponse(
            {"ok": False, "err": ERR_MASK_TOO_LARGE},
            status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    if isinstance(exc, map_edit_mod.MaskDecodeFailed):
        return JSONResponse(
            {"ok": False, "err": ERR_MASK_DECODE_FAILED},
            status_code=HTTPStatus.BAD_REQUEST,
        )
    if isinstance(exc, map_edit_mod.MaskShapeMismatch):
        return JSONResponse(
            {"ok": False, "err": ERR_MASK_SHAPE_MISMATCH, "detail": str(exc)},
            status_code=HTTPStatus.BAD_REQUEST,
        )
    if isinstance(exc, map_edit_mod.ActiveMapMissing):
        return JSONResponse(
            {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, map_edit_mod.EditFailed):
        return JSONResponse(
            {"ok": False, "err": ERR_EDIT_FAILED, "detail": str(exc)},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    return JSONResponse(
        {"ok": False, "err": "internal_error"},
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


def _map_mapping_exc_to_response(exc: Exception) -> JSONResponse:
    """issue#14 — Local error mapper for `mapping.*` exceptions. Status
    mapping per the API surface table in plan §5."""
    if isinstance(exc, mapping_mod.InvalidName):
        body: dict[str, object] = {"ok": False, "err": ERR_INVALID_MAPPING_NAME}
        if exc.args:
            body["detail"] = str(exc.args[0])
        return JSONResponse(body, status_code=HTTPStatus.BAD_REQUEST)
    if isinstance(exc, mapping_mod.NameAlreadyExists):
        return JSONResponse(
            {"ok": False, "err": ERR_NAME_EXISTS, "detail": str(exc)},
            status_code=HTTPStatus.CONFLICT,
        )
    if isinstance(exc, mapping_mod.MappingAlreadyActive):
        return JSONResponse(
            {"ok": False, "err": ERR_MAPPING_ALREADY_ACTIVE, "detail": str(exc)},
            status_code=HTTPStatus.CONFLICT,
        )
    if isinstance(exc, mapping_mod.ImageMissing):
        return JSONResponse(
            {
                "ok": False,
                "err": ERR_IMAGE_MISSING,
                "detail": (
                    "Build image: cd godo-mapping && docker build -t godo-mapping:dev ."
                ),
            },
            status_code=HTTPStatus.PRECONDITION_FAILED,
        )
    if isinstance(exc, mapping_mod.TrackerStopFailed):
        return JSONResponse(
            {"ok": False, "err": ERR_TRACKER_STOP_FAILED, "detail": str(exc)},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, mapping_mod.DockerUnavailable):
        return JSONResponse(
            {"ok": False, "err": ERR_DOCKER_UNAVAILABLE, "detail": str(exc)},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, mapping_mod.ContainerStartTimeout):
        return JSONResponse(
            {"ok": False, "err": ERR_CONTAINER_START_TIMEOUT, "detail": str(exc)},
            status_code=HTTPStatus.GATEWAY_TIMEOUT,
        )
    if isinstance(exc, mapping_mod.ContainerStopTimeout):
        return JSONResponse(
            {"ok": False, "err": ERR_CONTAINER_STOP_TIMEOUT, "detail": str(exc)},
            status_code=HTTPStatus.GATEWAY_TIMEOUT,
        )
    if isinstance(exc, mapping_mod.NoActiveMapping):
        return JSONResponse(
            {"ok": False, "err": ERR_NO_ACTIVE_MAPPING},
            status_code=HTTPStatus.NOT_FOUND,
        )
    if isinstance(exc, mapping_mod.StateFileCorrupt):
        return JSONResponse(
            {"ok": False, "err": ERR_STATE_FILE_CORRUPT, "detail": str(exc)},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    return JSONResponse(
        {"ok": False, "err": "internal_error"},
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


def _mapping_lockout_response() -> JSONResponse:
    """L14 — return 409 mapping_active when state ∈ {Starting, Running, Stopping}.
    Used by /api/calibrate, /api/live, /api/map/edit, /api/map/origin."""
    return JSONResponse(
        {"ok": False, "err": ERR_MAPPING_ACTIVE, "detail": "Mapping mode active"},
        status_code=HTTPStatus.CONFLICT,
    )


def _is_mapping_active(cfg: Settings) -> bool:
    """L14 — True when mapping mode coordinator says ∈ {Starting, Running, Stopping}."""
    try:
        s = mapping_mod.status(cfg)
    except mapping_mod.MappingError:
        return False
    return s.state in (
        mapping_mod.MappingState.STARTING,
        mapping_mod.MappingState.RUNNING,
        mapping_mod.MappingState.STOPPING,
    )


def _map_origin_exc_to_response(exc: Exception) -> JSONResponse:
    """Local error mapper for `map_origin.*` exceptions. Kept separate
    from `_map_edit_exc_to_response` because the two error families do
    not overlap (CODEBASE.md invariant (c)).

    Status mapping (Track B-MAPEDIT-2, see CODEBASE.md invariant (ab)):
      - `BadOriginValue` → 400 (`bad_origin_value`, detail = reason).
      - `OriginYamlParseFailed` → 500 (`origin_yaml_parse_failed`,
        detail = reason).
      - `ActiveYamlMissing` → 503 (`active_yaml_missing`).
      - `OriginEditFailed` (atomic-write or I/O) → 500
        (`origin_edit_failed`, detail = exception text).
    """
    if isinstance(exc, map_origin_mod.BadOriginValue):
        return JSONResponse(
            {"ok": False, "err": ERR_ORIGIN_BAD_VALUE, "detail": str(exc)},
            status_code=HTTPStatus.BAD_REQUEST,
        )
    if isinstance(exc, map_origin_mod.ActiveYamlMissing):
        return JSONResponse(
            {"ok": False, "err": ERR_ACTIVE_YAML_MISSING},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, map_origin_mod.OriginYamlParseFailed):
        return JSONResponse(
            {"ok": False, "err": ERR_ORIGIN_YAML_PARSE_FAILED, "detail": str(exc)},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    if isinstance(exc, map_origin_mod.OriginEditFailed):
        return JSONResponse(
            {"ok": False, "err": ERR_ORIGIN_EDIT_FAILED, "detail": str(exc)},
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


def _last_output_view(resp: dict[str, object]) -> dict[str, object]:
    """issue#27 — projection through LAST_OUTPUT_FIELDS. Same shape as
    `_last_pose_view`; the wire fields are the 8 channels emitted to UE
    after `udp::apply_output_transform_inplace`."""
    return {field: resp.get(field) for field in LAST_OUTPUT_FIELDS}


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


def _processes_view(snap: dict[str, object]) -> dict[str, object]:
    """PR-B — projection through PROCESSES_RESPONSE_FIELDS (envelope) +
    PROCESS_FIELDS (per row). The sampler's row order (sorted by
    cpu_pct desc) is preserved."""
    rows = snap.get("processes")
    out_rows: list[dict[str, object]] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                out_rows.append({field: row.get(field) for field in PROCESS_FIELDS})
    return {
        "processes": out_rows,
        "duplicate_alert": snap.get("duplicate_alert", False),
        "published_mono_ns": snap.get("published_mono_ns"),
    }


def _extended_resources_view(snap: dict[str, object]) -> dict[str, object]:
    """PR-B — projection through EXTENDED_RESOURCES_FIELDS so the wire
    shape is byte-stable."""
    return {field: snap.get(field) for field in EXTENDED_RESOURCES_FIELDS}


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


# --- issue#28 — Map-Edit pipeline helper -----------------------------
#
# Sole composer of the SUBTRACT origin → rotate-PGM → atomic pair-write
# → restart-pending sequence. Lives at module scope so the per-request
# closures stay small and so unit tests can drive it directly.
async def _apply_map_edit_pipeline(
    *,
    cfg: Settings,
    client: uds_mod.UdsClient,  # currently unused; reserved for future tracker UDS hand-off
    activity_log: activity_mod.ActivityLog,
    claims: auth_mod.Claims,
    map_edit_pipeline_lock: asyncio.Lock,
    mode: Literal["coord", "erase"],
    memo: str,
    x_m: float,
    y_m: float,
    theta_deg: float | None,
    mask_bytes: bytes | None,
    picked_world_x_m: float | None = None,
    picked_world_y_m: float | None = None,
) -> JSONResponse:
    import secrets as _secrets

    request_id = _secrets.token_hex(8)
    # 202-style synchronous: SPA waits for completion. SSE progress is
    # emitted in parallel for UX feedback.
    try:
        # Pipeline lock — fail fast when another Apply is in flight.
        try:
            await asyncio.wait_for(
                map_edit_pipeline_lock.acquire(),
                timeout=MAP_EDIT_PIPELINE_LOCK_TIMEOUT_S,
            )
        except TimeoutError:
            return JSONResponse(
                {"ok": False, "err": "pipeline_busy"},
                status_code=HTTPStatus.CONFLICT,
            )

        try:
            await sse_mod.publish_map_edit_progress(
                {"phase": "starting", "progress": 0.0, "request_id": request_id},
            )

            # 1. Resolve active map name + pristine path.
            active_name = await asyncio.to_thread(
                maps_mod.read_active_name, cfg.maps_dir,
            )
            if active_name is None:
                await sse_mod.publish_map_edit_progress(
                    {
                        "phase": "rejected",
                        "progress": 1.0,
                        "request_id": request_id,
                        "reason": "active_map_missing",
                    },
                )
                return JSONResponse(
                    {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            pristine_base = maps_mod.derived_base(active_name) or active_name
            try:
                pristine_pgm = maps_mod.pgm_for(cfg.maps_dir, pristine_base)
                pristine_yaml = maps_mod.yaml_for(cfg.maps_dir, pristine_base)
            except maps_mod.InvalidName as e:
                return _map_maps_exc_to_response(e)
            if not pristine_pgm.is_file() or not pristine_yaml.is_file():
                await sse_mod.publish_map_edit_progress(
                    {
                        "phase": "rejected",
                        "progress": 1.0,
                        "request_id": request_id,
                        "reason": "pristine_missing",
                    },
                )
                return JSONResponse(
                    {"ok": False, "err": "pristine_missing"},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )

            # 2. Build derived names. `derive_name` validates memo and
            # generates the second-resolution UTC timestamp.
            try:
                derived_name = maps_mod.derive_name(pristine_base, memo)
            except (maps_mod.InvalidName, maps_mod.InvalidMemo) as e:
                await sse_mod.publish_map_edit_progress(
                    {
                        "phase": "rejected",
                        "progress": 1.0,
                        "request_id": request_id,
                        "reason": "invalid_name",
                    },
                )
                return JSONResponse(
                    {"ok": False, "err": "invalid_memo", "detail": str(e)},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            try:
                derived_pgm = maps_mod.pgm_for(cfg.maps_dir, derived_name)
                derived_yaml = maps_mod.yaml_for(cfg.maps_dir, derived_name)
            except maps_mod.InvalidName as e:
                return _map_maps_exc_to_response(e)

            await sse_mod.publish_map_edit_progress(
                {"phase": "yaml_rewrite", "progress": 0.2, "request_id": request_id},
            )

            # 3. issue#30 — pick-anchored pipeline replaces SUBTRACT.
            # Coord mode: read parent's sidecar (if active map is a
            # derived) → compose cumulative_from_pristine via
            # sidecar.compose_cumulative → invoke
            # map_transform.transform_pristine_to_derived which handles
            # the YAML rewrite + C3-triple atomic write internally.
            # Erase mode: no origin change; reuse the pristine YAML
            # bytes byte-identically.
            pristine_yaml_text = await asyncio.to_thread(pristine_yaml.read_text, "utf-8")
            edit_result = None
            new_yaml_text = pristine_yaml_text  # default — erase mode

            # 4. Branch — coord runs map_transform (issue#30); erase runs map_edit.
            if mode == "coord":
                await sse_mod.publish_map_edit_progress(
                    {"phase": "rotate", "progress": 0.5, "request_id": request_id},
                )

                # 4a. Read parent's sidecar to compose cumulative.
                # active_name may equal pristine_base when active is the
                # pristine itself (PICK#1) — parent_cumulative defaults
                # to identity in that case.
                parent_cumulative = sidecar_mod.Cumulative(0.0, 0.0, 0.0)
                parent_lineage: list[str] = []
                active_sidecar_path = sidecar_mod.sidecar_path_for(cfg.maps_dir, active_name)
                if active_name != pristine_base and active_sidecar_path.is_file():
                    try:
                        parent_sc = await asyncio.to_thread(
                            sidecar_mod.read, active_sidecar_path,
                        )
                        # Verify integrity if the active is a derived
                        # — operator hand-edit between PICKs surfaces
                        # as 422 sidecar_sha_mismatch.
                        active_pgm_path = maps_mod.pgm_for(cfg.maps_dir, active_name)
                        active_yaml_path = maps_mod.yaml_for(cfg.maps_dir, active_name)
                        ok = await asyncio.to_thread(
                            sidecar_mod.verify_integrity,
                            parent_sc,
                            active_pgm_path,
                            active_yaml_path,
                        )
                        if not ok:
                            return JSONResponse(
                                {
                                    "ok": False,
                                    "err": "sidecar_sha_mismatch",
                                    "detail": (
                                        "Map files were modified outside the "
                                        "Apply pipeline. Treating active map as "
                                        "a new pristine baseline."
                                    ),
                                },
                                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                            )
                        parent_cumulative = parent_sc.cumulative_from_pristine
                        parent_lineage = list(parent_sc.lineage_parents) + [active_name]
                    except sidecar_mod.SidecarError as e:
                        logger.warning(
                            "map_edit.sidecar_read_failed: %s — proceeding with identity",
                            e,
                        )
                # NOTE [MI-B1]: a missing sidecar for an active derived
                # is impossible at this point — the startup recovery_sweep
                # synthesized one (auto_migrated_pre_issue30 for PR #81-era
                # files). The opportunistic in-list sweep is belt-and-braces.
                # The pre-round-2 slow-path fallback (`parent_lineage =
                # [active_name]` when active is a derived without sidecar)
                # was removed because the startup invariant guarantees a
                # sidecar exists on disk before any Apply runs.

                # 4b. Compose this Apply's typed step + cumulative.
                # Per Q2 + C-2.1 lock: SPA sends typed delta in
                # `x_m`/`y_m`/`theta_deg` AND the canvas-clicked world
                # coord in `picked_world_x_m`/`picked_world_y_m`. A
                # legacy SPA bundle (pre-issue#30) omits the picked
                # fields → treat as `picked_world = typed_delta`
                # (round-1 collapse, equivalent to pristine pivot) and
                # surface `X-GODO-Deprecation: picked_world_missing` on
                # the response so HIL spots stale-bundle regressions.
                effective_picked_x = (
                    picked_world_x_m if picked_world_x_m is not None else x_m
                )
                effective_picked_y = (
                    picked_world_y_m if picked_world_y_m is not None else y_m
                )
                this_step_local = sidecar_mod.ThisStep(
                    delta_translate_x_m=x_m,
                    delta_translate_y_m=y_m,
                    delta_rotate_deg=theta_deg if theta_deg is not None else 0.0,
                    picked_world_x_m=effective_picked_x,
                    picked_world_y_m=effective_picked_y,
                )
                cumulative = await asyncio.to_thread(
                    sidecar_mod.compose_cumulative,
                    sidecar_mod.Cumulative(
                        parent_cumulative.translate_x_m,
                        parent_cumulative.translate_y_m,
                        parent_cumulative.rotate_deg,
                    ),
                    this_step_local,
                )

                # 4c. Convert sidecar.Cumulative → map_transform.Cumulative.
                mt_cumulative = map_transform_mod.Cumulative(
                    translate_x_m=cumulative.translate_x_m,
                    translate_y_m=cumulative.translate_y_m,
                    rotate_deg=cumulative.rotate_deg,
                )
                mt_this_step = map_transform_mod.ThisStep(
                    delta_translate_x_m=this_step_local.delta_translate_x_m,
                    delta_translate_y_m=this_step_local.delta_translate_y_m,
                    delta_rotate_deg=this_step_local.delta_rotate_deg,
                    picked_world_x_m=this_step_local.picked_world_x_m,
                    picked_world_y_m=this_step_local.picked_world_y_m,
                )
                derived_sidecar_path = sidecar_mod.sidecar_path_for(
                    cfg.maps_dir, derived_name,
                )

                try:
                    rot = await asyncio.to_thread(
                        map_transform_mod.transform_pristine_to_derived,
                        pristine_pgm,
                        pristine_yaml,
                        derived_pgm,
                        derived_yaml,
                        derived_sidecar_path,
                        mt_cumulative,
                        mt_this_step,
                        parent_lineage,
                        memo=memo,
                        reason="operator_apply",
                    )
                except map_transform_mod.CanvasTooLarge as e:
                    await sse_mod.publish_map_edit_progress(
                        {
                            "phase": "rejected",
                            "progress": 1.0,
                            "request_id": request_id,
                            "reason": "canvas_too_large",
                        },
                    )
                    return JSONResponse(
                        {"ok": False, "err": "canvas_too_large", "detail": str(e)},
                        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                    )
                except map_transform_mod.PristineMissing:
                    await sse_mod.publish_map_edit_progress(
                        {
                            "phase": "rejected",
                            "progress": 1.0,
                            "request_id": request_id,
                            "reason": "pristine_missing",
                        },
                    )
                    return JSONResponse(
                        {"ok": False, "err": "pristine_missing"},
                        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                except map_transform_mod.RotateError as e:
                    await sse_mod.publish_map_edit_progress(
                        {
                            "phase": "rejected",
                            "progress": 1.0,
                            "request_id": request_id,
                            "reason": "transform_failed",
                        },
                    )
                    return JSONResponse(
                        {"ok": False, "err": "pair_write_failed", "detail": str(e)},
                        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                pixels_changed = rot.new_width_px * rot.new_height_px
                # Compose an OriginEditResult-like tuple for the
                # response body (prev/new origin display). prev_origin
                # comes from the pristine YAML; new_origin from the
                # transform result.
                pristine_origin = (
                    map_origin_mod._find_unique_origin_line(
                        pristine_yaml_text.splitlines(keepends=True),
                    )[1]
                )
                edit_result = map_origin_mod.OriginEditResult(
                    prev_origin=(
                        float(pristine_origin.group(4)),
                        float(pristine_origin.group(6)),
                        float(pristine_origin.group(8)),
                    ),
                    new_origin=(
                        rot.new_yaml_origin_xy_yaw[0],
                        rot.new_yaml_origin_xy_yaw[1],
                        # YAML stores yaw in radians; new_yaml_origin
                        # carries deg=0 → convert.
                        math.radians(rot.new_yaml_origin_xy_yaw[2]),
                    ),
                )
            else:
                # Erase mode: write derived PGM via map_edit on a copy
                # of the pristine PGM bytes, then write derived YAML.
                await sse_mod.publish_map_edit_progress(
                    {"phase": "rotate", "progress": 0.5, "request_id": request_id},
                )
                if mask_bytes is None:
                    return JSONResponse(
                        {"ok": False, "err": ERR_MASK_DECODE_FAILED},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                pristine_pgm_bytes = await asyncio.to_thread(pristine_pgm.read_bytes)
                # Compose a tmp pristine-copy so map_edit's atomic
                # writer lands on the derived path.
                try:
                    tmp_derived = derived_pgm
                    await asyncio.to_thread(tmp_derived.write_bytes, pristine_pgm_bytes)
                    edit_res = await asyncio.to_thread(
                        map_edit_mod.apply_edit, tmp_derived, mask_bytes,
                    )
                    # Write the (byte-identical-to-pristine) YAML beside it.
                    await asyncio.to_thread(
                        derived_yaml.write_bytes, new_yaml_text.encode("utf-8"),
                    )
                except map_edit_mod.MapEditError as e:
                    return _map_edit_exc_to_response(e)
                pixels_changed = edit_res.pixels_changed

            # 5. Activate the new derived pair (operator may want to
            # immediately restart). Activation is a separate user
            # action — we DO NOT auto-activate here. Only emit the
            # restart-pending sentinel.
            await sse_mod.publish_map_edit_progress(
                {"phase": "restart_pending", "progress": 0.95, "request_id": request_id},
            )

            try:
                await asyncio.to_thread(
                    restart_pending_mod.touch, cfg.restart_pending_path,
                )
            except OSError as e:
                return JSONResponse(
                    {
                        "ok": False,
                        "err": ERR_EDIT_FAILED,
                        "detail": f"restart_pending_touch: {e}",
                    },
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

            map_image_mod.invalidate_cache()
            activity_log.append(
                "map_edit_pipeline",
                f"mode={mode}, derived={derived_name}, pixels={pixels_changed}, "
                f"by={claims.username}",
            )

            await sse_mod.publish_map_edit_progress(
                {
                    "phase": "done",
                    "progress": 1.0,
                    "request_id": request_id,
                    "derived_name": derived_name,
                },
            )
            response_body: dict[str, object] = {
                "ok": True,
                "request_id": request_id,
                "derived_name": derived_name,
                "derived_pair": {
                    "pgm": derived_pgm.name,
                    "yaml": derived_yaml.name,
                },
                "pristine_pair": {
                    "pgm": maps_mod.pgm_for(cfg.maps_dir, pristine_base).name,
                    "yaml": maps_mod.yaml_for(cfg.maps_dir, pristine_base).name,
                },
                "pixels_changed": pixels_changed,
                "restart_required": True,
            }
            if edit_result is not None:
                response_body["prev_origin"] = list(edit_result.prev_origin)
                response_body["new_origin"] = list(edit_result.new_origin)
            response_headers: dict[str, str] = {}
            if (
                mode == "coord"
                and (picked_world_x_m is None or picked_world_y_m is None)
            ):
                # issue#30 wire-shape deprecation — legacy SPA bundle
                # omitted picked_world_*. Surface so HIL operators can
                # spot stale-bundle regressions.
                response_headers["X-GODO-Deprecation"] = "picked_world_missing"
            return JSONResponse(
                response_body,
                status_code=HTTPStatus.OK,
                headers=response_headers,
            )
        finally:
            map_edit_pipeline_lock.release()
    except Exception as e:  # noqa: BLE001 — defence-in-depth around the pipeline
        logger.exception("map_edit_pipeline.unexpected_error: %s", e)
        await sse_mod.publish_map_edit_progress(
            {
                "phase": "rejected",
                "progress": 1.0,
                "request_id": request_id,
                "reason": "internal_error",
            },
        )
        return JSONResponse(
            {"ok": False, "err": "internal_error", "detail": str(e)},
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    _ensure_logging_configured()
    cfg: Settings = settings if settings is not None else load_settings()
    client = uds_mod.UdsClient(cfg.uds_socket)
    activity_log = activity_mod.ActivityLog()

    # issue#28 — C4 lock. Serialises every Map-Edit Apply (coord OR
    # erase) so two concurrent POSTs cannot race a derived-pair write
    # against itself OR collide on the second-resolution timestamp.
    map_edit_pipeline_lock = asyncio.Lock()

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
        # issue#30 [MI-B1] — startup-time sidecar recovery sweep so
        # PR #81-era derived maps are auto-migrated to lineage-bearing
        # sidecars BEFORE the first list_maps call. The opportunistic
        # in-list sweep is now belt-and-braces; the startup sweep is
        # the load-bearing invariant.
        try:
            sidecar_mod.recovery_sweep(cfg.maps_dir)
        except Exception as e:  # noqa: BLE001
            logger.warning("startup.recovery_sweep_failed: %s", e)
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
        body: CalibrateBody | None = None,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        # issue#14 L14 lock-out: refuse calibrate when mapping is active.
        if _is_mapping_active(cfg):
            return _mapping_lockout_response()
        # issue#3 — optional pose hint. Empty body / `body is None` /
        # `body` with all fields None → byte-identical to pre-issue#3
        # wire (back-compat anti-regression pinned in test_protocol +
        # test_app_integration).
        seed: tuple[float, float, float] | None = None
        sigma_xy: float | None = None
        sigma_yaw: float | None = None
        if (
            body is not None
            and body.seed_x_m is not None
            and body.seed_y_m is not None
            and body.seed_yaw_deg is not None
        ):
            # Pydantic `all_or_none_seed` already enforced full triple
            # — the explicit None-checks above narrow the types so mypy
            # accepts the float-tuple constructor without a cast.
            seed = (body.seed_x_m, body.seed_y_m, body.seed_yaw_deg)
            sigma_xy = body.sigma_xy_m
            sigma_yaw = body.sigma_yaw_deg
        try:
            await uds_mod.call_uds(
                client.set_mode,
                MODE_ONESHOT,
                cfg.calibrate_uds_timeout_s,
                seed=seed,
                sigma_xy_m=sigma_xy,
                sigma_yaw_deg=sigma_yaw,
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
        # issue#14 L14 lock-out.
        if _is_mapping_active(cfg):
            return _mapping_lockout_response()
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
        # Resolve the active PGM via maps_dir/active.pgm symlink (mirrors
        # /api/map/edit + /api/map/origin patterns above). The previous
        # implementation passed `cfg.map_path` directly — that field is
        # the deprecated Track-E pre-symlink hook (default value points
        # at a non-existent path on hosts that never set it), so the
        # backup endpoint was unconditionally returning
        # `map_path_not_found`. Fix: read the active symlink target via
        # maps_mod and pass the realpath through to backup_map.
        active_name = await asyncio.to_thread(maps_mod.read_active_name, cfg.maps_dir)
        if active_name is None:
            return JSONResponse(
                {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        try:
            active_pgm = maps_mod.pgm_for(cfg.maps_dir, active_name)
        except maps_mod.InvalidName as e:
            return _map_maps_exc_to_response(e)
        if not active_pgm.is_file():
            return JSONResponse(
                {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        try:
            path = await asyncio.to_thread(
                backup_mod.backup_map,
                active_pgm,
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

    # ---- /api/map/edit (Track B-MAPEDIT, admin) -------------------------
    # Brush-erase + auto-backup + restart-required. Three-step sequence
    # is contractual (see CODEBASE.md invariant (aa)):
    #   1. backup_map(active_pgm, cfg.backup_dir) — backup-FIRST so an
    #      edit-failure leaves a recoverable snapshot.
    #   2. map_edit.apply_edit(active_pgm, mask_bytes) — atomic on-disk
    #      rewrite; backup-failure aborts BEFORE this step.
    #   3. restart_pending.touch(cfg.restart_pending_path) — last step;
    #      never set on a failure path (anti-monotone partner).
    # Tracker C++ has no awareness of edits — it reads PGM at boot only.
    # Operator restarts via /local (loopback) or /system (admin-non-
    # loopback per PR #27) to apply.
    @app.post("/api/map/edit")
    async def map_edit_endpoint(
        request: Request,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        # issue#14 L14 lock-out: refuse edits during mapping.
        if _is_mapping_active(cfg):
            return _mapping_lockout_response()
        # T2 fold: content-length check BEFORE any decode. Distinct
        # error from MaskShapeMismatch (which runs after decode).
        cl_header = request.headers.get("content-length")
        if cl_header is not None:
            try:
                cl = int(cl_header)
            except ValueError:
                cl = -1
            if cl > MAP_EDIT_MASK_PNG_MAX_BYTES:
                return JSONResponse(
                    {"ok": False, "err": ERR_MASK_TOO_LARGE},
                    status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
        # Resolve the active PGM realpath via maps.py. The active.pgm
        # symlink hop is intentional: if a future writer hand-edits the
        # symlink to a path outside maps_dir, `pgm_for` raises
        # InvalidName via realpath containment.
        active_name = await asyncio.to_thread(maps_mod.read_active_name, cfg.maps_dir)
        if active_name is None:
            return JSONResponse(
                {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        try:
            active_pgm = maps_mod.pgm_for(cfg.maps_dir, active_name)
        except maps_mod.InvalidName as e:
            return _map_maps_exc_to_response(e)
        if not active_pgm.is_file():
            return JSONResponse(
                {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        # Read the multipart body. FastAPI's `Form()` / `File()` would
        # require a Pydantic-style model; for a single binary part we
        # accept either:
        #   - multipart/form-data with a `mask` part
        #   - raw image/png body (operator using `curl -T`)
        ctype = request.headers.get("content-type", "")
        try:
            if "multipart/form-data" in ctype.lower():
                form = await request.form()
                mask_part = form.get("mask")
                if mask_part is None:
                    return JSONResponse(
                        {"ok": False, "err": ERR_MASK_DECODE_FAILED, "detail": "missing_mask_part"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                if hasattr(mask_part, "read"):
                    mask_bytes = await mask_part.read()  # type: ignore[union-attr]
                else:
                    mask_bytes = (
                        mask_part.encode("latin-1")
                        if isinstance(mask_part, str)
                        else bytes(mask_part)
                    )
            else:
                mask_bytes = await request.body()
        except (OSError, ValueError) as e:
            return JSONResponse(
                {"ok": False, "err": ERR_MASK_DECODE_FAILED, "detail": str(e)},
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # Defence-in-depth: re-check size on the decoded byte length
        # (multipart envelopes can hide the real payload size).
        if len(mask_bytes) > MAP_EDIT_MASK_PNG_MAX_BYTES:
            return JSONResponse(
                {"ok": False, "err": ERR_MASK_TOO_LARGE},
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )

        # Step 1: auto-backup. Backup-failure aborts the request BEFORE
        # the PGM is touched.
        try:
            backup_dir_path = await asyncio.to_thread(
                backup_mod.backup_map,
                active_pgm,
                cfg.backup_dir,
            )
        except backup_mod.BackupError as e:
            err = str(e)
            if err == "concurrent_backup_in_progress":
                return JSONResponse(
                    {
                        "ok": False,
                        "err": err,
                        "detail": "다른 백업이 진행 중입니다.",
                    },
                    status_code=HTTPStatus.CONFLICT,
                )
            if err == "map_path_not_found":
                return JSONResponse(
                    {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return JSONResponse(
                {"ok": False, "err": "backup_failed", "detail": err},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        backup_ts = backup_dir_path.name

        # Step 2: atomic PGM rewrite.
        try:
            result = await asyncio.to_thread(
                map_edit_mod.apply_edit,
                active_pgm,
                mask_bytes,
            )
        except map_edit_mod.MapEditError as e:
            return _map_edit_exc_to_response(e)

        # Step 3: restart-pending sentinel. Last step on the success
        # path; never touched on the failure path.
        try:
            await asyncio.to_thread(
                restart_pending_mod.touch,
                cfg.restart_pending_path,
            )
        except OSError as e:
            return JSONResponse(
                {"ok": False, "err": ERR_EDIT_FAILED, "detail": f"restart_pending_touch: {e}"},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        # Drop the cached PGM bytes so the next /api/map/image GET
        # re-renders from the just-modified PGM.
        map_image_mod.invalidate_cache()

        activity_log.append(
            "map_edit",
            f"backup={backup_ts}, pixels_changed={result.pixels_changed} by {claims.username}",
        )
        return JSONResponse(
            {
                "ok": True,
                "backup_ts": backup_ts,
                "pixels_changed": result.pixels_changed,
                "restart_required": True,
            },
            status_code=HTTPStatus.OK,
        )

    # ---- /api/map/origin (Track B-MAPEDIT-2, admin) ---------------------
    # Operator-triggered origin pick. Three-step sequence is contractual
    # (see CODEBASE.md invariant (ab)):
    #   1. backup_map(active_pgm, cfg.backup_dir) — backup-FIRST. The PGM
    #      is unchanged but is included in the snapshot per `backup_map`'s
    #      pair contract (one helper covers both B-MAPEDIT and -2).
    #   2. map_origin.apply_origin_edit(active_yaml, x_m, y_m, mode) —
    #      atomic line-level YAML rewrite; theta + every other byte
    #      preserved; backup-failure aborts BEFORE this step.
    #   3. restart_pending.touch(cfg.restart_pending_path) — last step;
    #      never set on a failure path (anti-monotone partner).
    #
    # `map_image.invalidate_cache()` is intentionally NOT called: the
    # PNG cache key is `PGM realpath + mtime`, both unchanged by an
    # origin edit (S4 fold).
    @app.post("/api/map/origin")
    async def map_origin_endpoint(
        request: Request,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        # issue#14 L14 lock-out.
        if _is_mapping_active(cfg):
            return _mapping_lockout_response()
        # Body-size pre-check BEFORE Pydantic parse (M3: mirror of
        # PATCH /api/config — `bad_payload + detail=body_too_large`).
        raw = await request.body()
        if len(raw) > ORIGIN_BODY_MAX_BYTES:
            return JSONResponse(
                {"ok": False, "err": "bad_payload", "detail": "body_too_large"},
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        try:
            body = OriginPatchBody.model_validate_json(raw)
        except ValueError as e:
            return JSONResponse(
                {"ok": False, "err": "bad_payload", "detail": str(e)},
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # NaN/Inf + magnitude pre-check (S5 fold: math.isfinite is the
        # load-bearing check; Pydantic's allow_inf_nan is best-effort).
        # Defence-in-depth: `apply_origin_edit` re-checks the COMPUTED
        # values after delta resolution.
        import math as _math

        if not _math.isfinite(body.x_m):
            return JSONResponse(
                {"ok": False, "err": ERR_ORIGIN_BAD_VALUE, "detail": "non_finite_x_m"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if not _math.isfinite(body.y_m):
            return JSONResponse(
                {"ok": False, "err": ERR_ORIGIN_BAD_VALUE, "detail": "non_finite_y_m"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if abs(body.x_m) > ORIGIN_X_Y_ABS_MAX_M or abs(body.y_m) > ORIGIN_X_Y_ABS_MAX_M:
            return JSONResponse(
                {
                    "ok": False,
                    "err": ERR_ORIGIN_BAD_VALUE,
                    "detail": "abs_value_exceeds_bound",
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # Resolve the active map's name + YAML realpath via maps.py.
        active_name = await asyncio.to_thread(maps_mod.read_active_name, cfg.maps_dir)
        if active_name is None:
            return JSONResponse(
                {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        try:
            active_pgm = maps_mod.pgm_for(cfg.maps_dir, active_name)
            active_yaml = maps_mod.yaml_for(cfg.maps_dir, active_name)
        except maps_mod.InvalidName as e:
            return _map_maps_exc_to_response(e)
        if not active_pgm.is_file():
            return JSONResponse(
                {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        if not active_yaml.is_file():
            return JSONResponse(
                {"ok": False, "err": ERR_ACTIVE_YAML_MISSING},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        # Step 1: auto-backup. Backup-failure aborts BEFORE the YAML is
        # touched. Mirror of /api/map/edit's mapping.
        try:
            backup_dir_path = await asyncio.to_thread(
                backup_mod.backup_map,
                active_pgm,
                cfg.backup_dir,
            )
        except backup_mod.BackupError as e:
            err = str(e)
            if err == "concurrent_backup_in_progress":
                return JSONResponse(
                    {
                        "ok": False,
                        "err": err,
                        "detail": "다른 백업이 진행 중입니다.",
                    },
                    status_code=HTTPStatus.CONFLICT,
                )
            if err == "map_path_not_found":
                return JSONResponse(
                    {"ok": False, "err": ERR_ACTIVE_MAP_MISSING},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return JSONResponse(
                {"ok": False, "err": "backup_failed", "detail": err},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        backup_ts = backup_dir_path.name

        # Step 2: atomic YAML rewrite via the sole-owner module.
        try:
            result = await asyncio.to_thread(
                map_origin_mod.apply_origin_edit,
                active_yaml,
                body.x_m,
                body.y_m,
                body.mode,
                body.theta_deg,
            )
        except map_origin_mod.OriginEditError as e:
            return _map_origin_exc_to_response(e)

        # Step 3: restart-pending sentinel. Last step on the success
        # path; never touched on the failure path (anti-monotone).
        try:
            await asyncio.to_thread(
                restart_pending_mod.touch,
                cfg.restart_pending_path,
            )
        except OSError as e:
            return JSONResponse(
                {
                    "ok": False,
                    "err": ERR_ORIGIN_EDIT_FAILED,
                    "detail": f"restart_pending_touch: {e}",
                },
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        prev_x, prev_y, prev_th = result.prev_origin
        new_x, new_y, new_th = result.new_origin
        activity_log.append(
            "map_origin",
            f"mode={body.mode}, prev={prev_x:.3f},{prev_y:.3f} "
            f"new={new_x:.3f},{new_y:.3f} by {claims.username}",
        )
        return JSONResponse(
            {
                "ok": True,
                "backup_ts": backup_ts,
                "prev_origin": [prev_x, prev_y, prev_th],
                "new_origin": [new_x, new_y, new_th],
                "restart_required": True,
            },
            status_code=HTTPStatus.OK,
        )

    # ---- issue#28 — Map-Edit pipeline (coord + erase + progress SSE) ----
    #
    # New paired endpoints replace the in-place /api/map/edit and
    # /api/map/origin contracts (those stay alive for backward compat
    # one release). The new flow ALWAYS reads from the pristine pair and
    # ALWAYS emits a NEW derived pair `<base>.YYYYMMDD-HHMMSS-<memo>`.
    # Pristine is byte-immutable across the call. The pipeline lock
    # serialises Apply across all paths; SSE progress is single-channel
    # broadcast (see sse.py::publish_map_edit_progress).
    #
    # /api/map/edit/coord — JSON body. Re-applies SUBTRACT (x_m, y_m,
    # theta_deg) on the pristine YAML AND rotates the pristine PGM by
    # `-theta_deg` if non-zero, then atomic pair-writes the derived.
    #
    # /api/map/edit/erase — multipart/form-data with `mask` part +
    # `memo` form field. Decodes mask, applies brush-erase to the
    # pristine PGM, then atomic pair-writes a derived pair (PGM
    # modified, YAML byte-identical to pristine).

    @app.post("/api/map/edit/coord")
    async def map_edit_coord_endpoint(
        body: MapEditCoordBody,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        if _is_mapping_active(cfg):
            return _mapping_lockout_response()

        # Memo + bounds pre-checks BEFORE acquiring the pipeline lock so
        # a malformed request never starves a legitimate Apply.
        try:
            maps_mod.validate_memo(body.memo)
        except maps_mod.InvalidMemo as e:
            return JSONResponse(
                {"ok": False, "err": "invalid_memo", "detail": str(e)},
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        import math as _math

        if (not _math.isfinite(body.x_m)) or (not _math.isfinite(body.y_m)):
            return JSONResponse(
                {"ok": False, "err": ERR_ORIGIN_BAD_VALUE, "detail": "non_finite_xy"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if abs(body.x_m) > ORIGIN_X_Y_ABS_MAX_M or abs(body.y_m) > ORIGIN_X_Y_ABS_MAX_M:
            return JSONResponse(
                {"ok": False, "err": ERR_ORIGIN_BAD_VALUE, "detail": "abs_value_exceeds_bound"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if body.theta_deg is not None and not _math.isfinite(body.theta_deg):
            return JSONResponse(
                {"ok": False, "err": ERR_ORIGIN_BAD_VALUE, "detail": "non_finite_theta"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        # issue#30 wire-shape — picked_world_* are optional but if
        # provided must be finite. Bound check is identical to x/y
        # (operator's click is a world coord in the same active frame).
        if body.picked_world_x_m is not None and not _math.isfinite(body.picked_world_x_m):
            return JSONResponse(
                {"ok": False, "err": ERR_ORIGIN_BAD_VALUE, "detail": "non_finite_picked_x"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if body.picked_world_y_m is not None and not _math.isfinite(body.picked_world_y_m):
            return JSONResponse(
                {"ok": False, "err": ERR_ORIGIN_BAD_VALUE, "detail": "non_finite_picked_y"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if (
            body.picked_world_x_m is not None
            and abs(body.picked_world_x_m) > ORIGIN_X_Y_ABS_MAX_M
        ):
            return JSONResponse(
                {
                    "ok": False,
                    "err": ERR_ORIGIN_BAD_VALUE,
                    "detail": "picked_x_abs_value_exceeds_bound",
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if (
            body.picked_world_y_m is not None
            and abs(body.picked_world_y_m) > ORIGIN_X_Y_ABS_MAX_M
        ):
            return JSONResponse(
                {
                    "ok": False,
                    "err": ERR_ORIGIN_BAD_VALUE,
                    "detail": "picked_y_abs_value_exceeds_bound",
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )

        return await _apply_map_edit_pipeline(
            cfg=cfg,
            client=client,
            activity_log=activity_log,
            claims=claims,
            map_edit_pipeline_lock=map_edit_pipeline_lock,
            mode="coord",
            memo=body.memo,
            x_m=body.x_m,
            y_m=body.y_m,
            theta_deg=body.theta_deg,
            mask_bytes=None,
            picked_world_x_m=body.picked_world_x_m,
            picked_world_y_m=body.picked_world_y_m,
        )

    @app.post("/api/map/edit/erase")
    async def map_edit_erase_endpoint(
        request: Request,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        if _is_mapping_active(cfg):
            return _mapping_lockout_response()

        cl_header = request.headers.get("content-length")
        if cl_header is not None:
            try:
                cl = int(cl_header)
            except ValueError:
                cl = -1
            if cl > MAP_EDIT_MASK_PNG_MAX_BYTES:
                return JSONResponse(
                    {"ok": False, "err": "mask_too_large"},
                    status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )

        try:
            form = await request.form()
        except (OSError, ValueError) as e:
            return JSONResponse(
                {"ok": False, "err": ERR_MASK_DECODE_FAILED, "detail": str(e)},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        memo_raw = form.get("memo")
        if not isinstance(memo_raw, str):
            return JSONResponse(
                {"ok": False, "err": "invalid_memo", "detail": "memo_missing"},
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        try:
            maps_mod.validate_memo(memo_raw)
        except maps_mod.InvalidMemo as e:
            return JSONResponse(
                {"ok": False, "err": "invalid_memo", "detail": str(e)},
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        mask_part = form.get("mask")
        if mask_part is None:
            return JSONResponse(
                {"ok": False, "err": ERR_MASK_DECODE_FAILED, "detail": "missing_mask_part"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if hasattr(mask_part, "read"):
            mask_bytes = await mask_part.read()  # type: ignore[union-attr]
        else:
            mask_bytes = (
                mask_part.encode("latin-1") if isinstance(mask_part, str) else bytes(mask_part)
            )
        if len(mask_bytes) > MAP_EDIT_MASK_PNG_MAX_BYTES:
            return JSONResponse(
                {"ok": False, "err": "mask_too_large"},
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )

        return await _apply_map_edit_pipeline(
            cfg=cfg,
            client=client,
            activity_log=activity_log,
            claims=claims,
            map_edit_pipeline_lock=map_edit_pipeline_lock,
            mode="erase",
            memo=memo_raw,
            x_m=0.0,
            y_m=0.0,
            theta_deg=None,
            mask_bytes=mask_bytes,
        )

    @app.get("/api/map/edit/progress")
    async def map_edit_progress_stream() -> StreamingResponse:
        return StreamingResponse(
            sse_mod.map_edit_progress_stream(),
            media_type=_SSE_MEDIA_TYPE,
            headers=sse_mod.SSE_RESPONSE_HEADERS,
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

    # ---- /api/last_output (issue#27, anon read) ------------------------
    @app.get("/api/last_output")
    async def last_output() -> JSONResponse:
        # Anonymous read OK — same envelope as /api/last_pose. The 8
        # channels reported here are the actual values being sent to UE
        # after `udp::apply_output_transform_inplace`.
        try:
            resp = await uds_mod.call_uds(client.get_last_output, cfg.health_uds_timeout_s)
        except uds_mod.UdsError as e:
            return _map_uds_exc_to_response(e)
        return JSONResponse(_last_output_view(resp), status_code=HTTPStatus.OK)

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

    # ---- /api/maps (Track E, PR-C; issue#28 grouped tree) ---------------
    # Anonymous-readable per Track F (read endpoints are anon, mutations
    # are admin-gated).
    #
    # issue#28 wire shape: response is `{"groups": [...], "flat": [...]}`
    # where `groups` is the new grouped-tree shape (pristine parents with
    # derived variants) and `flat` is the legacy list shape (kept one
    # release for backward compat with pre-issue#28 SPA bundles cached
    # in the browser). New SPA reads only `groups`.
    @app.get("/api/maps")
    async def list_maps() -> JSONResponse:
        try:
            # Opportunistic stale-tmp sweep on every list (cheap;
            # Mode-A C3 pin "test_orphan_tmp_swept_on_list").
            await asyncio.to_thread(map_transform_mod.sweep_stale_tmp, cfg.maps_dir)
            # issue#30 — also run sidecar recovery sweep so PR #81-era
            # derived maps get auto-migrated lineage on first list.
            await asyncio.to_thread(sidecar_mod.recovery_sweep, cfg.maps_dir)
            entries = await asyncio.to_thread(maps_mod.list_pairs, cfg.maps_dir)
            groups = await asyncio.to_thread(maps_mod.list_pairs_grouped, cfg.maps_dir)
        except maps_mod.MapsDirMissing as e:
            return _map_maps_exc_to_response(e)
        return JSONResponse(
            {
                "groups": [g.to_dict() for g in groups],
                "flat": [e.to_dict() for e in entries],
            },
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

    @app.get("/api/maps/{name}/sidecar")
    async def map_sidecar_named(name: str) -> JSONResponse:
        """issue#30 — return the `godo.map.sidecar.v1` JSON for a derived
        map. 404 when the map pair is absent; 200 with `{"sidecar": null}`
        when the pair exists but no sidecar is on disk yet (legacy /
        pristine map)."""
        try:
            maps_mod.validate_name(name)
        except maps_mod.InvalidName as e:
            return _map_maps_exc_to_response(e)
        if not maps_mod.is_pair_present(cfg.maps_dir, name):
            return _map_maps_exc_to_response(maps_mod.MapNotFound(name))
        sidecar_path = sidecar_mod.sidecar_path_for(cfg.maps_dir, name)
        if not sidecar_path.is_file():
            return JSONResponse(
                {"sidecar": None, "name": name},
                status_code=HTTPStatus.OK,
            )
        try:
            sc = await asyncio.to_thread(sidecar_mod.read, sidecar_path)
        except sidecar_mod.SidecarMissing:
            return JSONResponse(
                {"sidecar": None, "name": name},
                status_code=HTTPStatus.OK,
            )
        except sidecar_mod.SidecarSchemaMismatch as e:
            return JSONResponse(
                {"ok": False, "err": "sidecar_schema_mismatch", "detail": str(e)},
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        return JSONResponse(
            {"sidecar": sc.to_dict(), "name": name},
            status_code=HTTPStatus.OK,
        )

    @app.get("/api/maps/{name}/dimensions")
    async def map_dimensions_named(name: str) -> JSONResponse:
        """Track D scale fix — return PGM image dimensions in JSON.

        Width/height live in the PGM HEADER bytes, not the YAML, so the
        SPA cannot infer them by extending the YAML parser. Reads at
        most `PGM_HEADER_MAX_BYTES` from the file (no pixel decode).
        """
        try:
            pgm = maps_mod.pgm_for(cfg.maps_dir, name)
        except maps_mod.InvalidName as e:
            return _map_maps_exc_to_response(e)
        if not maps_mod.is_pair_present(cfg.maps_dir, name):
            return _map_maps_exc_to_response(maps_mod.MapNotFound(name))
        try:
            width, height = await asyncio.to_thread(maps_mod.read_pgm_dimensions, pgm)
        except maps_mod.PgmHeaderInvalid as e:
            return _map_maps_exc_to_response(e)
        except OSError:
            return _map_maps_exc_to_response(maps_mod.MapNotFound(name))
        return JSONResponse(
            {"width": width, "height": height},
            status_code=HTTPStatus.OK,
        )

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

    # ---- /api/system/processes (PR-B, anon read) -------------------------
    # One-shot snapshot. SPA's primary path is the SSE sibling below; the
    # GET exists for `curl`-debuggability and the operator's "one fresh
    # snapshot" use case (e.g. take-screenshot-now).
    #
    # Process list contains every live PID classified into general / godo /
    # managed; kernel threads (cmdline empty) are excluded. The endpoint
    # holds a closure-captured singleton `ProcessSampler` so successive
    # one-shot calls (e.g. `curl --interval`) accumulate prior-tick state
    # and surface meaningful cpu_pct deltas after the second call. The
    # very first call after webctl boot returns `cpu_pct=0.0` for every
    # row (no prior tick); subsequent calls compute the per-PID delta
    # against the previous one-shot snapshot. The SSE sibling stream uses
    # an INDEPENDENT per-stream sampler (created in `processes_stream`)
    # so per-stream cancellation doesn't leak prior-tick state into the
    # next subscriber. Sampler dict ops are GIL-atomic; concurrent
    # one-shot callers see approximate-but-non-crashy cpu_pct values.
    _processes_one_shot = processes_mod.ProcessSampler()

    @app.get("/api/system/processes")
    async def system_processes_endpoint() -> JSONResponse:
        snap = await asyncio.to_thread(_processes_one_shot.sample)
        return JSONResponse(_processes_view(snap), status_code=HTTPStatus.OK)

    @app.get("/api/system/processes/stream")
    async def system_processes_stream() -> StreamingResponse:
        return StreamingResponse(
            sse_mod.processes_stream(cfg),
            media_type=_SSE_MEDIA_TYPE,
            headers=sse_mod.SSE_RESPONSE_HEADERS,
        )

    # ---- /api/system/resources/extended (PR-B, anon read) ---------------
    # Per-core CPU + mem (MiB) + disk pct snapshot. GPU intentionally
    # omitted (per operator decision 2026-04-30 06:38 KST). Same one-shot
    # vs. SSE pattern as `/api/system/processes`.
    _resources_extended_one_shot = resources_extended_mod.ResourcesExtendedSampler(
        disk_check_path=str(cfg.disk_check_path),
    )

    @app.get("/api/system/resources/extended")
    async def system_resources_extended_endpoint() -> JSONResponse:
        snap = await asyncio.to_thread(_resources_extended_one_shot.sample)
        return JSONResponse(_extended_resources_view(snap), status_code=HTTPStatus.OK)

    @app.get("/api/system/resources/extended/stream")
    async def system_resources_extended_stream() -> StreamingResponse:
        return StreamingResponse(
            sse_mod.resources_extended_stream(cfg),
            media_type=_SSE_MEDIA_TYPE,
            headers=sse_mod.SSE_RESPONSE_HEADERS,
        )

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
        # issue#14 Mode-B M2(a) hard-block (2026-05-02 KST) — System tab
        # admin endpoint must NOT bypass the Map > Mapping coordinator
        # while a mapping run is in flight. The SPA's ServiceStatusCard
        # `actionsDisabled` prop is a UX gate only; this server-side gate
        # is what stops a curl / second-tab admin from killing the
        # container mid-run and corrupting state.json.
        #
        # When state ∈ {Starting, Running, Stopping}, the only valid
        # control path is /api/mapping/stop (which manages state.json
        # and respects the Maj-1 timing ladder).
        if name == MAPPING_UNIT_NAME.removesuffix(".service"):
            mapping_state = await asyncio.to_thread(mapping_mod.status, cfg)
            if mapping_state.state in (
                mapping_mod.MappingState.STARTING,
                mapping_mod.MappingState.RUNNING,
                mapping_mod.MappingState.STOPPING,
            ):
                return JSONResponse(
                    {
                        "ok": False,
                        "err": "mapping_pipeline_active",
                        "detail": (
                            "매핑 진행 중입니다. Map > Mapping 탭에서 Stop 버튼을 사용하세요."
                        ),
                    },
                    status_code=HTTPStatus.CONFLICT,
                )
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

    # ---- /api/mapping/* (issue#14) -------------------------------------
    # Mapping pipeline endpoints. Status / preview / monitor / journal
    # are anonymous (read-only observation). Start / stop require admin.

    def _mapping_status_view(s: mapping_mod.MappingStatus) -> dict[str, object]:
        """Project MappingStatus through MAPPING_STATUS_FIELDS for the wire."""
        d = s.to_dict()
        return {field: d.get(field) for field in MAPPING_STATUS_FIELDS}

    @app.post("/api/mapping/start")
    async def mapping_start_endpoint(
        body: MappingStartBody,
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            out = await asyncio.to_thread(mapping_mod.start, body.name, cfg)
        except mapping_mod.MappingError as e:
            return _map_mapping_exc_to_response(e)
        activity_log.append("mapping_start", f"{body.name} by {claims.username}")
        return JSONResponse(_mapping_status_view(out), status_code=HTTPStatus.OK)

    @app.post("/api/mapping/stop")
    async def mapping_stop_endpoint(
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            out = await asyncio.to_thread(mapping_mod.stop, cfg)
        except mapping_mod.MappingError as e:
            return _map_mapping_exc_to_response(e)
        activity_log.append("mapping_stop", claims.username)
        return JSONResponse(_mapping_status_view(out), status_code=HTTPStatus.OK)

    @app.get("/api/mapping/status")
    async def mapping_status_endpoint() -> JSONResponse:
        try:
            out = await asyncio.to_thread(mapping_mod.status, cfg)
        except mapping_mod.MappingError as e:
            return _map_mapping_exc_to_response(e)
        return JSONResponse(_mapping_status_view(out), status_code=HTTPStatus.OK)

    @app.get("/api/mapping/preview")
    async def mapping_preview_endpoint() -> Response:
        """Returns image/png re-encoded server-side from `.preview/<name>.pgm`.
        D5 amendment — re-encode via map_image so the SPA doesn't depend
        on browser PGM support.
        """
        try:
            current = await asyncio.to_thread(mapping_mod.status, cfg)
        except mapping_mod.MappingError as e:
            return _map_mapping_exc_to_response(e)
        if current.map_name is None:
            return JSONResponse(
                {"ok": False, "err": ERR_NO_ACTIVE_MAPPING},
                status_code=HTTPStatus.NOT_FOUND,
            )
        try:
            pgm_path = mapping_mod.preview_path(cfg, current.map_name)
        except mapping_mod.InvalidName as e:
            return _map_mapping_exc_to_response(e)
        if not pgm_path.is_file():
            return JSONResponse(
                {"ok": False, "err": ERR_PREVIEW_NOT_YET_PUBLISHED},
                status_code=HTTPStatus.NOT_FOUND,
            )
        try:
            png = await asyncio.to_thread(map_image_mod.render_pgm_to_png, pgm_path)
        except map_image_mod.MapImageNotFound:
            return JSONResponse(
                {"ok": False, "err": ERR_PREVIEW_NOT_YET_PUBLISHED},
                status_code=HTTPStatus.NOT_FOUND,
            )
        except map_image_mod.MapImageInvalid:
            return JSONResponse(
                {"ok": False, "err": "preview_invalid"},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return Response(content=png, media_type=_PNG_MEDIA_TYPE)

    @app.get("/api/mapping/monitor/stream")
    async def mapping_monitor_stream_endpoint() -> StreamingResponse:
        return StreamingResponse(
            mapping_sse_mod.mapping_monitor_stream(cfg),
            media_type=_SSE_MEDIA_TYPE,
            headers=sse_mod.SSE_RESPONSE_HEADERS,
        )

    @app.get("/api/mapping/journal")
    async def mapping_journal_endpoint(
        n: Annotated[
            int,
            Query(ge=1, le=MAPPING_JOURNAL_TAIL_MAX_N),
        ] = MAPPING_JOURNAL_TAIL_DEFAULT_N,
    ) -> JSONResponse:
        try:
            lines = await asyncio.to_thread(mapping_mod.journal_tail, cfg, n)
        except ValueError:
            return JSONResponse(
                {"ok": False, "err": ERR_BAD_N},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except mapping_mod.MappingError as e:
            return _map_mapping_exc_to_response(e)
        return JSONResponse({"lines": lines}, status_code=HTTPStatus.OK)

    # ---- /api/mapping/precheck (issue#16) ------------------------------
    # Anonymous-readable: mirrors `/api/mapping/status` so the SPA's 1 Hz
    # banner state stays consistent for unauthenticated viewers. NO L14
    # lock-out — precheck must remain readable while mapping is active so
    # the SPA can render the panel state coherently.
    @app.get("/api/mapping/precheck")
    async def mapping_precheck_endpoint(
        name: Annotated[str | None, Query(max_length=MAPPING_NAME_MAX_LEN)] = None,
    ) -> JSONResponse:
        try:
            result = await asyncio.to_thread(mapping_mod.precheck, cfg, name)
        except mapping_mod.MappingError as e:
            return _map_mapping_exc_to_response(e)
        return JSONResponse(result.to_dict(), status_code=HTTPStatus.OK)

    # ---- /api/mapping/recover-lidar (issue#16) -------------------------
    # Admin-only manual recovery for the CP2102N USB CDC stale-state race
    # observed during issue#14 HIL. Operator clicks "🔧 LiDAR USB 복구"
    # in the SPA when the precheck `lidar_readable` row goes red. NOT
    # automatic on Start — operator decides per spec memory
    # `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.
    @app.post("/api/mapping/recover-lidar")
    async def mapping_recover_lidar_endpoint(
        claims: auth_mod.Claims = Depends(auth_mod.require_admin),
    ) -> JSONResponse:
        try:
            await asyncio.to_thread(mapping_mod.recover_cp210x, cfg)
        except mapping_mod.LidarPortNotResolvable as e:
            return JSONResponse(
                {"ok": False, "err": ERR_LIDAR_PORT_NOT_RESOLVABLE, "detail": str(e)},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        except mapping_mod.CP210xRecoveryFailed as e:
            return JSONResponse(
                {"ok": False, "err": ERR_CP210X_RECOVERY_FAILED, "detail": str(e)},
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        activity_log.append("mapping_recover_lidar", claims.username)
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
