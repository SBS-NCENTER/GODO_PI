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


# --- issue#3 (pose hint) — encoder shape pin ----------------------------
def test_encode_set_mode_no_hint_byte_identical_to_pre_issue3() -> None:
    """Anti-regression pin: when seed=None, the wire shape is identical
    to the pre-issue#3 `encode_set_mode("OneShot")` byte sequence. A
    writer who introduces an unconditional `,"seed_x_m":...` would fail
    this case."""
    assert P.encode_set_mode("OneShot") == b'{"cmd":"set_mode","mode":"OneShot"}\n'
    assert P.encode_set_mode("OneShot", seed=None) == \
        b'{"cmd":"set_mode","mode":"OneShot"}\n'
    assert P.encode_set_mode("Live", seed=None) == \
        b'{"cmd":"set_mode","mode":"Live"}\n'


def test_encode_set_mode_with_full_hint() -> None:
    payload = P.encode_set_mode(
        "OneShot",
        seed=(1.5, -2.25, 90.0),
        sigma_xy_m=0.5,
        sigma_yaw_deg=20.0,
    )
    assert payload == (
        b'{"cmd":"set_mode","mode":"OneShot","seed_x_m":1.5,'
        b'"seed_y_m":-2.25,"seed_yaw_deg":90.0,'
        b'"sigma_xy_m":0.5,"sigma_yaw_deg":20.0}\n'
    )


def test_encode_set_mode_seed_only_no_sigma() -> None:
    """Operator places hint without σ overrides. Wire MUST NOT carry
    the σ keys (so the tracker's cfg default takes effect)."""
    payload = P.encode_set_mode("OneShot", seed=(0.0, 0.0, 0.0))
    assert payload == (
        b'{"cmd":"set_mode","mode":"OneShot","seed_x_m":0.0,'
        b'"seed_y_m":0.0,"seed_yaw_deg":0.0}\n'
    )


def test_encode_set_mode_rejects_sigma_without_seed() -> None:
    """σ override without seed is a programming error — encoder rejects
    as defence-in-depth (Pydantic catches the same shape upstream)."""
    with pytest.raises(ValueError, match="sigma overrides require seed"):
        P.encode_set_mode("OneShot", seed=None, sigma_xy_m=0.5)


def test_encode_set_mode_rejects_non_finite_hint() -> None:
    """NaN / Infinity in any hint field is a programming error
    (Pydantic + the C++ parser already reject it; encoder is the
    third defence layer)."""
    with pytest.raises(ValueError, match="non-finite"):
        P.encode_set_mode("OneShot", seed=(float("nan"), 0.0, 0.0))
    with pytest.raises(ValueError, match="non-finite"):
        P.encode_set_mode("OneShot", seed=(0.0, float("inf"), 0.0))


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


# --- Track B-BACKUP — map-backup history error codes -------------------


def test_track_b_backup_error_codes_pinned() -> None:
    """Mode-A M5 fold: only 2 new error codes (BACKUP_DIR_MISSING was
    dropped — list_backups returns [] for both missing-dir and
    empty-dir cases)."""
    assert P.ERR_BACKUP_NOT_FOUND == "backup_not_found"
    assert P.ERR_RESTORE_NAME_CONFLICT == "restore_name_conflict"


def test_track_b_backup_no_dir_missing_constant() -> None:
    """Mode-A M5 fold pin: the `ERR_BACKUP_DIR_MISSING` symbol MUST NOT
    exist (the wire-shape change collapsed the 503 path to a 200-empty
    response). A future writer who silently re-adds it fails this test."""
    assert not hasattr(P, "ERR_BACKUP_DIR_MISSING")


def test_maps_name_regex_pattern_str_mirrors_constants() -> None:
    from godo_webctl.constants import MAPS_NAME_REGEX

    # SSOT side on the LHS — drift from constants.py is what we catch.
    assert MAPS_NAME_REGEX.pattern == P.MAPS_NAME_REGEX_PATTERN_STR


