"""Tests for `godo_lidar.capture.raw_parser`.

All fixtures below are hand-derived from SLAMTEC protocol v2.8
(`RPLIDAR/sources/SLAMTEC_rplidar_protocol_v2.8_en.pdf`). Each fixture
constant cites the PDF section / figure it comes from. The parser is NOT
introspected to generate these bytes — they are computed from the protocol
spec and then asserted against whatever the parser produces.

Canonical standard-mode sample layout (PDF §"Start ScanSCAN Request and
Response", Figure 4-4, p.15; field definitions in Figure 4-5, p.16):

    byte 0: bits [7:2] = quality[5:0]   (6-bit quality)
            bit  1     = !S (inverse start flag)
            bit  0     = S  (start flag; S=1 marks a new 360° frame)
            Invariant: S XOR !S == 1.

    byte 1: bits [7:1] = angle_q6[6:0]
            bit  0     = C  (check bit, always 1)

    byte 2: bits [7:0] = angle_q6[14:7]

    byte 3: bits [7:0] = distance_q2[7:0]
    byte 4: bits [7:0] = distance_q2[15:8]

    angle_deg   = angle_q6   / 64.0    (Q6 fixed point, PDF Figure 4-5)
    distance_mm = distance_q2 / 4.0    (Q2 fixed point, PDF Figure 4-5)
    distance_q2 == 0 ⇒ measurement invalid (PDF Figure 4-5)

Response descriptor for SCAN (PDF p.15): A5 5A 05 00 00 40 81

Request packet format (PDF §"Request Packets' Format", Figure 2-4, p.6):
    No-payload:    A5 <cmd>
    With payload:  A5 <cmd> <size> <payload...> <xor-checksum>
    checksum = 0 XOR 0xA5 XOR cmd XOR size XOR payload[0] ... XOR payload[n]

MOTOR_SPEED_CTRL (PDF §"Device motor speed control command", Figure 4-31,
p.32): A5 A8 02 <rpm_lo> <rpm_hi> <checksum>   (rpm is u16 little-endian).
"""

from __future__ import annotations

import logging

import pytest

from godo_lidar.capture.raw_parser import (
    SCAN_REQUEST,
    SCAN_RESPONSE_DESCRIPTOR,
    STOP_REQUEST,
    build_motor_speed_request,
    build_request,
    decode_sample,
    decode_samples,
)


# ---------------------------------------------------------------------------
# Fixture 1 — a fully-specified valid sample, start-of-frame, angle 180°,
# distance 1000 mm, quality 63 (max for 6 bits).
#
# Derivation (PDF Figures 4-4 / 4-5):
#   angle_deg = 180    → angle_q6   = 180 * 64 = 11520  = 0x2D00
#   distance_mm = 1000 → distance_q2 = 1000 * 4 = 4000  = 0x0FA0
#   quality = 63 (6 bits, all ones)
#   S = 1, !S = 0  → byte 0 = (0b111111 << 2) | (0 << 1) | 1 = 0xFD
#   C = 1, angle_q6[6:0] = 0x2D00 & 0x7F = 0x00
#     → byte 1 = (0x00 << 1) | 1 = 0x01
#   byte 2 = angle_q6[14:7] = 0x2D00 >> 7 = 0x5A
#   byte 3 = distance_q2[7:0]  = 0xA0
#   byte 4 = distance_q2[15:8] = 0x0F
# ---------------------------------------------------------------------------
VALID_SAMPLE_BYTES = bytes([0xFD, 0x01, 0x5A, 0xA0, 0x0F])
VALID_SAMPLE_EXPECTED = {
    "angle_deg": 180.0,
    "distance_mm": 1000.0,
    "quality": 63,
    "flag": 1,
}


# ---------------------------------------------------------------------------
# Fixture 2 — the same sample but with the check bit C forced to 0.
# Per PDF Figure 4-5 "C: Check bit, constantly set to 1", so C=0 indicates
# mis-framing. The parser must drop the sample AND log a warning.
# ---------------------------------------------------------------------------
BAD_CHECK_BIT_BYTES = bytes([0xFD, 0x00, 0x5A, 0xA0, 0x0F])


