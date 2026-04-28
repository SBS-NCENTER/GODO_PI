"""
Auth surface — bcrypt + PyJWT (HS256, 6 h TTL).

`UserStore` owns a JSON file on disk. The file is small (≤ 100 users in
practice; P0 ships with 1-2). Reads happen on every login so that a CLI
password change (`scripts/godo-webctl-passwd`) takes effect without a
service restart. Writes are atomic (`flock(LOCK_EX)` + tmp file +
`os.replace`) so a crash mid-write cannot corrupt the file.

Startup behaviour (per CODEBASE.md invariant (j)):
- Missing file → lazy-seed `ncenter`/`ncenter` admin (FRONT_DESIGN §3.F).
- Present + valid → loaded into memory.
- Present + invalid (parse fail or schema fail) → store enters
  ``unavailable`` mode; routes that depend on `Depends(require_user)` /
  `Depends(require_admin)` return HTTP 503 with `auth_unavailable` so
  `/api/health` and B-LOCAL stay reachable for the operator.

JWT secret (per CODEBASE.md invariant (i)):
- Read once at startup into `app.state.jwt_secret`.
- If the file is missing, lazily generated (32 random bytes, mode 0600).
- `systemctl restart godo-webctl` rotates the secret and invalidates all
  extant sessions.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Final

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request

from .constants import BCRYPT_COST_FACTOR, JWT_ALGORITHM, JWT_TTL_SECONDS

logger = logging.getLogger("godo_webctl.auth")

ROLE_ADMIN: Final[str] = "admin"
ROLE_VIEWER: Final[str] = "viewer"
VALID_ROLES: Final[frozenset[str]] = frozenset({ROLE_ADMIN, ROLE_VIEWER})

DEFAULT_USERNAME: Final[str] = "ncenter"
DEFAULT_PASSWORD: Final[str] = "ncenter"
DEFAULT_ROLE: Final[str] = ROLE_ADMIN

# 32 random bytes = 256-bit HS256 secret. Defensible against brute-force.
JWT_SECRET_BYTES: Final[int] = 32

# Permission bits for sensitive on-disk artifacts.
_MODE_USER_RW: Final[int] = 0o600
_MODE_USER_RWX: Final[int] = 0o700


class AuthError(Exception):
    """Base for auth-module exceptions."""


class AuthUnavailable(AuthError):
    """Raised when ``users.json`` is malformed and the store cannot serve
    login attempts. Routes mapping this to HTTP 503 keep the rest of the
    process alive."""


class InvalidCredentials(AuthError):
    """Username unknown OR password mismatch (deliberately conflated to
    avoid leaking which usernames exist)."""


class TokenInvalid(AuthError):
    """JWT failed signature or expiry verification."""


@dataclass(frozen=True)
class Claims:
    """Payload fields we actually consume from a verified JWT."""

    username: str
    role: str
    exp: int


# --- secret -------------------------------------------------------------


def _load_or_create_secret(path: Path) -> bytes:
    """Read 32-byte secret from `path`; if missing, generate + persist
    with mode 0600. Returns the raw bytes (HS256 accepts arbitrary
    binary)."""
    try:
        data = path.read_bytes()
        if len(data) != JWT_SECRET_BYTES:
            logger.warning(
                "auth.secret_unexpected_length: path=%s len=%d (expected %d)",
                path,
                len(data),
                JWT_SECRET_BYTES,
            )
        return data
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True, mode=_MODE_USER_RWX)
    secret = secrets.token_bytes(JWT_SECRET_BYTES)
    # Write via tmp + replace so a partial write cannot leave a half-secret.
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _MODE_USER_RW)
    try:
        os.write(fd, secret)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    logger.info("auth.secret_generated: path=%s bytes=%d", path, JWT_SECRET_BYTES)
    return secret


# --- users.json ---------------------------------------------------------


def _hash_password(plain: str) -> str:
    """bcrypt at the project-pinned cost factor. Returns the encoded hash
    string (includes salt + cost prefix)."""
    salt = bcrypt.gensalt(rounds=BCRYPT_COST_FACTOR)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("ascii")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


def _validate_users_payload(obj: Any) -> dict[str, dict[str, str]]:
    """Strict schema check. Returns the validated mapping or raises
    ``AuthUnavailable`` with a human-readable detail."""
    if not isinstance(obj, dict):
        raise AuthUnavailable("users.json root must be a JSON object")
    out: dict[str, dict[str, str]] = {}
    for username, entry in obj.items():
        if not isinstance(username, str) or not username:
            raise AuthUnavailable(f"invalid username: {username!r}")
        if not isinstance(entry, dict):
            raise AuthUnavailable(f"user {username!r} entry must be an object")
        if "password_hash" not in entry or not isinstance(entry["password_hash"], str):
            raise AuthUnavailable(f"user {username!r}: missing/invalid password_hash")
        role = entry.get("role")
        if role not in VALID_ROLES:
            raise AuthUnavailable(
                f"user {username!r}: role {role!r} not in {sorted(VALID_ROLES)}",
            )
        out[username] = {"password_hash": entry["password_hash"], "role": role}
    return out


class UserStore:
    """File-backed credential store. Thread-safe writes via flock."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._unavailable: str | None = None  # set to error text on bad load
        self._cached: dict[str, dict[str, str]] | None = None
        self._reload()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable

    # ---- public ----------------------------------------------------------

    def lookup_role(self, username: str, password: str) -> str:
        """Validate credentials; return role on success. Raises
        ``InvalidCredentials`` on miss, ``AuthUnavailable`` if the store
        is in error state."""
        if self._unavailable is not None:
            raise AuthUnavailable(self._unavailable)
        # Re-read on every login so out-of-band CLI password changes apply
        # without restart (file is small; cost is dominated by bcrypt anyway).
        self._reload()
        if self._unavailable is not None:
            raise AuthUnavailable(self._unavailable)
        users = self._cached or {}
        entry = users.get(username)
        if entry is None or not _verify_password(password, entry["password_hash"]):
            raise InvalidCredentials("bad_credentials")
        return entry["role"]

    def set_password(self, username: str, password: str, role: str) -> None:
        """Insert or update a user record. Atomic write under flock."""
        if role not in VALID_ROLES:
            raise ValueError(f"invalid role: {role!r}")
        hashed = _hash_password(password)
        with self._exclusive_lock() as users:
            users[username] = {"password_hash": hashed, "role": role}
            self._write_atomic(users)
        self._cached = users
        self._unavailable = None

    # ---- internals -------------------------------------------------------

    def _reload(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Caller decides whether to seed; default behaviour at app
            # creation time is to lazy-seed the admin user.
            self._cached = {}
            self._unavailable = None
            return
        try:
            obj = json.loads(raw)
            self._cached = _validate_users_payload(obj)
            self._unavailable = None
        except (json.JSONDecodeError, AuthUnavailable) as e:
            detail = str(e)
            logger.error("auth.users_file_invalid: path=%s detail=%s", self._path, detail)
            self._cached = None
            self._unavailable = detail

    @contextlib.contextmanager
    def _exclusive_lock(self) -> Any:
        """Acquire exclusive flock, yield current users dict (re-read fresh
        under the lock), release on exit. Used by `set_password` to
        serialise concurrent writers (CLI helper + future P2 admin endpoint
        will use the same lock)."""
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=_MODE_USER_RWX)
        # Open the file (creating empty if missing) for the lock. We never
        # write through this fd — atomic write goes via tmp + replace.
        fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, _MODE_USER_RW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            # Re-read inside the lock: the cached snapshot may be stale.
            try:
                with os.fdopen(fd, "r+", encoding="utf-8", closefd=False) as f:
                    text = f.read()
                obj = json.loads(text) if text.strip() else {}
                users = _validate_users_payload(obj) if obj else {}
            except (json.JSONDecodeError, AuthUnavailable):
                # Caller is about to overwrite the file; an unparseable
                # current state is recoverable here (we are the writer).
                users = {}
            yield users
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _write_atomic(self, users: dict[str, dict[str, str]]) -> None:
        """Tmp-file + `os.replace` atomic write at mode 0600."""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        # We open + write + fsync the tmp, then rename. If anything raises
        # before `os.replace`, we clean up the tmp and surface the original
        # exception so the caller sees the failure (per T4-A/T4-B contract).
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _MODE_USER_RW)
        try:
            try:
                with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as f:
                    json.dump(users, f, indent=2, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
            try:
                os.replace(tmp, self._path)
            except OSError:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except BaseException:
            # Belt-and-braces — even non-OSError (e.g. KeyboardInterrupt)
            # should leave no .tmp behind.
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


def _lazy_seed_default(store: UserStore) -> None:
    """If `users.json` is absent (cached empty + no error), seed the
    default admin so first-boot is operable. No-op if any users exist or
    if the store is in error state."""
    if store.unavailable_reason is not None:
        return
    if store._cached:  # noqa: SLF001 — same module
        return
    store.set_password(DEFAULT_USERNAME, DEFAULT_PASSWORD, DEFAULT_ROLE)
    logger.warning(
        "auth.default_admin_seeded: username=%s — change via scripts/godo-webctl-passwd",
        DEFAULT_USERNAME,
    )


# --- JWT issue / verify -------------------------------------------------


def issue_token(secret: bytes, username: str, role: str) -> tuple[str, int]:
    """Returns ``(token, exp_unix)``."""
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r}")
    now = int(time.time())
    exp = now + JWT_TTL_SECONDS
    payload = {"sub": username, "role": role, "iat": now, "exp": exp}
    token = jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
    return token, exp


