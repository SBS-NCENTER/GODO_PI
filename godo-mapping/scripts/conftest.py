"""
Shared pytest fixtures + cross-package SSOT helpers for godo-mapping
diagnostic scripts (Track B).

`fake_uds_server` mirrors `godo-webctl/tests/conftest.py::FakeUdsServer`
but lives here so `repeatability.py` and `pose_watch.py` tests don't need
to import from a webctl test module at runtime (test isolation).

`sys.path` injection: the per-test drift-pin
`test_local_fields_match_protocol_mirror` imports
`godo_webctl.protocol.LAST_POSE_FIELDS` to assert byte-equal against the
local mirror in `_uds_bridge.py`. The runtime scripts have ZERO
`godo_webctl` import (per `godo-mapping/CODEBASE.md` invariant (f)); this
sys.path insertion is test-time only.
"""

from __future__ import annotations

import contextlib
import socket
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
from pathlib import Path

import pytest

# Anchor to the repo root and inject godo-webctl/src for test-time import
# of `godo_webctl.protocol`. Runtime scripts (repeatability.py,
# pose_watch.py, _uds_bridge.py) MUST NOT trigger this path — checked by
# test_repeatability.py::test_no_godo_webctl_runtime_import.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_WEBCTL_SRC = _REPO_ROOT.parent / "godo-webctl" / "src"
if str(_WEBCTL_SRC) not in sys.path:
    sys.path.insert(0, str(_WEBCTL_SRC))


class FakeUdsServer:
    """In-thread AF_UNIX server. Mirrors godo-webctl/tests/conftest.py.

    Each accepted connection reads one newline-terminated request, then
    writes one queued reply (or hangs until `_stop` is set if the queue
    is empty, simulating a tracker-side stall).

    Tests may also assign `server.delay = float` to make the server sleep
    before replying (timeout coverage), or call `disable_replies()` to
    drop incoming connections without responding (tracker-death scenario).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(path))
        self._sock.listen(4)
        self._sock.settimeout(0.2)
        self._stop = threading.Event()
        self._replies: deque[bytes] = deque()
        self._raw_replies: deque[bytes] = deque()
        self.captured: list[bytes] = []
        self.delay: float = 0.0
        self._silent = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def reply(self, payload: bytes) -> None:
        """Queue one well-formed JSON-line reply (newline auto-appended)."""
        if not payload.endswith(b"\n"):
            payload = payload + b"\n"
        self._replies.append(payload)

    def reply_raw(self, payload: bytes) -> None:
        """Queue one byte-exact reply (no newline auto-append)."""
        self._raw_replies.append(payload)

    def disable_replies(self) -> None:
        """Future accepts read the request then close without replying.
        Models tracker-death from the client's POV."""
        self._silent = True

    def enable_replies(self) -> None:
        self._silent = False

    def stop(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            self._sock.close()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            try:
                conn.settimeout(2.0)
                buf = bytearray()
                while b"\n" not in buf and len(buf) < 8192:
                    try:
                        chunk = conn.recv(4096)
                    except (TimeoutError, OSError):
                        break
                    if not chunk:
                        break
                    buf.extend(chunk)
                self.captured.append(bytes(buf))
                if self._silent:
                    continue        # close without replying
                if self.delay > 0:
                    time.sleep(self.delay)
                if self._raw_replies:
                    with contextlib.suppress(OSError):
                        conn.sendall(self._raw_replies.popleft())
                elif self._replies:
                    with contextlib.suppress(OSError):
                        conn.sendall(self._replies.popleft())
                else:
                    while not self._stop.is_set():
                        time.sleep(0.05)
            finally:
                with contextlib.suppress(OSError):
                    conn.close()


@pytest.fixture
def tmp_socket_path(tmp_path: Path) -> Path:
    name = f"u-{uuid.uuid4().hex[:8]}.sock"
    p = tmp_path / name
    assert len(str(p)) < 100      # sun_path 108-byte limit on Linux
    return p


@pytest.fixture
def fake_uds_server(tmp_socket_path: Path) -> Iterator[FakeUdsServer]:
    srv = FakeUdsServer(tmp_socket_path)
    try:
        yield srv
    finally:
        srv.stop()
