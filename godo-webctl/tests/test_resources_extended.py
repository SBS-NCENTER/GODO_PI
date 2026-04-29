"""
PR-B (Track B-SYSTEM PR-B) — `resources_extended` sampler tests.

Bias-blocking: parser tests use FIXTURE TEXT and algebraic edge cases.
"""

from __future__ import annotations

from pathlib import Path

from godo_webctl import resources_extended

# --- per-core jiffy parser ------------------------------------------------


def test_read_cpu_per_core_jiffies_happy(tmp_path: Path) -> None:
    stat = tmp_path / "stat"
    stat.write_text(
        "cpu  1000 100 500 800 50 0 0 0 0 0\n"
        "cpu0 250 25 125 200 12 0 0 0 0 0\n"
        "cpu1 250 25 125 200 12 0 0 0 0 0\n"
        "cpu2 250 25 125 200 13 0 0 0 0 0\n"
        "cpu3 250 25 125 200 13 0 0 0 0 0\n"
        "intr 1\nbtime 0\n",
        encoding="utf-8",
    )
    cores = resources_extended._read_cpu_per_core_jiffies(str(stat))
    assert [c.idx for c in cores] == [0, 1, 2, 3]
    # cpu0 columns sum to 612; idle column index 3 → 200.
    assert cores[0].total == 612
    assert cores[0].idle == 200


def test_read_cpu_per_core_jiffies_missing_file(tmp_path: Path) -> None:
    assert resources_extended._read_cpu_per_core_jiffies(str(tmp_path / "nope")) == []


def test_read_cpu_per_core_jiffies_no_per_core_lines(tmp_path: Path) -> None:
    """Aggregate-only `/proc/stat` (rare but possible on a stripped-down
    container) yields an empty list, not a crash."""
    stat = tmp_path / "stat"
    stat.write_text("cpu 1000 100 500 800 50 0 0 0 0 0\nintr 1\n", encoding="utf-8")
    assert resources_extended._read_cpu_per_core_jiffies(str(stat)) == []


# --- per-core delta math --------------------------------------------------


def test_per_core_pct_from_deltas_first_tick_returns_zero() -> None:
    """No prior tick → empty `prev` list → 0.0 for every core."""
    cur = [resources_extended.CoreJiffies(idx=0, total=1000, idle=500)]
    assert resources_extended.per_core_pct_from_deltas([], cur) == [0.0]


def test_per_core_pct_from_deltas_50_percent() -> None:
    prev = [resources_extended.CoreJiffies(idx=0, total=0, idle=0)]
    cur = [resources_extended.CoreJiffies(idx=0, total=1000, idle=500)]
    # 100 * (1 - 500/1000) = 50.0
    assert resources_extended.per_core_pct_from_deltas(prev, cur) == [50.0]


def test_per_core_pct_from_deltas_full_busy_100_percent() -> None:
    prev = [resources_extended.CoreJiffies(idx=0, total=0, idle=0)]
    cur = [resources_extended.CoreJiffies(idx=0, total=1000, idle=0)]
    assert resources_extended.per_core_pct_from_deltas(prev, cur) == [100.0]


def test_per_core_pct_from_deltas_zero_total_delta() -> None:
    """No elapsed time → 0.0, not NaN."""
    prev = [resources_extended.CoreJiffies(idx=0, total=1000, idle=500)]
    cur = [resources_extended.CoreJiffies(idx=0, total=1000, idle=500)]
    assert resources_extended.per_core_pct_from_deltas(prev, cur) == [0.0]


def test_per_core_pct_from_deltas_negative_idle_delta() -> None:
    """Counter wrap → idle_delta floored at 0; pct stays in range."""
    prev = [resources_extended.CoreJiffies(idx=0, total=0, idle=200)]
    cur = [resources_extended.CoreJiffies(idx=0, total=1000, idle=100)]
    pct = resources_extended.per_core_pct_from_deltas(prev, cur)
    assert pct == [100.0]


def test_per_core_pct_from_deltas_handles_hot_plug() -> None:
    """A core present in `cur` but not `prev` (rare on RPi 5 — frequency
    scaling can park cores) gets 0.0 for that tick."""
    prev = [resources_extended.CoreJiffies(idx=0, total=0, idle=0)]
    cur = [
        resources_extended.CoreJiffies(idx=0, total=1000, idle=500),
        resources_extended.CoreJiffies(idx=1, total=1000, idle=0),
    ]
    pcts = resources_extended.per_core_pct_from_deltas(prev, cur)
    assert pcts == [50.0, 0.0]


