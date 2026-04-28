"""
Server-Sent Events generators.

Two streams in scope for P0:

  `last_pose_stream(client, cfg, sleep=asyncio.sleep)`
      5 Hz polling of `client.get_last_pose`. JSON frame per tick.

  `services_stream(cfg, sleep=asyncio.sleep)`
      1 Hz polling of `services.list_active`. JSON frame per tick.

Both generators:
  - Emit `data: <json>\n\n` per frame.
  - Emit `: keepalive\n\n` once virtual elapsed time crosses
    `SSE_HEARTBEAT_S` since the last keepalive.
  - Are cancel-safe: an `asyncio.CancelledError` from the injected
    `sleep` callable terminates the loop within one tick.
  - Accept a parameterized ``sleep`` callable (defaults to
    ``asyncio.sleep``) so tests can inject a recorder/no-op generator and
    assert cadence via the **sequence of sleep durations** rather than
    wall-clock elapsed time (per reviewer T3).
  - On a tracker-side fault (UDS error from `call_uds`), the loop logs
    once and continues — no frame emitted, generator stays alive for
    the next tick.

Response headers (set by the route in `app.py`):
  - `Cache-Control: no-cache`
  - `X-Accel-Buffering: no`  (defensive against future nginx/Caddy
    buffering — see CODEBASE.md invariant (l) and risk row N5).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Final

from . import services as services_mod
from . import uds_client as uds_mod
from .config import Settings
from .constants import (
    SSE_HEARTBEAT_S,
    SSE_SERVICES_TICK_S,
    SSE_TICK_S,
    SSE_UDS_TIMEOUT_S,
)

logger = logging.getLogger("godo_webctl.sse")

SleepCallable = Callable[[float], Awaitable[None]]

SSE_RESPONSE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _sse_event(payload: dict[str, Any]) -> bytes:
    return ("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode("utf-8")


def _sse_keepalive() -> bytes:
    return b": keepalive\n\n"


async def last_pose_stream(
    client: uds_mod.UdsClient,
    cfg: Settings,  # noqa: ARG001 — reserved for future per-stream tuning
    *,
    sleep: SleepCallable = asyncio.sleep,
) -> AsyncIterator[bytes]:
    """5 Hz get_last_pose poller. Yields one frame per tick or skips on
    tracker fault. Heartbeat every `SSE_HEARTBEAT_S` of virtual time."""
    elapsed_since_keepalive = 0.0
    while True:
        try:
            resp = await uds_mod.call_uds(client.get_last_pose, SSE_UDS_TIMEOUT_S)
            yield _sse_event(resp)
        except asyncio.CancelledError:
            raise
        except uds_mod.UdsError as e:
            logger.debug("sse.last_pose_uds_error: %s", e)
            # Skip this frame; loop continues.
        try:
            await sleep(SSE_TICK_S)
        except asyncio.CancelledError:
            raise
        elapsed_since_keepalive += SSE_TICK_S
        if elapsed_since_keepalive >= SSE_HEARTBEAT_S:
            yield _sse_keepalive()
            elapsed_since_keepalive = 0.0


async def services_stream(
    cfg: Settings,  # noqa: ARG001 — reserved for future per-stream tuning
    *,
    sleep: SleepCallable = asyncio.sleep,
) -> AsyncIterator[bytes]:
    """1 Hz services-status poller. `services.list_active()` is sync so
    we run it on a worker thread to keep the event loop responsive."""
    elapsed_since_keepalive = 0.0
    while True:
        try:
            payload = await asyncio.to_thread(services_mod.list_active)
            yield _sse_event({"services": payload})
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — defence in depth around subprocess
            logger.debug("sse.services_error: %s", e)
        try:
            await sleep(SSE_SERVICES_TICK_S)
        except asyncio.CancelledError:
            raise
        elapsed_since_keepalive += SSE_SERVICES_TICK_S
        if elapsed_since_keepalive >= SSE_HEARTBEAT_S:
            yield _sse_keepalive()
            elapsed_since_keepalive = 0.0
