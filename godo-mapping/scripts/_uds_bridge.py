"""
Shared stdlib UDS client for godo-mapping diagnostic scripts (Track B).

SSOT (Option C invariant g): both `repeatability.py` and `pose_watch.py`
import `UdsBridge` from this module — never duplicate the class inline.
Future diagnostic tools follow the same pattern.

Runtime contract:

- Pure stdlib (socket, json, time). NO `godo_webctl` runtime import (the
  field-order SSOT is enforced at test time via conftest.py — see
  `godo-mapping/CODEBASE.md` invariant (f)).
- One request per UDS connection (matches the C++ server's one-shot
  connection model — see `production/RPi5/doc/uds_protocol.md §F.3`).
- `socket_path` is required; `timeout_s` defaults to 1.0 s. Tracker-side
  per-connection read timeout is 1 s, so anything beyond that risks
  ECONNRESET regardless of the client setting.
- Errors propagate as standard `OSError` / `socket.timeout` / `ValueError`
  / `json.JSONDecodeError`. Callers catch and translate.
"""

from __future__ import annotations

import json
import socket
from types import TracebackType
from typing import Any, Final, Self

# Local mirror of the wire field-name tuple. Drift against the C++ source
# (production/RPi5/src/uds/json_mini.cpp::format_ok_pose) is caught at
# test time by:
#   - godo-webctl/tests/test_protocol.py (regex-extract from C++)
#   - godo-mapping/scripts/test_repeatability.py
#     ::test_local_fields_match_protocol_mirror (test-time import of
#     godo_webctl.protocol.LAST_POSE_FIELDS via conftest sys.path
#     injection)
_LAST_POSE_FIELDS_LOCAL: Final[tuple[str, ...]] = (
    "valid",
    "x_m",
    "y_m",
    "yaw_deg",
    "xy_std_m",
    "yaw_std_deg",
    "iterations",
    "converged",
    "forced",
    "published_mono_ns",
)

# Bound on the bytes the bridge will read in a single response. The
# tracker-side reply for any of the 4 commands is well under 512 B
# (pinned by tests/test_uds_server.cpp::format_ok_pose_reply_under_512_bytes);
# 4096 matches the tracker's request cap and is comfortably above the
# response budget.
_RECV_BUFSIZE: Final[int] = 4096


class UdsBridge:
    """Synchronous one-shot-per-call UDS client.

    Usage as context manager (per-request open/close is also fine):

        with UdsBridge("/run/godo/ctl.sock") as br:
            mode = br.get_mode()
    """

    __slots__ = ("socket_path", "timeout_s")

    def __init__(self, socket_path: str, timeout_s: float = 1.0) -> None:
        if not socket_path:
            raise ValueError("socket_path must be a non-empty string")
        if timeout_s <= 0:
            raise ValueError(f"timeout_s must be > 0, got {timeout_s}")
        self.socket_path = socket_path
        self.timeout_s = timeout_s

    # Context manager — purely cosmetic; the bridge holds no per-instance
    # connection state. Each request opens a fresh socket.
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        return None

    # --- Internal request/response loop -----------------------------------

    def _round_trip(self, request: bytes) -> dict[str, Any]:
        """Send one request, read one newline-terminated reply, parse JSON.

        Raises:
            FileNotFoundError, ConnectionRefusedError, BrokenPipeError,
            ConnectionResetError — propagate so the caller can decide
                whether to retry or surface as fatal.
            socket.timeout — request did not complete inside `timeout_s`.
            json.JSONDecodeError — server returned garbage. Should never
                happen against the production server but is surfaced so
                callers can treat it as a hard fault.
            ValueError — server returned `{"ok":false,"err":"<code>"}`;
                the err code is in `args[0]`.
        """
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout_s)
            sock.connect(self.socket_path)
            sock.sendall(request)
            buf = bytearray()
            while b"\n" not in buf and len(buf) < _RECV_BUFSIZE:
                chunk = sock.recv(_RECV_BUFSIZE - len(buf))
                if not chunk:
                    break
                buf.extend(chunk)
        if b"\n" not in buf:
            raise ConnectionResetError(
                f"server closed before newline (got {len(buf)} bytes)"
            )
        # Drop the trailing newline + anything after it (server sends one
        # response then closes; nothing after the newline in practice).
        payload = bytes(buf).split(b"\n", 1)[0]
        reply = json.loads(payload.decode("ascii"))
        if not reply.get("ok", False):
            err_code = reply.get("err", "unknown")
            raise ValueError(f"server error: {err_code}")
        return reply

    # --- Public commands --------------------------------------------------

    def ping(self) -> None:
        """Liveness probe. Returns on success; raises on any failure."""
        self._round_trip(b'{"cmd":"ping"}\n')

    def get_mode(self) -> str:
        """Return the current AmclMode as a string ("Idle" / "OneShot" / "Live")."""
        reply = self._round_trip(b'{"cmd":"get_mode"}\n')
        mode = reply.get("mode")
        if not isinstance(mode, str):
            raise ValueError(f"missing/invalid 'mode' in reply: {reply!r}")
        return mode

    def set_mode(self, mode: str) -> None:
        """Set the AmclMode. Raises ValueError on bad_mode."""
        if mode not in ("Idle", "OneShot", "Live"):
            raise ValueError(f"invalid mode (client-side): {mode!r}")
        request = f'{{"cmd":"set_mode","mode":"{mode}"}}\n'.encode("ascii")
        self._round_trip(request)

    def get_last_pose(self) -> dict[str, Any]:
        """Read the last AMCL pose snapshot. Returns a dict with the
        keys in `_LAST_POSE_FIELDS_LOCAL`. Drops the JSON-level `ok`
        key but keeps every pose field — including `valid=0` for the
        "no pose ever published" sentinel.

        Raises:
            FileNotFoundError, ConnectionRefusedError, etc. — see _round_trip.
        """
        reply = self._round_trip(b'{"cmd":"get_last_pose"}\n')
        # Project to the canonical field tuple so callers can iterate
        # without worrying about the JSON-level `ok` key. Missing fields
        # are surfaced as KeyError to make any future schema drift loud.
        return {name: reply[name] for name in _LAST_POSE_FIELDS_LOCAL}
