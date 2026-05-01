"""
issue#14 — Mapping monitor SSE producer.

Singleton-ticker broadcast pattern (operator-locked, M4):

    HTTP request 1 ─┐
    HTTP request 2 ─┤
    HTTP request 3 ─┼─► one async ticker @ 1 Hz
                     │       │
                     │       ▼
                     │   subprocess (`docker stats` / `df` / `du`)
                     │       │
                     │       ▼
                     │   broadcast bytes frame
                     ▼
                 fan-out per-subscriber asyncio.Queue

One ticker task spawns one `docker stats` + one `df` + one `du` per
tick regardless of subscriber count. Per-subscriber `asyncio.Queue`
fans out the SAME frame. Subprocess cost is O(1) per tick, not O(N).

S2 amendment: NO one-shot polling fallback. When the stream closes
(mapping ended OR transient HTTP error), the SPA freezes the last
Docker frame and shows a "중단됨" badge; never re-issues HTTP.

S5 amendment: this module imports only `SSE_RESPONSE_HEADERS` from
`sse.py`; it does NOT touch `SSE_TICK_S` or any pose/scan stream
constants.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from . import mapping as mapping_mod
from .config import Settings
from .constants import (
    MAPPING_MONITOR_IDLE_GRACE_S,
    MAPPING_MONITOR_TICK_S,
)

logger = logging.getLogger("godo_webctl.mapping_sse")


def _sse_event(payload: dict[str, Any]) -> bytes:
    return ("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode("utf-8")


class _MonitorBroadcast:
    """Process-singleton ticker. Subscribers register a fresh
    `asyncio.Queue` each; the ticker pushes the same `bytes` frame
    onto every queue. Ticker stops `MAPPING_MONITOR_IDLE_GRACE_S`
    after the last subscriber drops to absorb tab-switch reconnects.

    Ticker self-terminates within one tick once the container has
    exited (the SPA freezes the last frame; no fallback per S2).
    """

    _instance: ClassVar[_MonitorBroadcast | None] = None

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[bytes]] = []
        self._ticker_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> _MonitorBroadcast:
        if cls._instance is None:
            cls._instance = _MonitorBroadcast()
        return cls._instance

    async def subscribe(
        self,
        cfg: Settings,
        *,
        sleep: Any = None,
        snapshot_fn: Any = None,
    ) -> AsyncIterator[bytes]:
        """Open one HTTP subscription. Returns an async iterator of SSE
        bytes frames. The generator's `finally` removes the subscriber
        from the broadcast list when the HTTP client disconnects.

        Test helpers:
          - ``sleep`` overrides ``asyncio.sleep`` (records cadence).
          - ``snapshot_fn`` overrides ``mapping.monitor_snapshot`` so
            tests can drive the loop deterministically.
        """
        sleep_fn = sleep if sleep is not None else asyncio.sleep
        snap_fn = snapshot_fn if snapshot_fn is not None else mapping_mod.monitor_snapshot

        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
        async with self._lock:
            self._subscribers.append(queue)
            if self._ticker_task is None or self._ticker_task.done():
                self._ticker_task = asyncio.create_task(
                    self._ticker_loop(cfg, sleep_fn, snap_fn),
                )

        try:
            while True:
                frame = await queue.get()
                if frame == b"__close__":
                    return
                yield frame
        finally:
            async with self._lock:
                with contextlib.suppress(ValueError):
                    self._subscribers.remove(queue)

    async def _ticker_loop(
        self,
        cfg: Settings,
        sleep_fn: Any,
        snap_fn: Any,
    ) -> None:
        idle_for = 0.0
        try:
            while True:
                # Take one snapshot per tick — singleton cost (M4).
                try:
                    snap = await asyncio.to_thread(snap_fn, cfg)
                except Exception as e:  # noqa: BLE001 — ticker keeps the stream alive
                    logger.debug("mapping_sse.snap_error: %s", e)
                    snap = {
                        "valid": False,
                        "container_state": "no_active",
                        "err": "docker_unreachable",
                    }

                frame = _sse_event(snap)
                await self._broadcast(frame)

                # Self-terminate when no container is active. SPA
                # freezes last frame + shows "중단됨" badge.
                state = snap.get("container_state")
                if state in ("no_active", "exited"):
                    await self._broadcast(b"__close__")
                    return

                # If no subscribers, run the idle-grace timer; absorb
                # rapid tab-switch reconnects without thrashing the
                # ticker.
                if not self._subscribers:
                    idle_for += MAPPING_MONITOR_TICK_S
                    if idle_for >= MAPPING_MONITOR_IDLE_GRACE_S:
                        return
                else:
                    idle_for = 0.0

                try:
                    await sleep_fn(MAPPING_MONITOR_TICK_S)
                except asyncio.CancelledError:
                    raise
        except asyncio.CancelledError:
            return
        finally:
            await self._broadcast(b"__close__")

    async def _broadcast(self, frame: bytes) -> None:
        """Push a frame to every subscriber. Drops to subscribers whose
        queue is full (slow client) so the ticker is never blocked.
        Slow-client drop is silent — the SPA's freshness gate surfaces
        the gap."""
        async with self._lock:
            for q in list(self._subscribers):
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(frame)


async def mapping_monitor_stream(
    cfg: Settings,
    *,
    sleep: Any = None,
    snapshot_fn: Any = None,
) -> AsyncIterator[bytes]:
    """Public API: yields one SSE frame per `MAPPING_MONITOR_TICK_S`
    until the container exits (S2 — no fallback)."""
    bcast = _MonitorBroadcast.instance()
    async for frame in bcast.subscribe(cfg, sleep=sleep, snapshot_fn=snapshot_fn):
        yield frame


def reset_for_test() -> None:
    """Test helper — clear the singleton between tests."""
    if _MonitorBroadcast._instance is not None:
        bcast = _MonitorBroadcast._instance
        if bcast._ticker_task is not None and not bcast._ticker_task.done():
            bcast._ticker_task.cancel()
    _MonitorBroadcast._instance = None
