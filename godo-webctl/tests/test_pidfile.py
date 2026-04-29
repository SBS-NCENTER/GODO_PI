"""Unit tests for the ``PidFileLock`` context manager.

10 cases per planner §5; case 4 + case 10 reworded per Mode-A M4.
Each test runs in isolation — no inter-test lock state. The autouse
``_pidfile_path_autouse`` fixture in conftest.py keeps the production
path out of every test environment (TB6).
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import time
from pathlib import Path

import pytest

from godo_webctl.app import create_app
from godo_webctl.config import load_settings
from godo_webctl.pidfile import (
    LockHeld,
    LockSetupError,
    PidFileLock,
    format_lock_held_message,
)

# Sentinel "definitely-dead" PID (exceeds /proc/sys/kernel/pid_max upper
# bound on every Linux): 2**31 - 1 cannot belong to a live process.
_SENTINEL_DEAD_PID = 2**31 - 1


# --- 1. acquire on fresh path -------------------------------------------
def test_acquire_on_fresh_path_writes_pid(tmp_path: Path) -> None:
    p = tmp_path / "x.pid"
    assert not p.exists()
    with PidFileLock(p) as lock:
        assert lock.path == p
        # File is created and contains our PID + trailing newline.
        # Note: dtor unlinks, so we must read INSIDE the with-block.
        assert p.read_text(encoding="ascii") == f"{os.getpid()}\n"
    # After release, the file is gone (M6 + invariant: unlink-then-close).
    assert not p.exists()


# --- 2. second acquire same process -------------------------------------
def test_second_acquire_same_process_raises_lock_held(tmp_path: Path) -> None:
    p = tmp_path / "x.pid"
    with PidFileLock(p):
        with pytest.raises(LockHeld) as ei:
            PidFileLock(p).acquire()
        # holder_pid in the message is our own PID; the file content
        # was written by the outer lock.
        assert ei.value.holder_pid == os.getpid()
        assert ei.value.path == p


# --- 3. subprocess holds; parent attempts -------------------------------
def _hold_lock_until_signal(pid_path: str, ready_path: str) -> None:
    """Worker: take the lock, write a ready marker, sleep until SIGTERM."""
    lock = PidFileLock(Path(pid_path))
    lock.acquire()
    Path(ready_path).write_text("ready", encoding="ascii")
    # Block until parent kills us. signal.pause() is portable.
    signal.pause()


def test_subprocess_holds_parent_attempt_raises_lock_held(tmp_path: Path) -> None:
    p = tmp_path / "x.pid"
    ready = tmp_path / "ready"
    ctx = mp.get_context("fork")
    proc = ctx.Process(target=_hold_lock_until_signal, args=(str(p), str(ready)))
    proc.start()
    try:
        # Wait for the child to take the lock (poll up to 5 s).
        deadline = time.monotonic() + 5.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "child failed to acquire lock in time"

        with pytest.raises(LockHeld) as ei:
            PidFileLock(p).acquire()
        assert ei.value.holder_pid == proc.pid
        assert "godo-webctl already running with PID" in str(ei.value)
    finally:
        os.kill(proc.pid, signal.SIGTERM)
        proc.join(timeout=2.0)
        if proc.is_alive():
            proc.kill()
            proc.join()


# --- 4. stale PID, no holder (M4 fold + TB1) ----------------------------
def test_stale_pid_takes_lock_when_no_holder(tmp_path: Path) -> None:
    """Sentinel PID 2**31-1 is always-dead; lock is unheld → next acquire
    succeeds and overwrites the PID. Lock — not file content — controls
    exclusivity.
    """
    p = tmp_path / "x.pid"
    p.write_text(f"{_SENTINEL_DEAD_PID}\n", encoding="ascii")
    with PidFileLock(p):
        assert p.read_text(encoding="ascii") == f"{os.getpid()}\n"


# --- 5. ctx-manager exit unlinks file -----------------------------------
def test_context_exit_unlinks_file(tmp_path: Path) -> None:
    p = tmp_path / "x.pid"
    assert not p.exists()
    with PidFileLock(p):
        assert p.exists()
    assert not p.exists()


# --- 6. nonexistent parent dir ------------------------------------------
def test_nonexistent_parent_raises_lock_setup_error(tmp_path: Path) -> None:
    p = tmp_path / "ghost" / "x.pid"
    with pytest.raises(LockSetupError) as ei:
        PidFileLock(p).acquire()
    assert "does not exist" in str(ei.value)


# --- 7. parent dir not writable -----------------------------------------
@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
def test_unwritable_parent_raises_lock_setup_error(tmp_path: Path) -> None:
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        p = parent / "x.pid"
        with pytest.raises(LockSetupError) as ei:
            PidFileLock(p).acquire()
        assert "not writable" in str(ei.value)
    finally:
        parent.chmod(0o700)  # let pytest clean up


# --- 8. fsync — content is durable on disk after acquire ----------------
def test_pid_content_is_durable_after_acquire(tmp_path: Path) -> None:
    p = tmp_path / "x.pid"
    with PidFileLock(p):
        # We do not directly observe fsync; instead pin that the PID
        # text is what we expect immediately after acquire (no buffer
        # flush race because we use os.write + os.fsync directly).
        content = p.read_text(encoding="ascii")
        assert content == f"{os.getpid()}\n"
        assert content.endswith("\n")
        assert int(content.strip()) == os.getpid()


# --- 9. SIGTERM mid-hold runs cleanup -----------------------------------
def test_sigterm_mid_hold_releases_lock(tmp_path: Path) -> None:
    """Spawn a subprocess that takes the lock then waits; SIGTERM it
    and verify the next acquire from the parent succeeds.

    The kernel auto-releases the lock when the child's FD closes on
    process death — even without our ctx-manager cleanup running.
    """
    p = tmp_path / "x.pid"
    ready = tmp_path / "ready"
    ctx = mp.get_context("fork")
    proc = ctx.Process(target=_hold_lock_until_signal, args=(str(p), str(ready)))
    proc.start()
    try:
        deadline = time.monotonic() + 5.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        os.kill(proc.pid, signal.SIGTERM)
        proc.join(timeout=2.0)
        assert not proc.is_alive(), "child did not exit on SIGTERM"
    finally:
        if proc.is_alive():
            proc.kill()
            proc.join()
    # Child is gone; lock is released by the kernel; we can take it.
    with PidFileLock(p):
        assert p.read_text(encoding="ascii") == f"{os.getpid()}\n"


# --- 10. EPERM diagnostic phrasing (M4 fold collapsed) ------------------
def test_eperm_pid_lookup_logs_softer_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the diagnostic ``kill(pid, 0)`` returns EPERM, the LockHeld
    message phrases the holder as ``PID held by another user`` instead
    of ``alive``. Pin the formatted text — the lock decision itself is
    unaffected (already failed at flock).
    """
    import errno as errno_mod

    def fake_kill(pid: int, sig: int) -> None:
        raise OSError(errno_mod.EPERM, "operation not permitted")

    monkeypatch.setattr(os, "kill", fake_kill)
    p = tmp_path / "x.pid"
    p.write_text(f"{_SENTINEL_DEAD_PID}\n", encoding="ascii")
    exc = LockHeld(p, _SENTINEL_DEAD_PID)
    msg = format_lock_held_message(exc)
    assert "PID held by another user" in msg
    assert str(_SENTINEL_DEAD_PID) in msg


