"""Capture backends. Two sibling implementations, same public shape.

- :class:`SdkBackend` — pyrplidar wrapper (fast baseline).
- :class:`RawBackend` — pyserial + in-house parser (byte-level research).

Convenience re-exports: ``from godo_lidar.capture import RawBackend`` works.
Importing this package eagerly triggers ``import serial`` (pyserial) and
``import pyrplidar``; callers that must avoid those dependencies (e.g.
analysis-only code paths, or parser unit tests) should import
:mod:`godo_lidar.capture.raw_parser` directly instead of this package.
"""

from __future__ import annotations

from godo_lidar.capture.raw import RawBackend
from godo_lidar.capture.sdk import SdkBackend

__all__ = ["RawBackend", "SdkBackend"]