# --- meminfo --------------------------------------------------------------


def test_read_meminfo_total_avail_happy(tmp_path: Path) -> None:
    p = tmp_path / "meminfo"
    p.write_text(
        "MemTotal:        8000000 kB\n"
        "MemFree:         2000000 kB\n"
        "MemAvailable:    6000000 kB\n"
        "Buffers:          200000 kB\n",
        encoding="utf-8",
    )
    total, avail = resources_extended._read_meminfo_total_avail(str(p))
    assert total == 8_000_000 * 1024
    assert avail == 6_000_000 * 1024


def test_read_meminfo_total_avail_missing_file(tmp_path: Path) -> None:
    total, avail = resources_extended._read_meminfo_total_avail(str(tmp_path / "nope"))
    assert total is None
    assert avail is None


def test_read_meminfo_total_avail_missing_avail_line(tmp_path: Path) -> None:
    """A kernel old enough to lack `MemAvailable:` still yields total
    populated and avail None — partial-success path."""
    p = tmp_path / "meminfo"
    p.write_text("MemTotal:        8000000 kB\nMemFree:         2000000 kB\n", encoding="utf-8")
    total, avail = resources_extended._read_meminfo_total_avail(str(p))
    assert total == 8_000_000 * 1024
    assert avail is None


# --- disk pct -------------------------------------------------------------


def test_read_disk_pct_returns_value_for_valid_path(tmp_path: Path) -> None:
    pct = resources_extended._read_disk_pct(str(tmp_path))
    assert pct is not None
    assert 0.0 <= pct <= 100.0


def test_read_disk_pct_returns_none_for_missing_path(tmp_path: Path) -> None:
    assert resources_extended._read_disk_pct(str(tmp_path / "nope")) is None


# --- ResourcesExtendedSampler ---------------------------------------------


def test_sampler_first_tick_yields_zero_per_core_pct(tmp_path: Path) -> None:
    """First tick has no prior counters → every per-core pct = 0.0."""
    stat = tmp_path / "stat"
    stat.write_text(
        "cpu  1000 100 500 800 50 0 0 0 0 0\n"
        "cpu0 250 25 125 200 12 0 0 0 0 0\n"
        "cpu1 250 25 125 200 13 0 0 0 0 0\n",
        encoding="utf-8",
    )
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1024 kB\nMemAvailable: 512 kB\n", encoding="utf-8")
    sampler = resources_extended.ResourcesExtendedSampler(
        proc_stat_path=str(stat),
        meminfo_path=str(meminfo),
        disk_check_path=str(tmp_path),
    )
    snap = sampler.sample()
    assert snap["cpu_per_core"] == [0.0, 0.0]
    assert snap["cpu_aggregate_pct"] == 0.0
    assert snap["mem_total_mb"] is not None
    assert snap["mem_used_mb"] is not None
    assert snap["disk_pct"] is not None


def test_sampler_subsequent_tick_computes_pct(tmp_path: Path) -> None:
    """Two-tick pump: tick 1 baseline (zero), tick 2 sees per-core
    total=1000 with idle=500 → 100*(1-500/1000) = 50.0 each.

    Layout chosen so the 10 columns sum to exactly 1000 with column 4
    (idle) = 500: 100 0 0 500 100 100 50 50 100 0  → sum 1000.
    """
    stat = tmp_path / "stat"
    stat.write_text(
        "cpu  0 0 0 0 0 0 0 0 0 0\ncpu0 0 0 0 0 0 0 0 0 0 0\ncpu1 0 0 0 0 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1024 kB\nMemAvailable: 512 kB\n", encoding="utf-8")
    sampler = resources_extended.ResourcesExtendedSampler(
        proc_stat_path=str(stat),
        meminfo_path=str(meminfo),
        disk_check_path=str(tmp_path),
    )
    sampler.sample()  # baseline — establishes prev = zero counters
    stat.write_text(
        "cpu  200 0 0 1000 200 200 100 100 200 0\n"
        "cpu0 100 0 0 500 100 100 50 50 100 0\n"
        "cpu1 100 0 0 500 100 100 50 50 100 0\n",
        encoding="utf-8",
    )
    snap = sampler.sample()
    assert snap["cpu_per_core"] == [50.0, 50.0]
    assert snap["cpu_aggregate_pct"] == 50.0