def verify_token(secret: bytes, token: str) -> Claims:
    """Decode + verify; raises ``TokenInvalid`` on failure."""
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise TokenInvalid(str(e)) from e
    sub = payload.get("sub")
    role = payload.get("role")
    exp = payload.get("exp")
    if not isinstance(sub, str) or role not in VALID_ROLES or not isinstance(exp, int):
        raise TokenInvalid("malformed_claims")
    return Claims(username=sub, role=role, exp=exp)


# --- FastAPI dependencies ----------------------------------------------


def _extract_bearer(request: Request) -> str:
    """Extract a bearer token from the ``Authorization`` header OR the
    ``token`` query param (per Q3 — EventSource cannot send headers,
    so SSE routes accept the token-on-URL fallback). 401 on miss."""
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    qp = request.query_params.get("token")
    if qp:
        return qp.strip()
    raise HTTPException(
        status_code=HTTPStatus.UNAUTHORIZED,
        detail={"ok": False, "err": "auth_required"},
    )


def _verify_request(request: Request) -> Claims:
    secret = getattr(request.app.state, "jwt_secret", None)
    if not isinstance(secret, bytes):
        # Process bug — secret should always be wired at app create time.
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail={"ok": False, "err": "auth_unavailable"},
        )
    token = _extract_bearer(request)
    try:
        return verify_token(secret, token)
    except TokenInvalid:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail={"ok": False, "err": "token_invalid"},
        ) from None


def require_user(request: Request) -> Claims:
    """Any valid token (admin or viewer) passes."""
    return _verify_request(request)


def require_admin(request: Request, claims: Claims = Depends(require_user)) -> Claims:
    if claims.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail={"ok": False, "err": "admin_required"},
        )
    return claims
