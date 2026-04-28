"""
Unit tests for `auth.py` — bcrypt + PyJWT + UserStore.

Coverage (per plan §"Test strategy" / Auth row):
- bcrypt round-trip + cost factor pin
- JWT issue / verify / expired / forged
- secret lazy-create with mode 0600
- users.json corruption recovery (per N2)
- users.json atomic write triple (per T4):
    A: os.replace raises mid-call
    B: f.write raises mid-call
    C: two threads writing concurrently → flock serialises
"""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path
from unittest import mock

import bcrypt
import jwt
import pytest

from godo_webctl import auth as A
from godo_webctl.constants import BCRYPT_COST_FACTOR, JWT_ALGORITHM, JWT_TTL_SECONDS

# ---- bcrypt --------------------------------------------------------------


def test_hash_password_uses_pinned_cost_factor() -> None:
    h = A._hash_password("secret123")
    # bcrypt encodes cost as e.g. "$2b$12$..." — `bcrypt.gensalt(rounds=12)`
    # produces the rounds segment after the second `$`.
    parts = h.split("$")
    assert parts[1] in {"2b", "2a", "2y"}
    assert int(parts[2]) == BCRYPT_COST_FACTOR


def test_verify_password_round_trip() -> None:
    h = A._hash_password("hunter2")
    assert A._verify_password("hunter2", h) is True
    assert A._verify_password("hunter3", h) is False


def test_verify_password_handles_garbage_hash() -> None:
    assert A._verify_password("anything", "not-a-real-bcrypt-string") is False


# ---- JWT issue/verify ----------------------------------------------------


def test_issue_token_carries_role_and_exp(tmp_path: Path) -> None:
    secret = b"\x01" * 32
    token, exp = A.issue_token(secret, "ncenter", "admin")
    now = int(time.time())
    assert exp >= now + JWT_TTL_SECONDS - 5
    decoded = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    assert decoded["sub"] == "ncenter"
    assert decoded["role"] == "admin"


def test_verify_token_round_trip() -> None:
    secret = b"\x02" * 32
    token, _exp = A.issue_token(secret, "alice", "viewer")
    claims = A.verify_token(secret, token)
    assert claims.username == "alice"
    assert claims.role == "viewer"


