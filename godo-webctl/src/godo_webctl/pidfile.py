"""
Single-instance pidfile lock.

Acquired by ``__main__.main()`` BEFORE ``uvicorn.run`` so a second
``python -m godo_webctl`` (even on a different port) cannot race the
first on the tracker UDS, the auth users.json, or the map-backup
directory. The lock is a kernel-managed advisory ``flock(LOCK_EX |
LOCK_NB)`` on a file in ``/run/godo/``; tmpfs guarantees the lock state
disappears on reboot, and the kernel auto-releases the lock when the
holding FD closes (process death, SIGKILL included).

Stale-PID handling is automatic: if the previous holder died, its FD
closed, the kernel released the lock, and the next ``flock`` call simply
succeeds. The PID written into the file is purely diagnostic — it lets
the second instance print ``godo-webctl already running with PID <pid>``
when the lock attempt fails. The lock itself, NOT the file contents,
controls exclusivity.

Module boundary: consumed ONLY by ``__main__.main()``. ``create_app()``
does NOT import this module — tests building the app via FastAPI's
``TestClient`` never acquire the lock.

CLAUDE.md §6 "Single-instance discipline" + invariant (e) in
godo-webctl/CODEBASE.md.
"""

from __future__ import annotations

import errno
import fcntl
import os
import sys
from pathlib import Path
from types import TracebackType


class LockHeld(RuntimeError):
    """Another process holds the lock; ``holder_pid`` may be -1 if unknown."""

    def __init__(self, path: Path, holder_pid: int) -> None:
        super().__init__(f"godo-webctl already running with PID {holder_pid} (lock={path})")
        self.path = path
        self.holder_pid = holder_pid


class LockSetupError(RuntimeError):
    """Parent dir missing / unwritable, or ``open(O_CREAT)`` failed."""


def _read_holder_pid_or_minus_one(path: Path) -> int:
    """Best-effort read of the PID written by the holder. Diagnostic only."""
    try:
        text = path.read_text(encoding="ascii", errors="replace").strip()
        return int(text)
    except (OSError, ValueError):
        return -1


def _diagnose_holder(pid: int) -> str:
    """Return a short label for the stderr message: alive / dead / unknown.

    The label does NOT influence the lock decision (we already failed
    flock); it just tweaks the message phrasing so an operator can tell
    apart "another live webctl" from "different uid holds it" from
    "stale file content from a kernel-released lock".
    """
    if pid <= 0:
        return "unknown"
    try:
        os.kill(pid, 0)
    except OSError as e:
        if e.errno == errno.ESRCH:
            return "dead"
        if e.errno == errno.EPERM:
            return "PID held by another user"
        return "unknown"
    return "alive"


class PidFileLock:
    """Context manager that holds an exclusive ``flock`` on ``path``.

    Usage::

        with PidFileLock(path):
            uvicorn.run(...)

    Acquire failure (``LockHeld``) means another instance is running.
    Setup failure (``LockSetupError``) means the parent directory is
    missing / unwritable; usually a systemd-tmpfiles bug or a manual
    teardown of ``/run/godo``.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self) -> None:
        """Open + flock + write own PID. Idempotent: re-entry is rejected."""
        if self._fd is not None:
            raise RuntimeError(f"PidFileLock already acquired: {self._path}")
        # Defence-in-depth: confirm the parent exists and is writable.
        # systemd-tmpfiles (RuntimeDirectory=godo) creates /run/godo on
        # tracker boot; tests use tmp_path which is always writable.
        parent = self._path.parent
        if not parent.is_dir():
            raise LockSetupError(f"pidfile parent dir does not exist: {parent}")
        if not os.access(parent, os.W_OK | os.X_OK):
            raise LockSetupError(f"pidfile parent dir is not writable: {parent}")

        # O_CREAT — first-ever boot has no file. O_RDWR — must be
        # writable for the PID overwrite below. Mode 0o644 — readable by
        # any local user (helpful for `cat /run/godo/godo-webctl.pid`).
        fd = os.open(
            str(self._path),
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC,
            0o644,
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder_pid = _read_holder_pid_or_minus_one(self._path)
            os.close(fd)
            raise LockHeld(self._path, holder_pid) from None
        # Lock acquired — write our PID. truncate-then-write so a stale
        # decimal from a prior dead holder is overwritten cleanly.
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            payload = f"{os.getpid()}\n".encode("ascii")
            os.write(fd, payload)
            os.fsync(fd)
        except OSError:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
            raise
        self._fd = fd

    def release(self) -> None:
        """Unlink first (so a third process sees ENOENT promptly), then close.

        Order matters per Mode-A M6: the kernel holds the lock until the
        FD closes, so unlinking the path while still holding the FD does
        NOT release the lock — it just makes the path stop pointing at
        our locked inode. A third process that does open() now creates a
        fresh inode that we are NOT locked on, and its flock succeeds.
        That is the intended behaviour: our lock outlives the path.
        """
        if self._fd is None:
            return
        # unlink() is safe even if a concurrent `open(O_CREAT)` is in
        # flight: that race is exactly what flock + path-rebind is for.
        try:
            os.unlink(str(self._path))
        except FileNotFoundError:
            pass
        except OSError as e:
            # Log to stderr — do NOT raise; we still need to close the FD.
            sys.stderr.write(f"godo-webctl: pidfile unlink failed: {e}\n")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> PidFileLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()


def format_lock_held_message(exc: LockHeld) -> str:
    """Operator-friendly stderr line for the LockHeld case."""
    state = _diagnose_holder(exc.holder_pid)
    return f"godo-webctl already running with PID {exc.holder_pid} ({state}; lock={exc.path})"
