"""SDK-wrapper backend using the third-party :mod:`pyrplidar` library.

Honesty caveat (RPLIDAR_C1.md §4): pyrplidar is an **unofficial** Python
port of the SLAMTEC protocol and does not list the C1 as officially
supported. It works in practice because the standard-mode wire protocol is
identical across A1 / C1 / S-series at the byte level, but we treat this
backend as a **baseline, not a certified reference**.

Motor speed constraint: this backend lets the firmware spin the motor at
its default speed. The C1 motor is driven by command `0xA8`
(`MOTOR_SPEED_CTRL`, u16 little-endian RPM — SLAMTEC protocol v2.8 Figure
4-31, p.32), which pyrplidar does not expose. `pyrplidar.set_motor_pwm`
emits the A1-style PWM command `0xF0`, which the C1 silently ignores. For
motor-speed-controlled captures, use the raw backend.

A three-way comparison — SDK wrapper vs. raw parser vs. the official C++
`rplidar_sdk` `ultra_simple` CLI — is scheduled as a Phase 1 follow-up task
once the C++ toolchain is set up on RPi 5 / Windows.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from types import TracebackType
from typing import Any, Final

from pyrplidar import PyRPlidar  # type: ignore[import-untyped]

from godo_lidar.frame import Frame, Sample

_LOG = logging.getLogger(__name__)

DEFAULT_BAUD: Final[int] = 460_800


class SdkBackend:
    """SDK-wrapper backend.

    Public shape matches :class:`godo_lidar.capture.raw.RawBackend`
    (duck typing — no shared ABC, see the original design brief for why).

    Motor speed is left at the firmware default; see the module docstring.
    """

    def __init__(
        self,
        port: str,
        *,
        baud: int = DEFAULT_BAUD,
    ) -> None:
        self._port = port
        self._baud = baud
        self._lidar: PyRPlidar | None = None

    def __enter__(self) -> SdkBackend:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def open(self) -> None:
        if self._lidar is not None:
            return
        _LOG.info(
            "sdk backend: opening %s @ %d bps (motor: firmware default)",
            self._port,
            self._baud,
        )
        lidar = PyRPlidar()
        # pyrplidar's connect() swallows serial exceptions with a stdout print
        # and leaves lidar_serial._serial as None; the failure only surfaces
        # as an AttributeError deep inside start_scan(). Detect it up front.
        lidar.connect(port=self._port, baudrate=self._baud, timeout=3.0)
        if getattr(lidar.lidar_serial, "_serial", None) is None:
            raise ConnectionError(
                f"failed to open serial port {self._port!r} @ {self._baud} bps. "
                "verify the port exists ('Get-WmiObject Win32_SerialPort' in "
                "PowerShell), the CP2102 driver is installed, and no other "
                "process (RoboStudio, serial monitor, Arduino IDE) holds it."
            )
        self._lidar = lidar

    def close(self) -> None:
        lidar = self._lidar
        if lidar is None:
            return
        try:
            lidar.stop()
        except Exception as e:  # pyrplidar raises bare Exception
            _LOG.warning("sdk backend: error during shutdown: %s", e)
        finally:
            lidar.disconnect()
            self._lidar = None

    def scan_frames(self, frames: int) -> Iterator[Frame]:
        if frames < 1:
            raise ValueError(f"frames must be >= 1; got {frames!r}")
        lidar = self._lidar
        if lidar is None:
            raise RuntimeError("SdkBackend.open() must be called first")

        scan_generator = lidar.start_scan()
        try:
            stream: Iterator[Any] = scan_generator()
            current: Frame | None = None
            emitted = 0
            for measurement in stream:
                # pyrplidar yields objects with .start_flag, .quality,
                # .angle, .distance; timestamps are ours to capture.
                t_ns = time.monotonic_ns()
                start_flag = bool(measurement.start_flag)
                angle_deg = float(measurement.angle) % 360.0
                distance_mm = float(measurement.distance)
                quality = int(measurement.quality) & 0xFF
                flag = 1 if start_flag else 0
                try:
                    sample = Sample(
                        angle_deg=angle_deg,
                        distance_mm=distance_mm,
                        quality=quality,
                        flag=flag,
                        timestamp_ns=t_ns,
                    )
                except ValueError as e:
                    _LOG.warning(
                        "sdk backend: dropping sample failing validation: %s",
                        e,
                    )
                    continue

                if start_flag:
                    if current is not None and current.samples:
                        yield current
                        emitted += 1
                        if emitted >= frames:
                            return
                    current = Frame(index=emitted, samples=[sample])
                else:
                    if current is None:
                        continue
                    current.samples.append(sample)
        finally:
            try:
                lidar.stop()
            except Exception as e:  # noqa: BLE001 — library contract
                _LOG.warning("sdk backend: error stopping scan: %s", e)


__all__ = ["SdkBackend", "Sample", "Frame"]
