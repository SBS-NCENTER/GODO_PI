"""Tests for `godo_lidar.frame.Sample` / `Frame`."""

from __future__ import annotations

import pytest

from godo_lidar.frame import Frame, Sample


def test_sample_accepts_valid_values() -> None:
    s = Sample(
        angle_deg=0.0,
        distance_mm=1000.0,
        quality=128,
        flag=1,
        timestamp_ns=123456789,
    )
    assert s.angle_deg == 0.0
    assert s.distance_mm == 1000.0
    assert s.quality == 128
    assert s.flag == 1
    assert s.timestamp_ns == 123456789


def test_sample_rejects_angle_at_360() -> None:
    # Boundary: 360 must be wrapped to 0 by the caller (see frame.py docstring).
    with pytest.raises(ValueError, match="angle_deg"):
        Sample(
            angle_deg=360.0,
            distance_mm=1000.0,
            quality=0,
            flag=0,
            timestamp_ns=0,
        )


@pytest.mark.parametrize(
    "bad_angle",
    [-0.001, -1.0, 360.5, 1000.0, float("nan")],
)
def test_sample_rejects_out_of_range_angle(bad_angle: float) -> None:
    with pytest.raises(ValueError, match="angle_deg"):
        Sample(
            angle_deg=bad_angle,
            distance_mm=1000.0,
            quality=0,
            flag=0,
            timestamp_ns=0,
        )


@pytest.mark.parametrize(
    ("field", "value", "msg"),
    [
        ("distance_mm", -0.1, "distance_mm"),
        ("quality", -1, "quality"),
        ("quality", 256, "quality"),
        ("flag", -1, "flag"),
        ("flag", 256, "flag"),
        ("timestamp_ns", -1, "timestamp_ns"),
    ],
)
def test_sample_rejects_out_of_range_other_fields(
    field: str, value: float | int, msg: str
) -> None:
    kwargs: dict[str, float | int] = {
        "angle_deg": 0.0,
        "distance_mm": 1000.0,
        "quality": 128,
        "flag": 0,
        "timestamp_ns": 0,
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=msg):
        Sample(**kwargs)  # type: ignore[arg-type]


def test_frame_default_samples_is_empty_list_and_independent() -> None:
    # Dataclass default_factory regression guard: each Frame must own its list.
    f1 = Frame(index=0)
    f2 = Frame(index=1)
    assert f1.samples == []
    assert f2.samples == []
    f1.samples.append(
        Sample(
            angle_deg=10.0,
            distance_mm=1.0,
            quality=0,
            flag=1,
            timestamp_ns=0,
        )
    )
    assert f2.samples == []