def test_verify_token_rejects_forged() -> None:
    secret = b"\x03" * 32
    other = b"\xff" * 32
    forged = jwt.encode(
        {"sub": "x", "role": "admin", "exp": int(time.time()) + 60},
        other,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(A.TokenInvalid):
        A.verify_token(secret, forged)


def test_verify_token_rejects_expired() -> None:
    secret = b"\x04" * 32
    expired = jwt.encode(
        {"sub": "x", "role": "admin", "exp": int(time.time()) - 1},
        secret,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(A.TokenInvalid):
        A.verify_token(secret, expired)


def test_verify_token_rejects_malformed_role() -> None:
    secret = b"\x05" * 32
    bad = jwt.encode(
        {"sub": "x", "role": "wizard", "exp": int(time.time()) + 60},
        secret,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(A.TokenInvalid):
        A.verify_token(secret, bad)


def test_issue_token_rejects_unknown_role() -> None:
    with pytest.raises(ValueError):
        A.issue_token(b"\x00" * 32, "u", "wizard")


# ---- secret lazy create / mode 0600 -------------------------------------


def test_load_or_create_secret_lazy_creates_with_mode_0600(tmp_path: Path) -> None:
    p = tmp_path / "auth" / "jwt_secret"
    secret = A.load_or_create_secret(p)
    assert len(secret) == A.JWT_SECRET_BYTES
    assert p.is_file()
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600
    # Reading again returns the same bytes.
    again = A.load_or_create_secret(p)
    assert again == secret


# ---- UserStore lazy seed -------------------------------------------------


def test_lazy_seed_default_creates_admin_when_missing(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    assert store.unavailable_reason is None
    A.lazy_seed_default(store)
    assert users.is_file()
    payload = json.loads(users.read_text())
    assert "ncenter" in payload
    assert payload["ncenter"]["role"] == "admin"
    # Mode 0600 on the file.
    assert stat.S_IMODE(users.stat().st_mode) == 0o600


def test_lazy_seed_default_no_op_when_users_exist(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    store.set_password("alice", "pw", "viewer")
    A.lazy_seed_default(store)  # should not seed admin
    payload = json.loads(users.read_text())
    assert "ncenter" not in payload
    assert "alice" in payload


def test_has_users_reflects_cached_state(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    assert not store.has_users()
    store.set_password("alice", "pw", "viewer")
    assert store.has_users()


def test_bootstrap_returns_secret_and_seeded_store(tmp_path: Path) -> None:
    """`auth.bootstrap` is the single entry point app.py uses; it must
    create the secret, build the store, and seed the default admin
    when users.json is absent — all in one call."""
    secret_path = tmp_path / "auth" / "jwt_secret"
    users_path = tmp_path / "users.json"
    secret, store = A.bootstrap(secret_path, users_path)
    assert isinstance(secret, bytes) and len(secret) == A.JWT_SECRET_BYTES
    assert secret_path.is_file()
    assert store.unavailable_reason is None
    # Default admin was seeded because users.json was absent.
    assert store.has_users()
    payload = json.loads(users_path.read_text())
    assert payload["ncenter"]["role"] == "admin"


def test_bootstrap_does_not_seed_when_store_unavailable(tmp_path: Path) -> None:
    """If users.json is corrupt, bootstrap must NOT attempt to seed
    over it — the operator's broken file is the SSOT until they fix it."""
    secret_path = tmp_path / "auth" / "jwt_secret"
    users_path = tmp_path / "users.json"
    users_path.write_text("not json {{{", encoding="utf-8")
    _, store = A.bootstrap(secret_path, users_path)
    assert store.unavailable_reason is not None
    # File contents preserved; no seed overwrite happened.
    assert users_path.read_text(encoding="utf-8") == "not json {{{"


def test_user_store_lookup_role_happy(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    store.set_password("bob", "p4ss", "admin")
    assert store.lookup_role("bob", "p4ss") == "admin"


def test_user_store_lookup_role_bad_password(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    store.set_password("bob", "p4ss", "viewer")
    with pytest.raises(A.InvalidCredentials):
        store.lookup_role("bob", "WRONG")


def test_user_store_lookup_role_unknown_user(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    store.set_password("bob", "p4ss", "viewer")
    with pytest.raises(A.InvalidCredentials):
        store.lookup_role("eve", "p4ss")


# ---- N2: corruption recovery --------------------------------------------


def test_user_store_unavailable_when_users_file_invalid_json(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    users.write_text("not-json", encoding="utf-8")
    store = A.UserStore(users)
    assert store.unavailable_reason is not None
    with pytest.raises(A.AuthUnavailable):
        store.lookup_role("anyone", "x")


def test_user_store_unavailable_when_schema_missing_password_hash(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"alice": {"role": "admin"}}), encoding="utf-8")
    store = A.UserStore(users)
    assert store.unavailable_reason is not None


def test_user_store_unavailable_when_role_invalid(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    users.write_text(
        json.dumps({"alice": {"password_hash": "x", "role": "wizard"}}),
        encoding="utf-8",
    )
    store = A.UserStore(users)
    assert store.unavailable_reason is not None


# ---- T4-A: os.replace raises -------------------------------------------


def test_atomic_write_a_os_replace_raises_leaves_original(tmp_path: Path) -> None:
    """T4-A: original users.json unchanged + tmp cleaned when os.replace
    fails."""
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    store.set_password("alice", "first", "viewer")
    original = users.read_bytes()

    real_replace = os.replace
    call_count = {"n": 0}

    def boom_then_pass(src: str, dst: str) -> None:
        # The first call (to write the second user) raises; subsequent
        # writes (none in this test) would succeed.
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OSError("boom")
        real_replace(src, dst)

    with mock.patch("godo_webctl.auth.os.replace", side_effect=boom_then_pass):
        with pytest.raises(OSError):
            store.set_password("bob", "second", "admin")

    assert users.read_bytes() == original
    # Tmp must be cleaned up.
    tmp_files = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert tmp_files == []


def test_atomic_write_b_write_raises_leaves_original(tmp_path: Path) -> None:
    """T4-B: f.write() (via json.dump) raises mid-call → tmp cleaned,
    original unchanged."""
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    store.set_password("alice", "first", "viewer")
    original = users.read_bytes()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    with mock.patch("godo_webctl.auth.json.dump", side_effect=boom):
        with pytest.raises(OSError):
            store.set_password("bob", "second", "admin")

    assert users.read_bytes() == original
    tmp_files = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert tmp_files == []


def test_atomic_write_c_concurrent_writers_serialise(tmp_path: Path) -> None:
    """T4-C: two threads call set_password concurrently → flock serialises;
    one wins, the other observes the winner's state. (We don't assert
    *which* one wins — fcntl semantics make that schedule-dependent.)"""
    users = tmp_path / "users.json"
    store = A.UserStore(users)
    barrier = threading.Barrier(2)

    def writer(name: str) -> None:
        barrier.wait()
        store.set_password(name, name + "-pw", "admin")

    t1 = threading.Thread(target=writer, args=("alice",))
    t2 = threading.Thread(target=writer, args=("bob",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    payload = json.loads(users.read_text())
    # Both users must be present — flock prevents one writer from
    # clobbering the other's record because each acquires the lock,
    # re-reads, merges its update, then writes.
    assert "alice" in payload
    assert "bob" in payload


# ---- bcrypt direct sanity ------------------------------------------------


def test_bcrypt_external_lib_actually_hashes() -> None:
    """Sanity: confirm the external lib is wired (catches a future
    `import bcrypt` regression that would silently return mock data)."""
    h = bcrypt.hashpw(b"x", bcrypt.gensalt(rounds=4))
    assert h.startswith(b"$2")
