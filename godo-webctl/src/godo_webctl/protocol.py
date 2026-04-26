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

# --- Mode names (mirrors json_mini.cpp:119-121 mode_to_string + :127-129) -
MODE_IDLE: Final[str] = "Idle"  # json_mini.cpp:119, :127
MODE_ONESHOT: Final[str] = "OneShot"  # json_mini.cpp:120, :128
MODE_LIVE: Final[str] = "Live"  # json_mini.cpp:121, :129

VALID_MODES: Final[frozenset[str]] = frozenset({MODE_IDLE, MODE_ONESHOT, MODE_LIVE})

# --- Error codes (mirrors json_mini.cpp::format_err callers) --------------
ERR_PARSE_ERROR: Final[str] = "parse_error"  # json_mini.cpp callers
ERR_UNKNOWN_CMD: Final[str] = "unknown_cmd"  # uds_server.cpp:225
ERR_BAD_MODE: Final[str] = "bad_mode"  # json_mini.cpp:215 caller

# --- Backup-side Tier-1 (webctl-internal) ---------------------------------
# Bound on rename collision retries inside backup.backup_map. Above 9 means
# more than 9 backups in the same UTC second, which never happens in practice.
MAX_RENAME_ATTEMPTS: Final[int] = 9


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