# --- Track B-MAPEDIT — POST /api/map/edit error codes + response shape ---


def test_map_edit_error_codes_pinned() -> None:
    """All five Track B-MAPEDIT error codes. Drift from this file fails
    the SPA mirror in `lib/protocol.ts`."""
    assert P.ERR_MASK_SHAPE_MISMATCH == "mask_shape_mismatch"
    assert P.ERR_MASK_TOO_LARGE == "mask_too_large"
    assert P.ERR_MASK_DECODE_FAILED == "mask_decode_failed"
    assert P.ERR_EDIT_FAILED == "edit_failed"
    assert P.ERR_ACTIVE_MAP_MISSING == "active_map_missing"


def test_edit_response_fields_pinned() -> None:
    """`POST /api/map/edit` 200-response field order. `restart_required`
    is forward-compat (always True in v1; field stays for a future hot-
    reload edit class). S2 fold: pinned both as a tuple of names AND as
    a literal-value reminder that v1 emits True."""
    assert P.EDIT_RESPONSE_FIELDS == (
        "ok",
        "backup_ts",
        "pixels_changed",
        "restart_required",
    )
    # Literal-value drift catch — encoded as a comment-test so a future
    # writer who flips the wire to `restart_required: False` fails here.
    assert "restart_required" in P.EDIT_RESPONSE_FIELDS


# --- Track B-MAPEDIT-2 — POST /api/map/origin error codes + response ----


def test_origin_error_codes_pinned() -> None:
    """Track B-MAPEDIT-2 error codes. Drift from this file fails the SPA
    mirror in `lib/protocol.ts`."""
    assert P.ERR_ORIGIN_BAD_VALUE == "bad_origin_value"
    assert P.ERR_ORIGIN_YAML_PARSE_FAILED == "origin_yaml_parse_failed"
    assert P.ERR_ORIGIN_EDIT_FAILED == "origin_edit_failed"
    assert P.ERR_ACTIVE_YAML_MISSING == "active_yaml_missing"


def test_origin_edit_response_fields_pinned() -> None:
    """`POST /api/map/origin` 200-response field order. `restart_required`
    is always True in v1 (origin lives in YAML, tracker reads at boot only);
    field stays in the wire schema for future hot-reload symmetry with
    EDIT_RESPONSE_FIELDS."""
    assert P.ORIGIN_EDIT_RESPONSE_FIELDS == (
        "ok",
        "backup_ts",
        "prev_origin",
        "new_origin",
        "restart_required",
    )
    assert "restart_required" in P.ORIGIN_EDIT_RESPONSE_FIELDS


def test_origin_modes_pinned() -> None:
    """Track B-MAPEDIT-2 — mode literals match the SPA's OriginMode
    union. Drift catch: a writer flipping to a new mode here without
    updating `lib/protocol.ts::OriginMode` fails this set-equality."""
    assert P.ORIGIN_MODE_ABSOLUTE == "absolute"
    assert P.ORIGIN_MODE_DELTA == "delta"
    assert frozenset({"absolute", "delta"}) == P.VALID_ORIGIN_MODES  # noqa: SIM300


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
    rt_types.hpp struct declaration and assert SET-equality against
    LAST_SCAN_HEADER_FIELDS. Catches rename / addition / removal drift
    on either side. Wire-order drift is caught by the sister test
    test_last_scan_wire_order_matches_format_ok_scan below — together
    they pin both the field set (vs. struct) and the field sequence
    (vs. wire format string).

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
    # (catches rename / addition / removal drift). Wire-order drift is
    # caught by the sister test test_last_scan_wire_order_matches_format_
    # ok_scan below.
    assert set(P.LAST_SCAN_HEADER_FIELDS) == set(visible), (
        f"Field-name drift: C++={visible} Python={P.LAST_SCAN_HEADER_FIELDS}"
    )


