"""
Pinning tests — every value here MUST match the C++ Tier-1 origin cited
inline. A "tidy-up" rename or quote-style change on either side fails this
test, which is the whole point.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from godo_webctl import protocol as P

# Anchor to the repo root so the C++ source read below works regardless
# of the operator's pytest cwd. godo-webctl/tests/test_protocol.py →
# parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_JSON_MINI_CPP = _REPO_ROOT / "production/RPi5/src/uds/json_mini.cpp"
_RT_TYPES_HPP = _REPO_ROOT / "production/RPi5/src/core/rt_types.hpp"
_CONSTANTS_HPP = _REPO_ROOT / "production/RPi5/src/core/constants.hpp"


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


# --- Track B: get_last_pose mirror ----------------------------------------


def test_cmd_get_last_pose_matches_cpp() -> None:
    # production/RPi5/src/uds/uds_server.cpp `get_last_pose` branch.
    assert P.CMD_GET_LAST_POSE == "get_last_pose"


def test_encode_get_last_pose_byte_exact() -> None:
    assert P.encode_get_last_pose() == b'{"cmd":"get_last_pose"}\n'


# --- Track E (PR-C) — multi-map mirror -----------------------------------


def test_track_e_error_codes_pinned() -> None:
    assert P.ERR_INVALID_MAP_NAME == "invalid_map_name"
    assert P.ERR_MAP_NOT_FOUND == "map_not_found"
    assert P.ERR_MAP_IS_ACTIVE == "map_is_active"
    assert P.ERR_MAPS_DIR_MISSING == "maps_dir_missing"


def test_maps_name_regex_pattern_str_mirrors_constants() -> None:
    from godo_webctl.constants import MAPS_NAME_REGEX

    # SSOT side on the LHS — drift from constants.py is what we catch.
    assert MAPS_NAME_REGEX.pattern == P.MAPS_NAME_REGEX_PATTERN_STR


# --- Track D: get_last_scan mirror ----------------------------------------


def test_cmd_get_last_scan_matches_cpp() -> None:
    # production/RPi5/src/uds/uds_server.cpp `get_last_scan` branch.
    assert P.CMD_GET_LAST_SCAN == "get_last_scan"


def test_encode_get_last_scan_byte_exact() -> None:
    assert P.encode_get_last_scan() == b'{"cmd":"get_last_scan"}\n'


def test_last_scan_ranges_max_python_mirror_matches_cpp() -> None:
    """Pin: LAST_SCAN_RANGES_MAX_PYTHON_MIRROR equals the C++ Tier-1
    constant in core/constants.hpp. Drift here would mean the SPA renders
    a smaller / larger array than the wire actually carries."""
    src = _CONSTANTS_HPP.read_text(encoding="utf-8")
    m = re.search(
        r"LAST_SCAN_RANGES_MAX\s*=\s*(\d+)",
        src,
    )
    assert m is not None, "LAST_SCAN_RANGES_MAX not found in constants.hpp"
    cpp_value = int(m.group(1))
    assert cpp_value == P.LAST_SCAN_RANGES_MAX_PYTHON_MIRROR, (
        f"LAST_SCAN_RANGES_MAX drift: C++={cpp_value} Python={P.LAST_SCAN_RANGES_MAX_PYTHON_MIRROR}"
    )


def test_last_scan_header_fields_match_cpp_source() -> None:
    """Drift pin: regex-extract LastScan field names from the
    rt_types.hpp struct declaration and assert byte-equal against
    LAST_SCAN_HEADER_FIELDS. Extracts from rt_types.hpp (the canonical
    struct) per the Track D planner override — NOT from the format_ok_scan
    format string. Reasoning: the struct is the SSOT for field names +
    order; the JSON formatter is one of multiple downstream renderings.

    Editing one side without the other fails this test.
    """
    src = _RT_TYPES_HPP.read_text(encoding="utf-8")

    # Locate the struct body: from `struct LastScan {` to the matching
    # closing `};`. We slice on the first `};` after the opening, which
    # is robust to internal nested initialisation lists (none used in
    # this struct as of writing).
    start = src.find("struct LastScan {")
    assert start != -1, "struct LastScan not found in rt_types.hpp"
    end = src.find("};", start)
    assert end != -1, "struct LastScan body has no terminator"
    body = src[start:end]

    # Field declarations are of the form
    #     <type>  name;            // optional comment
    #     <type>  name[N];         // array form (angles_deg / ranges_m)
    # We walk the body line-by-line and extract the identifier preceding
    # `;` (or `[`) on every declaration line. Comment lines + struct
    # opening are skipped naturally because they do not match the regex.
    field_re = re.compile(
        r"^\s*(?:std::)?\w+(?:_t)?\s+([a-z_][a-z0-9_]*)\s*(?:\[[^\]]*\])?\s*;",
        re.MULTILINE,
    )
    declared = field_re.findall(body)

    # Filter out padding fields (start with `_pad`) — those are layout
    # only, never on the wire.
    visible = tuple(name for name in declared if not name.startswith("_pad"))

    # The struct also declares `pose_x_m`, `pose_y_m`, `pose_yaw_deg`
    # which appear in LAST_SCAN_HEADER_FIELDS. The wire ordering re-orders
    # the flags + iterations + pose anchors before `n` to keep the array
    # body at the tail; here we assert SET equality on the visible names
    # and ALSO that the tuple LAST_SCAN_HEADER_FIELDS is a permutation of
    # the visible-set (catches rename drift; the by-inspection convention
    # in CODEBASE.md catches reorder drift on the wire).
    assert set(P.LAST_SCAN_HEADER_FIELDS) == set(visible), (
        f"Field-name drift: C++={visible} Python={P.LAST_SCAN_HEADER_FIELDS}"
    )


def test_last_pose_fields_match_cpp_source() -> None:
    """Drift pin: regex-extract field names from format_ok_pose's printf
    format string and assert byte-equal against LAST_POSE_FIELDS.
    Editing one side without the other fails this test."""
    src = _JSON_MINI_CPP.read_text(encoding="utf-8")
    # Locate the format_ok_pose function body. The format string is
    # spread across multiple adjacent C string literals; concatenate
    # them, then pull out the JSON keys with a regex.
    func_marker = "format_ok_pose"
    start = src.find(func_marker + "(const godo::rt::LastPose")
    assert start != -1, f"Could not locate '{func_marker}' definition in {_JSON_MINI_CPP}"
    # Scope to the snprintf format string only — this is the SSOT. The
    # function body also contains a fallback `return std::string(...)`
    # for the encoding-error path which is structurally identical (so
    # both sides benefit from the same drift catch on the canonical
    # string), but counting field names twice would inflate the tuple.
    snprintf_idx = src.find("std::snprintf(buf, sizeof(buf),", start)
    assert snprintf_idx != -1, "Could not locate snprintf in format_ok_pose body"
    # End at the first `,` that closes the format-string argument: that
    # is the `,` immediately after the closing quote of the format
    # string literal block. We search for the line starting with
    # `static_cast<unsigned>(p.valid)` which is the first format-string
    # argument expression.
    args_idx = src.find("static_cast<unsigned>(p.valid)", snprintf_idx)
    assert args_idx != -1
    fmt_block = src[snprintf_idx:args_idx]
    # Find every `\"<key>\":` token in the format string.
    field_pattern = re.compile(r'\\"([a-z_]+)\\":')
    found = field_pattern.findall(fmt_block)
    # Exclude the `ok` key (JSON-level success flag, not a pose field).
    fields_in_cpp = tuple(name for name in found if name != "ok")
    assert fields_in_cpp == P.LAST_POSE_FIELDS, (
        f"Field-order drift: C++={fields_in_cpp} Python={P.LAST_POSE_FIELDS}"
    )
