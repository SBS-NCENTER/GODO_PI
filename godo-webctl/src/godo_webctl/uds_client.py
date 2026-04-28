"""
Synchronous AF_UNIX client for the godo_tracker_rt UDS server.

Wire shape: JSON-lines, one request per connection (server is one-shot).
See production/RPi5/doc/uds_protocol.md for the canonical spec.

Async usage from FastAPI: wrap calls in ``asyncio.to_thread(...)`` via the
module-level ``call_uds`` helper.

Timeout semantics (S5)
----------------------
``timeout`` is **per-syscall** (the value passed to ``socket.settimeout``).
Worst-case wall-clock for a single ``ping``/``get_mode``/``set_mode`` round
trip is ``~3 × timeout`` (connect + sendall + recv). Tune the env defaults
``GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S`` / ``GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S``
upward if benign tracker stalls show up as ``tracker_timeout`` in production.
A deadline-based upgrade (single shared monotonic deadline) is documented in
CODEBASE.md as a Phase 4.5 candidate.

Terminal read-loop cases (M3)
-----------------------------
1. ``\\n`` found within ``UDS_RESPONSE_READ_BUFSIZE`` → parse JSON, return.
2. ``recv`` returns 0 before ``\\n`` → ``UdsUnreachable("eof_before_newline")``.
3. Buffer fills (``len(buf) >= UDS_RESPONSE_READ_BUFSIZE``) without ``\\n``
   → ``UdsProtocolError("response_too_large")``.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .protocol import (
    LAST_SCAN_RESPONSE_CAP,
    UDS_RESPONSE_READ_BUFSIZE,
    encode_get_amcl_rate,
    encode_get_jitter,
    encode_get_last_pose,
    encode_get_last_scan,
    encode_get_mode,
    encode_ping,
    encode_set_mode,
)


class UdsError(Exception):
    """Base for all UDS client errors."""


class UdsUnreachable(UdsError):
    """The socket is missing, connection refused, or the server hung up."""


class UdsTimeout(UdsError):
    """A socket syscall (connect/send/recv) exceeded the configured timeout."""


class UdsProtocolError(UdsError):
    """The server replied with malformed JSON or missing ``ok`` (wire-level fault)."""


class UdsServerRejected(UdsError):
    """The server replied ``{"ok": false, "err": "<code>"}`` — protocol-valid
    rejection that the application layer (e.g. the calibrate handler in
    ``app.py``) should propagate as the operator-facing error code.

    Carries ``err`` as an attribute (not just stringified) so callers can
    dispatch on the value without scraping ``str(exc)`` (Mode-B SHOULD-FIX
    S3 — was previously folded into ``UdsProtocolError`` and required
    string-startswith dispatch in ``app.py``)."""

    def __init__(self, err: str) -> None:
        super().__init__(err)
        self.err = err


class UdsClient:
    """One client per ``socket_path``. Sync API, intended for ``asyncio.to_thread``."""

    def __init__(self, socket_path: Path) -> None:
        self._path = socket_path

    # ---- public surface ---------------------------------------------------

    def ping(self, timeout: float) -> dict[str, Any]:
        return self._roundtrip(encode_ping(), timeout)

    def get_mode(self, timeout: float) -> dict[str, Any]:
        return self._roundtrip(encode_get_mode(), timeout)

    def set_mode(self, mode: str, timeout: float) -> dict[str, Any]:
        return self._roundtrip(encode_set_mode(mode), timeout)

    def get_last_pose(self, timeout: float) -> dict[str, Any]:
        """Track B `get_last_pose` round-trip; response shape pinned by
        ``protocol.LAST_POSE_FIELDS`` (regex-checked against C++)."""
        return self._roundtrip(encode_get_last_pose(), timeout)

    def get_last_scan(self, timeout: float) -> dict[str, Any]:
        """Track D `get_last_scan` round-trip; response shape pinned by
        ``protocol.LAST_SCAN_HEADER_FIELDS`` (regex-checked against
        rt_types.hpp). The reply is wider than the standard 4 KiB cap
        (~14 KiB worst case for a 720-ray scan), so we read with a
        dedicated 32 KiB buffer; the request side stays at 4 KiB."""
        return self._roundtrip(
            encode_get_last_scan(),
            timeout,
            response_cap=LAST_SCAN_RESPONSE_CAP,
        )

    def get_jitter(self, timeout: float) -> dict[str, Any]:
        """PR-DIAG `get_jitter` round-trip; response shape pinned by
        ``protocol.JITTER_FIELDS`` (regex-checked against
        json_mini.cpp::format_ok_jitter). Reply is small (~200 B), so
        the standard 4 KiB read cap is fine."""
        return self._roundtrip(encode_get_jitter(), timeout)

    def get_amcl_rate(self, timeout: float) -> dict[str, Any]:
        """PR-DIAG `get_amcl_rate` round-trip; response shape pinned by
        ``protocol.AMCL_RATE_FIELDS``. Mode-A M2 fold renamed the
        underlying metric from `scan_rate` to `amcl_rate`."""
        return self._roundtrip(encode_get_amcl_rate(), timeout)

    # ---- internals --------------------------------------------------------

    def _roundtrip(
        self,
        request: bytes,
        timeout: float,
        *,
        response_cap: int | None = None,
    ) -> dict[str, Any]:
        # Narrowest-first exception ordering (S4): TimeoutError (which is
        # the modern alias for socket.timeout in Python 3.10+) is an OSError
        # subclass; if we caught OSError first we'd shadow timeouts.
        cap = response_cap if response_cap is not None else UDS_RESPONSE_READ_BUFSIZE
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(self._path))
                sock.sendall(request)
                payload = self._recv_line(sock, cap=cap)
        except TimeoutError as e:
            raise UdsTimeout(str(e)) from e
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise UdsUnreachable(str(e)) from e
        except OSError as e:
            raise UdsUnreachable(f"os_error: {e}") from e

        try:
            obj = json.loads(payload.decode("ascii"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise UdsProtocolError(f"malformed_json: {e}") from e

        if not isinstance(obj, dict) or "ok" not in obj:
            raise UdsProtocolError("missing_ok_field")
        if obj["ok"] is not True:
            err = obj.get("err", "unspecified")
            raise UdsServerRejected(str(err))
        return obj

    @staticmethod
    def _recv_line(sock: socket.socket, *, cap: int = UDS_RESPONSE_READ_BUFSIZE) -> bytes:
        """Read until a single ``\\n`` or one of the two error terminals (M3).

        ``cap`` overrides the per-call buffer ceiling; defaults to
        ``UDS_RESPONSE_READ_BUFSIZE`` (4 KiB) for the small-reply commands
        (ping / get_mode / set_mode / get_last_pose). Track D
        ``get_last_scan`` passes a wider cap to fit ~14 KiB worst-case
        replies.
        """
        buf = bytearray()
        while len(buf) < cap:
            chunk = sock.recv(cap - len(buf))
            if not chunk:  # EOF before newline
                raise UdsUnreachable("eof_before_newline")
            buf.extend(chunk)
            nl = buf.find(b"\n")
            if nl != -1:
                return bytes(buf[:nl])  # strip newline + tail
        # Filled the buffer, still no newline.
        raise UdsProtocolError("response_too_large")


# --- async helper ----------------------------------------------------------


async def call_uds(
    fn: Callable[..., dict[str, Any]],
    *args: Any,
) -> dict[str, Any]:
    """Run a sync ``UdsClient`` method on a worker thread."""
    return await asyncio.to_thread(fn, *args)