def test_last_scan_wire_order_matches_format_ok_scan() -> None:
    """Drift pin: regex-extract JSON keys from format_ok_scan's snprintf
    format string in json_mini.cpp and assert TUPLE-EQUAL against
    LAST_SCAN_HEADER_FIELDS.

    Mode-B S1 fold (2026-04-29). The sister test above asserts SET
    equality vs. struct names (catches rename drift); this test asserts
    TUPLE equality vs. the wire format string (catches wire-order
    drift). The two together pin both the field set and the field
    sequence between C++ wire and Python mirror.
    """
    src = _JSON_MINI_CPP.read_text(encoding="utf-8")
    func_marker = "format_ok_scan"
    start = src.find(func_marker + "(const godo::rt::LastScan")
    assert start != -1, f"Could not locate '{func_marker}' definition in {_JSON_MINI_CPP}"
    # End at the next free-function definition after format_ok_scan. After
    # PR-DIAG that is `format_ok_jitter`; pre-PR-DIAG it was
    # `mode_to_string`. Either is a fine sentinel — both are unique markers
    # outside any function body. We try the closer one first.
    end = src.find("\nstd::string format_ok_jitter", start)
    if end == -1:
        end = src.find("\nstd::string_view mode_to_string", start)
    assert end != -1, "Could not locate end of format_ok_scan body"
    body = src[start:end]
    # Find every `\"<key>\":` token in the function body. The format
    # string is split across multiple snprintf calls (header + array
    # bodies); every JSON key still matches this pattern because the
    # array key (e.g., "ranges_m") is followed by `:[`.
    field_pattern = re.compile(r'\\"([a-z_]+)\\":')
    found = field_pattern.findall(body)
    # Exclude the `ok` key (JSON-level success flag). De-duplicate while
    # preserving first-seen order: the truncation-fallback returns
    # repeat the same key sequence, and we want a single tuple.
    seen: set[str] = set()
    fields_in_cpp: list[str] = []
    for name in found:
        if name == "ok":
            continue
        if name in seen:
            continue
        seen.add(name)
        fields_in_cpp.append(name)
    assert tuple(fields_in_cpp) == P.LAST_SCAN_HEADER_FIELDS, (
        f"Field-order drift: C++={tuple(fields_in_cpp)} Python={P.LAST_SCAN_HEADER_FIELDS}"
    )


# --- PR-DIAG: get_jitter / get_amcl_rate mirror --------------------------


def test_cmd_get_jitter_matches_cpp() -> None:
    # production/RPi5/src/uds/uds_server.cpp `get_jitter` branch.
    assert P.CMD_GET_JITTER == "get_jitter"


def test_cmd_get_amcl_rate_matches_cpp() -> None:
    # production/RPi5/src/uds/uds_server.cpp `get_amcl_rate` branch.
    # Mode-A M2 fold: command name is amcl_rate (NOT scan_rate).
    assert P.CMD_GET_AMCL_RATE == "get_amcl_rate"


def test_encode_get_jitter_byte_exact() -> None:
    assert P.encode_get_jitter() == b'{"cmd":"get_jitter"}\n'


def test_encode_get_amcl_rate_byte_exact() -> None:
    assert P.encode_get_amcl_rate() == b'{"cmd":"get_amcl_rate"}\n'


def _extract_format_keys(src: str, fn_marker: str, sentinel: str) -> tuple[str, ...]:
    """Helper — slice the JSON keys out of a snprintf format string in
    json_mini.cpp. Used by both the jitter and amcl_rate drift pins."""
    start = src.find(fn_marker)
    assert start != -1, f"Could not locate '{fn_marker}' definition"
    end = src.find(sentinel, start)
    assert end != -1, f"Could not locate sentinel '{sentinel}' after {fn_marker}"
    body = src[start:end]
    field_pattern = re.compile(r'\\"([a-z_0-9]+)\\":')
    found = field_pattern.findall(body)
    seen: set[str] = set()
    out: list[str] = []
    for name in found:
        if name == "ok":
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return tuple(out)


