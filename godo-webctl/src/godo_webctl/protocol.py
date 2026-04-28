"""
UDS wire-protocol constants. Mirrors a subset of the C++ Tier-1 invariants
in production/RPi5/src/core/{constants.hpp, rt_flags.hpp} that appear ON
THE WIRE (request max bytes, command names, mode names, error codes).

This module deliberately does NOT mirror tracker-internal Tier-1: FreeD
packet layout (FREED_*), RT cadence (FRAME_PERIOD_NS), AMCL kernel sizes
(PARTICLE_BUFFER_MAX, EDT_MAX_CELLS), GPIO debounce window
(GPIO_DEBOUNCE_NS), shutdown timeout (SHUTDOWN_POLL_TIMEOUT_MS). Those
are C++-only and webctl never sees them.

Cross-language drift policy: see godo-webctl/CODEBASE.md invariant (b).
SSOT for the wire format is production/RPi5/doc/uds_protocol.md.
"""

from __future__ import annotations

from typing import Final

from .constants import MAPS_NAME_REGEX

# --- Bytes on the wire (mirrors constants.hpp) ----------------------------
# UDS_REQUEST_MAX_BYTES: production/RPi5/src/core/constants.hpp:54
UDS_REQUEST_MAX_BYTES: Final[int] = 4096

# Client-side response read cap. Matches the server's request cap; responses
# are far smaller in practice (~30 bytes), but we share the bound so the
# read loop has a single ceiling.
UDS_RESPONSE_READ_BUFSIZE: Final[int] = 4096

# --- Command names (mirrors uds_server.cpp:201,206,212 — req.cmd compares) -
CMD_PING: Final[str] = "ping"  # uds_server.cpp:201
CMD_GET_MODE: Final[str] = "get_mode"  # uds_server.cpp:206
CMD_SET_MODE: Final[str] = "set_mode"  # uds_server.cpp:212
# Track B (Phase 4-2 D Track B) — uds_server.cpp `get_last_pose` branch
# below the `set_mode` branch. Field-name SSOT is the format string in
# production/RPi5/src/uds/json_mini.cpp::format_ok_pose; LAST_POSE_FIELDS
# below is regex-pinned against that source by tests/test_protocol.py.
CMD_GET_LAST_POSE: Final[str] = "get_last_pose"

# --- Mode names (mirrors json_mini.cpp:119-121 mode_to_string + :127-129) -
MODE_IDLE: Final[str] = "Idle"  # json_mini.cpp:119, :127
MODE_ONESHOT: Final[str] = "OneShot"  # json_mini.cpp:120, :128
MODE_LIVE: Final[str] = "Live"  # json_mini.cpp:121, :129

VALID_MODES: Final[frozenset[str]] = frozenset({MODE_IDLE, MODE_ONESHOT, MODE_LIVE})

# --- Track B: get_last_pose response field order --------------------------
# SOLE Python mirror of the field names embedded in the C++ wire format
# string. Order MUST match production/RPi5/src/uds/json_mini.cpp::
# format_ok_pose verbatim. tests/test_protocol.py reads the C++ source as
# text, regex-extracts field names from the format-string literal, and
# asserts byte-equal against this tuple — so editing one side without the
# other fails the drift pin.
#
# `ok` is intentionally NOT in this tuple: it is the JSON-level success
# flag (always true for get_last_pose; error responses use the standard
# {"ok":false,"err":...} shape and are surfaced via UdsError).
LAST_POSE_FIELDS: Final[tuple[str, ...]] = (
    "valid",
    "x_m",
    "y_m",
    "yaw_deg",
    "xy_std_m",
    "yaw_std_deg",
    "iterations",
    "converged",
    "forced",
    "published_mono_ns",
)

# --- Error codes (mirrors json_mini.cpp::format_err callers) --------------
ERR_PARSE_ERROR: Final[str] = "parse_error"  # json_mini.cpp callers
ERR_UNKNOWN_CMD: Final[str] = "unknown_cmd"  # uds_server.cpp:225
ERR_BAD_MODE: Final[str] = "bad_mode"  # json_mini.cpp:215 caller

# --- Track E (PR-C) — multi-map error codes ------------------------------
# These are webctl-internal (no C++ wire counterpart) but live here so
# the frontend mirror can be derived from a single source.
ERR_INVALID_MAP_NAME: Final[str] = "invalid_map_name"
ERR_MAP_NOT_FOUND: Final[str] = "map_not_found"
ERR_MAP_IS_ACTIVE: Final[str] = "map_is_active"
ERR_MAPS_DIR_MISSING: Final[str] = "maps_dir_missing"

# Mirror the regex pattern as a string so the SPA can do client-side
# validation without depending on a Python regex parse. Frontend file:
# `godo-frontend/src/lib/protocol.ts::MAPS_NAME_REGEX_PATTERN_STR`.
MAPS_NAME_REGEX_PATTERN_STR: Final[str] = MAPS_NAME_REGEX.pattern


# --- Canonical request encoders -------------------------------------------
# The server tolerates whitespace + arbitrary key order, but the client MUST
# emit canonical form (declaration order, no whitespace, ASCII, single
# trailing '\n') so the server's request log is grep-able and the wire test
# is byte-exact.
def encode_ping() -> bytes:
    """Canonical wire encoding of the ``ping`` request."""
    return b'{"cmd":"ping"}\n'


def encode_get_mode() -> bytes:
    """Canonical wire encoding of the ``get_mode`` request."""
    return b'{"cmd":"get_mode"}\n'


def encode_set_mode(mode: str) -> bytes:
    """Canonical wire encoding of ``set_mode`` for a validated mode name."""
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    return b'{"cmd":"set_mode","mode":"' + mode.encode("ascii") + b'"}\n'


def encode_get_last_pose() -> bytes:
    """Canonical wire encoding of the Track B ``get_last_pose`` request."""
    return b'{"cmd":"get_last_pose"}\n'
