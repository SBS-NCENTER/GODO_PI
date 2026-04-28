"""ActivityLog ring buffer."""

from __future__ import annotations

import threading

from godo_webctl.activity import ActivityLog
from godo_webctl.constants import ACTIVITY_BUFFER_SIZE


def test_append_then_tail_returns_newest_first() -> None:
    log = ActivityLog()
    log.append("login", "alice")
    log.append("calibrate", "alice")
    log.append("live_on", "alice")
    items = log.tail(3)
    assert [it["type"] for it in items] == ["live_on", "calibrate", "login"]


def test_tail_clamps_to_capacity() -> None:
    log = ActivityLog()
    log.append("a", "")
    log.append("b", "")
    items = log.tail(50_000)  # absurdly large request
    assert len(items) == 2


def test_tail_minimum_clamp() -> None:
    log = ActivityLog()
    log.append("a", "")
    items = log.tail(0)
    # n=0 clamps to 1 (the minimum); the value here is the *behaviour*,
    # not a magic number — pinned by `_MIN_TAIL` inside the module.
    assert len(items) == 1


def test_buffer_bounded_at_capacity() -> None:
    log = ActivityLog()
    for i in range(ACTIVITY_BUFFER_SIZE + 25):
        log.append("x", str(i))
    assert len(log) == ACTIVITY_BUFFER_SIZE
    items = log.tail(ACTIVITY_BUFFER_SIZE)
    # Newest item's detail should be `ACTIVITY_BUFFER_SIZE + 24` (last
    # appended), oldest retained should be detail "25".
    assert items[0]["detail"] == str(ACTIVITY_BUFFER_SIZE + 25 - 1)
    assert items[-1]["detail"] == "25"


def test_concurrent_appends_safe() -> None:
    """deque.append is GIL-protected for CPython. We assert no entries
    are lost (capacity-permitting) under concurrent producers."""
    log = ActivityLog(capacity=10_000)
    n_threads = 8
    per_thread = 500

    def producer() -> None:
        for i in range(per_thread):
            log.append("t", str(i))

    threads = [threading.Thread(target=producer) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(log) == n_threads * per_thread


def test_capacity_must_be_positive() -> None:
    import pytest

    with pytest.raises(ValueError):
        ActivityLog(capacity=0)