def test_jitter_fields_match_cpp_source() -> None:
    """PR-DIAG drift pin: regex-extract JSON keys from format_ok_jitter's
    snprintf format string and assert tuple-equal against JITTER_FIELDS."""
    src = _JSON_MINI_CPP.read_text(encoding="utf-8")
    found = _extract_format_keys(
        src,
        "format_ok_jitter(const godo::rt::JitterSnapshot",
        "\nstd::string format_ok_amcl_rate",
    )
    assert found == P.JITTER_FIELDS, f"Field-order drift: C++={found} Python={P.JITTER_FIELDS}"


def test_amcl_rate_fields_match_cpp_source() -> None:
    """PR-DIAG drift pin (Mode-A M2): same shape as jitter pin."""
    src = _JSON_MINI_CPP.read_text(encoding="utf-8")
    found = _extract_format_keys(
        src,
        "format_ok_amcl_rate(const godo::rt::AmclIterationRate",
        # issue#27: format_ok_output now sits between amcl_rate and
        # mode_to_string, so use the function-end `}\n` close as the
        # sentinel. The amcl_rate body has a single fallback `return
        # std::string(...)` that ends right before the closing brace; we
        # bound on the comment marker that introduces format_ok_output.
        "// Field order pin — MUST match godo::rt::LastOutputFrame",
    )
    assert found == P.AMCL_RATE_FIELDS, (
        f"Field-order drift: C++={found} Python={P.AMCL_RATE_FIELDS}"
    )


def test_jitter_struct_fields_match_cpp_source() -> None:
    """Mirror `test_last_scan_header_fields_match_cpp_source` for
    JitterSnapshot — set-equality between struct names (after pad
    filter) and the Python tuple."""
    src = _RT_TYPES_HPP.read_text(encoding="utf-8")
    start = src.find("struct JitterSnapshot {")
    assert start != -1, "struct JitterSnapshot not found in rt_types.hpp"
    end = src.find("};", start)
    assert end != -1
    body = src[start:end]
    field_re = re.compile(
        r"^\s*(?:std::)?\w+(?:_t)?\s+([a-z_][a-z0-9_]*)\s*(?:\[[^\]]*\])?\s*;",
        re.MULTILINE,
    )
    declared = field_re.findall(body)
    visible = tuple(name for name in declared if not name.startswith("_pad"))
    assert set(P.JITTER_FIELDS) == set(visible), (
        f"Field-name drift: C++={visible} Python={P.JITTER_FIELDS}"
    )


def test_amcl_rate_struct_fields_match_cpp_source() -> None:
    """Mode-A M2 fold mirror — set-equality vs. AmclIterationRate
    struct."""
    src = _RT_TYPES_HPP.read_text(encoding="utf-8")
    start = src.find("struct AmclIterationRate {")
    assert start != -1, "struct AmclIterationRate not found in rt_types.hpp"
    end = src.find("};", start)
    assert end != -1
    body = src[start:end]
    field_re = re.compile(
        r"^\s*(?:std::)?\w+(?:_t)?\s+([a-z_][a-z0-9_]*)\s*(?:\[[^\]]*\])?\s*;",
        re.MULTILINE,
    )
    declared = field_re.findall(body)
    visible = tuple(name for name in declared if not name.startswith("_pad"))
    assert set(P.AMCL_RATE_FIELDS) == set(visible), (
        f"Field-name drift: C++={visible} Python={P.AMCL_RATE_FIELDS}"
    )


def test_resources_fields_pinned() -> None:
    """RESOURCES_FIELDS is webctl-only (no C++ counterpart). Pin values
    + count to catch drift between resources.snapshot() and the SPA's
    Resources interface."""
    assert P.RESOURCES_FIELDS == (
        "cpu_temp_c",
        "mem_used_pct",
        "mem_total_bytes",
        "mem_avail_bytes",
        "disk_used_pct",
        "disk_total_bytes",
        "disk_avail_bytes",
        "published_mono_ns",
    )


