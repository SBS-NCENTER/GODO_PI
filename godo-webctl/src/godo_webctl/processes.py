"""
PR-B (Track B-SYSTEM PR-B) — process-list snapshot for the System tab.

This module is a STDLIB-ONLY `/proc` parser. It enumerates every live PID
on the host (kernel threads excluded), parses ``/proc/<pid>/{cmdline,
stat, status}`` directly, and computes a per-PID `cpu_pct` from a delta
sample held in `ProcessSampler` between SSE ticks.

**No `subprocess`. No `psutil`. No `ps -ef` shell-out.** A future writer
who reaches for either should fail Mode-B review.

`MANAGED_PROCESS_NAMES` is the PROCESS-NAME (argv-derived) projection of
the three `services.py::ALLOWED_SERVICES` units. The set elements differ
from the systemd unit names by binary-vs-unit asymmetry: `godo-tracker.service`
runs the `godo_tracker_rt` binary; `godo-webctl.service` runs
`python -m godo_webctl` (matched via argv[1..]); `godo-irq-pin.service`
is `Type=oneshot` and is never live in the process list. The classifier
keeps the literal so a future `RemainAfterExit=yes` flip would be
classified correctly without another patch.

cmdline privacy: `/proc/<pid>/cmdline` is world-readable on Linux. This
endpoint surfaces it verbatim to anonymous SPA viewers (anon-readable per
godo-webctl/CODEBASE.md invariant (n)) — so it is NOT a new disclosure
surface; the kernel already exposes the same bytes to any LAN viewer who
runs `cat /proc/<pid>/cmdline`. Operators who don't want a transient
debug command (e.g. `python -c 'secret=...'`) visible to other LAN
viewers should run it after the SPA's Processes sub-tab is closed by all
clients (acknowledged limitation, deferred).

argv[0] basename matching: a process launched via a wrapper that mangles
argv[0] (`bash -c 'exec -a fake_name godo_tracker_rt'`) would slip past
the classifier. Robust matching via `/proc/<pid>/comm` fallback is a
future enhancement; the current studio environment has no argv-rewriting
wrappers.

Expected cost (RPi 5 + Trixie target, 1 Hz tick):
    /proc walk:      1× scandir + ~150× DirEntry.is_dir() (cached)
    Per-PID reads:   ~150 × (cmdline + stat + status)
                     each is a syscall + memcpy of a few hundred bytes
                     — pure kernel data, no disk I/O.
    Wall-time:       5–15 ms CPU on cores 0–2 per tick ⇒ <1.5% of one
                     core, ≪0.5% aggregate.
    RAM:             ~10 KB prior-tick map; ~150 dict objects/tick
                     (Python GC reclaims same tick) ⇒ <2 MB resident
                     overhead on top of webctl baseline.
    Comparison:      htop default refresh = 1.5 s with similar `/proc`
                     walk plus per-thread + I/O accounting we skip
                     ⇒ our cost is roughly ~half of htop at the same
                     refresh rate.
    RT-isolation:    webctl runs on cores 0–2 (cgroup default); the
                     tracker's RT thread is pinned to core 3 with
                     SCHED_FIFO. Worst-case per-tick spikes never touch
                     core 3 ⇒ zero risk to AMCL hot path.

Leaf module: imports stdlib + `.constants` + `.protocol` only.
"""

from __future__ import annotations

import logging
import os
import pwd
import time
from dataclasses import dataclass
from typing import Any, Final, Literal

from .constants import PROC_PATH, PROC_STAT_PATH
from .protocol import (
    GODO_PROCESS_NAMES,
    MANAGED_PROCESS_NAMES,
    PROCESS_FIELDS,
)

logger = logging.getLogger("godo_webctl.processes")

# Wire-side classification values. ``Literal`` keeps the type system honest;
# any new value must be added on both Python and TS sides.
Category = Literal["general", "godo", "managed"]

# webctl-internal: argv-substring pattern that identifies our own
# uvicorn/python process. We match argv[0]=="python*" or argv[0] basename
# in `_PYTHON_BASENAMES` AND any argv[1..] containing this token.
_GODO_WEBCTL_ARGV_TOKEN: Final[str] = "godo_webctl"
_PYTHON_BASENAMES: Final[frozenset[str]] = frozenset(
    {"python", "python3", "uvicorn"},
)

