"""
PR-B (Track B-SYSTEM PR-B) — extended-resources sampler.

Three sources, all stdlib:
  - ``/proc/stat`` per-core CPU jiffies (delta sample between ticks)
  - ``/proc/meminfo`` MemTotal + MemAvailable
  - ``os.statvfs(disk_check_path)`` total / free disk

GPU is intentionally out of scope (per operator decision 2026-04-30
06:38 KST — V3D `gpu_busy_percent` is unreliable on Trixie firmware,
CPU temp is already covered by the existing System tab CPU-temp panel
via `RESOURCES_FIELDS.cpu_temp_c`). No `vcgencmd`. No DRM sysfs reads.

Per-source try/except: any one source failing yields a partial snapshot
with ``None`` for the failed fields. SPA renders ``null`` as a "—"
placeholder.

Deliberately NOT re-export-merged with `resources.py` — Track E
"uncoupled leaves" discipline keeps the two SSOTs orthogonal so a future
edit to one doesn't drag the other.

Expected cost (RPi 5, 1 Hz tick):
    /proc/stat read:        1× small file (5–8 KB) ⇒ ~50 µs
    /proc/meminfo read:     1× small file (~3 KB)  ⇒ ~30 µs
    os.statvfs:             1× syscall              ⇒ ~5 µs
    Per-core delta math:    O(N_cores) floats       ⇒ negligible
    Total per-tick:         ~100 µs CPU  ⇒  <0.01% of one core.
    RAM:                    ~200 B prior-tick map; same alloc churn
                            as the snapshot dict ⇒ <100 KB resident.

Leaf module: imports stdlib + `.constants` only.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from .constants import MEMINFO_PATH, PROC_STAT_PATH

logger = logging.getLogger("godo_webctl.resources_extended")

# Bytes per MiB. Inline magic-number-clean alternative to a Tier-1
# constant for a unit-conversion factor that is universally agreed.
_BYTES_PER_MIB = 1024 * 1024


@dataclass(frozen=True)
class CoreJiffies:
    """One row of `/proc/stat`'s per-core line: ``cpu0``, ``cpu1``, ...

    `idle` separated for the pct math; `total` is the sum of every
    column on the line."""

    idx: int
    total: int
    idle: int


def _read_cpu_per_core_jiffies(stat_path: str = PROC_STAT_PATH) -> list[CoreJiffies]:
    """Parse the per-core ``cpuN ...`` lines of ``/proc/stat``. Returns
    one entry per core in ascending index order. Returns an empty list
    on read failure or a `/proc/stat` lacking per-core lines."""
    try:
        with open(stat_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    out: list[CoreJiffies] = []
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        head, _, _ = line.partition(" ")
        if head == "cpu":
            continue  # aggregate line — skip
        # head is `cpuN`; the rest is whitespace-separated counters.
        try:
            idx = int(head[3:])
        except ValueError:
            continue
        parts = line.split()
        # Columns (kernel `kernel/sched/cputime.c`):
        #   0: label  1: user  2: nice  3: system  4: idle  5: iowait
        #   6: irq    7: softirq  8: steal  9: guest  10: guest_nice
        if len(parts) < 5:  # noqa: PLR2004 — at minimum the idle column
            continue
        try:
            counters = [int(p) for p in parts[1:]]
        except ValueError:
            continue
        idle = counters[3]
        total = sum(counters)
        out.append(CoreJiffies(idx=idx, total=total, idle=idle))
    out.sort(key=lambda c: c.idx)
    return out


def per_core_pct_from_deltas(
    prev: list[CoreJiffies],
    cur: list[CoreJiffies],
) -> list[float]:
    """Compute per-core utilisation pct as ``100 * (1 - idle_delta /
    total_delta)``. First tick or counter wrap → 0.0 for that core.

    Length of the output matches `cur`; cores in `cur` not present in
    `prev` (rare hot-plug case on RPi 5) yield 0.0.
    """
    prev_by_idx = {c.idx: c for c in prev}
    out: list[float] = []
    for c in cur:
        p = prev_by_idx.get(c.idx)
        if p is None:
            out.append(0.0)
            continue
        total_delta = c.total - p.total
        idle_delta = c.idle - p.idle
        if total_delta <= 0:
            out.append(0.0)
            continue
        if idle_delta < 0:
            idle_delta = 0
        pct = 100.0 * (1.0 - idle_delta / total_delta)
        # Floor at 0 (numerical noise) but do NOT clamp at 100 —
        # rounding can briefly emit 100.0001 on a saturated core.
        out.append(max(0.0, round(pct, 2)))
    return out


def _read_meminfo_total_avail(
    path: str = MEMINFO_PATH,
) -> tuple[int | None, int | None]:
    """Return ``(mem_total_bytes, mem_avail_bytes)`` parsed from
    ``/proc/meminfo``. Either value can be ``None`` on a missing or
    malformed source.

    Deliberately NOT re-using `resources._read_meminfo` — the helpers
    are leaves of separate modules per the uncoupled-leaves discipline
    documented at the top of this file.
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return (None, None)
    total: int | None = None
    avail: int | None = None
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            total = _parse_kib_line(line)
        elif line.startswith("MemAvailable:"):
            avail = _parse_kib_line(line)
        if total is not None and avail is not None:
            break
    return (total, avail)