def test_diag_frame_fields_pinned() -> None:
    """Mode-A M2 fold: top-level keys are `pose / jitter / amcl_rate /
    resources` (NOT scan_rate)."""
    assert P.DIAG_FRAME_FIELDS == ("pose", "jitter", "amcl_rate", "resources")


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


def test_last_output_fields_match_cpp_format_ok_output() -> None:
    """issue#27 drift pin: regex-extract field names from
    format_ok_output's printf format string and assert byte-equal against
    LAST_OUTPUT_FIELDS. Editing one side without the other fails."""
    src = _JSON_MINI_CPP.read_text(encoding="utf-8")
    func_marker = "format_ok_output"
    start = src.find(func_marker + "(const godo::rt::LastOutputFrame")
    assert start != -1, f"Could not locate '{func_marker}' definition in {_JSON_MINI_CPP}"
    snprintf_idx = src.find("std::snprintf(buf, sizeof(buf),", start)
    assert snprintf_idx != -1, "Could not locate snprintf in format_ok_output body"
    args_idx = src.find("static_cast<unsigned>(f.valid)", snprintf_idx)
    assert args_idx != -1
    fmt_block = src[snprintf_idx:args_idx]
    # Match `\"<key>\":` allowing digits in the key (z_m, x_m, etc.).
    field_pattern = re.compile(r'\\"([a-z_0-9]+)\\":')
    found = field_pattern.findall(fmt_block)
    fields_in_cpp = tuple(name for name in found if name != "ok")
    assert fields_in_cpp == P.LAST_OUTPUT_FIELDS, (
        f"Field-order drift: C++={fields_in_cpp} Python={P.LAST_OUTPUT_FIELDS}"
    )


def test_encode_get_last_output_byte_exact() -> None:
    """issue#27 — canonical wire encoding pin."""
    assert P.encode_get_last_output() == b'{"cmd":"get_last_output"}\n'


def test_cmd_get_last_output_matches_cpp() -> None:
    """issue#27 — command name matches the C++ dispatch branch in
    `production/RPi5/src/uds/uds_server.cpp`."""
    assert P.CMD_GET_LAST_OUTPUT == "get_last_output"


# --- Track B-CONFIG (PR-CONFIG-β) — config edit pipeline pins -----------


def test_config_command_names() -> None:
    """Pin the 3 new wire commands."""
    assert P.CMD_GET_CONFIG == "get_config"
    assert P.CMD_GET_CONFIG_SCHEMA == "get_config_schema"
    assert P.CMD_SET_CONFIG == "set_config"


def test_reload_class_strings_match_cpp_source() -> None:
    """Pin against `reload_class_to_string` in config_schema.hpp."""
    src = (_REPO_ROOT / "production/RPi5/src/core/config_schema.hpp").read_text(encoding="utf-8")
    # The C++ enum maps Hot→"hot", Restart→"restart", Recalibrate→"recalibrate".
    # Pull the literals from the function body.
    matches = re.findall(r'return\s+"(hot|restart|recalibrate)"', src)
    cpp_strings = set(matches)
    # The function has 3 cases + a default duplicating "hot".
    assert {"hot", "restart", "recalibrate"} <= cpp_strings
    assert P.RELOAD_CLASS_HOT == "hot"
    assert P.RELOAD_CLASS_RESTART == "restart"
    assert P.RELOAD_CLASS_RECALIBRATE == "recalibrate"
    assert frozenset({"hot", "restart", "recalibrate"}) == P.VALID_RELOAD_CLASSES


def test_encode_get_config_byte_exact() -> None:
    assert P.encode_get_config() == b'{"cmd":"get_config"}\n'


def test_encode_get_config_schema_byte_exact() -> None:
    assert P.encode_get_config_schema() == b'{"cmd":"get_config_schema"}\n'


