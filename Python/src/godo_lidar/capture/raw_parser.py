"""Pure bytes-to-Sample decoder for RPLIDAR C1 standard scan mode.

Depends only on the stdlib and :mod:`godo_lidar.frame`. No I/O, no logging
handlers — callers pass a `logging.Logger`. Split out so `test_raw_protocol`
can exercise the protocol logic without pyserial.

Authoritative source: SLAMTEC RPLIDAR S & C series Interface Protocol, v2.8
(`RPLIDAR/sources/SLAMTEC_rplidar_protocol_v2.8_en.pdf`). Section refs below
are to that document.

Standard-mode sample layout (PDF §"Start ScanSCAN Request and Response",
Figure 4-4, p.15). Each sample is 5 bytes, little-endian:

    byte 0: quality[7:2]  | !S (bit 1)  | S (bit 0)
    byte 1: angle_q6[6:0] | C  (bit 0, always 1)
    byte 2: angle_q6[14:7]
    byte 3: distance_q2[7:0]
    byte 4: distance_q2[15:8]

    angle_deg   = angle_q6   / 64.0       # Q6 fixed point, degrees
    distance_mm = distance_q2 / 4.0       # Q2 fixed point, millimeters

Invariants enforced by this module:

    * S and !S must be inverses of each other (PDF Figure 4-5).
    * C must be 1 (PDF Figure 4-5). Samples with C=0 are dropped and a
      warning is logged (the bytes are almost certainly mis-framed).
    * distance_q2 == 0 signals "measurement invalid" (PDF Figure 4-5).
      We keep such samples (distance_mm = 0.0) so the analysis stage can
      see the miss pattern.
    * angle_deg is modulo-wrapped into [0, 360) before constructing Sample,
      per `frame.py`'s Sample invariant.

Response descriptor for the standard SCAN request (PDF p.15):
    A5 5A 05 00 00 40 81
"""

from __future__ import annotations

import logging
from typing import Final

from godo_lidar.frame import Sample

SAMPLE_SIZE: Final[int] = 5

# PDF p.15 "Response Descriptor: A5 5A 05 00 00 40 81"
SCAN_RESPONSE_DESCRIPTOR: Final[bytes] = bytes(
    [0xA5, 0x5A, 0x05, 0x00, 0x00, 0x40, 0x81]
)
DESCRIPTOR_SIZE: Final[int] = len(SCAN_RESPONSE_DESCRIPTOR)


def decode_sample(
    data: bytes,
    timestamp_ns: int,
    *,
    logger: logging.Logger | None = None,
) -> Sample | None:
    """Decode exactly one 5-byte standard-mode sample.

    Returns None if the sample fails the S/!S inverse check or the C=1 check.
    A warning is logged in that case (Embedded_CheckPoint §1.4 — UART
    framing errors are logged, never raised, since they are expected under
    sync loss).

    Callers must have already byte-aligned to a sample boundary; this
    function does not search for sync.
    """
    if len(data) != SAMPLE_SIZE:
        raise ValueError(
            f"decode_sample expects {SAMPLE_SIZE} bytes, got {len(data)}"
        )

    b0, b1, b2, b3, b4 = data

    s = b0 & 0x01
    not_s = (b0 >> 1) & 0x01
    if s == not_s:
        if logger is not None:
            logger.warning(
                "raw_parser: dropping sample — S/!S inverse check failed "
                "(byte0=0x%02X)",
                b0,
            )
        return None

    check_bit = b1 & 0x01
    if check_bit != 1:
        if logger is not None:
            logger.warning(
                "raw_parser: dropping sample — bad check bit C=0 "
                "(byte1=0x%02X)",
                b1,
            )
        return None

    quality = b0 >> 2
    angle_q6 = ((b2 << 7) | (b1 >> 1)) & 0x7FFF  # 15-bit Q6
    distance_q2 = (b4 << 8) | b3  # 16-bit Q2

    angle_deg = (angle_q6 / 64.0) % 360.0  # wrap; Sample rejects 360.0
    distance_mm = distance_q2 / 4.0

    # flag bit 0 mirrors S (start-of-frame). We keep it narrow on purpose;
    # extra bits can be added if a future scan mode needs them.
    flag = s & 0x01

    return Sample(
        angle_deg=angle_deg,
        distance_mm=distance_mm,
        quality=quality,
        flag=flag,
        timestamp_ns=timestamp_ns,
    )