# uid → username cache. `pwd.getpwuid` reads `/etc/passwd` (no nscd on
# RPi 5 by default); per-call cost is microseconds but the failure mode
# (ephemeral `userdel` race) is more interesting — cache lazily, never
# invalidate. webctl restart clears it. Per Mode-A N2 fold.
_uid_cache: dict[int, str] = {}


@dataclass(frozen=True)
class PidStat:
    """Subset of ``/proc/<pid>/stat`` fields we read."""

    state: str  # field 3 (single char R/S/D/Z/T/I/W/X)
    utime_jiffies: int  # field 14
    stime_jiffies: int  # field 15
    starttime_jiffies: int  # field 22


def parse_proc_stat_total_jiffies(text: str) -> int:
    """Parse the aggregate `cpu` line of ``/proc/stat`` and return the
    sum of every column (user + nice + system + idle + iowait + irq +
    softirq + steal + guest + guest_nice). Used as the denominator in
    `cpu_pct_from_deltas`.

    Raises `ValueError` if the file does not contain a leading `cpu`
    line — that would indicate a fundamentally broken `/proc`."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            parts = line.split()
            return sum(int(p) for p in parts[1:])
    raise ValueError("no aggregate `cpu` line found in /proc/stat")


def parse_pid_stat(text: str) -> PidStat:
    """Parse ``/proc/<pid>/stat``.

    Field 2 of the line is `(comm)`, where `comm` may contain spaces and
    a literal `)` — the classic parse footgun is a naïve
    ``text.split()[1]``. Correct algorithm: find the LAST `)` in the
    line, then split the suffix on whitespace. Field 3 (state) is the
    first token after that closing paren; fields 14, 15, 22 follow.

    Raises `ValueError` on a malformed line.
    """
    last_paren = text.rfind(")")
    if last_paren < 0:
        raise ValueError("no closing paren found in /proc/<pid>/stat line")
    # Tokens after the closing paren start at field 3 (state).
    tail = text[last_paren + 1 :].split()
    if len(tail) < 20:  # noqa: PLR2004 — at least state(0) + utime(11) + stime(12) + starttime(19)
        raise ValueError("not enough fields after `)` in /proc/<pid>/stat line")
    state = tail[0]
    # tail[0] = field 3, so utime (field 14) = tail[11], stime = tail[12],
    # starttime = tail[19] (field 22).
    utime = int(tail[11])
    stime = int(tail[12])
    starttime = int(tail[19])
    return PidStat(
        state=state,
        utime_jiffies=utime,
        stime_jiffies=stime,
        starttime_jiffies=starttime,
    )


def parse_pid_status_rss_kb(text: str) -> int | None:
    """Parse the ``VmRSS`` line of ``/proc/<pid>/status``. Returns the
    integer kB value, or ``None`` if the file lacks the line (typical of
    kernel threads / zombie processes)."""
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:  # noqa: PLR2004
                try:
                    return int(parts[1])
                except ValueError:
                    return None
            return None
    return None


def parse_pid_status_uid(text: str) -> int | None:
    """Parse the ``Uid`` line of ``/proc/<pid>/status``. Returns the
    real-uid (first of the four space-separated values) or ``None`` if
    the line is missing or malformed."""
    for line in text.splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            if len(parts) >= 2:  # noqa: PLR2004
                try:
                    return int(parts[1])
                except ValueError:
                    return None
            return None
    return None


def parse_pid_cmdline(raw: bytes) -> tuple[str, list[str]]:
    """Parse ``/proc/<pid>/cmdline`` (NUL-separated argv).

    Returns ``(name, args)`` where:
      - ``name`` is the argv[0] basename (or the empty string for kernel
        threads — they have a zero-byte cmdline file). For the special
        case of ``python`` / ``python3`` / ``uvicorn`` invocations whose
        argv[1..] mentions ``godo_webctl``, ``name`` becomes
        ``"godo-webctl"`` so the classifier doesn't have to special-case
        the wrapper.
      - ``args`` is the full argv list (UTF-8-decoded with `replace`
        errors), including argv[0].

    Empty / NUL-only cmdline → ``("", [])`` (kernel-thread sentinel).
    """
    if not raw:
        return ("", [])
    # cmdline is NUL-separated argv with a trailing NUL after the last
    # element (kernel convention). Strip the trailing NUL before split.
    if raw.endswith(b"\x00"):
        raw = raw[:-1]
    if not raw:
        return ("", [])
    parts = raw.split(b"\x00")
    args = [p.decode("utf-8", errors="replace") for p in parts]
    if not args or not args[0]:
        return ("", [])
    base = os.path.basename(args[0])
    # godo-webctl exception: matched via argv[1..] containing the
    # `godo_webctl` token. Without this the SPA's Processes sub-tab
    # would never see itself, defeating the operator's "is the webctl
    # alive?" use case.
    if base in _PYTHON_BASENAMES:
        for arg in args[1:]:
            if _GODO_WEBCTL_ARGV_TOKEN in arg:
                return ("godo-webctl", args)
    return (base, args)


def cpu_pct_from_deltas(
    prev_total: int,
    prev_proc: int,
    cur_total: int,
    cur_proc: int,
) -> float:
    """Derive a per-PID CPU percentage from prev/cur jiffy counters.

    The formula: ``100.0 * (proc_delta / total_delta)`` where
    `total_delta` is the aggregate CPU jiffies elapsed across all cores.
    On a 4-core machine fully saturating one core gives ~25%; saturating
    all four gives ~100%. Aggregate-CPU normalisation matches the
    operator's expectation that "100% means the whole RPi 5 is pegged".

    Edge cases (algebraic, not implementation-detail):

      - ``cur_total == prev_total`` (no time elapsed between samples,
        clock skew, or ``/proc/stat`` jitter) → 0.0, NOT NaN.
      - ``cur_proc < prev_proc`` (counter went BACKWARDS — kernel jiffy
        accounting can race with the read; should be rare on aarch64
        but defence-in-depth) → floor at 0.0.
      - 4-core saturation can legitimately read above 100% — we do NOT
        clamp at 100.0; the SPA is responsible for any visual cap.
    """
    total_delta = cur_total - prev_total
    proc_delta = cur_proc - prev_proc
    if total_delta <= 0:
        return 0.0
    if proc_delta < 0:
        return 0.0
    # `* 100 * core_count` math is encoded in the per-core total_delta:
    # on a 4-core machine /proc/stat sums per-core jiffies so total_delta
    # already reflects 4-core elapsed. Hence dividing by it gives the
    # aggregate-normalised pct without an explicit core-count multiplier.
    # Multi-core saturation can produce values > 100.0 — see docstring.
    return 100.0 * proc_delta / total_delta


def classify_pid(name: str) -> Category:
    """Classify a process by its argv-derived name.

    Order matters: ``managed`` is checked before ``godo`` so that a
    process that appears in BOTH sets (e.g. `godo_tracker_rt`, in
    `MANAGED_PROCESS_NAMES` because the `godo-tracker.service` runs it,
    and also in `GODO_PROCESS_NAMES`) classifies as `managed`.
    """
    if name in MANAGED_PROCESS_NAMES:
        return "managed"
    if name in GODO_PROCESS_NAMES:
        return "godo"
    return "general"


def _resolve_username(uid: int | None) -> str:
    """Resolve a real-uid to a username via ``pwd.getpwuid`` with a
    module-level lazy cache. Falls back to the numeric uid string on
    `KeyError` (uid not present in the passwd database).
    """
    if uid is None:
        return "?"
    cached = _uid_cache.get(uid)
    if cached is not None:
        return cached
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = str(uid)
    _uid_cache[uid] = name
    return name


def _read_text_file(path: str) -> str:
    """Read a `/proc` text file. Raises `FileNotFoundError` on PID
    disappear; other OSErrors propagate (caller treats as drop-row)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _read_binary_file(path: str) -> bytes:
    """Read a `/proc` binary file (e.g. cmdline). Same race semantics."""
    with open(path, "rb") as f:
        return f.read()


