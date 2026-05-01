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


# --- Track E (PR-C) — multi-map management constants ---------------------


def test_maps_name_max_len_pinned() -> None:
    # Hard cap shared with the regex below.
    assert C.MAPS_NAME_MAX_LEN == 64


def test_maps_active_basename_pinned() -> None:
    # Operators see this name in `ls /var/lib/godo/maps/`.
    assert C.MAPS_ACTIVE_BASENAME == "active"


def test_maps_activate_lock_basename_is_hidden() -> None:
    # Leading dot keeps it out of `list_pairs` enumeration.
    assert C.MAPS_ACTIVATE_LOCK_BASENAME == ".activate.lock"
    assert C.MAPS_ACTIVATE_LOCK_BASENAME.startswith(".")


def test_maps_name_regex_accepts_typical_stems() -> None:
    assert C.MAPS_NAME_REGEX.match("studio_v1")
    assert C.MAPS_NAME_REGEX.match("studio-v1")
    assert C.MAPS_NAME_REGEX.match("2026-04-28_v3")
    assert C.MAPS_NAME_REGEX.match("a")
    assert C.MAPS_NAME_REGEX.match("a" * 64)


def test_maps_name_regex_accepts_dot_inside_stem() -> None:
    # Operator-friendly date-style names like "04.29_1", "v1.2", "1.0(rc)".
    assert C.MAPS_NAME_REGEX.match("04.29_1")
    assert C.MAPS_NAME_REGEX.match("v1.2")
    assert C.MAPS_NAME_REGEX.match("a.b.c")


def test_maps_name_regex_accepts_parens() -> None:
    assert C.MAPS_NAME_REGEX.match("studio(1)")
    assert C.MAPS_NAME_REGEX.match("backup(test)")
    assert C.MAPS_NAME_REGEX.match("(prefix)tail")


def test_maps_name_regex_rejects_leading_dot() -> None:
    # Hidden-file forms and traversal-shaped inputs all start with '.';
    # the first-char restriction in the regex blocks them.
    assert not C.MAPS_NAME_REGEX.match(".")
    assert not C.MAPS_NAME_REGEX.match("..")
    assert not C.MAPS_NAME_REGEX.match(".hidden")
    assert not C.MAPS_NAME_REGEX.match(".activate.lock")


def test_maps_name_regex_rejects_slash() -> None:
    assert not C.MAPS_NAME_REGEX.match("foo/bar")
    assert not C.MAPS_NAME_REGEX.match("../etc/passwd")


def test_maps_name_regex_rejects_empty() -> None:
    assert not C.MAPS_NAME_REGEX.match("")


def test_maps_name_regex_rejects_too_long() -> None:
    assert not C.MAPS_NAME_REGEX.match("a" * 65)
    # Length cap also applies to dot-bearing names.
    assert not C.MAPS_NAME_REGEX.match("a" + ".a" * 32)  # 65 chars


def test_maps_name_regex_rejects_null_byte() -> None:
    assert not C.MAPS_NAME_REGEX.match("foo\x00bar")


def test_maps_name_regex_rejects_whitespace_and_unallowed() -> None:
    # Whitespace, glob, shell metas — all forbidden anywhere in the stem.
    assert not C.MAPS_NAME_REGEX.match("foo bar")
    assert not C.MAPS_NAME_REGEX.match("foo\tbar")
    assert not C.MAPS_NAME_REGEX.match("foo*bar")
    assert not C.MAPS_NAME_REGEX.match("foo;bar")
    assert not C.MAPS_NAME_REGEX.match("한글")


def test_maps_name_regex_accepts_reserved_active_name() -> None:
    # Regex itself accepts "active"; the reserved-name check lives at
    # the maps.py public-function layer (set_active / delete_pair).
    assert C.MAPS_NAME_REGEX.match("active")


def test_pgm_header_max_bytes_pinned() -> None:
    # 64 bytes comfortably fits any practical netpbm `P5` header
    # (`P5\nW H\nMAXVAL\n`); bounds `read_pgm_dimensions` against
    # streaming pixel data from a pathologically large PGM.
    assert C.PGM_HEADER_MAX_BYTES == 64


# --- PR-DIAG (Track B-DIAG) constants ------------------------------------


def test_resources_cache_ttl_pinned() -> None:
    assert C.RESOURCES_CACHE_TTL_S == 1.0


def test_logs_tail_max_n_pinned() -> None:
    assert C.LOGS_TAIL_MAX_N == 500


def test_logs_tail_default_n_pinned() -> None:
    assert C.LOGS_TAIL_DEFAULT_N == 50