def test_encode_set_config_byte_exact() -> None:
    out = P.encode_set_config("smoother.deadband_mm", "12.5")
    assert out == b'{"cmd":"set_config","key":"smoother.deadband_mm","value":"12.5"}\n'


def test_encode_set_config_rejects_quote_in_key() -> None:
    with pytest.raises(ValueError):
        P.encode_set_config('a"b', "1")


def test_encode_set_config_rejects_backslash_in_value() -> None:
    with pytest.raises(ValueError):
        P.encode_set_config("k", "a\\b")


def test_encode_set_config_rejects_newline_in_value() -> None:
    with pytest.raises(ValueError):
        P.encode_set_config("k", "a\nb")


def test_config_schema_response_cap_above_4kb() -> None:
    """37 rows × ~200 B → ~7.5 KiB; cap MUST be wider than the default."""
    assert P.CONFIG_SCHEMA_RESPONSE_CAP >= 16 * 1024


# --- Track B-SYSTEM PR-2 — service observability pins ---------------------


def test_system_services_fields_pinned() -> None:
    """Pin the 8-field tuple verbatim. Drift between this constant and
    `services.ServiceShow` is also caught by the dataclass-time assertion
    `services._ensure_field_order_pin()` at import; this test is the
    cross-module SSOT pin.

    `env_stale` was added 2026-04-30 (PR-A): True when any
    EnvironmentFile='s mtime is later than the service's
    ActiveEnterTimestamp, signalling the operator made an envfile
    edit that has not yet taken effect (service restart needed).
    """
    assert P.SYSTEM_SERVICES_FIELDS == (
        "name",
        "active_state",
        "sub_state",
        "main_pid",
        "active_since_unix",
        "memory_bytes",
        "env_redacted",
        "env_stale",
    )


def test_env_redaction_patterns_pinned() -> None:
    """All 6 substring patterns. False-positives (`MOST_KEY_BUNDLES`)
    are accepted by design — safe direction."""
    assert P.ENV_REDACTION_PATTERNS == (
        "SECRET",
        "KEY",
        "TOKEN",
        "PASSWORD",
        "PASSWD",
        "CREDENTIAL",
    )


def test_redacted_placeholder_pinned() -> None:
    assert P.REDACTED_PLACEHOLDER == "<redacted>"


def test_service_transition_error_codes_pinned() -> None:
    assert P.ERR_SERVICE_STARTING == "service_starting"
    assert P.ERR_SERVICE_STOPPING == "service_stopping"


# --- Track B-SYSTEM PR-B — process monitor + extended resources ---------


def test_process_fields_pinned() -> None:
    """Pin the 10-field row tuple verbatim. Drift between this constant
    and `processes.ProcessSampler.sample()` per-row dict is also caught
    by the import-time assertion in `processes._ensure_field_order_pin`;
    this test is the cross-module SSOT pin.

    Mode-A M3 fold: wire field name is `category` everywhere — `class`
    does not appear (TS reserved word + Svelte template collision).
    """
    assert P.PROCESS_FIELDS == (
        "name",
        "pid",
        "user",
        "state",
        "cmdline",
        "cpu_pct",
        "rss_mb",
        "etime_s",
        "category",
        "duplicate",
    )


def test_processes_response_fields_pinned() -> None:
    """Top-level envelope of `/api/system/processes`."""
    assert P.PROCESSES_RESPONSE_FIELDS == (
        "processes",
        "duplicate_alert",
        "published_mono_ns",
    )


def test_extended_resources_fields_pinned() -> None:
    """Six fields. GPU fields intentionally absent (operator decision
    2026-04-30 06:38 KST — V3D `gpu_busy_percent` unreliable on Trixie
    firmware; CPU temp is already covered by RESOURCES_FIELDS)."""
    assert P.EXTENDED_RESOURCES_FIELDS == (
        "cpu_per_core",
        "cpu_aggregate_pct",
        "mem_total_mb",
        "mem_used_mb",
        "disk_pct",
        "published_mono_ns",
    )


