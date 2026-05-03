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

from . import processes as processes_mod
from . import resources as resources_mod
from . import resources_extended as resources_extended_mod
from . import services as services_mod
from . import uds_client as uds_mod
from . import webctl_toml as webctl_toml_mod
from .config import Settings
from .constants import (
    SSE_HEARTBEAT_S,
    SSE_PROCESSES_TICK_S,
    SSE_RESOURCES_EXTENDED_TICK_S,
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


def _resolve_pose_tick_s(cfg: Settings) -> float:
    """Resolve the ``last_pose_stream`` tick period (seconds) from
    ``[webctl] pose_stream_hz`` in tracker.toml, with env-var override
    and a hard fallback to ``WEBCTL_POSE_STREAM_HZ_DEFAULT``.

    Resolved per-stream-open (NOT cached at module import) so an
    operator who edits tracker.toml + restarts godo-webctl picks up
    the new value on the next stream open. issue#12 reload class is
    Restart — webctl restart IS the propagation path; per-tick
    re-resolution is not implemented (would race the SSE async loop).

    On ``WebctlTomlError`` (malformed TOML / out-of-range) the loop
    falls back to defaults rather than crashing the stream — the
    operator already gets a startup WARNING in ``__main__.py`` (A6).
    """
    try:
        section = webctl_toml_mod.read_webctl_section(cfg.tracker_toml_path)
        return 1.0 / section.pose_stream_hz
    except webctl_toml_mod.WebctlTomlError:
        return 1.0 / webctl_toml_mod.WEBCTL_POSE_STREAM_HZ_DEFAULT


def _resolve_scan_tick_s(cfg: Settings) -> float:
    """Twin of ``_resolve_pose_tick_s`` for ``last_scan_stream``.
    Reads the ``scan_stream_hz`` key; same fallback semantics."""
    try:
        section = webctl_toml_mod.read_webctl_section(cfg.tracker_toml_path)
        return 1.0 / section.scan_stream_hz
    except webctl_toml_mod.WebctlTomlError:
        return 1.0 / webctl_toml_mod.WEBCTL_SCAN_STREAM_HZ_DEFAULT


def _sse_event(payload: dict[str, Any]) -> bytes:
    return ("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode("utf-8")


def _sse_keepalive() -> bytes:
    return b": keepalive\n\n"


async def last_pose_stream(
    client: uds_mod.UdsClient,
    cfg: Settings,
    *,
    sleep: SleepCallable = asyncio.sleep,
) -> AsyncIterator[bytes]:
    """get_last_pose + get_last_output multiplexed poller. Tick cadence
    resolves at stream open from ``[webctl] pose_stream_hz`` in
    tracker.toml (default 30 Hz, operator-tunable in [1, 60]; issue#12).

    Wire shape (issue#27 wrap-and-version, locked Mode-A 2026-05-03 KST):
    each frame is ``{"pose": {<LastPose fields>}, "output":
    {<LastOutputFrame fields>}}``. Either sub-payload may be a
    ``{"valid": 0, "err": "<exception_class>"}`` sentinel if its UDS
    round-trip failed (per ``_sentinel_for_error`` precedent in
    ``diag_stream``). Both fail → frame still emitted with two
    sentinels; the SPA renders both sub-cards as "unavailable".

    Lifecycle mirrors the pre-issue#27 stream: cancel-safe, heartbeat
    every ``SSE_HEARTBEAT_S`` of virtual time, skip-on-cancel only.
    """
    tick_s = _resolve_pose_tick_s(cfg)
    elapsed_since_keepalive = 0.0
    while True:
        # Two UDS round-trips in parallel — bound on slowest, not sum.
        try:
            results = await asyncio.gather(
                uds_mod.call_uds(client.get_last_pose, SSE_UDS_TIMEOUT_S),
                uds_mod.call_uds(client.get_last_output, SSE_UDS_TIMEOUT_S),
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            raise

        pose_r, output_r = results
        pose = _sentinel_for_error(pose_r) if isinstance(pose_r, BaseException) else pose_r
        output = (
            _sentinel_for_error(output_r)
            if isinstance(output_r, BaseException)
            else output_r
        )
        yield _sse_event({"pose": pose, "output": output})

        try:
            await sleep(tick_s)
        except asyncio.CancelledError:
            raise
        elapsed_since_keepalive += tick_s
        if elapsed_since_keepalive >= SSE_HEARTBEAT_S:
            yield _sse_keepalive()
            elapsed_since_keepalive = 0.0


async def last_scan_stream(
    client: uds_mod.UdsClient,
    cfg: Settings,
    *,
    sleep: SleepCallable = asyncio.sleep,
) -> AsyncIterator[bytes]:
    """get_last_scan poller. Tick cadence resolves at stream open
    from ``[webctl] scan_stream_hz`` in tracker.toml (default 30 Hz,
    operator-tunable in [1, 60]; issue#12). Identical lifecycle/error
    pattern to ``last_pose_stream``: one frame per tick or skip on
    tracker fault, heartbeat every ``SSE_HEARTBEAT_S`` of virtual time,
    cancel-safe."""
    tick_s = _resolve_scan_tick_s(cfg)
    elapsed_since_keepalive = 0.0
    while True:
        try:
            resp = await uds_mod.call_uds(client.get_last_scan, SSE_UDS_TIMEOUT_S)
            yield _sse_event(resp)
        except asyncio.CancelledError:
            raise
        except uds_mod.UdsError as e:
            logger.debug("sse.last_scan_uds_error: %s", e)
            # Skip this frame; loop continues.
        try:
            await sleep(tick_s)
        except asyncio.CancelledError:
            raise
        elapsed_since_keepalive += tick_s
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


async def processes_stream(
    cfg: Settings,  # noqa: ARG001 — reserved for future per-stream tuning
    *,
    sampler: processes_mod.ProcessSampler | None = None,
    sleep: SleepCallable = asyncio.sleep,
) -> AsyncIterator[bytes]:
    """PR-B — 1 Hz process-list poller.

    Sampler state is per-subscriber: each connection owns its own
    `ProcessSampler` so a previously-cancelled stream's stale prior-tick
    map doesn't leak. The first tick after open returns ``cpu_pct=0.0``
    for every PID by design — operator UI shows 0% for one second after
    stream open which is acceptable (R5).

    Tests inject ``sampler=`` to drive the loop with a fake `/proc`
    fixture; production callers omit it and the default sampler walks
    real `/proc`."""
    s = sampler if sampler is not None else processes_mod.ProcessSampler()
    elapsed_since_keepalive = 0.0
    while True:
        try:
            payload = await asyncio.to_thread(s.sample)
            yield _sse_event(payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — defence in depth around /proc reads
            logger.debug("sse.processes_error: %s", e)
        try:
            await sleep(SSE_PROCESSES_TICK_S)
        except asyncio.CancelledError:
            raise
        elapsed_since_keepalive += SSE_PROCESSES_TICK_S
        if elapsed_since_keepalive >= SSE_HEARTBEAT_S:
            yield _sse_keepalive()
            elapsed_since_keepalive = 0.0


async def resources_extended_stream(
    cfg: Settings,
    *,
    sampler: resources_extended_mod.ResourcesExtendedSampler | None = None,
    sleep: SleepCallable = asyncio.sleep,
) -> AsyncIterator[bytes]:
    """PR-B — 1 Hz extended-resources poller.

    Per-subscriber `ResourcesExtendedSampler` for the same reason as
    `processes_stream`. First tick yields per-core pct = 0.0 (no prior
    tick to delta against)."""
    s = (
        sampler
        if sampler is not None
        else resources_extended_mod.ResourcesExtendedSampler(
            disk_check_path=str(cfg.disk_check_path),
        )
    )
    elapsed_since_keepalive = 0.0
    while True:
        try:
            payload = await asyncio.to_thread(s.sample)
            yield _sse_event(payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — defence in depth around /proc + statvfs
            logger.debug("sse.resources_extended_error: %s", e)
        try:
            await sleep(SSE_RESOURCES_EXTENDED_TICK_S)
        except asyncio.CancelledError:
            raise
        elapsed_since_keepalive += SSE_RESOURCES_EXTENDED_TICK_S
        if elapsed_since_keepalive >= SSE_HEARTBEAT_S:
            yield _sse_keepalive()
            elapsed_since_keepalive = 0.0


def _sentinel_for_error(e: BaseException) -> dict[str, Any]:
    """Per-sub-payload sentinel when one of the four diag fetches fails.
    PR-DIAG TM9: a failure of any single source must not block the other
    three — the SPA renders that sub-panel as "unavailable" while the
    rest stay live."""
    return {"valid": 0, "err": type(e).__name__}


async def diag_stream(
    client: uds_mod.UdsClient,
    cfg: Settings,
    *,
    sleep: SleepCallable = asyncio.sleep,
) -> AsyncIterator[bytes]:
    """PR-DIAG — multiplexed 5 Hz Diagnostics stream.

    Per tick, issues three parallel UDS round-trips (pose + jitter +
    amcl_rate) via ``asyncio.gather`` so the per-tick wall-clock is
    bounded by the SLOWEST of the three (≈ ``SSE_UDS_TIMEOUT_S``), not
    the sum. Then runs ``resources.snapshot()`` on a worker thread.

    Any individual sub-fetch failure becomes a ``{"valid": 0, "err": ...}``
    sentinel for that key — the OTHER three sub-payloads still emit.

    Lifecycle mirrors ``last_pose_stream`` / ``last_scan_stream``:
      - cancel-safe (CancelledError from ``sleep`` propagates),
      - heartbeat every ``SSE_HEARTBEAT_S`` of virtual time,
      - one frame per tick OR no frame at all (we emit even when all
        sub-payloads are sentinels so the SPA freshness gate keeps the
        UI honest about "tracker reachable but every source failed").
    """
    elapsed_since_keepalive = 0.0
    while True:
        # Three UDS round-trips in parallel — bound on slowest, not sum.
        try:
            results = await asyncio.gather(
                uds_mod.call_uds(client.get_last_pose, SSE_UDS_TIMEOUT_S),
                uds_mod.call_uds(client.get_jitter, SSE_UDS_TIMEOUT_S),
                uds_mod.call_uds(client.get_amcl_rate, SSE_UDS_TIMEOUT_S),
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            raise

        pose_r, jitter_r, amcl_rate_r = results
        pose = _sentinel_for_error(pose_r) if isinstance(pose_r, BaseException) else pose_r
        jitter = _sentinel_for_error(jitter_r) if isinstance(jitter_r, BaseException) else jitter_r
        amcl_rate = (
            _sentinel_for_error(amcl_rate_r)
            if isinstance(amcl_rate_r, BaseException)
            else amcl_rate_r
        )

        try:
            resources_dict = await asyncio.to_thread(
                resources_mod.snapshot,
                disk_check_path=cfg.disk_check_path,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — defence in depth
            logger.debug("sse.diag_resources_error: %s", e)
            resources_dict = _sentinel_for_error(e)

        frame: dict[str, Any] = {
            "pose": pose,
            "jitter": jitter,
            "amcl_rate": amcl_rate,
            "resources": resources_dict,
        }
        yield _sse_event(frame)

        try:
            await sleep(SSE_TICK_S)
        except asyncio.CancelledError:
            raise
        elapsed_since_keepalive += SSE_TICK_S
        if elapsed_since_keepalive >= SSE_HEARTBEAT_S:
            yield _sse_keepalive()
            elapsed_since_keepalive = 0.0