# --- M5 fold pin: create_app() does NOT acquire the lock ---------------
def test_create_app_does_not_acquire_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building the app via create_app() must not import or invoke
    pidfile.py. Verified by: (a) the env-overridden pidfile_path is not
    written, (b) the file does not exist after the factory runs.
    """
    # Override default state-paths to tmp_path so auth bootstrap (which
    # touches jwt_secret + users.json) does not need /var/lib/godo.
    monkeypatch.setenv("GODO_WEBCTL_JWT_SECRET_PATH", str(tmp_path / "jwt_secret"))
    monkeypatch.setenv("GODO_WEBCTL_USERS_FILE", str(tmp_path / "users.json"))
    settings = load_settings()
    pid_path = settings.pidfile_path
    # Pre-condition: the file does not exist.
    assert not pid_path.exists()
    app = create_app(settings)
    assert app is not None
    # Post-condition: still does not exist. create_app() never touched it.
    assert not pid_path.exists()


# --- bonus pin: __main__ truly imports pidfile (boundary docs) ----------
def test_main_imports_pidfile_but_app_does_not() -> None:
    """Pin the module boundary documented in invariant (e) and M5.

    ``__main__`` MUST import pidfile (it acquires the lock); ``app``
    MUST NOT (the create_app factory is unaffected by single-instance
    discipline because tests use it via TestClient).
    """
    import importlib

    main_mod = importlib.import_module("godo_webctl.__main__")
    app_mod = importlib.import_module("godo_webctl.app")
    assert hasattr(main_mod, "PidFileLock")
    assert not hasattr(app_mod, "PidFileLock")
