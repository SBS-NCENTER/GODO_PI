"""
In-process ring buffer for operator-visible activity events.

Bounded at ``ACTIVITY_BUFFER_SIZE``; older entries fall off silently.
Process restart wipes the buffer (documented in CODEBASE.md invariant —
in-memory only for P0; durable persistence is P2 if it ever matters).

Thread-safety: ``deque.append`` and iteration are GIL-protected for
CPython, which is sufficient for our 1-3 concurrent FastAPI handlers.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Final

from .constants import ACTIVITY_BUFFER_SIZE


@dataclass(frozen=True)
class ActivityEntry:
    ts: float  # unix seconds, time.time()
    type: str  # short token, e.g. "calibrate", "live_on", "login"
    detail: str  # short free-form, e.g. username or err code

    def to_dict(self) -> dict[str, object]:
        return {"ts": self.ts, "type": self.type, "detail": self.detail}


_MIN_TAIL: Final[int] = 1


class ActivityLog:
    def __init__(self, *, capacity: int = ACTIVITY_BUFFER_SIZE) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._buf: deque[ActivityEntry] = deque(maxlen=capacity)
        self._capacity = capacity

    @property
    def capacity(self) -> int:
        return self._capacity

    def append(self, type_: str, detail: str = "") -> None:
        self._buf.append(ActivityEntry(ts=time.time(), type=type_, detail=detail))

    def tail(self, n: int) -> list[dict[str, object]]:
        """Return the last ``n`` entries newest-first. ``n`` is clamped to
        ``[1, capacity]``."""
        n = max(_MIN_TAIL, min(n, self._capacity))
        # `deque` does not slice; convert and take from the right edge.
        items = list(self._buf)[-n:]
        items.reverse()
        return [e.to_dict() for e in items]

    def __len__(self) -> int:  # used by tests for bound assertion
        return len(self._buf)
