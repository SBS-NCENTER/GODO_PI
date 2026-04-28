"""PR-DIAG — resources.snapshot() unit tests.

All tests reset the module-level cache before running; the cache test
cases drive its TTL behavior directly via mocked monotonic_ns.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from godo_webctl import resources


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    resources._reset_cache_for_tests()


def _write_meminfo(tmp_path: Path, total_kib: int, avail_kib: int) -> Path:
    p = tmp_path / "meminfo"
    p.write_text(
        f"MemTotal:       {total_kib} kB\n"
        f"MemFree:        100000 kB\n"
        f"MemAvailable:   {avail_kib} kB\n"
        "Cached:         500000 kB\n",
    )
    return p


def _write_thermal(tmp_path: Path, milli_c: int) -> Path:
    p = tmp_path / "temp"
    p.write_text(f"{milli_c}\n")
    return p


def test_snapshot_happy_returns_all_fields(tmp_path: Path) -> None:
    thermal = _write_thermal(tmp_path, 52300)
    meminfo = _write_meminfo(tmp_path, 8 * 1024 * 1024, 6 * 1024 * 1024)
    snap = resources.snapshot(
        disk_check_path=tmp_path,
        thermal_path=str(thermal),
        meminfo_path=str(meminfo),
    )
    assert snap["cpu_temp_c"] == 52.3
    assert snap["mem_total_bytes"] == 8 * 1024 * 1024 * 1024
    assert snap["mem_avail_bytes"] == 6 * 1024 * 1024 * 1024
    # used_pct = (total - avail) / total × 100 → 25.00
    assert snap["mem_used_pct"] == 25.0
    assert snap["disk_total_bytes"] is not None
    assert snap["disk_used_pct"] is not None
    assert snap["published_mono_ns"] > 0


def test_thermal_missing_returns_none_temp(tmp_path: Path) -> None:
    meminfo = _write_meminfo(tmp_path, 1024, 512)
    snap = resources.snapshot(
        disk_check_path=tmp_path,
        thermal_path=str(tmp_path / "no-such-thermal"),
        meminfo_path=str(meminfo),
    )
    assert snap["cpu_temp_c"] is None
    assert snap["mem_total_bytes"] == 1024 * 1024
    assert snap["mem_avail_bytes"] == 512 * 1024


def test_meminfo_missing_returns_none_mem(tmp_path: Path) -> None:
    thermal = _write_thermal(tmp_path, 30000)
    snap = resources.snapshot(
        disk_check_path=tmp_path,
        thermal_path=str(thermal),
        meminfo_path=str(tmp_path / "no-meminfo"),
    )
    assert snap["mem_total_bytes"] is None
    assert snap["mem_avail_bytes"] is None
    assert snap["mem_used_pct"] is None
    assert snap["cpu_temp_c"] == 30.0


def test_disk_path_missing_returns_none_disk(tmp_path: Path) -> None:
    thermal = _write_thermal(tmp_path, 40000)
    meminfo = _write_meminfo(tmp_path, 1024, 512)
    snap = resources.snapshot(
        disk_check_path=tmp_path / "absolutely-no-such-dir",
        thermal_path=str(thermal),
        meminfo_path=str(meminfo),
    )
    assert snap["disk_total_bytes"] is None
    assert snap["disk_avail_bytes"] is None
    assert snap["disk_used_pct"] is None
    # Other fields still populated.
    assert snap["cpu_temp_c"] == 40.0


def test_all_sources_failing_returns_all_nones(tmp_path: Path) -> None:
    snap = resources.snapshot(
        disk_check_path=tmp_path / "ghost",
        thermal_path=str(tmp_path / "ghost-temp"),
        meminfo_path=str(tmp_path / "ghost-meminfo"),
    )
    assert snap["cpu_temp_c"] is None
    assert snap["mem_total_bytes"] is None
    assert snap["mem_avail_bytes"] is None
    assert snap["mem_used_pct"] is None
    assert snap["disk_total_bytes"] is None
    assert snap["disk_used_pct"] is None
    # published_mono_ns is always populated — webctl monotonic clock.
    assert snap["published_mono_ns"] > 0


def test_cache_hit_within_ttl(tmp_path: Path) -> None:
    """Two calls within the TTL window produce the same dict object
    (cache hit). Verified by mocking time.monotonic_ns to advance by
    less than the TTL between calls."""
    thermal = _write_thermal(tmp_path, 30000)
    meminfo = _write_meminfo(tmp_path, 1024, 512)
    times = iter([0, 0, 100_000_000])  # build call, cache-key call, hit call
    with mock.patch("godo_webctl.resources.time.monotonic_ns", side_effect=lambda: next(times)):
        first = resources.snapshot(
            disk_check_path=tmp_path,
            thermal_path=str(thermal),
            meminfo_path=str(meminfo),
        )
        second = resources.snapshot(
            disk_check_path=tmp_path,
            thermal_path=str(thermal),
            meminfo_path=str(meminfo),
        )
    assert first is second  # same dict object → cache hit


def test_cache_miss_after_ttl(tmp_path: Path) -> None:
    """Calls separated by more than the TTL produce distinct snapshots."""
    thermal = _write_thermal(tmp_path, 30000)
    meminfo = _write_meminfo(tmp_path, 1024, 512)
    # TTL is 1 s = 1e9 ns. Advance by 2 s between calls.
    times = iter([0, 0, 2_000_000_000, 2_000_000_000])
    with mock.patch("godo_webctl.resources.time.monotonic_ns", side_effect=lambda: next(times)):
        first = resources.snapshot(
            disk_check_path=tmp_path,
            thermal_path=str(thermal),
            meminfo_path=str(meminfo),
        )
        second = resources.snapshot(
            disk_check_path=tmp_path,
            thermal_path=str(thermal),
            meminfo_path=str(meminfo),
        )
    assert first is not second


def test_dict_shape_contains_all_fields(tmp_path: Path) -> None:
    """Pin: every RESOURCES_FIELDS key is present in the dict regardless
    of source-availability state."""
    from godo_webctl.protocol import RESOURCES_FIELDS

    snap = resources.snapshot(
        disk_check_path=tmp_path / "ghost",
        thermal_path=str(tmp_path / "ghost"),
        meminfo_path=str(tmp_path / "ghost"),
    )
    for field in RESOURCES_FIELDS:
        assert field in snap, f"RESOURCES_FIELDS missing key: {field}"
