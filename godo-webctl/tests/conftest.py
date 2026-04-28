"""
Shared fixtures.

``fake_uds_server`` — in-thread AF_UNIX listener, scriptable response queue,
captures the most recent client request bytes verbatim. Tests may also
assign ``server.delay = float`` to make the server sleep before replying
(useful for the timeout test).

``tmp_socket_path`` — short tmp_path-derived UDS path that fits inside
``sun_path`` (108 bytes on Linux).

``tmp_map_pair`` — writes a 1-byte ``.pgm`` and a 5-line ``.yaml`` and
returns the ``.pgm`` ``Path`` (the ``GODO_WEBCTL_MAP_PATH`` semantic).
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
from pathlib import Path

import pytest


class FakeUdsServer:
    """In-thread AF_UNIX server. Replies one canned response per accept."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(path))
        self._sock.listen(4)
        self._sock.settimeout(0.5)
        self._stop = threading.Event()
        self._replies: deque[bytes] = deque()
        self._raw_replies: deque[bytes] = deque()  # M3 case (h)
        self.captured: list[bytes] = []
        self.delay: float = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def reply(self, payload: bytes) -> None:
        """Queue one well-formed JSON-line reply (no trailing newline needed)."""
        if not payload.endswith(b"\n"):
            payload = payload + b"\n"
        self._replies.append(payload)

    def reply_raw(self, payload: bytes) -> None:
        """Queue one byte-exact reply (used for the buffer-full test)."""
        self._raw_replies.append(payload)

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
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf.extend(chunk)
                self.captured.append(bytes(buf))
                if self.delay > 0:
                    time.sleep(self.delay)
                if self._raw_replies:
                    conn.sendall(self._raw_replies.popleft())
                elif self._replies:
                    conn.sendall(self._replies.popleft())
                else:
                    # No reply queued — hold the connection open until the
                    # client times out (instead of EOF-closing it). Polls
                    # _stop so the fixture teardown is responsive.
                    while not self._stop.is_set():
                        time.sleep(0.05)
            finally:
                with contextlib.suppress(OSError):
                    conn.close()


@pytest.fixture
def tmp_socket_path(tmp_path: Path) -> Path:
    # sun_path is 108 bytes on Linux. tmp_path under /tmp/pytest-of-... is
    # already short, but use a short uuid suffix to be defensive.
    name = f"u-{uuid.uuid4().hex[:8]}.sock"
    p = tmp_path / name
    assert len(str(p)) < 100
    return p


@pytest.fixture
def fake_uds_server(tmp_socket_path: Path) -> Iterator[FakeUdsServer]:
    srv = FakeUdsServer(tmp_socket_path)
    try:
        yield srv
    finally:
        srv.stop()


@pytest.fixture
def tmp_map_pair(tmp_path: Path) -> Path:
    """Returns the ``.pgm`` Path; ``.yaml`` sibling is alongside."""
    pgm = tmp_path / "studio_v1.pgm"
    yaml = tmp_path / "studio_v1.yaml"
    pgm.write_bytes(b"P5\n1 1\n255\n\x00")
    yaml.write_text(
        "image: studio_v1.pgm\n"
        "resolution: 0.05\n"
        "origin: [0.0, 0.0, 0.0]\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n"
        "negate: 0\n"
    )
    return pgm


@pytest.fixture
def tmp_backup_dir(tmp_path: Path) -> Path:
    """Track B-BACKUP fixture.

    Returns a fresh `backup_dir` pre-populated with two canonical
    backup directories at distinct UTC timestamps and one `<ts>.tmp/`
    orphan (mirror of a crashed `backup.backup_map` mid-rename).

        <backup_dir>/
        ├─ 20260101T010101Z/   (older)
        │   ├─ studio_v1.pgm
        │   └─ studio_v1.yaml
        ├─ 20260202T020202Z/   (newer)
        │   ├─ studio_v2.pgm
        │   └─ studio_v2.yaml
        └─ 20260303T030303Z.tmp/   (orphan — must be skipped)
            └─ studio_v3.pgm
    """
    backup_dir = tmp_path / "map-backups"
    backup_dir.mkdir(mode=0o750)
    older = backup_dir / "20260101T010101Z"
    older.mkdir()
    (older / "studio_v1.pgm").write_bytes(b"P5\n4 4\n255\n" + bytes([10] * 16))
    (older / "studio_v1.yaml").write_text(
        "image: studio_v1.pgm\nresolution: 0.05\norigin: [0,0,0]\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\nnegate: 0\n",
    )
    newer = backup_dir / "20260202T020202Z"
    newer.mkdir()
    (newer / "studio_v2.pgm").write_bytes(b"P5\n4 4\n255\n" + bytes([20] * 16))
    (newer / "studio_v2.yaml").write_text(
        "image: studio_v2.pgm\nresolution: 0.05\norigin: [0,0,0]\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\nnegate: 0\n",
    )
    orphan = backup_dir / "20260303T030303Z.tmp"
    orphan.mkdir()
    (orphan / "studio_v3.pgm").write_bytes(b"P5\n1 1\n255\n\x00")
    return backup_dir


@pytest.fixture
def tmp_maps_dir(tmp_path: Path) -> Path:
    """Track E (PR-C) fixture.

    Returns a fresh `maps_dir` pre-populated with two map pairs
    (`studio_v1.{pgm,yaml}`, `studio_v2.{pgm,yaml}`) and `active.{pgm,yaml}`
    symlinks pointing at `studio_v1`. Tests that need a different active
    state should call `maps.set_active` themselves.
    """
    import os

    maps_dir = tmp_path / "maps"
    maps_dir.mkdir(mode=0o750)
    for name in ("studio_v1", "studio_v2"):
        pgm = maps_dir / f"{name}.pgm"
        yaml = maps_dir / f"{name}.yaml"
        # 4×4 PGM so PIL accepts it as a real netpbm image.
        pgm.write_bytes(b"P5\n4 4\n255\n" + bytes([128] * 16))
        yaml.write_text(
            f"image: {name}.pgm\nresolution: 0.05\norigin: [0,0,0]\n"
            "occupied_thresh: 0.65\nfree_thresh: 0.196\nnegate: 0\n",
        )
    os.symlink("studio_v1.pgm", maps_dir / "active.pgm")
    os.symlink("studio_v1.yaml", maps_dir / "active.yaml")
    return maps_dir
