#!/usr/bin/env python3
"""
Tiny stub HTTP server for playwright e2e.

Serves:
  - /api/* — canned responses that mirror the real godo-webctl wire shapes
    (godo-webctl/src/godo_webctl/app.py is the SSOT we mirror).
  - / and everything else — the built SPA from `godo-frontend/dist/`.

Token "magic":
  - POST /api/auth/login with body {"username": "ncenter", "password": "ncenter"}
    returns role=admin.
  - POST /api/auth/login with body {"username": "viewer", "password": "viewer"}
    returns role=viewer.
  - Anything else → 401 bad_credentials.

The token returned is opaque from the SPA's perspective — but for /api/auth/me
to work we encode the role into the token shape. We use the same JWT format
the real backend does (HS256, base64url payload), but the "secret" is fixed.

This file is intentionally stdlib-only so it can run on any developer
machine without a venv. Per the plan's N8 punt: e2e runs on dev machines
(Mac/Linux x86) only; CI on RPi5 runs only `vitest` + backend pytest.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import sys
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = REPO_ROOT / "dist"

JWT_SECRET = b"stub-secret-fixed-for-tests-only-32b"
JWT_TTL_SECONDS = 21600

# Shared state.
LOCK = Lock()
ACTIVITY: list[dict[str, Any]] = []
CURRENT_MODE = {"value": "Idle"}

USERS = {
    "ncenter": {"password": "ncenter", "role": "admin"},
    "viewer": {"password": "viewer", "role": "viewer"},
}

# Track E (PR-C) — multi-map state. Stub remembers activate/delete in-
# memory so repeated calls in one spec see consistent state (per
# Mode-A note in plan §"_stub_server.py updates").
MAPS_STATE: dict[str, dict[str, Any]] = {
    "studio_v1": {"size_bytes": 1024, "mtime_unix": 1700000000.0},
    "studio_v2": {"size_bytes": 2048, "mtime_unix": 1700000100.0},
}
ACTIVE_MAP = {"value": "studio_v1"}

# Per Mode-A M4: a query-string flag flips the loopback gate so e2e can
# exercise the non-loopback `restart` denial path. Set with
# `?stub_loopback=false` on the page URL once before navigating to /map.
STUB_FLAGS: dict[str, Any] = {"loopback": True}

# Track E `name` regex; mirror of MAPS_NAME_REGEX_PATTERN_STR.
import re as _re

_MAPS_NAME_RE = _re.compile(r"^[a-zA-Z0-9_()-][a-zA-Z0-9._()-]{0,63}$")

# Track B-BACKUP — canonical UTC stamp regex; mirror of
# `godo_webctl.map_backup._TS_REGEX`.
_BACKUP_TS_RE = _re.compile(r"^[0-9]{8}T[0-9]{6}Z$")

# In-memory backup state. Stub remembers a list of canonical-stamp
# entries plus an "already restored" set (informational only — restore
# always succeeds for known stamps, mirroring the real backend's
# overwrite-by-design contract).
BACKUPS_STATE: dict[str, dict[str, Any]] = {
    "20260202T020202Z": {
        "files": ["studio_v2.pgm", "studio_v2.yaml"],
        "size_bytes": 4096,
    },
    "20260101T010101Z": {
        "files": ["studio_v1.pgm", "studio_v1.yaml"],
        "size_bytes": 2048,
    },
}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _issue_token(username: str, role: str) -> tuple[str, int]:
    now = int(time.time())
    exp = now + JWT_TTL_SECONDS
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(
        json.dumps({"sub": username, "role": role, "iat": now, "exp": exp}).encode(),
    )
    signing = f"{header}.{payload}".encode()
    sig = _b64url_encode(hmac.new(JWT_SECRET, signing, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}", exp


def _verify_token(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header, payload, sig = parts
    expected = _b64url_encode(
        hmac.new(JWT_SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest(),
    )
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        claims = json.loads(_b64url_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if claims.get("exp", 0) < int(time.time()):
        return None
    return claims


def _activity_append(type_: str, detail: str) -> None:
    with LOCK:
        ACTIVITY.append({"ts": time.time(), "type": type_, "detail": detail})
        if len(ACTIVITY) > 50:
            del ACTIVITY[0]


def _file_response(path: Path) -> tuple[int, dict[str, str], bytes]:
    if not path.exists() or not path.is_file():
        return HTTPStatus.NOT_FOUND, {}, b"not found"
    body = path.read_bytes()
    suffix = path.suffix.lower()
    ctype = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")
    return HTTPStatus.OK, {"Content-Type": ctype}, body


def _png_1x1() -> bytes:
    # 1×1 transparent PNG. Hand-crafted so we don't need Pillow.
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
    )


class StubHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        # Quiet by default; flip to stderr for debug.
        pass

    # --- request helpers ---------------------------------------------------

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _send_json(self, status: int, body: Any, *, extra_headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, status: int, ctype: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _claims_or_401(self) -> dict[str, Any] | None:
        auth = self.headers.get("authorization", "")
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        else:
            qs = parse_qs(urlparse(self.path).query)
            if "token" in qs:
                token = qs["token"][0]
        if not token:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "err": "auth_required"})
            return None
        claims = _verify_token(token)
        if not claims:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "err": "token_invalid"})
            return None
        return claims

    def _require_admin(self) -> dict[str, Any] | None:
        c = self._claims_or_401()
        if c is None:
            return None
        if c.get("role") != "admin":
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "err": "admin_required"})
            return None
        return c

    # --- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        path = urlparse(self.path).path
        handler = GET_ROUTES.get(path)
        if handler:
            handler(self)
            return
        # Static / SPA fallback.
        if path == "/":
            target = DIST_DIR / "index.html"
        else:
            target = DIST_DIR / path.lstrip("/")
            if not target.exists() or not target.is_file():
                target = DIST_DIR / "index.html"
        status, headers, body = _file_response(target)
        self._send_bytes(status, headers.get("Content-Type", "text/html"), body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        handler = POST_ROUTES.get(path)
        if handler:
            handler(self)
            return
        # Allow service action paths like /api/local/service/<name>/<action>.
        parts = path.split("/")
        if len(parts) == 6 and parts[:4] == ["", "api", "local", "service"]:
            _route_service_action(self, parts[4], parts[5])
            return
        # Track B-SYSTEM PR-2 — /api/system/service/<name>/<action> (admin-non-loopback).
        if len(parts) == 6 and parts[:4] == ["", "api", "system", "service"]:
            _route_system_service_action(self, parts[4], parts[5])
            return
        # Track E (PR-C): /api/maps/<name>/activate
        if path.startswith("/api/maps/") and path.endswith("/activate"):
            name = path[len("/api/maps/") : -len("/activate")]
            _h_maps_activate(self, name)
            return
        # Track B-BACKUP: /api/map/backup/<ts>/restore
        if path.startswith("/api/map/backup/") and path.endswith("/restore"):
            ts = path[len("/api/map/backup/") : -len("/restore")]
            _h_backup_restore(self, ts)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "not_found"})

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib API
        path = urlparse(self.path).path
        if path == "/api/config":
            _h_patch_config(self)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "not_found"})

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib API
        path = urlparse(self.path).path
        # Track E: /api/maps/<name>
        if path.startswith("/api/maps/"):
            name = path[len("/api/maps/") :]
            _h_maps_delete(self, name)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "not_found"})


# --- handlers (routed) ------------------------------------------------------


def _h_health(req: StubHandler) -> None:
    req._send_json(
        HTTPStatus.OK, {"webctl": "ok", "tracker": "ok", "mode": CURRENT_MODE["value"]},
    )


def _h_login(req: StubHandler) -> None:
    body = req._read_json_body() or {}
    u = body.get("username", "")
    p = body.get("password", "")
    user = USERS.get(u)
    if not user or user["password"] != p:
        req._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "err": "bad_credentials"})
        return
    token, exp = _issue_token(u, user["role"])
    _activity_append("login", u)
    req._send_json(
        HTTPStatus.OK,
        {"ok": True, "token": token, "exp": exp, "role": user["role"], "username": u},
    )


def _h_logout(req: StubHandler) -> None:
    if req._claims_or_401() is None:
        return
    req._send_json(HTTPStatus.OK, {"ok": True})


def _h_me(req: StubHandler) -> None:
    c = req._claims_or_401()
    if c is None:
        return
    req._send_json(
        HTTPStatus.OK,
        {"ok": True, "username": c["sub"], "role": c["role"], "exp": c["exp"]},
    )


def _h_refresh(req: StubHandler) -> None:
    c = req._claims_or_401()
    if c is None:
        return
    token, exp = _issue_token(c["sub"], c["role"])
    req._send_json(HTTPStatus.OK, {"ok": True, "token": token, "exp": exp})


def _h_calibrate(req: StubHandler) -> None:
    c = req._require_admin()
    if c is None:
        return
    CURRENT_MODE["value"] = "OneShot"
    _activity_append("calibrate", c["sub"])
    req._send_json(HTTPStatus.OK, {"ok": True})


def _h_live(req: StubHandler) -> None:
    c = req._require_admin()
    if c is None:
        return
    body = req._read_json_body() or {}
    enable = bool(body.get("enable"))
    CURRENT_MODE["value"] = "Live" if enable else "Idle"
    _activity_append("live_on" if enable else "live_off", c["sub"])
    req._send_json(HTTPStatus.OK, {"ok": True, "mode": CURRENT_MODE["value"]})


def _h_backup(req: StubHandler) -> None:
    c = req._require_admin()
    if c is None:
        return
    _activity_append("map_backup", c["sub"])
    req._send_json(HTTPStatus.OK, {"ok": True, "path": "/var/lib/godo/map-backups/stub/studio.pgm"})


def _h_last_pose(req: StubHandler) -> None:
    if req._claims_or_401() is None:
        return
    req._send_json(HTTPStatus.OK, _canned_pose())


def _canned_scan() -> dict[str, Any]:
    """Track D — minimal LastScan with 5 dots laid out around the origin
    so e2e specs can count rendered dots deterministically."""
    return {
        "valid": 1,
        "forced": 1,
        "pose_valid": 1,
        "iterations": 7,
        "published_mono_ns": 1_000_000_000,
        "pose_x_m": 0.0,
        "pose_y_m": 0.0,
        "pose_yaw_deg": 0.0,
        "n": 5,
        "angles_deg": [0.0, 30.0, 60.0, 90.0, 180.0],
        "ranges_m": [1.0, 1.0, 1.0, 1.0, 1.0],
    }


def _h_last_scan(req: StubHandler) -> None:
    # Track F: anonymous-readable per backend. Stub mirrors that —
    # no auth check.
    req._send_json(HTTPStatus.OK, _canned_scan())


def _h_last_scan_stream(req: StubHandler) -> None:
    # Same SSE pattern as /api/last_pose/stream; anon access (Track F).
    req.send_response(HTTPStatus.OK)
    req.send_header("Content-Type", "text/event-stream")
    req.send_header("Cache-Control", "no-cache")
    req.send_header("X-Accel-Buffering", "no")
    req.end_headers()
    for _ in range(3):
        line = f"data: {json.dumps(_canned_scan())}\n\n"
        try:
            req.wfile.write(line.encode())
            req.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        time.sleep(0.05)


# --- PR-DIAG (Track B-DIAG) — diagnostics handlers ----------------------


def _canned_jitter() -> dict[str, Any]:
    return {
        "valid": 1,
        "p50_ns": 4567,
        "p95_ns": 12345,
        "p99_ns": 45678,
        "max_ns": 123456,
        "mean_ns": 5678,
        "sample_count": 2048,
        "published_mono_ns": 1_000_000_000,
    }


def _canned_amcl_rate() -> dict[str, Any]:
    return {
        "valid": 1,
        "hz": 9.987,
        "last_iteration_mono_ns": 1_000_000_000,
        "total_iteration_count": 42,
        "published_mono_ns": 1_000_000_001,
    }


def _canned_resources() -> dict[str, Any]:
    return {
        "cpu_temp_c": 50.0,
        "mem_used_pct": 25.0,
        "mem_total_bytes": 1 << 32,
        "mem_avail_bytes": 1 << 30,
        "disk_used_pct": 41.5,
        "disk_total_bytes": 1 << 35,
        "disk_avail_bytes": 1 << 33,
        "published_mono_ns": 1_000_000_002,
    }


def _h_system_jitter(req: StubHandler) -> None:
    req._send_json(HTTPStatus.OK, _canned_jitter())


def _h_system_amcl_rate(req: StubHandler) -> None:
    req._send_json(HTTPStatus.OK, _canned_amcl_rate())


def _h_system_resources(req: StubHandler) -> None:
    req._send_json(HTTPStatus.OK, _canned_resources())


def _h_diag_stream(req: StubHandler) -> None:
    # Anon access (Track F mirror).
    req.send_response(HTTPStatus.OK)
    req.send_header("Content-Type", "text/event-stream")
    req.send_header("Cache-Control", "no-cache")
    req.send_header("X-Accel-Buffering", "no")
    req.end_headers()
    frame = {
        "pose": _canned_pose(),
        "jitter": _canned_jitter(),
        "amcl_rate": _canned_amcl_rate(),
        "resources": _canned_resources(),
    }
    for _ in range(3):
        line = f"data: {json.dumps(frame)}\n\n"
        try:
            req.wfile.write(line.encode())
            req.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        time.sleep(0.05)


# --- Track B-CONFIG (PR-CONFIG-β) — config edit pipeline ----------------


# In-memory schema mirror for stub. Real backend parses
# config_schema.hpp; the stub uses a small representative set so e2e
# can verify the table renders + the edit loop works without parsing
# the real C++ source from playwright.
STUB_SCHEMA = [
    {
        "name": "smoother.deadband_mm",
        "type": "double",
        "min": 0.0,
        "max": 200.0,
        "default": "10.0",
        "reload_class": "hot",
        "description": "Deadband on translation (mm).",
    },
    {
        "name": "smoother.deadband_deg",
        "type": "double",
        "min": 0.0,
        "max": 5.0,
        "default": "0.1",
        "reload_class": "hot",
        "description": "Deadband on yaw (deg).",
    },
    {
        "name": "network.ue_port",
        "type": "int",
        "min": 1.0,
        "max": 65535.0,
        "default": "6666",
        "reload_class": "restart",
        "description": "UE receiver UDP port.",
    },
    {
        "name": "amcl.map_path",
        "type": "string",
        "min": 0.0,
        "max": 0.0,
        "default": "/etc/godo/maps/studio_v1.pgm",
        "reload_class": "recalibrate",
        "description": "PGM map path.",
    },
]
CONFIG_VALUES: dict[str, Any] = {
    "smoother.deadband_mm": 10.0,
    "smoother.deadband_deg": 0.1,
    "network.ue_port": 6666,
    "amcl.map_path": "/etc/godo/maps/studio_v1.pgm",
}
RESTART_PENDING_FLAG = {"value": False}


def _h_get_config(req: StubHandler) -> None:
    req._send_json(HTTPStatus.OK, dict(CONFIG_VALUES))


def _h_get_config_schema(req: StubHandler) -> None:
    req._send_json(HTTPStatus.OK, STUB_SCHEMA)


def _h_patch_config(req: StubHandler) -> None:
    c = req._require_admin()
    if c is None:
        return
    body = req._read_json_body() or {}
    key = body.get("key", "")
    value = body.get("value", None)
    schema_row = next((r for r in STUB_SCHEMA if r["name"] == key), None)
    if schema_row is None:
        req._send_json(
            HTTPStatus.BAD_REQUEST,
            {"ok": False, "err": "bad_key", "detail": f"unknown key: {key}"},
        )
        return
    # Crude type coercion mirroring the tracker.
    if schema_row["type"] == "int":
        try:
            value = int(value)
        except (TypeError, ValueError):
            req._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "err": "bad_value", "detail": "int parse failed"},
            )
            return
    elif schema_row["type"] == "double":
        try:
            value = float(value)
        except (TypeError, ValueError):
            req._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "err": "bad_value", "detail": "double parse failed"},
            )
            return
    else:
        value = str(value)
    CONFIG_VALUES[key] = value
    cls = schema_row["reload_class"]
    if cls != "hot":
        RESTART_PENDING_FLAG["value"] = True
    _activity_append("config_set", f"{key} by {c['sub']}")
    req._send_json(HTTPStatus.OK, {"ok": True, "reload_class": cls})


def _h_restart_pending(req: StubHandler) -> None:
    req._send_json(HTTPStatus.OK, {"pending": RESTART_PENDING_FLAG["value"]})


def _h_logs_tail(req: StubHandler) -> None:
    # Allow-list match.
    qs = parse_qs(urlparse(req.path).query)
    unit = qs.get("unit", [""])[0]
    n_str = qs.get("n", ["50"])[0]
    if unit not in {"godo-tracker", "godo-webctl", "godo-irq-pin"}:
        req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "unknown_service"})
        return
    try:
        n = int(n_str)
    except ValueError:
        n = 50
    n = max(1, min(n, 500))
    lines = [f"[stub] {unit} log line {i}" for i in range(min(n, 5))]
    req._send_json(HTTPStatus.OK, lines)


def _canned_pose() -> dict[str, Any]:
    return {
        "valid": True,
        "x_m": 1.5,
        "y_m": 2.0,
        "yaw_deg": 45.0,
        "xy_std_m": 0.01,
        "yaw_std_deg": 0.5,
        "iterations": 12,
        "converged": True,
        "forced": False,
        "published_mono_ns": 1_000_000_000,
    }


def _h_last_pose_stream(req: StubHandler) -> None:
    if req._claims_or_401() is None:
        return
    req.send_response(HTTPStatus.OK)
    req.send_header("Content-Type", "text/event-stream")
    req.send_header("Cache-Control", "no-cache")
    req.send_header("X-Accel-Buffering", "no")
    req.end_headers()
    # Emit a few frames then close, so playwright sees activity quickly.
    for _ in range(3):
        line = f"data: {json.dumps(_canned_pose())}\n\n"
        try:
            req.wfile.write(line.encode())
            req.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        time.sleep(0.05)


def _h_map_image(req: StubHandler) -> None:
    if req._claims_or_401() is None:
        return
    req._send_bytes(HTTPStatus.OK, "image/png", _png_1x1())


def _h_activity(req: StubHandler) -> None:
    if req._claims_or_401() is None:
        return
    qs = parse_qs(urlparse(req.path).query)
    n = int(qs.get("n", ["5"])[0])
    with LOCK:
        items = list(reversed(ACTIVITY[-n:]))
    req._send_json(HTTPStatus.OK, items)


def _h_local_services(req: StubHandler) -> None:
    if req._require_admin() is None:
        return
    req._send_json(HTTPStatus.OK, _canned_services())


def _canned_services() -> list[dict[str, Any]]:
    return [
        {"name": "godo-irq-pin", "active": "active"},
        {"name": "godo-tracker", "active": "active"},
        {"name": "godo-webctl", "active": "active"},
    ]


def _h_local_services_stream(req: StubHandler) -> None:
    if req._require_admin() is None:
        return
    req.send_response(HTTPStatus.OK)
    req.send_header("Content-Type", "text/event-stream")
    req.send_header("Cache-Control", "no-cache")
    req.send_header("X-Accel-Buffering", "no")
    req.end_headers()
    for _ in range(2):
        line = f"data: {json.dumps({'services': _canned_services()})}\n\n"
        try:
            req.wfile.write(line.encode())
            req.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        time.sleep(0.05)


def _h_local_journal(req: StubHandler) -> None:
    if req._require_admin() is None:
        return
    # Path is like /api/local/journal/godo-tracker
    parts = urlparse(req.path).path.split("/")
    svc = parts[-1]
    qs = parse_qs(urlparse(req.path).query)
    n = int(qs.get("n", ["30"])[0])
    lines = [f"[stub] {svc} log line {i}" for i in range(min(n, 5))]
    req._send_json(HTTPStatus.OK, lines)


def _route_service_action(req: StubHandler, name: str, action: str) -> None:
    # Mode-A M4: backend gates `/api/local/*` on actual TCP peer IP. The
    # stub mimics that gate via `STUB_FLAGS["loopback"]` (flipped by the
    # `?stub_loopback=false` query string flag) so e2e can exercise the
    # 403 path without spoofing the peer IP.
    if not STUB_FLAGS["loopback"]:
        req._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "err": "loopback_only"})
        return
    c = req._require_admin()
    if c is None:
        return
    if name not in {"godo-tracker", "godo-webctl", "godo-irq-pin"}:
        req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "unknown_service"})
        return
    if action not in {"start", "stop", "restart"}:
        req._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "err": "unknown_action"})
        return
    _activity_append(f"svc_{action}", f"{name} by {c['sub']}")
    req._send_json(HTTPStatus.OK, {"ok": True, "status": "active"})


# Track B-SYSTEM PR-2 — `/api/system/services` snapshot stub.
def _canned_system_services() -> list[dict[str, Any]]:
    return [
        {
            "name": "godo-irq-pin",
            "active_state": "active",
            "sub_state": "running",
            "main_pid": 4567,
            "active_since_unix": 1714397472,
            "memory_bytes": 4 * 1024 * 1024,
            "env_redacted": {"GODO_LOG_DIR": "/var/log/godo"},
        },
        {
            "name": "godo-tracker",
            "active_state": "active",
            "sub_state": "running",
            "main_pid": 1234,
            "active_since_unix": 1714397472,
            "memory_bytes": 53477376,
            # T6 fold: mixed corpus — one redacted KEY + one non-redacted
            # KEY so the e2e test can assert BOTH render paths.
            "env_redacted": {
                "JWT_SECRET": "<redacted>",
                "GODO_LOG_DIR": "/var/log/godo",
            },
        },
        {
            "name": "godo-webctl",
            "active_state": "active",
            "sub_state": "running",
            "main_pid": 2345,
            "active_since_unix": 1714397472,
            "memory_bytes": 12 * 1024 * 1024,
            "env_redacted": {"GODO_LOG_DIR": "/var/log/godo"},
        },
    ]


def _h_system_services(req: StubHandler) -> None:
    # Track F: anon-readable.
    req._send_json(HTTPStatus.OK, {"services": _canned_system_services()})


# `STUB_FLAGS["system_service_409"]` — when set to "starting" or
# "stopping", the next /api/system/service/<name>/<action> POST returns
# 409 with the matching err+detail. Lets the playwright admin-409 case
# exercise the toast logic without driving a real transition state.
def _route_system_service_action(req: StubHandler, name: str, action: str) -> None:
    c = req._require_admin()
    if c is None:
        return
    if name not in {"godo-tracker", "godo-webctl", "godo-irq-pin"}:
        req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "unknown_service"})
        return
    if action not in {"start", "stop", "restart"}:
        req._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "err": "unknown_action"})
        return
    forced = STUB_FLAGS.get("system_service_409")
    if forced == "starting":
        req._send_json(
            HTTPStatus.CONFLICT,
            {
                "ok": False,
                "err": "service_starting",
                "detail": f"{name}가 시동 중입니다. 잠시 후 다시 시도해주세요.",
            },
        )
        return
    if forced == "stopping":
        req._send_json(
            HTTPStatus.CONFLICT,
            {
                "ok": False,
                "err": "service_stopping",
                "detail": f"{name}이 종료 중입니다. 잠시 후 다시 시도해주세요.",
            },
        )
        return
    _activity_append(f"svc_{action}", f"{name} by {c['sub']}")
    req._send_json(HTTPStatus.OK, {"ok": True, "status": "active"})


# --- Track E (PR-C) — multi-map handlers --------------------------------


def _maps_list_payload() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with LOCK:
        for name in sorted(MAPS_STATE.keys()):
            meta = MAPS_STATE[name]
            rows.append(
                {
                    "name": name,
                    "size_bytes": meta["size_bytes"],
                    "mtime_unix": meta["mtime_unix"],
                    "is_active": name == ACTIVE_MAP["value"],
                },
            )
    return rows


def _h_maps_list(req: StubHandler) -> None:
    req._send_json(HTTPStatus.OK, _maps_list_payload())


def _h_maps_image(req: StubHandler, name: str) -> None:
    if not _MAPS_NAME_RE.match(name):
        req._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "err": "invalid_map_name"})
        return
    if name not in MAPS_STATE:
        req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "map_not_found"})
        return
    req._send_bytes(HTTPStatus.OK, "image/png", _png_1x1())


def _h_maps_yaml(req: StubHandler, name: str) -> None:
    if not _MAPS_NAME_RE.match(name):
        req._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "err": "invalid_map_name"})
        return
    if name != "active" and name not in MAPS_STATE:
        req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "map_not_found"})
        return
    body = (
        f"image: {name}.pgm\nresolution: 0.05\norigin: [0,0,0]\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\nnegate: 0\n"
    ).encode("utf-8")
    req._send_bytes(HTTPStatus.OK, "text/plain; charset=utf-8", body)


def _h_maps_dimensions(req: StubHandler, name: str) -> None:
    """Track D scale fix — return PGM dimensions JSON. Non-square (200×100)
    so e2e exercises the H-1 - (wy-oy)/res row math."""
    if not _MAPS_NAME_RE.match(name):
        req._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "err": "invalid_map_name"})
        return
    if name != "active" and name not in MAPS_STATE:
        req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "map_not_found"})
        return
    req._send_json(HTTPStatus.OK, {"width": 200, "height": 100})


def _h_maps_activate(req: StubHandler, name: str) -> None:
    c = req._require_admin()
    if c is None:
        return
    if name == "active":
        req._send_json(
            HTTPStatus.BAD_REQUEST,
            {"ok": False, "err": "invalid_map_name", "detail": "reserved_name"},
        )
        return
    if not _MAPS_NAME_RE.match(name):
        req._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "err": "invalid_map_name"})
        return
    with LOCK:
        if name not in MAPS_STATE:
            req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "map_not_found"})
            return
        ACTIVE_MAP["value"] = name
    _activity_append("map_activate", f"{name} by {c['sub']}")
    req._send_json(HTTPStatus.OK, {"ok": True, "restart_required": True})


def _h_maps_delete(req: StubHandler, name: str) -> None:
    c = req._require_admin()
    if c is None:
        return
    if name == "active":
        req._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "err": "invalid_map_name"})
        return
    if not _MAPS_NAME_RE.match(name):
        req._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "err": "invalid_map_name"})
        return
    with LOCK:
        if name not in MAPS_STATE:
            req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "map_not_found"})
            return
        if ACTIVE_MAP["value"] == name:
            req._send_json(HTTPStatus.CONFLICT, {"ok": False, "err": "map_is_active"})
            return
        del MAPS_STATE[name]
    _activity_append("map_delete", f"{name} by {c['sub']}")
    req._send_json(HTTPStatus.OK, {"ok": True})


# --- Track B-BACKUP — map-backup history handlers ---------------------


def _h_backup_list(req: StubHandler) -> None:
    """Anon-readable list. Mode-A M5: always 200; items=[] when state
    is empty (mirror of backend `list_backups` returning [] for both
    missing-dir and empty-dir)."""
    items: list[dict[str, Any]] = []
    with LOCK:
        for ts in sorted(BACKUPS_STATE.keys(), reverse=True):
            meta = BACKUPS_STATE[ts]
            items.append(
                {
                    "ts": ts,
                    "files": list(meta["files"]),
                    "size_bytes": meta["size_bytes"],
                },
            )
    req._send_json(HTTPStatus.OK, {"items": items})


def _h_backup_restore(req: StubHandler, ts: str) -> None:
    """Admin-only restore. Mirrors the backend wire shape:
    - 422 (or 404) on malformed `<ts>` (FastAPI Path constraint).
    - 404 on unknown `<ts>` (`backup_not_found`).
    - 200 with `{ok, ts, restored}` on success.
    - 401 on anon (handled by `_require_admin`)."""
    if not _BACKUP_TS_RE.match(ts):
        # Mirror FastAPI Path(pattern=...) → 422.
        req._send_json(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            {"ok": False, "err": "validation_error"},
        )
        return
    c = req._require_admin()
    if c is None:
        return
    with LOCK:
        meta = BACKUPS_STATE.get(ts)
    if meta is None:
        req._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "err": "backup_not_found"})
        return
    restored = list(meta["files"])
    _activity_append("map_backup_restored", f"{ts} ({len(restored)} files)")
    req._send_json(HTTPStatus.OK, {"ok": True, "ts": ts, "restored": restored})


def _h_system_reboot(req: StubHandler) -> None:
    c = req._require_admin()
    if c is None:
        return
    _activity_append("reboot", c["sub"])
    req._send_json(HTTPStatus.OK, {"ok": True})


def _h_system_shutdown(req: StubHandler) -> None:
    c = req._require_admin()
    if c is None:
        return
    _activity_append("shutdown", c["sub"])
    req._send_json(HTTPStatus.OK, {"ok": True})


GET_ROUTES: dict[str, Callable[[StubHandler], None]] = {
    "/api/health": _h_health,
    "/api/auth/me": _h_me,
    "/api/last_pose": _h_last_pose,
    "/api/last_pose/stream": _h_last_pose_stream,
    "/api/last_scan": _h_last_scan,
    "/api/last_scan/stream": _h_last_scan_stream,
    "/api/map/image": _h_map_image,
    "/api/activity": _h_activity,
    "/api/local/services": _h_local_services,
    "/api/local/services/stream": _h_local_services_stream,
    # PR-DIAG endpoints.
    "/api/system/jitter": _h_system_jitter,
    "/api/system/amcl_rate": _h_system_amcl_rate,
    "/api/system/resources": _h_system_resources,
    "/api/diag/stream": _h_diag_stream,
    "/api/logs/tail": _h_logs_tail,
    # Track B-SYSTEM PR-2 — service observability.
    "/api/system/services": _h_system_services,
    # Track B-CONFIG endpoints.
    "/api/config": _h_get_config,
    "/api/config/schema": _h_get_config_schema,
    "/api/system/restart_pending": _h_restart_pending,
    # /api/local/journal/<svc> matches by prefix below — but BaseHTTPServer
    # routes by exact equality, so we add a fallback in do_GET.
}

# Fallback prefix-routing for /api/local/journal/<svc>
_orig_do_get = StubHandler.do_GET


def _do_get_with_prefix(self: StubHandler) -> None:
    path = urlparse(self.path).path
    qs = parse_qs(urlparse(self.path).query)
    if "stub_loopback" in qs:
        STUB_FLAGS["loopback"] = qs["stub_loopback"][0].lower() in {"1", "true", "yes"}
    if "stub_svc_409" in qs:
        # Track B-SYSTEM PR-2 — flip to "starting" / "stopping" / "" (cleared).
        v = qs["stub_svc_409"][0]
        STUB_FLAGS["system_service_409"] = v if v in {"starting", "stopping"} else None
    if path.startswith("/api/local/journal/"):
        _h_local_journal(self)
        return
    if path == "/api/maps":
        _h_maps_list(self)
        return
    if path.startswith("/api/maps/") and path.endswith("/image"):
        name = path[len("/api/maps/") : -len("/image")]
        _h_maps_image(self, name)
        return
    if path.startswith("/api/maps/") and path.endswith("/yaml"):
        name = path[len("/api/maps/") : -len("/yaml")]
        _h_maps_yaml(self, name)
        return
    if path.startswith("/api/maps/") and path.endswith("/dimensions"):
        name = path[len("/api/maps/") : -len("/dimensions")]
        _h_maps_dimensions(self, name)
        return
    if path == "/api/map/backup/list":
        _h_backup_list(self)
        return
    _orig_do_get(self)


StubHandler.do_GET = _do_get_with_prefix  # type: ignore[method-assign]


POST_ROUTES: dict[str, Callable[[StubHandler], None]] = {
    "/api/auth/login": _h_login,
    "/api/auth/logout": _h_logout,
    "/api/auth/refresh": _h_refresh,
    "/api/calibrate": _h_calibrate,
    "/api/live": _h_live,
    "/api/map/backup": _h_backup,
    "/api/system/reboot": _h_system_reboot,
    "/api/system/shutdown": _h_system_shutdown,
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8081)
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), StubHandler)
    print(f"stub serving on http://127.0.0.1:{args.port} (dist={DIST_DIR})", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
