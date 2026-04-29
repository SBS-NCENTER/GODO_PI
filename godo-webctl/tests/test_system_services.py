"""Track B-SYSTEM PR-2 — system_services.snapshot() unit tests.

All tests reset the module-level cache before running; the cache test
cases drive its TTL behavior directly via mocked monotonic_ns.
"""

from __future__ import annotations

from unittest import mock

import pytest

from godo_webctl import services, system_services
from godo_webctl.protocol import SYSTEM_SERVICES_FIELDS


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    system_services._reset_cache_for_tests()


def _show(
    name: str,
    *,
    active_state: str = "active",
    sub_state: str = "running",
    main_pid: int | None = 1234,
    active_since_unix: int | None = 1714397472,
    memory_bytes: int | None = 53477376,
    env_redacted: dict[str, str] | None = None,
    env_stale: bool = False,
) -> services.ServiceShow:
    return services.ServiceShow(
        name=name,
        active_state=active_state,
        sub_state=sub_state,
        main_pid=main_pid,
        active_since_unix=active_since_unix,
        memory_bytes=memory_bytes,
        env_redacted=env_redacted if env_redacted is not None else {},
        env_stale=env_stale,
    )


def test_snapshot_returns_pinned_fields() -> None:
    """Every entry contains exactly the SYSTEM_SERVICES_FIELDS keys, in
    that order."""
    with mock.patch(
        "godo_webctl.system_services.services.service_show",
        side_effect=lambda name: _show(name),
    ):
        snap = system_services.snapshot()
    assert isinstance(snap, list)
    assert len(snap) == 3  # godo-tracker, godo-webctl, godo-irq-pin
    for entry in snap:
        assert tuple(entry.keys()) == SYSTEM_SERVICES_FIELDS


def test_snapshot_returns_alphabetical_service_order() -> None:
    """ALLOWED_SERVICES is a frozenset; we sort for stable wire order."""
    with mock.patch(
        "godo_webctl.system_services.services.service_show",
        side_effect=lambda name: _show(name),
    ):
        snap = system_services.snapshot()
    names = [e["name"] for e in snap]
    assert names == sorted(names)
    assert names == ["godo-irq-pin", "godo-tracker", "godo-webctl"]


def test_snapshot_redacts_secret_keys() -> None:
    """The snapshot's env_redacted is the post-redaction dict — secret-
    pattern KEYS surface as `<redacted>`."""
    env = {"GODO_LOG_DIR": "/var/log/godo", "JWT_SECRET": "real-value"}

    def _show_one(name: str) -> services.ServiceShow:
        return _show(name, env_redacted=services.redact_env(env))

    with mock.patch(
        "godo_webctl.system_services.services.service_show",
        side_effect=_show_one,
    ):
        snap = system_services.snapshot()
    for entry in snap:
        assert entry["env_redacted"]["GODO_LOG_DIR"] == "/var/log/godo"
        assert entry["env_redacted"]["JWT_SECRET"] == "<redacted>"


def test_snapshot_handles_memory_not_set() -> None:
    """R3: the `MemoryCurrent=[not set]` case becomes None on the wire."""
    with mock.patch(
        "godo_webctl.system_services.services.service_show",
        side_effect=lambda name: _show(name, memory_bytes=None),
    ):
        snap = system_services.snapshot()
    for entry in snap:
        assert entry["memory_bytes"] is None


def test_snapshot_one_service_failed_returns_unknown_state() -> None:
    """M5 fold pin: when `service_show` raises for one service, that
    entry has `active_state="unknown"` and the other 2 services have
    real values. The aggregate endpoint never returns 503."""

    def _show_one(name: str) -> services.ServiceShow:
        if name == "godo-tracker":
            raise services.CommandFailed(returncode=1, stderr="boom")
        return _show(name)

    with mock.patch(
        "godo_webctl.system_services.services.service_show",
        side_effect=_show_one,
    ):
        snap = system_services.snapshot()
    by_name = {e["name"]: e for e in snap}
    assert by_name["godo-tracker"]["active_state"] == "unknown"
    assert by_name["godo-tracker"]["main_pid"] is None
    assert by_name["godo-webctl"]["active_state"] == "active"
    assert by_name["godo-irq-pin"]["active_state"] == "active"


def test_snapshot_cache_hit_within_ttl() -> None:
    """T1 fold: monkeypatch `service_show` and assert exact call_count
    after two calls within TTL. Expect 3 (one per service × 1 invocation),
    NOT 6."""
    show_mock = mock.MagicMock(side_effect=lambda name: _show(name))
    # snapshot() reads `time.monotonic_ns()` once per call.
    times = iter([0, 100_000_000])
    with (
        mock.patch("godo_webctl.system_services.services.service_show", show_mock),
        mock.patch(
            "godo_webctl.system_services.time.monotonic_ns",
            side_effect=lambda: next(times),
        ),
    ):
        first = system_services.snapshot()
        second = system_services.snapshot()
    assert show_mock.call_count == 3
    assert first is second


def test_snapshot_cache_miss_after_ttl() -> None:
    """T1 fold: advance time past TTL between calls; assert call_count == 6."""
    show_mock = mock.MagicMock(side_effect=lambda name: _show(name))
    # TTL = 1 s = 1_000_000_000 ns. Second call at 2 s > expiry (1 s).
    times = iter([0, 2_000_000_000])
    with (
        mock.patch("godo_webctl.system_services.services.service_show", show_mock),
        mock.patch(
            "godo_webctl.system_services.time.monotonic_ns",
            side_effect=lambda: next(times),
        ),
    ):
        first = system_services.snapshot()
        second = system_services.snapshot()
    assert show_mock.call_count == 6
    assert first is not second


def test_snapshot_degraded_entry_has_pinned_field_set() -> None:
    """Even the degraded entry must carry every SYSTEM_SERVICES_FIELDS
    key — drift between happy + degraded shapes would break the SPA's
    type-safe rendering."""
    with mock.patch(
        "godo_webctl.system_services.services.service_show",
        side_effect=services.CommandFailed(returncode=1, stderr="boom"),
    ):
        snap = system_services.snapshot()
    for entry in snap:
        assert tuple(entry.keys()) == SYSTEM_SERVICES_FIELDS
        assert entry["active_state"] == "unknown"
        assert entry["env_redacted"] == {}
