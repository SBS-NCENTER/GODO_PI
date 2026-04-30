"""
PR-B (Track B-SYSTEM PR-B) — `/proc` parsers + ProcessSampler tests.

Bias-blocking discipline (planner pre-emption):
- Every parser test asserts on FIXTURE TEXT laid out under tmp_path,
  not on a synthesized `format(...)` string from production code.
- `cpu_pct_from_deltas` enumerates ALGEBRAIC edge cases (zero-elapsed,
  negative drift, multi-core saturation), not "what the function
  returns" tautology.
- `enumerate_all_pids` walks a fake `/proc` tree under tmp_path; no
  reads on the real host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from godo_webctl import processes


def _write_pid_dir(
    proc_root: Path,
    pid: int,
    *,
    cmdline: bytes,
    stat: str,
    status: str,
) -> None:
    """Lay out a fake `/proc/<pid>/` triplet."""
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True, exist_ok=True)
    (pid_dir / "cmdline").write_bytes(cmdline)
    (pid_dir / "stat").write_text(stat, encoding="utf-8")
    (pid_dir / "status").write_text(status, encoding="utf-8")


def _write_proc_stat(proc_root: Path, *, total_jiffies: int = 1000, btime: int = 0) -> None:
    """Lay out `/proc/stat` with an aggregate `cpu` line whose columns
    sum to `total_jiffies`. Layout: 10 columns of equal share + a
    `btime` line."""
    share = total_jiffies // 10
    extra = total_jiffies - share * 10
    cols = " ".join(str(share + (1 if i == 0 else 0) * extra) for i in range(10))
    (proc_root / "stat").write_text(
        f"cpu {cols}\ncpu0 {cols}\nbtime {btime}\n",
        encoding="utf-8",
    )


def _build_pid_stat(
    *,
    pid: int = 1234,
    comm: str = "myproc",
    state: str = "S",
    utime: int = 100,
    stime: int = 200,
    starttime: int = 5000000,
) -> str:
    """Build a `/proc/<pid>/stat` line. Field 22 (starttime) is jiffies
    since boot. This helper is the test-side mirror of the kernel's
    `fs/proc/array.c::do_task_stat` writer.

    Layout (1-indexed):
      1: pid
      2: (comm)            ← may contain spaces and `)` — see M7
      3: state
      4..13: ppid pgrp session tty_nr tpgid flags minflt cminflt majflt cmajflt
      14: utime
      15: stime
      16..21: cutime cstime priority nice num_threads itrealvalue
      22: starttime
      23..52: ...
    """
    # Head fields 4..13 (10 cols) — placeholder zeros except ppid=1.
    head = "1 1234 1234 0 -1 4194304 0 0 0 0"
    # Tail after stime: cutime cstime priority nice num_threads itrealvalue.
    tail = "0 0 20 0 1 0"
    return f"{pid} ({comm}) {state} {head} {utime} {stime} {tail} {starttime} " + "0 " * 30 + "\n"


def _build_status(
    *,
    name: str = "myproc",
    uid: int = 1000,
    rss_kb: int | None = 4096,
) -> str:
    rss_line = f"VmRSS:\t{rss_kb} kB\n" if rss_kb is not None else ""
    return f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n{rss_line}"


# --- pure parsers ---------------------------------------------------------


def test_parse_proc_stat_total_jiffies_happy() -> None:
    text = "cpu 100 50 25 10 5 0 0 0 0 0\nintr 1\nbtime 1000\n"
    assert processes.parse_proc_stat_total_jiffies(text) == 190


def test_parse_proc_stat_total_jiffies_missing_cpu_line() -> None:
    with pytest.raises(ValueError, match="aggregate"):
        processes.parse_proc_stat_total_jiffies("intr 1\nbtime 1000\n")


def test_parse_pid_stat_happy() -> None:
    line = _build_pid_stat(pid=42, comm="bash", state="S", utime=100, stime=200, starttime=5000)
    s = processes.parse_pid_stat(line)
    assert s.state == "S"
    assert s.utime_jiffies == 100
    assert s.stime_jiffies == 200
    assert s.starttime_jiffies == 5000


def test_parse_pid_stat_handles_paren_in_comm() -> None:
    """Mode-A M7 fold: `comm` may contain BOTH a space AND a literal `)`.
    The kernel emits `(comm)` — so a comm ending in `)` produces `))`
    in the line. Naive `text.split()[1]` fails; our `rfind(')')` fix
    finds the LAST `)`."""
    line = (
        "1234 (Web Content)) S 1 1234 1234 0 -1 4194304 0 0 0 0 100 200 "
        "0 0 20 0 1 0 5000000 " + "0 " * 30 + "\n"
    )
    s = processes.parse_pid_stat(line)
    assert s.state == "S"
    assert s.utime_jiffies == 100
    assert s.stime_jiffies == 200
    assert s.starttime_jiffies == 5000000


def test_parse_pid_stat_malformed_raises() -> None:
    with pytest.raises(ValueError):
        processes.parse_pid_stat("malformed line no parens")


def test_parse_pid_status_rss_kb_happy() -> None:
    text = "Name:\tbash\nUid:\t1000\t1000\t1000\t1000\nVmRSS:\t8192 kB\n"
    assert processes.parse_pid_status_rss_kb(text) == 8192


def test_parse_pid_status_rss_kb_missing_kernel_thread() -> None:
    text = "Name:\t[ksoftirqd]\nUid:\t0\t0\t0\t0\n"
    assert processes.parse_pid_status_rss_kb(text) is None


def test_parse_pid_status_uid_happy() -> None:
    text = "Name:\tbash\nUid:\t1000\t1001\t1002\t1003\n"
    # Real-uid is the FIRST of the four.
    assert processes.parse_pid_status_uid(text) == 1000


def test_parse_pid_cmdline_nul_separated() -> None:
    raw = b"python3\x00-m\x00uvicorn\x00app:create_app\x00"
    name, args = processes.parse_pid_cmdline(raw)
    # python wrapper without the `godo_webctl` argv token falls back to
    # the literal basename `python3`.
    assert name == "python3"
    assert args == ["python3", "-m", "uvicorn", "app:create_app"]


def test_parse_pid_cmdline_empty_kernel_thread() -> None:
    assert processes.parse_pid_cmdline(b"") == ("", [])
    assert processes.parse_pid_cmdline(b"\x00") == ("", [])


def test_parse_pid_cmdline_godo_webctl_python_argv() -> None:
    """N1 docstring assertion: `python -m godo_webctl` resolves to name
    `godo-webctl` (hyphen, NOT underscore — matches `MANAGED_PROCESS_NAMES`)."""
    raw = b"/usr/bin/python3\x00-m\x00godo_webctl\x00--bind\x00:8000\x00"
    name, _ = processes.parse_pid_cmdline(raw)
    assert name == "godo-webctl"


def test_parse_pid_cmdline_uvicorn_godo_webctl() -> None:
    """Same special case via the uvicorn wrapper."""
    raw = b"uvicorn\x00godo_webctl.app:create_app\x00--factory\x00"
    name, _ = processes.parse_pid_cmdline(raw)
    assert name == "godo-webctl"


def test_parse_pid_cmdline_argv0_basename_strip_path() -> None:
    """argv[0] is often a fully-qualified path."""
    raw = b"/opt/godo-tracker/godo_tracker_rt\x00--config\x00/etc/godo/tracker.toml\x00"
    name, _ = processes.parse_pid_cmdline(raw)
    assert name == "godo_tracker_rt"


# --- cpu_pct algebraic edge cases (Mode-A M8) -----------------------------


def test_cpu_pct_from_deltas_happy() -> None:
    # 100 jiffies of process time / 1000 jiffies of total = 10%.
    assert processes.cpu_pct_from_deltas(0, 0, 1000, 100) == 10.0


def test_cpu_pct_from_deltas_zero_total_delta_returns_zero() -> None:
    """Mode-A M8(2): denominator zero → 0.0, not NaN. Even if numerator
    is positive, no time-elapsed means we cannot derive a rate."""
    assert processes.cpu_pct_from_deltas(1000, 0, 1000, 50) == 0.0


def test_cpu_pct_from_deltas_negative_delta_floors_to_zero() -> None:
    """Mode-A M8(1): if the kernel's per-PID counter goes BACKWARDS
    between reads (race / wraparound), floor at 0.0 rather than emit a
    negative number."""
    assert processes.cpu_pct_from_deltas(0, 1000, 2000, 500) == 0.0


def test_cpu_pct_from_deltas_does_not_clamp_at_100_for_multicore() -> None:
    """Mode-A M8(3): 4-core saturation of a single PID is legitimate
    400% (each core's full jiffies attributed to the PID's utime+stime).
    The helper does not clamp."""
    # total_delta = 1000 (1 sec aggregate across 4 cores at 250 jiffies/core)
    # proc_delta  = 4000 (PID had 4 threads each pegging a core)
    pct = processes.cpu_pct_from_deltas(0, 0, 1000, 4000)
    assert pct == 400.0


def test_cpu_pct_from_deltas_quarter_core_one_of_four() -> None:
    """Per-core 25% utilisation → aggregate 25% of one-of-four-cores."""
    assert processes.cpu_pct_from_deltas(0, 0, 4000, 1000) == 25.0


# --- classify_pid ---------------------------------------------------------


def test_classify_pid_managed_takes_priority_over_godo() -> None:
    """`godo_tracker_rt` is in BOTH `MANAGED_PROCESS_NAMES` and
    `GODO_PROCESS_NAMES`; `classify_pid` returns `managed`."""
    assert processes.classify_pid("godo_tracker_rt") == "managed"


def test_classify_pid_godo_only() -> None:
    assert processes.classify_pid("godo_smoke") == "godo"
    assert processes.classify_pid("godo_jitter") == "godo"


def test_classify_pid_general_fallback() -> None:
    assert processes.classify_pid("bash") == "general"
    assert processes.classify_pid("vim") == "general"


def test_classify_pid_godo_webctl_is_managed() -> None:
    assert processes.classify_pid("godo-webctl") == "managed"


# --- enumerate_all_pids ---------------------------------------------------


def test_enumerate_all_pids_happy(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc, total_jiffies=10000)
    # 3 godo processes.
    _write_pid_dir(
        proc,
        100,
        cmdline=b"/opt/godo-tracker/godo_tracker_rt\x00",
        stat=_build_pid_stat(pid=100, comm="godo_tracker_rt"),
        status=_build_status(name="godo_tracker_rt", uid=1000, rss_kb=51200),
    )
    _write_pid_dir(
        proc,
        101,
        cmdline=b"godo_smoke\x00",
        stat=_build_pid_stat(pid=101, comm="godo_smoke"),
        status=_build_status(name="godo_smoke", uid=1000, rss_kb=2048),
    )
    _write_pid_dir(
        proc,
        102,
        cmdline=b"/usr/bin/python3\x00-m\x00godo_webctl\x00",
        stat=_build_pid_stat(pid=102, comm="python3"),
        status=_build_status(name="python3", uid=1000, rss_kb=8192),
    )
    # 2 non-godo processes.
    _write_pid_dir(
        proc,
        200,
        cmdline=b"bash\x00",
        stat=_build_pid_stat(pid=200, comm="bash"),
        status=_build_status(name="bash", uid=1000, rss_kb=1024),
    )
    _write_pid_dir(
        proc,
        201,
        cmdline=b"vim\x00",
        stat=_build_pid_stat(pid=201, comm="vim"),
        status=_build_status(name="vim", uid=1000, rss_kb=4096),
    )
    # 1 kernel thread (cmdline empty).
    _write_pid_dir(
        proc,
        2,
        cmdline=b"",
        stat=_build_pid_stat(pid=2, comm="kthreadd"),
        status=_build_status(name="kthreadd", uid=0, rss_kb=None),
    )
    entries = processes.enumerate_all_pids(str(proc))
    pids = sorted(e.pid for e in entries)
    # Kernel thread excluded; the 5 userspace PIDs come back.
    assert pids == [100, 101, 102, 200, 201]


def test_enumerate_handles_pid_disappearing_mid_iteration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode-A R1 mitigation: a PID that exits between scandir() and the
    per-file reads silently drops out of the result. Inject a fake
    `_read_text_file` that raises `FileNotFoundError` on PID 100's
    `stat` read; PID 200 still comes back."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc, total_jiffies=10000)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"godo_smoke\x00",
        stat=_build_pid_stat(pid=100, comm="godo_smoke"),
        status=_build_status(name="godo_smoke"),
    )
    _write_pid_dir(
        proc,
        200,
        cmdline=b"bash\x00",
        stat=_build_pid_stat(pid=200, comm="bash"),
        status=_build_status(name="bash"),
    )

    real_read = processes._read_text_file

    def flaky_read(path: str) -> str:
        if path.endswith("/100/stat"):
            raise FileNotFoundError(path)
        return real_read(path)

    monkeypatch.setattr(processes, "_read_text_file", flaky_read)
    entries = processes.enumerate_all_pids(str(proc))
    pids = sorted(e.pid for e in entries)
    assert pids == [200]


def test_enumerate_skips_kernel_thread(tmp_path: Path) -> None:
    """Mode-A M4 fold: cmdline-empty entries are excluded BEFORE
    classification runs, so a userspace process with empty cmdline is
    dropped (not classified as `general`). Defence-in-depth at the
    boundary."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    _write_pid_dir(
        proc,
        2,
        cmdline=b"",  # kernel thread
        stat=_build_pid_stat(pid=2, comm="kthreadd"),
        status=_build_status(name="kthreadd", rss_kb=None),
    )
    entries = processes.enumerate_all_pids(str(proc))
    assert entries == []