def test_sampler_published_mono_ns_present_and_monotonic(tmp_path: Path) -> None:
    """Mode-A M6: clock-domain note — `published_mono_ns` is
    `time.monotonic_ns()` (Python). Pinned smoke."""
    stat = tmp_path / "stat"
    stat.write_text("cpu0 0 0 0 0 0 0 0 0 0 0\n", encoding="utf-8")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1024 kB\nMemAvailable: 512 kB\n", encoding="utf-8")
    sampler = resources_extended.ResourcesExtendedSampler(
        proc_stat_path=str(stat),
        meminfo_path=str(meminfo),
        disk_check_path=str(tmp_path),
    )
    s1 = sampler.sample()
    s2 = sampler.sample()
    assert isinstance(s1["published_mono_ns"], int)
    assert s2["published_mono_ns"] >= s1["published_mono_ns"]


def test_sampler_partial_failure_meminfo_missing_yields_none(tmp_path: Path) -> None:
    """Per-source resilience — a missing `/proc/meminfo` yields
    mem_total/used = None but the rest of the snapshot is still
    populated. SPA renders `null` as `—`."""
    stat = tmp_path / "stat"
    stat.write_text("cpu0 0 0 0 0 0 0 0 0 0 0\n", encoding="utf-8")
    sampler = resources_extended.ResourcesExtendedSampler(
        proc_stat_path=str(stat),
        meminfo_path=str(tmp_path / "missing_meminfo"),
        disk_check_path=str(tmp_path),
    )
    snap = sampler.sample()
    assert snap["mem_total_mb"] is None
    assert snap["mem_used_mb"] is None
    assert snap["disk_pct"] is not None
    assert snap["cpu_per_core"] == [0.0]


def test_sampler_partial_failure_disk_path_missing_yields_none(
    tmp_path: Path,
) -> None:
    stat = tmp_path / "stat"
    stat.write_text("cpu0 0 0 0 0 0 0 0 0 0 0\n", encoding="utf-8")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1024 kB\nMemAvailable: 512 kB\n", encoding="utf-8")
    sampler = resources_extended.ResourcesExtendedSampler(
        proc_stat_path=str(stat),
        meminfo_path=str(meminfo),
        disk_check_path=str(tmp_path / "no_such_dir"),
    )
    snap = sampler.sample()
    assert snap["disk_pct"] is None
    assert snap["mem_total_mb"] is not None


def test_sampler_aggregate_pct_average_of_per_core(tmp_path: Path) -> None:
    """Aggregate is the simple mean across cores — not a re-derivation
    from `/proc/stat`'s aggregate line. Two cores at 50/100 → 75.

    cpu0 layout: total=1000, idle=500   → 50% busy.
    cpu1 layout: total=1000, idle=0     → 100% busy.
    """
    stat = tmp_path / "stat"
    stat.write_text(
        "cpu  0 0 0 0 0 0 0 0 0 0\ncpu0 0 0 0 0 0 0 0 0 0 0\ncpu1 0 0 0 0 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1024 kB\nMemAvailable: 512 kB\n", encoding="utf-8")
    sampler = resources_extended.ResourcesExtendedSampler(
        proc_stat_path=str(stat),
        meminfo_path=str(meminfo),
        disk_check_path=str(tmp_path),
    )
    sampler.sample()
    stat.write_text(
        "cpu  300 0 0 500 300 300 100 100 300 100\n"
        # cpu0: 100+0+0+500+100+100+50+50+100+0 = 1000, idle=500 → 50%.
        "cpu0 100 0 0 500 100 100 50 50 100 0\n"
        # cpu1: 200+0+0+0+200+200+50+50+200+100 = 1000, idle=0 → 100%.
        "cpu1 200 0 0 0 200 200 50 50 200 100\n",
        encoding="utf-8",
    )
    snap = sampler.sample()
    assert snap["cpu_per_core"] == [50.0, 100.0]
    assert snap["cpu_aggregate_pct"] == 75.0