def test_godo_process_names_match_cmake_executables() -> None:
    """Drift catch — the C++ subset of `GODO_PROCESS_NAMES` must equal
    the union of `add_executable(<name>` lines across each
    `production/RPi5/src/*/CMakeLists.txt`. A future writer adding a
    binary without updating the whitelist fails this pin.

    The `godo-webctl` literal is webctl-internal (matched via argv[1..]
    in `parse_pid_cmdline`) — pinned separately by inspection.
    """
    cmake_dirs = (
        "godo_tracker_rt",
        "godo_freed_passthrough",
        "godo_smoke",
        "godo_jitter",
    )
    found: set[str] = set()
    pattern = re.compile(r"^add_executable\(([A-Za-z0-9_]+)", re.MULTILINE)
    for d in cmake_dirs:
        cm = _REPO_ROOT / "production" / "RPi5" / "src" / d / "CMakeLists.txt"
        text = cm.read_text(encoding="utf-8")
        m = pattern.search(text)
        assert m is not None, f"add_executable() not found in {cm}"
        found.add(m.group(1))
    cpp_subset = P.GODO_PROCESS_NAMES - {"godo-webctl"}
    assert cpp_subset == found, f"Whitelist drift: protocol={cpp_subset} CMake={found}"


def test_managed_process_names_cardinality() -> None:
    """Mode-A M2 fold: `MANAGED_PROCESS_NAMES` is the process-name view
    of `services.ALLOWED_SERVICES` MINUS the units that don't appear in
    the host process list (godo-mapping@active runs inside Docker — its
    container processes show up as `slam_toolbox_node` etc., not as
    `godo-mapping`). Binary-vs-unit asymmetry means the set membership
    differs by exactly the substitution `godo-tracker → godo_tracker_rt`
    AND the omission of `godo-mapping@active`.

    issue#14 Patch C2 (2026-05-02): godo-mapping@active joined
    ALLOWED_SERVICES so the System tab can render its status; it is
    NOT added to MANAGED_PROCESS_NAMES because the docker container's
    processes don't carry that argv-derived name."""
    from godo_webctl import services

    assert len(P.MANAGED_PROCESS_NAMES) == 3
    assert len(services.ALLOWED_SERVICES) == 4
    diff = P.MANAGED_PROCESS_NAMES.symmetric_difference(services.ALLOWED_SERVICES)
    assert diff == {
        "godo-tracker",
        "godo_tracker_rt",
        "godo-mapping@active",
    }, f"Asymmetric-diff mismatch: {diff}"


# --- issue#14 — mapping pipeline state + monitor field pins -------------


def test_mapping_state_strings_pinned() -> None:
    """Mirrored on the SPA via `lib/protocol.ts::MAPPING_STATE_*`. Drift
    detected by inspection per godo-frontend/CODEBASE.md invariant."""
    assert P.MAPPING_STATE_IDLE == "idle"
    assert P.MAPPING_STATE_STARTING == "starting"
    assert P.MAPPING_STATE_RUNNING == "running"
    assert P.MAPPING_STATE_STOPPING == "stopping"
    assert P.MAPPING_STATE_FAILED == "failed"


def test_valid_mapping_states_set_pinned() -> None:
    assert frozenset(
        {"idle", "starting", "running", "stopping", "failed"},
    ) == P.VALID_MAPPING_STATES


def test_mapping_status_fields_pinned() -> None:
    """Wire shape of GET /api/mapping/status. Drift from this tuple
    breaks the SPA's mappingStatus store."""
    assert P.MAPPING_STATUS_FIELDS == (
        "state",
        "map_name",
        "container_id_short",
        "started_at",
        "error_detail",
        "journal_tail_available",
    )


