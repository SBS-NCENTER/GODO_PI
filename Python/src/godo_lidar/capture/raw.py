"""Non-SDK backend: raw pyserial + in-house parser.

Purpose: directly observe what the SDK-wrapper paths hide — framing errors,
quality-field handling, motor-spin-up transients. See
`SYSTEM_DESIGN.md §10.1` and `RPLIDAR/RPLIDAR_C1.md §5` for why both
backends exist.

Startup sequence (per SLAMTEC protocol v2.8):

    1. Send STOP (0xA5 0x25); wait ≥ 10 ms           (PDF p.13)
    2. Send MOTOR_SPEED_CTRL with target RPM         (PDF p.32, Figure 4-31)
       C1 has no MOTOCTL PWM pin — motor is command-driven only
       (RPLIDAR_C1.md §6).
    3. Wait ≈ 500 ms for motor speed to stabilize    (RPLIDAR_C1.md §5,
       cause 6: motor-not-yet-in-sync → angle drift).
    4. Send SCAN (0xA5 0x20); read 7-byte response
       descriptor 0xA5 0x5A 0x05 0x00 0x00 0x40 0x81 (PDF p.15).
    5. Stream 5-byte samples until STOP.

Shutdown: STOP, then MOTOR_SPEED_CTRL rpm=0 to park the motor, then close.

C1 typical motor RPM: 10 Hz scan rate × 60 = 600 rpm. The MOTOR_SPEED_CTRL
default used here matches that.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from types import TracebackType
from typing import Final

import serial  # type: ignore[import-untyped]

from godo_lidar.capture.raw_parser import (
    DESCRIPTOR_SIZE,
    SAMPLE_SIZE,
    SCAN_REQUEST,
    SCAN_RESPONSE_DESCRIPTOR,
    STOP_REQUEST,
    build_motor_speed_request,
    decode_samples,
)
from godo_lidar.frame import Frame, Sample

_LOG = logging.getLogger(__name__)

DEFAULT_BAUD: Final[int] = 460_800  # RPLIDAR_C1.md §3
DEFAULT_RPM: Final[int] = 600  # 10 Hz typical scan rate
MOTOR_SETTLE_S: Final[float] = 0.5  # RPLIDAR_C1.md §5 cause 6
STOP_SETTLE_S: Final[float] = 0.02  # PDF p.13: ≥ 10 ms, use 20 ms for margin
DESCRIPTOR_TIMEOUT_S: Final[float] = 2.0
READ_CHUNK_BYTES: Final[int] = 1024


class RawBackend:
    """Non-SDK backend using pyserial + the in-house parser."""

    def __init__(
        self,
        port: str,
        *,
        baud: int = DEFAULT_BAUD,
        rpm: int = DEFAULT_RPM,
    ) -> None:
        self._port = port
        self._baud = baud
        self._rpm = rpm
        self._serial: serial.Serial | None = None

    def __enter__(self) -> RawBackend:
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
        if self._serial is not None:
            return
        _LOG.info(
            "raw backend: opening %s @ %d bps, target %d rpm",
            self._port,
            self._baud,
            self._rpm,
        )
        ser = serial.Serial(
            port=self._port,
            baudrate=self._baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
        )
        self._serial = ser
        # Flush any stale bytes from a previous process' scan.
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        # Reset to idle before any state-changing command.
        ser.write(STOP_REQUEST)
        time.sleep(STOP_SETTLE_S)
        ser.write(build_motor_speed_request(self._rpm))
        time.sleep(MOTOR_SETTLE_S)

    def close(self) -> None:
        ser = self._serial
        if ser is None:
            return
        try:
            ser.write(STOP_REQUEST)
            time.sleep(STOP_SETTLE_S)
            ser.write(build_motor_speed_request(0))
        except serial.SerialException as e:
            _LOG.warning("raw backend: error on shutdown write: %s", e)
        finally:
            ser.close()
            self._serial = None

    def scan_frames(self, frames: int) -> Iterator[Frame]:
        """Yield up to `frames` whole 360° frames, then stop.

        Frame boundaries are defined by the S=1 start-of-frame flag
        (PDF p.15). The first partial frame (before the first S=1) is
        discarded.
        """
        if frames < 1:
            raise ValueError(f"frames must be >= 1; got {frames!r}")
        ser = self._serial
        if ser is None:
            raise RuntimeError("RawBackend.open() must be called first")

        ser.write(SCAN_REQUEST)
        _read_descriptor(ser)

        leftover = b""
        current: Frame | None = None
        emitted = 0
        expected_s = frames / 10.0  # C1 scans at ~10 Hz (RPLIDAR_C1.md §2)
        deadline_budget_s = max(30.0, expected_s * 2.0)
        start = time.monotonic()

        while emitted < frames:
            if time.monotonic() - start > deadline_budget_s:
                _LOG.warning(
                    "raw backend: capture deadline exceeded after %d frames",
                    emitted,
                )
                break
            chunk = ser.read(READ_CHUNK_BYTES)
            if not chunk:
                continue
            t_ns = time.monotonic_ns()
            buf = leftover + chunk
            samples, leftover = decode_samples(buf, t_ns, logger=_LOG)
            for sample in samples:
                if sample.flag & 0x01:
                    # Start-of-frame bit: emit the previous frame (if any)
                    # and begin a new one.
                    if current is not None and current.samples:
                        yield current
                        emitted += 1
                        if emitted >= frames:
                            break
                    current = Frame(index=emitted, samples=[sample])
                else:
                    if current is None:
                        # Pre-first-S samples — discard per docstring.
                        continue
                    current.samples.append(sample)

        # Intentionally do NOT emit the in-progress `current` frame:
        # a truncated frame would confuse per-direction statistics.


def _read_descriptor(ser: serial.Serial) -> None:
    deadline = time.monotonic() + DESCRIPTOR_TIMEOUT_S
    buf = b""
    while len(buf) < DESCRIPTOR_SIZE:
        if time.monotonic() > deadline:
            raise TimeoutError(
                "raw backend: timed out waiting for SCAN response descriptor"
            )
        chunk = ser.read(DESCRIPTOR_SIZE - len(buf))
        if chunk:
            buf += chunk
    if buf != SCAN_RESPONSE_DESCRIPTOR:
        raise RuntimeError(
            f"raw backend: unexpected SCAN response descriptor {buf.hex()}; "
            f"expected {SCAN_RESPONSE_DESCRIPTOR.hex()}"
        )


__all__ = ["RawBackend", "Sample", "Frame"]
