"""
Track B-SYSTEM PR-2 — `/api/system/services` snapshot layer.

Mirrors `resources.py` shape (the parallel is deliberate; reviewer can
compare side-by-side):
  - Module-level `_cache: tuple[expiry_mono_ns, list[dict]] | None`,
    TTL = `SYSTEM_SERVICES_CACHE_TTL_S`.
  - `snapshot()` invokes `services.service_show()` over
    `services.ALLOWED_SERVICES` (sorted for stable wire order).
  - Per-service degradation: a `services.service_show` failure yields
    `active_state="unknown"` for that entry and leaves the rest nullable.
    The aggregate endpoint always returns 200 (Mode-A M5 fold drops 503).
  - `_reset_cache_for_tests()` test seam.

Single uvicorn worker (CODEBASE.md invariant (e)) ⇒ no inter-worker race.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from . import services
from .constants import SYSTEM_SERVICES_CACHE_TTL_S
from .protocol import SYSTEM_SERVICES_FIELDS

logger = logging.getLogger("godo_webctl")

# (cache_expiry_mono_ns, snapshot_list) | None.
_cache: tuple[int, list[dict[str, Any]]] | None = None


def _degraded_entry(name: str) -> dict[str, Any]:
    """Per-service degraded shape on failure — `active_state="unknown"`,
    rest nullable. Field order matches `SYSTEM_SERVICES_FIELDS`."""
    return {
        "name": name,
        "active_state": "unknown",
        "sub_state": "",
        "main_pid": None,
        "active_since_unix": None,
        "memory_bytes": None,
        "env_redacted": {},
        "env_stale": False,
    }


def _serialize(show: services.ServiceShow) -> dict[str, Any]:
    """Project `ServiceShow` → wire dict in `SYSTEM_SERVICES_FIELDS`
    order. Hand-mirror to keep the field tuple authoritative."""
    return {
        "name": show.name,
        "active_state": show.active_state,
        "sub_state": show.sub_state,
        "main_pid": show.main_pid,
        "active_since_unix": show.active_since_unix,
        "memory_bytes": show.memory_bytes,
        "env_redacted": dict(show.env_redacted),
        "env_stale": show.env_stale,
    }


def _build_snapshot() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for svc in sorted(services.ALLOWED_SERVICES):
        try:
            show = services.service_show(svc)
        except services.ServicesError as e:
            logger.warning("system_services.show_failed: svc=%s err=%s", svc, e)
            out.append(_degraded_entry(svc))
            continue
        except (FileNotFoundError, OSError) as e:
            # systemctl missing or sandboxed — uniform degraded shape.
            logger.warning("system_services.show_unavailable: svc=%s err=%s", svc, e)
            out.append(_degraded_entry(svc))
            continue
        out.append(_serialize(show))
    return out


def snapshot() -> list[dict[str, Any]]:
    """Return a fresh-or-cached `/api/system/services` list payload.
    Cache lifetime is `SYSTEM_SERVICES_CACHE_TTL_S` seconds."""
    global _cache
    now_ns = time.monotonic_ns()
    if _cache is not None:
        expiry_ns, cached = _cache
        if now_ns < expiry_ns:
            return cached
    snap = _build_snapshot()
    ttl_ns = int(SYSTEM_SERVICES_CACHE_TTL_S * 1e9)
    _cache = (now_ns + ttl_ns, snap)
    return snap


def _reset_cache_for_tests() -> None:
    """Test-only — clears the module-level cache so independent tests
    don't see each other's cached values."""
    global _cache
    _cache = None


__all__ = [
    "SYSTEM_SERVICES_FIELDS",
    "_reset_cache_for_tests",
    "snapshot",
]