# ---------------------------------------------------------------------------
# Fixture 3 — invalid measurement (distance_q2 == 0 per PDF Figure 4-5).
# angle 90°, quality 32, S=0 (mid-frame).
#
#   angle_q6 = 90 * 64 = 5760 = 0x1680
#   quality = 32  → high 6 bits = 0b100000
#   S = 0, !S = 1 → byte 0 = (0b100000 << 2) | (1 << 1) | 0 = 0x82
#   angle_q6[6:0] = 0x1680 & 0x7F = 0x00
#     → byte 1 = (0x00 << 1) | 1 = 0x01
#   byte 2 = 0x1680 >> 7 = 0x2D
#   distance_q2 = 0 → bytes 3,4 = 0x00, 0x00
# ---------------------------------------------------------------------------
INVALID_DISTANCE_BYTES = bytes([0x82, 0x01, 0x2D, 0x00, 0x00])


# ---------------------------------------------------------------------------
# Fixture 4 — sample at angle very close to 360 that must wrap via modulo.
# Using angle_q6 = 23039 (= 64 * 359.984375), valid [0, 360).
# To also exercise modulo wrap in decode_sample, try angle_q6 = 23040
# (= 64 * 360 → must wrap to 0).
#
#   angle_q6 = 23040 = 0x5A00, quality=10, S=0, !S=1, distance=2048 mm
#   distance_q2 = 2048 * 4 = 8192 = 0x2000
#   byte 0 = (10 << 2) | (1 << 1) | 0 = 0x2A
#   angle_q6[6:0] = 0x00, byte 1 = (0x00 << 1) | 1 = 0x01
#   byte 2 = 0x5A00 >> 7 = 0xB4
#   byte 3 = 0x00
#   byte 4 = 0x20
# ---------------------------------------------------------------------------
WRAP_SAMPLE_BYTES = bytes([0x2A, 0x01, 0xB4, 0x00, 0x20])
WRAP_SAMPLE_EXPECTED_ANGLE = 0.0  # 360 mod 360 = 0
WRAP_SAMPLE_EXPECTED_DISTANCE = 2048.0


# ---------------------------------------------------------------------------
# Fixture 5 — S/!S both zero (protocol violation per PDF Figure 4-5
# "Inversed start flag bit, always has != S"). Must drop + warn.
#
# Take VALID_SAMPLE_BYTES and zero both flag bits in byte 0.
#   VALID byte 0 = 0xFD → 0b11111101 → quality=0b111111, !S=0, S=1
#   Zero both     → 0b11111100 = 0xFC
# ---------------------------------------------------------------------------
BAD_SYNC_BIT_BYTES = bytes([0xFC, 0x01, 0x5A, 0xA0, 0x0F])


# ===========================================================================
# Tests
# ===========================================================================


def test_decode_valid_sample_matches_pdf_derived_expected() -> None:
    sample = decode_sample(VALID_SAMPLE_BYTES, timestamp_ns=42)
    assert sample is not None
    assert sample.angle_deg == VALID_SAMPLE_EXPECTED["angle_deg"]
    assert sample.distance_mm == VALID_SAMPLE_EXPECTED["distance_mm"]
    assert sample.quality == VALID_SAMPLE_EXPECTED["quality"]
    assert sample.flag == VALID_SAMPLE_EXPECTED["flag"]
    assert sample.timestamp_ns == 42


def test_decode_invalid_distance_still_returns_sample_with_zero() -> None:
    # PDF Figure 4-5: distance_q2=0 means invalid measurement; we keep the
    # sample so downstream can see the miss pattern.
    sample = decode_sample(INVALID_DISTANCE_BYTES, timestamp_ns=7)
    assert sample is not None
    assert sample.distance_mm == 0.0
    assert sample.angle_deg == 90.0
    assert sample.quality == 32
    assert sample.flag == 0