def test_mapping_monitor_fields_pinned() -> None:
    """Docker-only frame (S1 amendment). RPi5 host stats are in the
    existing `/api/system/resources/extended/stream`. Drift in this
    field tuple breaks the SPA's MappingMonitorStrip Docker region."""
    assert P.MAPPING_MONITOR_FIELDS == (
        "valid",
        "container_id_short",
        "container_state",
        "container_cpu_pct",
        "container_mem_bytes",
        "container_net_rx_bytes",
        "container_net_tx_bytes",
        "var_lib_godo_disk_avail_bytes",
        "var_lib_godo_disk_total_bytes",
        "in_progress_map_size_bytes",
        "published_mono_ns",
    )


def test_mapping_error_codes_pinned() -> None:
    """All 13 mapping-pipeline error codes. Drift from this file fails
    the SPA mirror in `lib/protocol.ts`."""
    assert P.ERR_INVALID_MAPPING_NAME == "invalid_mapping_name"
    assert P.ERR_NAME_EXISTS == "name_exists"
    assert P.ERR_MAPPING_ALREADY_ACTIVE == "mapping_already_active"
    assert P.ERR_MAPPING_ACTIVE == "mapping_active"
    assert P.ERR_IMAGE_MISSING == "image_missing"
    assert P.ERR_DOCKER_UNAVAILABLE == "docker_unavailable"
    assert P.ERR_TRACKER_STOP_FAILED == "tracker_stop_failed"
    assert P.ERR_CONTAINER_START_TIMEOUT == "container_start_timeout"
    assert P.ERR_CONTAINER_STOP_TIMEOUT == "container_stop_timeout"
    assert P.ERR_NO_ACTIVE_MAPPING == "no_active_mapping"
    assert P.ERR_PREVIEW_NOT_YET_PUBLISHED == "preview_not_yet_published"
    assert P.ERR_STATE_FILE_CORRUPT == "state_file_corrupt"
    assert P.ERR_BAD_N == "bad_n"


# --- issue#16 — precheck + cp210x recovery wire pins --------------------


def test_precheck_fields_pinned() -> None:
    """Top-level envelope of `GET /api/mapping/precheck`. Drift from
    this tuple breaks the SPA's precheckStore."""
    assert P.PRECHECK_FIELDS == ("ready", "checks")


def test_precheck_check_fields_pinned() -> None:
    """One row of the `checks` array. The SPA renderer iterates this
    tuple verbatim."""
    assert P.PRECHECK_CHECK_FIELDS == ("name", "ok", "value", "detail")


def test_precheck_check_names_pinned() -> None:
    """Canonical names + emit order of the 7 checks. Drift here breaks
    the SPA's labelled rows + Korean strings.

    v7 (2026-05-02 KST) added `mapping_unit_clean` after operator HIL
    surfaced precheck-passes-but-Start-fails caused by a residual
    systemd unit failed-state OR a lingering `godo-mapping` container.
    """
    assert P.PRECHECK_CHECK_NAMES == (
        "lidar_readable",
        "tracker_stopped",
        "image_present",
        "disk_space_mb",
        "name_available",
        "state_clean",
        "mapping_unit_clean",
    )


def test_precheck_check_names_cardinality() -> None:
    """All 7 names must be unique."""
    assert len(P.PRECHECK_CHECK_NAMES) == 7
    assert len(set(P.PRECHECK_CHECK_NAMES)) == 7


def test_precheck_disk_free_min_mb_pinned() -> None:
    """Tier-1 mirror of the spec value. Lowering this without operator
    sign-off would let mapping start with insufficient disk."""
    assert P.PRECHECK_DISK_FREE_MIN_MB == 500


def test_issue16_error_codes_pinned() -> None:
    """issue#16 error codes. Drift fails the SPA mirror in
    `lib/protocol.ts`."""
    assert P.ERR_CP210X_RECOVERY_FAILED == "cp210x_recovery_failed"
    assert P.ERR_LIDAR_PORT_NOT_RESOLVABLE == "lidar_port_not_resolvable"