def test_enumerate_ignores_non_pid_dirs(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    (proc / "self").mkdir()
    (proc / "sys").mkdir()
    (proc / "uptime").write_text("0 0\n")
    entries = processes.enumerate_all_pids(str(proc))
    assert entries == []


def test_enumerate_missing_proc_root_returns_empty(tmp_path: Path) -> None:
    """`/proc` not mounted (e.g. in a stripped-down container) returns
    an empty list rather than raising."""
    assert processes.enumerate_all_pids(str(tmp_path / "missing")) == []


# --- ProcessSampler -------------------------------------------------------


def test_processes_sampler_first_tick_returns_zero_cpu_pct(tmp_path: Path) -> None:
    """Mode-A R5: first tick after construction has no prior counters,
    so cpu_pct = 0.0 by design."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc, total_jiffies=10000, btime=int(__import__("time").time()) - 100)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"godo_smoke\x00",
        stat=_build_pid_stat(pid=100, comm="godo_smoke", utime=500, stime=500),
        status=_build_status(name="godo_smoke", rss_kb=2048),
    )
    sampler = processes.ProcessSampler(proc_root=str(proc))
    snap = sampler.sample()
    assert snap["duplicate_alert"] is False
    rows = snap["processes"]
    assert len(rows) == 1
    assert rows[0]["cpu_pct"] == 0.0
    assert rows[0]["pid"] == 100
    assert rows[0]["category"] == "godo"
    assert rows[0]["rss_mb"] == round(2048 / 1024.0, 2)


def test_processes_sampler_subsequent_tick_returns_correct_cpu_pct(
    tmp_path: Path,
) -> None:
    """Two-tick pump: tick 1 establishes the baseline; tick 2 sees an
    additional 100 jiffies of process time against +1000 of total."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc, total_jiffies=10000)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"godo_smoke\x00",
        stat=_build_pid_stat(pid=100, comm="godo_smoke", utime=400, stime=100),
        status=_build_status(name="godo_smoke", rss_kb=2048),
    )
    sampler = processes.ProcessSampler(proc_root=str(proc))
    sampler.sample()  # tick 1 — baseline
    # Tick 2 — bump utime by 100 + total by 1000.
    _write_proc_stat(proc, total_jiffies=11000)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"godo_smoke\x00",
        stat=_build_pid_stat(pid=100, comm="godo_smoke", utime=500, stime=100),
        status=_build_status(name="godo_smoke", rss_kb=2048),
    )
    snap = sampler.sample()
    rows = snap["processes"]
    assert len(rows) == 1
    # 100 / 1000 = 10%.
    assert rows[0]["cpu_pct"] == 10.0


