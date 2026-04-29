"""
Process entrypoint. ``python -m godo_webctl`` (or ``uv run godo-webctl``)
launches uvicorn with a single worker.

``workers=1`` is a project invariant (D11): the tracker UDS server is
single-client and one-shot per connection; multi-worker uvicorn would
serialise nothing meaningful and only multiply the chances of stale-socket
races. Documented in CODEBASE.md.

Single-instance discipline (CLAUDE.md §6): we acquire a per-process
``fcntl.flock(LOCK_EX | LOCK_NB)`` on ``Settings.pidfile_path`` BEFORE
``uvicorn.run``. A second invocation — same port or different — exits 1
with a documented stderr message. Module boundary: ``create_app()`` does
NOT import ``pidfile``; tests using ``TestClient`` never acquire the
lock.
"""

from __future__ import annotations

import signal
import sys
from types import FrameType

import uvicorn

from .app import create_app
from .config import load_settings
from .pidfile import LockHeld, LockSetupError, PidFileLock, format_lock_held_message


def _factory():  # pragma: no cover — invoked by uvicorn at process start
    return create_app()


def _install_release_on_signal_handlers(lock: PidFileLock) -> None:  # pragma: no cover
    """Release the lock on SIGTERM/SIGINT before exiting.

    Uvicorn's ``capture_signals`` context wraps our handlers: it
    overrides them while the server is running, restores them on
    server exit, then **re-raises the captured signal** (LIFO). The
    re-raise hits our handler, which unlinks the pidfile and exits
    with the conventional 128+signum code. This guarantees the
    pidfile is gone after a graceful SIGTERM (CODEBASE invariant (e)).
    """

    def _release_and_exit(signum: int, frame: FrameType | None) -> None:
        lock.release()
        # 128 + signum is the conventional shell exit code for a
        # signal-terminated process; matches what bash reports.
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _release_and_exit)
    signal.signal(signal.SIGINT, _release_and_exit)


def main() -> None:  # pragma: no cover — entrypoint shim
    settings = load_settings()
    lock = PidFileLock(settings.pidfile_path)
    try:
        lock.acquire()
    except LockHeld as e:
        sys.stderr.write(format_lock_held_message(e) + "\n")
        sys.exit(1)
    except LockSetupError as e:
        sys.stderr.write(f"godo-webctl: pidfile setup failed: {e}\n")
        sys.exit(1)
    _install_release_on_signal_handlers(lock)
    try:
        uvicorn.run(
            "godo_webctl.__main__:_factory",
            host=settings.host,
            port=settings.port,
            factory=True,
            workers=1,
            log_level="info",
        )
    finally:
        lock.release()


if __name__ == "__main__":  # pragma: no cover
    main()