def test_thermal_zone_path_pinned() -> None:
    # Standard Linux thermal_zone0 path; deviating from this on RPi 5 would
    # mean the operator is on a non-standard kernel, which is out of scope.
    assert C.THERMAL_ZONE_PATH == "/sys/class/thermal/thermal_zone0/temp"


def test_meminfo_path_pinned() -> None:
    assert C.MEMINFO_PATH == "/proc/meminfo"


# --- Track B-SYSTEM PR-2 — service observability constants ---------------


def test_system_services_cache_ttl_pinned() -> None:
    # 1 s matches the SPA's 1 Hz polling cadence.
    assert C.SYSTEM_SERVICES_CACHE_TTL_S == 1.0


def test_service_transition_messages_ko_pinned() -> None:
    """All 6 (svc, transition) tuples + their literal Korean strings.

    Particle convention (M3 fold): Korean reading convention. 트래커→가,
    웹씨티엘→이, 아이알큐 핀→이. A future writer who flips to the
    Latin-letter convention (-r as consonant → 트래커 → 이) breaks this
    test, which is the whole point.
    """
    assert C.SERVICE_TRANSITION_MESSAGES_KO == {
        ("godo-tracker", "starting"): "godo-tracker가 시동 중입니다. 잠시 후 다시 시도해주세요.",
        ("godo-tracker", "stopping"): "godo-tracker가 종료 중입니다. 잠시 후 다시 시도해주세요.",
        ("godo-webctl", "starting"): "godo-webctl이 시동 중입니다. 잠시 후 다시 시도해주세요.",
        ("godo-webctl", "stopping"): "godo-webctl이 종료 중입니다. 잠시 후 다시 시도해주세요.",
        ("godo-irq-pin", "starting"): "godo-irq-pin이 시동 중입니다. 잠시 후 다시 시도해주세요.",
        ("godo-irq-pin", "stopping"): "godo-irq-pin이 종료 중입니다. 잠시 후 다시 시도해주세요.",
    }


# --- Track B-MAPEDIT — POST /api/map/edit constants ----------------------


def test_map_edit_mask_png_max_bytes_pinned() -> None:
    # 4 MiB ceiling on the multipart `mask` part.
    assert C.MAP_EDIT_MASK_PNG_MAX_BYTES == 4_194_304


def test_map_edit_free_pixel_value_pinned() -> None:
    # Canonical "free" sentinel; 254 (NOT 255) so it does not collide
    # with uninitialised cells.
    assert C.MAP_EDIT_FREE_PIXEL_VALUE == 254


def test_map_edit_paint_threshold_pinned() -> None:
    # Greyscale mask threshold; conventional midpoint of 0..255.
    assert C.MAP_EDIT_PAINT_THRESHOLD == 128


# --- Track B-MAPEDIT-2 — POST /api/map/origin constants -----------------


def test_origin_body_max_bytes_pinned() -> None:
    # Body-size cap for `POST /api/map/origin`. Single-key JSON ~80 B
    # in practice; 256 covers full-precision floats + modest whitespace.
    assert C.ORIGIN_BODY_MAX_BYTES == 256


def test_origin_x_y_abs_max_m_pinned() -> None:
    # Magnitude bound; reviewer N2 fold accepted by Parent — 1 km covers
    # the studio (~10 m) plus 100× headroom for shared-frame debug.
    assert C.ORIGIN_X_Y_ABS_MAX_M == 1_000.0


def test_service_transition_messages_ko_covers_allowed_services() -> None:
    """Drift-catch: every ALLOWED_SERVICE has both a starting + stopping
    entry. Adding a new service to ALLOWED_SERVICES requires extending
    this dict in the same PR."""
    from godo_webctl.services import ALLOWED_SERVICES

    keys = set(C.SERVICE_TRANSITION_MESSAGES_KO.keys())
    for svc in ALLOWED_SERVICES:
        assert (svc, "starting") in keys, f"missing starting message for {svc}"
        assert (svc, "stopping") in keys, f"missing stopping message for {svc}"


# --- issue#14 — mapping pipeline constants -------------------------------


def test_mapping_runtime_dir_default_pinned() -> None:
    # M2 fix: /run is tmpfs; webctl creates the dir at runtime.
    assert C.MAPPING_RUNTIME_DIR_DEFAULT == "/run/godo/mapping"


def test_mapping_preview_subdir_pinned() -> None:
    # Hidden (dot-prefix) so MAPS_NAME_REGEX leading-dot rejection
    # filters it out of `maps.list_pairs`.
    assert C.MAPPING_PREVIEW_SUBDIR == ".preview"
    assert C.MAPPING_PREVIEW_SUBDIR.startswith(".")


def test_mapping_container_name_pinned() -> None:
    assert C.MAPPING_CONTAINER_NAME == "godo-mapping"


