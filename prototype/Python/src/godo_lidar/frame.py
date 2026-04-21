"""Frame and Sample dataclasses shared between capture backends.

Both the SDK-wrapper backend (`capture.sdk`) and the Non-SDK backend
(`capture.raw`) must emit `Sample` / `Frame` instances of this shape so every
downstream stage (CSV writer, analyzer) stays backend-agnostic.

Angle invariant:
    Callers are responsible for modulo-wrapping raw angles into [0, 360)
    before constructing a Sample. Sample rejects 360.0 exactly — that value
    must be wrapped to 0.0 upstream. Rationale: the RPLIDAR protocol emits
    `angle_q6 / 64.0` which can be ≥ 360 for a few q6 ticks near frame end;
    letting 360 through would break histogram binning and per-direction
    variance grouping.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Sample:
    """One LiDAR ranging sample.

    Fields mirror SLAMTEC protocol v2.8 §4 standard-mode response,
    post-decoded to physical units.
    """

    angle_deg: float
    distance_mm: float
    quality: int
    flag: int  # bit 0 = start-of-frame (S); further bits reserved
    timestamp_ns: int

    def __post_init__(self) -> None:
        if not (0.0 <= self.angle_deg < 360.0):
            raise ValueError(
                f"angle_deg must be in [0, 360); got {self.angle_deg!r}"
            )
        if self.distance_mm < 0.0:
            raise ValueError(
                f"distance_mm must be >= 0; got {self.distance_mm!r}"
            )
        if not (0 <= self.quality <= 255):
            raise ValueError(
                f"quality must be in [0, 255]; got {self.quality!r}"
            )
        if not (0 <= self.flag <= 0xFF):
            raise ValueError(f"flag must fit in a byte; got {self.flag!r}")
        if self.timestamp_ns < 0:
            raise ValueError(
                f"timestamp_ns must be >= 0; got {self.timestamp_ns!r}"
            )


@dataclass(slots=True)
class Frame:
    """One full 360° rotation worth of samples.

    `index` is assigned by the capture layer (monotonic from 0).
    The first sample's `flag & 1` is expected to be 1 (start-of-frame bit S).
    """

    index: int
    samples: list[Sample] = field(default_factory=list)