def test_processes_sampler_duplicate_alert_when_two_godo_tracker_rt(
    tmp_path: Path,
) -> None:
    """Mode-A: top-level `duplicate_alert` triggers + per-row `duplicate`
    flag set on both PIDs sharing a managed name."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    for pid in (100, 101):
        _write_pid_dir(
            proc,
            pid,
            cmdline=b"godo_tracker_rt\x00",
            stat=_build_pid_stat(pid=pid, comm="godo_tracker_rt"),
            status=_build_status(name="godo_tracker_rt", rss_kb=4096),
        )
    sampler = processes.ProcessSampler(proc_root=str(proc))
    snap = sampler.sample()
    assert snap["duplicate_alert"] is True
    rows = snap["processes"]
    assert all(r["duplicate"] is True for r in rows)
    assert all(r["category"] == "managed" for r in rows)


def test_processes_sampler_no_duplicate_when_two_general_processes(
    tmp_path: Path,
) -> None:
    """Two `bash` is normal — `general` processes never trigger
    duplicate_alert (operator's debug shells stack)."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    for pid in (100, 101):
        _write_pid_dir(
            proc,
            pid,
            cmdline=b"bash\x00",
            stat=_build_pid_stat(pid=pid, comm="bash"),
            status=_build_status(name="bash"),
        )
    sampler = processes.ProcessSampler(proc_root=str(proc))
    snap = sampler.sample()
    assert snap["duplicate_alert"] is False
    rows = snap["processes"]
    assert all(r["duplicate"] is False for r in rows)


def test_processes_sampler_no_duplicate_when_single_pid_per_name(
    tmp_path: Path,
) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"godo_smoke\x00",
        stat=_build_pid_stat(pid=100, comm="godo_smoke"),
        status=_build_status(name="godo_smoke"),
    )
    snap = processes.ProcessSampler(proc_root=str(proc)).sample()
    assert snap["duplicate_alert"] is False


