"""
issue#12 — webctl-side reader for the `[webctl]` section of
``/var/lib/godo/tracker.toml``.

The two keys ``pose_stream_hz`` and ``scan_stream_hz`` live in the
tracker's ``CONFIG_SCHEMA[]`` so the SPA's schema-driven Config tab can
edit them, but no tracker logic path consumes the value (see
``production/RPi5/CODEBASE.md`` invariant (r) — Config carries the
fields verbatim through ``apply_one`` + ``read_effective`` +
``render_toml`` only). godo-webctl is the sole consumer.

Precedence (highest first):

1. Env var: ``GODO_WEBCTL_POSE_STREAM_HZ`` / ``GODO_WEBCTL_SCAN_STREAM_HZ``.
2. TOML: ``[webctl]`` table in the file at ``toml_path``.
3. Schema defaults: 30 Hz for both keys.

A missing TOML file is NOT an error — defaults apply silently. A
malformed TOML, an out-of-range integer, or a non-integer value raises
``WebctlTomlError`` with the offending key in the message.

Atomic-rename note: the tracker writes ``tracker.toml`` via
``atomic_toml_writer.cpp`` (``mkstemp + fsync + rename``) so a
concurrent ``read_webctl_section`` call cannot observe a half-written
file. The reader either sees the OLD content (rename hasn't completed)
or the NEW content (rename completed); both are valid by construction.

Leaf module: depends on stdlib only — no other ``godo_webctl`` import
back-edges. ``sse.py`` imports this module; this module imports
nothing from the package. Range constants live HERE (not in
``constants.py``) so the dep edge stays ``sse.py → webctl_toml.py
→ stdlib``.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Final, NamedTuple

# Defaults locked here (no magic numbers in business logic per CLAUDE.md
# §6). Tracker schema row defaults match these byte-exactly.
WEBCTL_POSE_STREAM_HZ_DEFAULT: Final[int] = 30
WEBCTL_SCAN_STREAM_HZ_DEFAULT: Final[int] = 30

# Range bounds match the C++ schema row's (min_d, max_d) for
# ``webctl.pose_stream_hz`` / ``webctl.scan_stream_hz`` — defence in
# depth: tracker validates via apply_set; webctl re-validates here when
# reading the rendered TOML so a manually-edited tracker.toml that
# bypassed the SPA still gets a clear error at startup.
WEBCTL_STREAM_HZ_MIN: Final[int] = 1
WEBCTL_STREAM_HZ_MAX: Final[int] = 60

# Env var names. Mirror the CLI / schema convention (UPPERCASE +
# underscored prefix matching `GODO_WEBCTL_*`).
_ENV_POSE_KEY: Final[str] = "GODO_WEBCTL_POSE_STREAM_HZ"
_ENV_SCAN_KEY: Final[str] = "GODO_WEBCTL_SCAN_STREAM_HZ"


class WebctlTomlError(ValueError):
    """Raised on malformed TOML / out-of-range value / non-integer value.

    The message includes the offending key (or env var name) so a
    startup-log WARNING is actionable without diff-checking the file.
    """


class WebctlSection(NamedTuple):
    """Resolved webctl-owned config values, ready for SSE producers."""

    pose_stream_hz: int
    scan_stream_hz: int


def _coerce_int(raw: object, key: str) -> int:
    """Accept ``int`` (TOML's native integer) or a digit-only ``str``
    (for env var values), reject anything else."""
    if isinstance(raw, bool):
        # bool is a subclass of int; reject it explicitly so
        # ``pose_stream_hz = true`` does not silently coerce to 1.
        raise WebctlTomlError(f"{key}: must be an integer (got bool)")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw, 10)
        except ValueError as e:
            raise WebctlTomlError(f"{key}: not a valid integer: {raw!r}") from e
    raise WebctlTomlError(f"{key}: must be an integer (got {type(raw).__name__})")


def _validate_range(value: int, key: str) -> int:
    if not (WEBCTL_STREAM_HZ_MIN <= value <= WEBCTL_STREAM_HZ_MAX):
        raise WebctlTomlError(
            f"{key}: {value} out of range "
            f"[{WEBCTL_STREAM_HZ_MIN}, {WEBCTL_STREAM_HZ_MAX}]",
        )
    return value


def _read_toml_section(toml_path: Path) -> dict[str, object]:
    """Return the ``[webctl]`` table or an empty dict.

    Missing file → empty (defaults will apply). Malformed file →
    ``WebctlTomlError`` with the parse error chained.
    """
    if not toml_path.exists():
        return {}
    try:
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise WebctlTomlError(
            f"failed to parse {toml_path}: {e}",
        ) from e
    section = data.get("webctl", {})
    if not isinstance(section, dict):
        raise WebctlTomlError(
            f"{toml_path}: [webctl] is not a table (got {type(section).__name__})",
        )
    return section


def _resolve_one(
    *,
    toml_value: object | None,
    env_value: str | None,
    default: int,
    toml_key: str,
    env_key: str,
) -> int:
    """Apply the precedence ladder: env > TOML > default. Each layer
    runs through type + range validation.

    Forward-compat: tracker-unrelated keys in ``[webctl]`` (e.g. future
    additions) are tolerated by ``read_webctl_section`` — only the two
    keys this module knows about are validated. Drift surfaces in
    parity tests, not at runtime.
    """
    if env_value is not None:
        coerced = _coerce_int(env_value, env_key)
        return _validate_range(coerced, env_key)
    if toml_value is not None:
        coerced = _coerce_int(toml_value, toml_key)
        return _validate_range(coerced, toml_key)
    return default


# --- issue#14: tracker-owned serial section reader ----------------------
# Mirror of the `[serial]` table the tracker writes to tracker.toml. webctl
# READS this table for the mapping pipeline (LiDAR USB device path) but
# does NOT own the keys — the SSOT is
# `production/RPi5/src/core/config_schema.hpp:120` (`serial.lidar_port`).
# DO NOT add `serial_lidar_port` to `WebctlSection` (PR #63 lock-in).
TRACKER_SERIAL_LIDAR_PORT_DEFAULT: Final[str] = "/dev/ttyUSB0"


class TrackerSerialSection(NamedTuple):
    """Tracker-owned `[serial]` table values consumed by webctl.

    Fields:
        lidar_port: TOML `[serial] lidar_port` (canonical dotted name
            `serial.lidar_port`). Default ``/dev/ttyUSB0`` matches the
            tracker schema row default at
            `production/RPi5/src/core/config_schema.hpp:120`.
    """

    lidar_port: str


def read_tracker_serial_section(toml_path: Path) -> TrackerSerialSection:
    """Read the tracker-owned `[serial]` table.

    Returns the lidar_port string (verbatim from TOML) or the schema
    default. Missing file / missing table / missing key all silently
    fall back to the default — matches the discipline of
    ``read_webctl_section``. Malformed TOML raises ``WebctlTomlError``.

    Note: this helper does NOT validate the value (the path may not
    exist on this host; the operator might have udev-renamed it). The
    tracker's apply_set already validated it before writing the TOML.
    """
    if not toml_path.exists():
        return TrackerSerialSection(lidar_port=TRACKER_SERIAL_LIDAR_PORT_DEFAULT)
    try:
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise WebctlTomlError(
            f"failed to parse {toml_path}: {e}",
        ) from e
    section = data.get("serial", {})
    if not isinstance(section, dict):
        raise WebctlTomlError(
            f"{toml_path}: [serial] is not a table (got {type(section).__name__})",
        )
    raw = section.get("lidar_port")
    if raw is None:
        return TrackerSerialSection(lidar_port=TRACKER_SERIAL_LIDAR_PORT_DEFAULT)
    if not isinstance(raw, str):
        raise WebctlTomlError(
            f"serial.lidar_port: must be a string (got {type(raw).__name__})",
        )
    if not raw:
        return TrackerSerialSection(lidar_port=TRACKER_SERIAL_LIDAR_PORT_DEFAULT)
    return TrackerSerialSection(lidar_port=raw)


def read_webctl_section(
    toml_path: Path,
    env: Mapping[str, str] | None = None,
) -> WebctlSection:
    """Resolve the SSE pose/scan stream cadence keys.

    Args:
        toml_path: Filesystem path to the tracker's ``tracker.toml``
            (typically ``/var/lib/godo/tracker.toml``).
        env: Mapping for env-var lookup; defaults to ``os.environ``
            when ``None``. Tests use a fixed dict so ``monkeypatch``
            edits to the real env don't bleed across cases.

    Returns:
        ``WebctlSection`` carrying the resolved integer values.

    Raises:
        WebctlTomlError: malformed TOML, non-integer value, or
            out-of-range integer in any precedence layer that supplied
            a value.
    """
    src: Mapping[str, str] = env if env is not None else os.environ
    section = _read_toml_section(toml_path)

    pose = _resolve_one(
        toml_value=section.get("pose_stream_hz"),
        env_value=src.get(_ENV_POSE_KEY),
        default=WEBCTL_POSE_STREAM_HZ_DEFAULT,
        toml_key="webctl.pose_stream_hz",
        env_key=_ENV_POSE_KEY,
    )
    scan = _resolve_one(
        toml_value=section.get("scan_stream_hz"),
        env_value=src.get(_ENV_SCAN_KEY),
        default=WEBCTL_SCAN_STREAM_HZ_DEFAULT,
        toml_key="webctl.scan_stream_hz",
        env_key=_ENV_SCAN_KEY,
    )
    return WebctlSection(pose_stream_hz=pose, scan_stream_hz=scan)