def test_mapping_unit_name_pinned() -> None:
    # D4: instance fixed to `active`.
    assert C.MAPPING_UNIT_NAME == "godo-mapping@active.service"


def test_mapping_image_tag_default_pinned() -> None:
    assert C.MAPPING_IMAGE_TAG_DEFAULT == "godo-mapping:dev"


def test_mapping_monitor_tick_s_pinned() -> None:
    # 1 Hz cadence; mirrors frontend MAPPING_STATUS_POLL_MS = 1000.
    assert C.MAPPING_MONITOR_TICK_S == 1.0


def test_mapping_monitor_idle_grace_s_pinned() -> None:
    assert C.MAPPING_MONITOR_IDLE_GRACE_S == 5.0


def test_mapping_tracker_stop_timeout_s_pinned() -> None:
    assert C.MAPPING_TRACKER_STOP_TIMEOUT_S == 5.0


def test_mapping_container_start_timeout_s_pinned() -> None:
    assert C.MAPPING_CONTAINER_START_TIMEOUT_S == 8.0


def test_mapping_container_stop_timeout_ordering_invariant() -> None:
    """M5 fix — the timeout ordering invariant is the load-bearing pin:

        docker stop --time grace (10s) < TimeoutStopSec (20s) < webctl_timeout (25s)

    The systemd unit's `TimeoutStopSec=20s` and the docker `--time=10`
    grace inside `ExecStop=` must satisfy this ordering. Webctl's 25 s
    is the outermost ceiling — the systemd unit kills before webctl's
    poll loop loses patience."""
    assert C.MAPPING_CONTAINER_STOP_TIMEOUT_S == 25.0
    # Sanity: must be strictly greater than the systemd TimeoutStopSec
    # value pinned in the unit file (20).
    assert C.MAPPING_CONTAINER_STOP_TIMEOUT_S > 20.0
    # And greater than the docker stop --time grace (10).
    assert C.MAPPING_CONTAINER_STOP_TIMEOUT_S > 10.0


def test_mapping_docker_inspect_poll_s_pinned() -> None:
    assert C.MAPPING_DOCKER_INSPECT_POLL_S == 0.25


def test_mapping_journal_tail_default_n_pinned() -> None:
    assert C.MAPPING_JOURNAL_TAIL_DEFAULT_N == 50


def test_mapping_journal_tail_max_n_pinned() -> None:
    assert C.MAPPING_JOURNAL_TAIL_MAX_N == 500


def test_mapping_name_regex_accepts_typical_stems() -> None:
    assert C.MAPPING_NAME_REGEX.match("studio_v1")
    assert C.MAPPING_NAME_REGEX.match("control_room_2026")
    assert C.MAPPING_NAME_REGEX.match("studio.2026.05.01")
    assert C.MAPPING_NAME_REGEX.match("(prefix)tail")
    assert C.MAPPING_NAME_REGEX.match("Date,Loc")
    assert C.MAPPING_NAME_REGEX.match("a")
    assert C.MAPPING_NAME_REGEX.match("a" * 64)


def test_mapping_name_regex_rejects_leading_dot() -> None:
    """C5 fix — leading-dot REJECTED. Operator-locked 2026-05-01."""
    assert not C.MAPPING_NAME_REGEX.match(".foo")
    assert not C.MAPPING_NAME_REGEX.match("..bar")
    assert not C.MAPPING_NAME_REGEX.match(".hidden")
    assert not C.MAPPING_NAME_REGEX.match(".")


def test_mapping_name_regex_rejects_whitespace() -> None:
    assert not C.MAPPING_NAME_REGEX.match("foo bar")
    assert not C.MAPPING_NAME_REGEX.match("foo\tbar")


def test_mapping_name_regex_rejects_too_long() -> None:
    assert not C.MAPPING_NAME_REGEX.match("a" * 65)


def test_mapping_name_regex_rejects_empty() -> None:
    assert not C.MAPPING_NAME_REGEX.match("")


def test_mapping_name_max_len_pinned() -> None:
    assert C.MAPPING_NAME_MAX_LEN == 64


def test_mapping_reserved_names_pinned() -> None:
    assert frozenset({".", "..", "active"}) == C.MAPPING_RESERVED_NAMES


def test_mapping_docker_stats_timeout_s_pinned() -> None:
    assert C.MAPPING_DOCKER_STATS_TIMEOUT_S == 3.0


def test_mapping_docker_inspect_timeout_s_pinned() -> None:
    assert C.MAPPING_DOCKER_INSPECT_TIMEOUT_S == 2.0


def test_mapping_du_timeout_s_pinned() -> None:
    assert C.MAPPING_DU_TIMEOUT_S == 2.0