def test_processes_sampler_published_mono_ns_present(tmp_path: Path) -> None:
    """Mode-A M6: `published_mono_ns` clock-domain note. The wire field
    is `time.monotonic_ns()` (Python clock domain). Smoke-test it's
    populated and monotonic across two samples."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"godo_smoke\x00",
        stat=_build_pid_stat(pid=100, comm="godo_smoke"),
        status=_build_status(name="godo_smoke"),
    )
    sampler = processes.ProcessSampler(proc_root=str(proc))
    snap1 = sampler.sample()
    snap2 = sampler.sample()
    assert isinstance(snap1["published_mono_ns"], int)
    assert snap2["published_mono_ns"] >= snap1["published_mono_ns"]


def test_processes_sampler_user_resolved_via_pwd(tmp_path: Path) -> None:
    """`user` field carries the resolved username (not the numeric uid)
    when uid is in the passwd database. We use uid 0 (root) which is
    universally present."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    _write_pid_dir(
        proc,
        1,
        cmdline=b"systemd\x00",
        stat=_build_pid_stat(pid=1, comm="systemd"),
        status=_build_status(name="systemd", uid=0, rss_kb=8192),
    )
    processes._reset_uid_cache_for_tests()
    snap = processes.ProcessSampler(proc_root=str(proc)).sample()
    rows = snap["processes"]
    assert len(rows) == 1
    assert rows[0]["user"] == "root"