def _parse_kib_line(line: str) -> int | None:
    """Parse a `Key:    <value> kB` /proc/meminfo line into bytes."""
    parts = line.split()
    if len(parts) < 2:  # noqa: PLR2004
        return None
    try:
        return int(parts[1]) * 1024
    except ValueError:
        return None


def _read_disk_pct(check_path: str) -> float | None:
    """Return percentage-used from `os.statvfs(check_path)`. ``None`` on
    OSError."""
    try:
        st = os.statvfs(check_path)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    if total <= 0:
        return None
    return round((total - avail) / total * 100.0, 2)


class ResourcesExtendedSampler:
    """Holds prior-tick per-core jiffy counters across SSE ticks so the
    delta math has a denominator on tick #2 onwards. First tick yields
    every per-core pct = 0.0 (same convention as `ProcessSampler`)."""

    def __init__(
        self,
        *,
        proc_stat_path: str = PROC_STAT_PATH,
        meminfo_path: str = MEMINFO_PATH,
        disk_check_path: str = "/",
    ) -> None:
        self._proc_stat_path = proc_stat_path
        self._meminfo_path = meminfo_path
        self._disk_check_path = disk_check_path
        self._prev_cores: list[CoreJiffies] = []

    def sample(self) -> dict[str, Any]:
        """Return one snapshot dict matching `EXTENDED_RESOURCES_FIELDS`."""
        cur_cores = _read_cpu_per_core_jiffies(self._proc_stat_path)
        cpu_per_core = per_core_pct_from_deltas(self._prev_cores, cur_cores)
        cpu_aggregate_pct = round(sum(cpu_per_core) / len(cpu_per_core), 2) if cpu_per_core else 0.0
        self._prev_cores = cur_cores

        mem_total_bytes, mem_avail_bytes = _read_meminfo_total_avail(self._meminfo_path)
        mem_total_mb: float | None = None
        mem_used_mb: float | None = None
        if mem_total_bytes is not None and mem_avail_bytes is not None:
            mem_total_mb = round(mem_total_bytes / _BYTES_PER_MIB, 2)
            mem_used_mb = round((mem_total_bytes - mem_avail_bytes) / _BYTES_PER_MIB, 2)

        disk_pct = _read_disk_pct(self._disk_check_path)

        return {
            "cpu_per_core": cpu_per_core,
            "cpu_aggregate_pct": cpu_aggregate_pct,
            "mem_total_mb": mem_total_mb,
            "mem_used_mb": mem_used_mb,
            "disk_pct": disk_pct,
            "published_mono_ns": time.monotonic_ns(),
        }