@dataclass(frozen=True)
class PidEntry:
    """One enumerated PID with its parsed inputs (pre-cpu-pct math).

    Lives outside the wire payload — used internally by `ProcessSampler`
    so the cpu_pct delta can be computed across two ticks."""

    pid: int
    name: str
    cmdline: list[str]
    state: str
    uid: int | None
    rss_kb: int | None
    utime_jiffies: int
    stime_jiffies: int
    starttime_jiffies: int


def enumerate_all_pids(
    proc_root: str = PROC_PATH,
) -> list[PidEntry]:
    """Walk ``proc_root`` and return one ``PidEntry`` per live PID.

    Kernel threads (cmdline empty) are EXCLUDED from the list — they
    would inflate the table to ~200 rows of `[ksoftirqd]`-style entries
    with zero RSS and operator-irrelevant info.

    PID-disappear races (R1) are handled per-PID: a PID that exits
    between `scandir` and the per-file reads silently drops out of the
    result. All other OSErrors are logged at DEBUG and the entry is
    skipped.
    """
    out: list[PidEntry] = []
    try:
        scan = os.scandir(proc_root)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return out
    with scan:
        for entry in scan:
            name = entry.name
            if not name.isdigit():
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            pid = int(name)
            base = f"{proc_root}/{name}"
            try:
                cmdline_raw = _read_binary_file(f"{base}/cmdline")
                stat_text = _read_text_file(f"{base}/stat")
                status_text = _read_text_file(f"{base}/status")
            except (FileNotFoundError, ProcessLookupError):
                # PID exited mid-iteration — skip silently.
                continue
            except OSError as e:
                logger.debug("processes.read_pid_failed pid=%d err=%s", pid, e)
                continue
            try:
                proc_name, args = parse_pid_cmdline(cmdline_raw)
            except (UnicodeDecodeError, ValueError) as e:
                logger.debug("processes.parse_cmdline_failed pid=%d err=%s", pid, e)
                continue
            if not proc_name:
                # Kernel thread or zombie with cleared cmdline — drop.
                continue
            try:
                pidstat = parse_pid_stat(stat_text)
            except ValueError as e:
                logger.debug("processes.parse_pid_stat_failed pid=%d err=%s", pid, e)
                continue
            uid = parse_pid_status_uid(status_text)
            rss_kb = parse_pid_status_rss_kb(status_text)
            out.append(
                PidEntry(
                    pid=pid,
                    name=proc_name,
                    cmdline=args,
                    state=pidstat.state,
                    uid=uid,
                    rss_kb=rss_kb,
                    utime_jiffies=pidstat.utime_jiffies,
                    stime_jiffies=pidstat.stime_jiffies,
                    starttime_jiffies=pidstat.starttime_jiffies,
                ),
            )
    return out