def test_decode_sample_wraps_angle_equal_to_360(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.wrap")
    sample = decode_sample(WRAP_SAMPLE_BYTES, timestamp_ns=1, logger=logger)
    assert sample is not None
    assert sample.angle_deg == WRAP_SAMPLE_EXPECTED_ANGLE
    assert sample.distance_mm == WRAP_SAMPLE_EXPECTED_DISTANCE


def test_bad_check_bit_drops_sample_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.raw_parser")
    with caplog.at_level(logging.WARNING, logger="test.raw_parser"):
        result = decode_sample(BAD_CHECK_BIT_BYTES, timestamp_ns=0, logger=logger)
    # (a) returned None — sample excluded
    assert result is None
    # (b) warning record emitted with specific substring
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert warnings, "no warning record emitted"
    assert any("bad check bit" in r.getMessage() for r in warnings)


def test_bad_sync_bits_drop_sample_and_log_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.raw_parser_sync")
    with caplog.at_level(logging.WARNING, logger="test.raw_parser_sync"):
        result = decode_sample(
            BAD_SYNC_BIT_BYTES, timestamp_ns=0, logger=logger
        )
    assert result is None
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert warnings
    assert any(
        "S/!S inverse check failed" in r.getMessage() for r in warnings
    )


def test_decode_samples_streams_and_returns_leftover(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.raw_parser_stream")
    # Two valid samples + 3 leftover bytes that do not form a whole sample.
    tail = bytes([0x11, 0x22, 0x33])
    stream = VALID_SAMPLE_BYTES + INVALID_DISTANCE_BYTES + tail

    samples, leftover = decode_samples(
        stream, timestamp_ns=99, logger=logger
    )
    assert len(samples) == 2
    assert leftover == tail
    assert samples[0].angle_deg == 180.0
    assert samples[0].flag == 1
    assert samples[1].angle_deg == 90.0
    assert samples[1].flag == 0
    # All successful samples share the caller-provided timestamp.
    for s in samples:
        assert s.timestamp_ns == 99


def test_decode_samples_drops_bad_samples_amid_good_ones(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.raw_parser_mixed")
    stream = VALID_SAMPLE_BYTES + BAD_CHECK_BIT_BYTES + INVALID_DISTANCE_BYTES
    with caplog.at_level(logging.WARNING, logger="test.raw_parser_mixed"):
        samples, leftover = decode_samples(
            stream, timestamp_ns=0, logger=logger
        )
    # 3 input samples, 1 dropped → 2 out, 0 leftover.
    assert len(samples) == 2
    assert leftover == b""
    # Warning must have been logged for the dropped one.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings


# ---------------------------------------------------------------------------
# Protocol-level request / descriptor assertions.
# ---------------------------------------------------------------------------


def test_scan_response_descriptor_matches_pdf() -> None:
    # PDF p.15: "Response Descriptor: A5 5A 05 00 00 40 81"
    assert SCAN_RESPONSE_DESCRIPTOR == bytes(
        [0xA5, 0x5A, 0x05, 0x00, 0x00, 0x40, 0x81]
    )


def test_stop_and_scan_requests_match_pdf() -> None:
    # PDF p.13: "Request Packet: A5 25" (STOP)
    assert STOP_REQUEST == bytes([0xA5, 0x25])
    # PDF p.15: "Request Packet: A5 20" (SCAN)
    assert SCAN_REQUEST == bytes([0xA5, 0x20])


def test_build_request_checksum_matches_pdf_formula() -> None:
    # PDF §"Request Packets' Format": checksum = 0 XOR 0xA5 XOR cmd XOR
    # size XOR payload[0] XOR ... XOR payload[n]
    cmd = 0x84
    payload = bytes([0x7C, 0x00, 0x00, 0x00])  # GET_LIDAR_CONF TYPICAL type
    packet = build_request(cmd, payload)
    assert packet[0] == 0xA5
    assert packet[1] == cmd
    assert packet[2] == len(payload)
    assert packet[3:-1] == payload

    expected_cs = 0xA5 ^ cmd ^ len(payload)
    for b in payload:
        expected_cs ^= b
    assert packet[-1] == (expected_cs & 0xFF)


def test_motor_speed_request_matches_pdf_format() -> None:
    # PDF Figure 4-31 (p.32): A5 A8 02 <rpm_lo> <rpm_hi> <checksum>
    rpm = 600
    req = build_motor_speed_request(rpm)
    assert req[0] == 0xA5
    assert req[1] == 0xA8
    assert req[2] == 0x02
    assert req[3] == rpm & 0xFF
    assert req[4] == (rpm >> 8) & 0xFF

    expected_cs = 0xA5 ^ 0xA8 ^ 0x02 ^ (rpm & 0xFF) ^ ((rpm >> 8) & 0xFF)
    assert req[5] == (expected_cs & 0xFF)


def test_decode_sample_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="5 bytes"):
        decode_sample(b"\x00\x00\x00\x00", timestamp_ns=0)