def decode_samples(
    data: bytes,
    timestamp_ns: int,
    *,
    logger: logging.Logger | None = None,
) -> tuple[list[Sample], bytes]:
    """Decode a contiguous byte stream into whole samples.

    Returns (samples, leftover). Samples that fail validation are dropped
    with a warning; they are NOT included in the returned list.

    `leftover` is the tail (< 5 bytes) that did not make a complete sample;
    the caller is expected to prepend it to the next chunk.

    All successfully decoded samples share the same `timestamp_ns`. Per-sample
    timestamping at 460,800 bps (~11 kB/s → ~2,200 samples/s) is finer than
    what we need for noise characterization; a per-chunk timestamp keeps the
    hot path free of extra syscalls.

    No resync: this function assumes the incoming stream is already aligned
    to a 5-byte sample boundary. It does NOT scan for a new alignment when
    the check bit (C=1) or the S/!S inverse fails — it just drops the bad
    sample and advances five bytes. If a caller observes more than
    ``10`` consecutive C-bit failures within one chunk, the stream has
    almost certainly lost framing; the caller should restart the backend
    (STOP → MOTOR → wait ≈500 ms → SCAN → descriptor) rather than continue
    feeding this function. Automatic resync is a Phase 2+ item.
    """
    n_full = len(data) // SAMPLE_SIZE
    leftover = data[n_full * SAMPLE_SIZE :]

    out: list[Sample] = []
    for i in range(n_full):
        chunk = data[i * SAMPLE_SIZE : (i + 1) * SAMPLE_SIZE]
        sample = decode_sample(chunk, timestamp_ns, logger=logger)
        if sample is not None:
            out.append(sample)
    return out, leftover


def build_request(cmd: int, payload: bytes = b"") -> bytes:
    """Build a request packet per PDF §"Request Packets' Format" (Figure 2-4).

    No-payload form:  A5 <cmd>
    With-payload:     A5 <cmd> <size> <payload...> <xor-checksum>
    Checksum = 0 XOR 0xA5 XOR cmd XOR size XOR payload[0] XOR ... XOR payload[n]
    """
    if not (0 <= cmd <= 0xFF):
        raise ValueError(f"cmd must fit in a byte; got {cmd!r}")
    if not payload:
        return bytes([0xA5, cmd])
    if len(payload) > 0xFF:
        raise ValueError(
            f"payload length {len(payload)} exceeds 255-byte protocol limit"
        )
    size = len(payload)
    checksum = 0xA5 ^ cmd ^ size
    for b in payload:
        checksum ^= b
    return bytes([0xA5, cmd, size]) + payload + bytes([checksum & 0xFF])


# Request packets used by the Non-SDK backend. Sourced from PDF Figure 4-1.
STOP_REQUEST: Final[bytes] = build_request(0x25)
RESET_REQUEST: Final[bytes] = build_request(0x40)
SCAN_REQUEST: Final[bytes] = build_request(0x20)


def build_motor_speed_request(rpm: int) -> bytes:
    """Build a MOTOR_SPEED_CTRL request (PDF §4 Figure 4-31, p.32).

    Request: A5 A8 02 <rpm_lo> <rpm_hi> <checksum>
    `rpm` is u16 little-endian. Setting rpm=0 returns the device to idle.
    """
    if not (0 <= rpm <= 0xFFFF):
        raise ValueError(f"rpm must fit in u16; got {rpm!r}")
    payload = bytes([rpm & 0xFF, (rpm >> 8) & 0xFF])
    return build_request(0xA8, payload)
