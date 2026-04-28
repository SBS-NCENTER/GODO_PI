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
    "/api/map/image": _h_map_image,
    "/api/activity": _h_activity,
    "/api/local/services": _h_local_services,
    "/api/local/services/stream": _h_local_services_stream,
    # /api/local/journal/<svc> matches by prefix below — but BaseHTTPServer
    # routes by exact equality, so we add a fallback in do_GET.
}

# Fallback prefix-routing for /api/local/journal/<svc>
_orig_do_get = StubHandler.do_GET


def _do_get_with_prefix(self: StubHandler) -> None:
    path = urlparse(self.path).path
    if path.startswith("/api/local/journal/"):
        _h_local_journal(self)
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
