"""GODO Phase 1 LiDAR prototype package.

Public surface kept deliberately small. See the module docstrings for the
full API — `frame`, `capture`, `io`, `analyze`.
"""

from __future__ import annotations

from godo_lidar.frame import Frame, Sample

__all__ = ["Frame", "Sample"]
__version__ = "0.1.0"
