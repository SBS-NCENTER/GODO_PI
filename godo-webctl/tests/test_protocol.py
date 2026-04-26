"""
Pinning tests — every value here MUST match the C++ Tier-1 origin cited
inline. A "tidy-up" rename or quote-style change on either side fails this
test, which is the whole point.
"""

from __future__ import annotations

import pytest

from godo_webctl import protocol as P


def test_uds_request_max_bytes_matches_cpp() -> None:
    # production/RPi5/src/core/constants.hpp:54
    assert P.UDS_REQUEST_MAX_BYTES == 4096


def test_response_read_bufsize_matches_request_cap() -> None:
    assert P.UDS_RESPONSE_READ_BUFSIZE == P.UDS_REQUEST_MAX_BYTES


def test_command_names_match_cpp() -> None:
    # production/RPi5/src/uds/json_mini.cpp::parse_request L46-72
    assert P.CMD_PING == "ping"
    assert P.CMD_GET_MODE == "get_mode"
    assert P.CMD_SET_MODE == "set_mode"


def test_mode_names_match_cpp() -> None:
    # production/RPi5/src/uds/json_mini.cpp::parse_mode_arg L126-130
    assert P.MODE_IDLE == "Idle"
    assert P.MODE_ONESHOT == "OneShot"
    assert P.MODE_LIVE == "Live"
    assert set(P.VALID_MODES) == {"Idle", "OneShot", "Live"}


def test_error_codes_match_cpp() -> None:
    # production/RPi5/src/uds/uds_server.cpp:189,196,215,225
    assert P.ERR_PARSE_ERROR == "parse_error"
    assert P.ERR_UNKNOWN_CMD == "unknown_cmd"
    assert P.ERR_BAD_MODE == "bad_mode"


def test_max_rename_attempts_is_tier1() -> None:
    assert P.MAX_RENAME_ATTEMPTS == 9


def test_encode_ping_byte_exact() -> None:
    assert P.encode_ping() == b'{"cmd":"ping"}\n'


def test_encode_get_mode_byte_exact() -> None:
    assert P.encode_get_mode() == b'{"cmd":"get_mode"}\n'


def test_encode_set_mode_byte_exact() -> None:
    assert P.encode_set_mode("Idle") == b'{"cmd":"set_mode","mode":"Idle"}\n'
    assert P.encode_set_mode("OneShot") == b'{"cmd":"set_mode","mode":"OneShot"}\n'
    assert P.encode_set_mode("Live") == b'{"cmd":"set_mode","mode":"Live"}\n'


def test_encode_set_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        P.encode_set_mode("Calibrate")
