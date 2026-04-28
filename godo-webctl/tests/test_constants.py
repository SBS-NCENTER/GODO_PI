"""
Pin every value in ``constants.py``. Changing a constant requires a
visible diff in this file — that is the whole point.

The MAX_RENAME_ATTEMPTS pin specifically guards the relocation from
``protocol.py:78`` (verified value 9) into the new webctl-internal home.
"""

from __future__ import annotations

from godo_webctl import constants as C


def test_module_imports_cleanly() -> None:
    # Leaf-module guarantee: importing constants must not pull in any
    # of the package's other modules.
    from godo_webctl import constants  # noqa: F401


def test_jwt_algorithm_pinned() -> None:
    assert C.JWT_ALGORITHM == "HS256"


def test_jwt_ttl_seconds_pinned() -> None:
    # 6 h × 3600 s.
    assert C.JWT_TTL_SECONDS == 21600


def test_bcrypt_cost_factor_pinned() -> None:
    # See module docstring + auth.py: ~300 ms on RPi 5; do not lower.
    assert C.BCRYPT_COST_FACTOR == 12


def test_sse_tick_s_pinned() -> None:
    assert C.SSE_TICK_S == 0.2


def test_sse_services_tick_s_pinned() -> None:
    assert C.SSE_SERVICES_TICK_S == 1.0


def test_sse_heartbeat_s_pinned() -> None:
    assert C.SSE_HEARTBEAT_S == 15.0


def test_map_image_cache_ttl_s_pinned() -> None:
    assert C.MAP_IMAGE_CACHE_TTL_S == 300.0


def test_activity_buffer_size_pinned() -> None:
    assert C.ACTIVITY_BUFFER_SIZE == 50


def test_journal_tail_default_n_pinned() -> None:
    assert C.JOURNAL_TAIL_DEFAULT_N == 30


def test_activity_tail_default_n_pinned() -> None:
    # Mirrors FRONT_DESIGN §7.1 DASH "last 5 activities".
    assert C.ACTIVITY_TAIL_DEFAULT_N == 5


def test_login_username_max_len_pinned() -> None:
    assert C.LOGIN_USERNAME_MAX_LEN == 64


def test_login_password_max_len_pinned() -> None:
    assert C.LOGIN_PASSWORD_MAX_LEN == 256


def test_sse_uds_timeout_s_pinned() -> None:
    # Per-poll UDS timeout for the SSE loop. Short so the loop skips on
    # tracker stall instead of stalling the stream.
    assert C.SSE_UDS_TIMEOUT_S == 0.5


def test_max_rename_attempts_relocated_value_preserved() -> None:
    # Was at protocol.py:78 with value 9; relocation must preserve it.
    assert C.MAX_RENAME_ATTEMPTS == 9
