"""
PR-DIAG — system-resource snapshot for the Diagnostics page.

Reads three sources every call (subject to a 1 s TTL cache):
  - `/sys/class/thermal/thermal_zone0/temp`  → CPU temperature in °C
  - `/proc/meminfo`                         → MemTotal / MemAvailable
  - `os.statvfs(disk_check_path)`           → disk total / free

Per-source try/except: a missing thermal zone (e.g. dev Mac running
tests) yields `cpu_temp_c=None` rather than failing the whole call.
SPA renders `null` as a "—" placeholder.

Cache: process-local module-level `_cache: tuple[mono_ns, dict] | None`.
Webctl runs single-uvicorn-worker (CODEBASE.md invariant (e)) so no
inter-worker race; the cache is invalidated on TTL elapse measured by
`time.monotonic_ns()`.

`published_mono_ns` is the WEBCTL `time.monotonic_ns()` (Python clock
domain). Per Track D Mode-A M2 + the protocol.py comment, the SPA does
NOT compare it against the C++ tracker's CLOCK_MONOTONIC; freshness
gating uses the SPA's `Date.now() - _arrival_ms` instead.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .constants import (
    MEMINFO_PATH,
    RESOURCES_CACHE_TTL_S,
    THERMAL_ZONE_PATH,
)

# (cache_expiry_mono_ns, snapshot_dict) | None.
_cache: tuple[int, dict[str, Any]] | None = None


def _read_thermal(path: str = THERMAL_ZONE_PATH) -> float | None:
    """Read the milli-°C value from the thermal_zone file. Missing file or
    unparseable contents → None."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read().strip()
        return int(raw) / 1000.0
    except (FileNotFoundError, PermissionError, ValueError, OSError):
        return None


def _read_meminfo(
    path: str = MEMINFO_PATH,
) -> tuple[int | None, int | None]:
    """Return ``(mem_total_bytes, mem_avail_bytes)`` parsed from /proc/meminfo.
    Either field can be None on a missing or malformed source."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return (None, None)

    total: int | None = None
    avail: int | None = None
    for line in raw.splitlines():
        if line.startswith("MemTotal:"):
            total = _parse_meminfo_kib_line(line)
        elif line.startswith("MemAvailable:"):
            avail = _parse_meminfo_kib_line(line)
        if total is not None and avail is not None:
            break
    return (total, avail)


def _parse_meminfo_kib_line(line: str) -> int | None:
    """Parse one ``Key:    <value> kB`` line into bytes. Tolerant: returns
    None if the second token is not an integer."""
    parts = line.split()
    if len(parts) < 2:
        return None
    try:
        kib = int(parts[1])
    except ValueError:
        return None
    return kib * 1024


def _read_disk(
    check_path: Path | str,
) -> tuple[int | None, int | None]:
    """Return ``(disk_total_bytes, disk_avail_bytes)`` via os.statvfs.
    Both None on any OSError (e.g., the path does not exist)."""
    try:
        st = os.statvfs(str(check_path))
    except (OSError, FileNotFoundError):
        return (None, None)
    total = st.f_blocks * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    return (total, avail)


def _build_snapshot(
    *,
    disk_check_path: Path | str,
    thermal_path: str = THERMAL_ZONE_PATH,
    meminfo_path: str = MEMINFO_PATH,
) -> dict[str, Any]:
    cpu_temp_c = _read_thermal(thermal_path)
    mem_total, mem_avail = _read_meminfo(meminfo_path)
    disk_total, disk_avail = _read_disk(disk_check_path)

    mem_used_pct: float | None = None
    if mem_total is not None and mem_total > 0 and mem_avail is not None:
        mem_used_pct = round(
            (mem_total - mem_avail) / mem_total * 100.0,
            2,
        )

    disk_used_pct: float | None = None
    if disk_total is not None and disk_total > 0 and disk_avail is not None:
        disk_used_pct = round(
            (disk_total - disk_avail) / disk_total * 100.0,
            2,
        )

    return {
        "cpu_temp_c": cpu_temp_c,
        "mem_used_pct": mem_used_pct,
        "mem_total_bytes": mem_total,
        "mem_avail_bytes": mem_avail,
        "disk_used_pct": disk_used_pct,
        "disk_total_bytes": disk_total,
        "disk_avail_bytes": disk_avail,
        "published_mono_ns": time.monotonic_ns(),
    }


def snapshot(
    *,
    disk_check_path: Path | str = "/",
    thermal_path: str = THERMAL_ZONE_PATH,
    meminfo_path: str = MEMINFO_PATH,
) -> dict[str, Any]:
    """Return a fresh-or-cached snapshot dict. Cache lifetime is
    ``RESOURCES_CACHE_TTL_S`` seconds; the cache key is "any call within
    the TTL window" — we deliberately do NOT key on the path arguments,
    because the production deployment fixes them at startup and the
    tests reset the cache via ``_reset_cache_for_tests``."""
    global _cache
    now_ns = time.monotonic_ns()
    if _cache is not None:
        expiry_ns, cached = _cache
        if now_ns < expiry_ns:
            return cached

    snap = _build_snapshot(
        disk_check_path=disk_check_path,
        thermal_path=thermal_path,
        meminfo_path=meminfo_path,
    )
    ttl_ns = int(RESOURCES_CACHE_TTL_S * 1e9)
    _cache = (now_ns + ttl_ns, snap)
    return snap


def _reset_cache_for_tests() -> None:
    """Test-only — clears the module-level cache so independent tests
    don't see each other's cached values."""
    global _cache
    _cache = None