def _read_total_jiffies(stat_path: str) -> int:
    """Read the `/proc/stat` aggregate-CPU jiffies. Returns 0 on read
    failure (caller treats 0 as "no delta possible this tick")."""
    try:
        text = _read_text_file(stat_path)
    except OSError:
        return 0
    try:
        return parse_proc_stat_total_jiffies(text)
    except ValueError:
        return 0


# Conversion factor: kernel jiffies → seconds. `os.sysconf("SC_CLK_TCK")`
# returns 100 on RPi 5 + most distros; we read it once at module load so
# the `etime_s` math doesn't pay the syscall every tick.
_CLK_TCK: Final[int] = max(int(os.sysconf("SC_CLK_TCK")), 1)


def _btime(stat_path: str) -> int | None:
    """Parse the `btime` (boot time, unix-seconds) line of `/proc/stat`.
    Returns ``None`` on failure; the caller falls back to 0 elapsed.
    """
    try:
        text = _read_text_file(stat_path)
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("btime "):
            parts = line.split()
            if len(parts) >= 2:  # noqa: PLR2004
                try:
                    return int(parts[1])
                except ValueError:
                    return None
    return None


class ProcessSampler:
    """Holds prior-tick state across SSE ticks so per-PID cpu_pct can be
    computed as a delta. First tick after construction returns
    ``cpu_pct=0.0`` for every PID by design (R5 — operator UI showing
    0% for one second after stream open is acceptable).

    NOT thread-safe in the strict sense; the SSE producer task runs
    single-threaded under asyncio so per-stream isolation is provided
    by giving each subscriber its own sampler instance. The one-shot
    `GET /api/system/processes` handler shares a single sampler across
    concurrent requests via `asyncio.to_thread` — Python dict ops are
    GIL-atomic so the worst case under concurrency is approximate
    cpu_pct (no torn reads / no crash); see `app.py` `_processes_one_shot`.
    A new SSE subscriber MUST construct its own sampler so a previously-
    cancelled stream's stale prior-tick map doesn't leak into the next.
    """

    def __init__(self, proc_root: str = PROC_PATH) -> None:
        self._proc_root = proc_root
        # pid -> (utime + stime jiffies)
        self._prev_proc_jiffies: dict[int, int] = {}
        self._prev_total_jiffies: int = 0
        self._stat_path = f"{proc_root}/stat" if proc_root != PROC_PATH else PROC_STAT_PATH

    def sample(self) -> dict[str, Any]:
        """Return one snapshot of the wire shape

        ``{"processes": [...], "duplicate_alert": bool, "published_mono_ns": int}``

        with one entry per live (non-kernel-thread) PID.
        """
        cur_total = _read_total_jiffies(self._stat_path)
        entries = enumerate_all_pids(self._proc_root)
        btime = _btime(self._stat_path) or 0
        now_unix = int(time.time())
        # First pass: count names so per-row `duplicate` flag and
        # top-level `duplicate_alert` agree by construction.
        name_counts: dict[str, int] = {}
        for e in entries:
            name_counts[e.name] = name_counts.get(e.name, 0) + 1

        rows: list[dict[str, Any]] = []
        any_dup = False
        cur_proc_jiffies: dict[int, int] = {}
        for e in entries:
            proc_jiffies = e.utime_jiffies + e.stime_jiffies
            cur_proc_jiffies[e.pid] = proc_jiffies
            prev_proc = self._prev_proc_jiffies.get(e.pid)
            if prev_proc is None or self._prev_total_jiffies <= 0 or cur_total <= 0:
                cpu_pct = 0.0
            else:
                cpu_pct = cpu_pct_from_deltas(
                    self._prev_total_jiffies,
                    prev_proc,
                    cur_total,
                    proc_jiffies,
                )
            rss_mb = round(e.rss_kb / 1024.0, 2) if e.rss_kb is not None else None
            etime_s = max(0, now_unix - (btime + e.starttime_jiffies // _CLK_TCK)) if btime else 0
            category = classify_pid(e.name)
            duplicate = name_counts[e.name] > 1 and category != "general"
            if duplicate:
                any_dup = True
            rows.append(
                {
                    "name": e.name,
                    "pid": e.pid,
                    "user": _resolve_username(e.uid),
                    "state": e.state,
                    "cmdline": e.cmdline,
                    "cpu_pct": round(cpu_pct, 2),
                    "rss_mb": rss_mb,
                    "etime_s": etime_s,
                    "category": category,
                    "duplicate": duplicate,
                },
            )

        # Sort default: cpu_pct descending. SPA still re-sorts on column
        # click, but the wire default keeps a debug `curl` readable.
        rows.sort(key=lambda r: (-_as_float(r["cpu_pct"]), r["pid"]))

        # Stash for next tick. Replace wholesale — the "PID exited"
        # case naturally drops out of the next tick's denominator since
        # `enumerate_all_pids` won't return it.
        self._prev_proc_jiffies = cur_proc_jiffies
        self._prev_total_jiffies = cur_total

        return {
            "processes": rows,
            "duplicate_alert": any_dup,
            "published_mono_ns": time.monotonic_ns(),
        }


def _as_float(v: Any) -> float:
    """Defensive cast for the sort key — a future schema-extension that
    introduces a non-numeric `cpu_pct` shouldn't crash the sort."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _ensure_field_order_pin() -> None:
    """Internal — keep the dict-row keys in `ProcessSampler.sample` in
    lockstep with `PROCESS_FIELDS`. Rather than reflect on the dict
    (its order isn't authoritative), we pin a synthetic row at import
    time."""
    sample_keys = (
        "name",
        "pid",
        "user",
        "state",
        "cmdline",
        "cpu_pct",
        "rss_mb",
        "etime_s",
        "category",
        "duplicate",
    )
    assert sample_keys == PROCESS_FIELDS, (
        f"ProcessSampler.sample row-key drift: code={sample_keys} protocol={PROCESS_FIELDS}"
    )


_ensure_field_order_pin()


def _reset_uid_cache_for_tests() -> None:
    """Test-only — clears the lazy uid→username cache."""
    _uid_cache.clear()