def test_processes_sampler_unknown_uid_fallback_numeric_string(
    tmp_path: Path,
) -> None:
    """An ephemeral uid (no passwd entry) falls back to the numeric
    string form."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"foo\x00",
        stat=_build_pid_stat(pid=100, comm="foo"),
        status=_build_status(name="foo", uid=999_999),
    )
    processes._reset_uid_cache_for_tests()
    snap = processes.ProcessSampler(proc_root=str(proc)).sample()
    rows = snap["processes"]
    assert len(rows) == 1
    assert rows[0]["user"] == "999999"


def test_processes_sampler_state_carried_through(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"foo\x00",
        stat=_build_pid_stat(pid=100, comm="foo", state="D"),
        status=_build_status(name="foo"),
    )
    snap = processes.ProcessSampler(proc_root=str(proc)).sample()
    rows = snap["processes"]
    assert len(rows) == 1
    assert rows[0]["state"] == "D"


def test_processes_sampler_sorted_by_cpu_pct_desc(tmp_path: Path) -> None:
    """Wire-default sort is cpu_pct descending so a `curl` debug is
    legible. Pump two ticks so a pair of PIDs see different deltas."""
    proc = tmp_path / "proc"
    proc.mkdir()
    _write_proc_stat(proc, total_jiffies=10000)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"foo\x00",
        stat=_build_pid_stat(pid=100, comm="foo", utime=100),
        status=_build_status(name="foo"),
    )
    _write_pid_dir(
        proc,
        101,
        cmdline=b"bar\x00",
        stat=_build_pid_stat(pid=101, comm="bar", utime=100),
        status=_build_status(name="bar"),
    )
    sampler = processes.ProcessSampler(proc_root=str(proc))
    sampler.sample()  # baseline
    # PID 100 racks up much more cpu than PID 101 over the next tick.
    _write_proc_stat(proc, total_jiffies=11000)
    _write_pid_dir(
        proc,
        100,
        cmdline=b"foo\x00",
        stat=_build_pid_stat(pid=100, comm="foo", utime=300),
        status=_build_status(name="foo"),
    )
    _write_pid_dir(
        proc,
        101,
        cmdline=b"bar\x00",
        stat=_build_pid_stat(pid=101, comm="bar", utime=110),
        status=_build_status(name="bar"),
    )
    rows = sampler.sample()["processes"]
    assert [r["pid"] for r in rows] == [100, 101]


def test_uid_cache_returns_same_string_on_repeat_resolve(tmp_path: Path) -> None:
    """Mode-A N2 fold: lazy cache populated on first hit; subsequent
    calls don't re-syscall."""
    processes._reset_uid_cache_for_tests()
    name1 = processes._resolve_username(0)
    name2 = processes._resolve_username(0)
    assert name1 == name2 == "root"
    assert 0 in processes._uid_cache
