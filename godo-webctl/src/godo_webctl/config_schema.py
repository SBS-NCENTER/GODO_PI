"""
Track B-CONFIG (PR-CONFIG-β) — Python mirror of
``production/RPi5/src/core/config_schema.hpp``.

The C++ source is the SSOT. This module regex-extracts the constexpr
``ConfigSchemaRow`` table at process startup, parses each row into a
``ConfigSchemaRow`` NamedTuple, and caches the result. The
``// clang-format off`` block in the C++ header keeps each row on its
own line so the regex stays robust against future formatter runs.

Drift detection: ``tests/test_config_schema_parity.py`` loads the same
source file by real path (mirrors the LAST_POSE_FIELDS pin in
``tests/test_protocol.py``), asserts row count + per-key field set
equality. CI fails on any drift.

Usage::

    from godo_webctl.config_schema import load_schema
    rows = load_schema()
    assert len(rows) == 46
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final, NamedTuple


class ConfigSchemaError(RuntimeError):
    """Raised when the C++ source cannot be parsed (developer broke it)."""


class ConfigSchemaRow(NamedTuple):
    """One row of the Tier-2 schema. Parsed verbatim from the C++ source.

    `min_d` / `max_d` are zero for ``string`` rows — the C++ struct uses
    them as numeric range placeholders that the validator only consults
    for Int / Double. Mirror that here so the wire shape stays uniform.
    """

    name: str
    type: str  # "int" | "double" | "string"
    min_d: float
    max_d: float
    default_repr: str
    reload_class: str  # "hot" | "restart" | "recalibrate"
    description: str


# Path resolution: tiered.
#
# 1. `GODO_WEBCTL_CONFIG_SCHEMA_PATH` env var, if set — operator override.
#    The systemd unit's EnvironmentFile=/etc/godo/webctl.env carries this
#    on production hosts, where the dev-tree layout assumption below
#    fails (godo-webctl is at /opt/godo-webctl while the tracker source
#    has been copied separately to /opt/godo-tracker/share/).
# 2. Dev-tree sibling layout — `<repo>/godo-webctl/...` and
#    `<repo>/production/RPi5/...` cohabit. This is the path on
#    contributor machines (Mac/Windows/Linux dev hosts).
# 3. `/opt/godo-tracker/share/config_schema.hpp` — production install
#    convention (see `production/RPi5/systemd/install.sh`). Used only
#    if (1) is unset, so the env override remains authoritative.
import os

_DEV_TREE_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3]
    / "production" / "RPi5" / "src" / "core" / "config_schema.hpp"
)
_PROD_FALLBACK_PATH: Final[Path] = Path(
    "/opt/godo-tracker/share/config_schema.hpp",
)


def _resolve_schema_path() -> Path:
    """Return the first existing candidate from (env var, dev tree, prod
    fallback). The fallback chain matters: dev hosts expect dev-tree
    discovery to "just work" without setting an env var, while prod
    hosts can either set the env var explicitly or land on the
    `/opt/godo-tracker/share/` convention. Returns the env-var path
    even if non-existent (so the error message names what the
    operator configured)."""
    override = os.environ.get("GODO_WEBCTL_CONFIG_SCHEMA_PATH")
    if override:
        return Path(override)
    if _DEV_TREE_PATH.exists():
        return _DEV_TREE_PATH
    return _PROD_FALLBACK_PATH


_CPP_SCHEMA_PATH: Final[Path] = _resolve_schema_path()

# Row matcher. The C++ array layout is one initializer per line:
#   {"key.name", ValueType::Double, 0.0, 1.0, "0.5", ReloadClass::Hot, "desc"},
# We capture each component group; the description allows escaped quotes.
_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"\{\s*"
    r'"(?P<name>[^"]+)"\s*,\s*'
    r"ValueType::(?P<type>Int|Double|String)\s*,\s*"
    r"(?P<min>-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s*,\s*"
    r"(?P<max>-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s*,\s*"
    r'"(?P<default>(?:[^"\\]|\\.)*)"\s*,\s*'
    r"ReloadClass::(?P<reload>Hot|Restart|Recalibrate)\s*,\s*"
    r'"(?P<desc>(?:[^"\\]|\\.)*)"\s*'
    r"\}",
)

# The static_assert pin in the C++ source gives us a compile-time row
# count. We mirror it here so the loader can early-detect a mismatch and
# raise a clear error instead of silently shipping a short list.
EXPECTED_ROW_COUNT: Final[int] = 46

_VALUE_TYPE_MAP: Final[dict[str, str]] = {
    "Int": "int",
    "Double": "double",
    "String": "string",
}

_RELOAD_MAP: Final[dict[str, str]] = {
    "Hot": "hot",
    "Restart": "restart",
    "Recalibrate": "recalibrate",
}

# Module-level cache. Populated lazily on first `load_schema()`; the
# parse is deterministic for the same source file mtime + content, so
# we never need to invalidate within a process lifetime. (The schema
# is C++ Tier-1 — adding a row requires a tracker rebuild.)
_CACHE: tuple[ConfigSchemaRow, ...] | None = None


def _parse_source(source_text: str) -> tuple[ConfigSchemaRow, ...]:
    """Parse a raw `config_schema.hpp` text into rows.

    Public for tests (``test_config_schema.py`` constructs synthetic
    fixtures + the real source). Production uses ``load_schema()``.
    """
    rows: list[ConfigSchemaRow] = []
    for m in _ROW_RE.finditer(source_text):
        rows.append(
            ConfigSchemaRow(
                name=m["name"],
                type=_VALUE_TYPE_MAP[m["type"]],
                min_d=float(m["min"]),
                max_d=float(m["max"]),
                default_repr=m["default"],
                reload_class=_RELOAD_MAP[m["reload"]],
                description=m["desc"],
            ),
        )
    return tuple(rows)


def load_schema(source_path: Path | None = None) -> tuple[ConfigSchemaRow, ...]:
    """Return the cached schema, parsing the C++ source on first call.

    `source_path` is for tests; production callers omit it.
    """
    global _CACHE
    if source_path is not None:
        # Test path — bypass the cache entirely so a fixture can be
        # parsed without poisoning the production cache.
        text = source_path.read_text(encoding="utf-8")
        rows = _parse_source(text)
        if len(rows) != EXPECTED_ROW_COUNT:
            raise ConfigSchemaError(
                f"parsed {len(rows)} rows from {source_path}, expected {EXPECTED_ROW_COUNT}",
            )
        return rows

    if _CACHE is not None:
        return _CACHE

    if not _CPP_SCHEMA_PATH.exists():
        raise ConfigSchemaError(
            f"C++ schema source not found at {_CPP_SCHEMA_PATH}. Set "
            "GODO_WEBCTL_CONFIG_SCHEMA_PATH to override, or ensure the dev "
            "tree layout (godo-webctl is a sibling of production/RPi5) "
            "or the production install (`/opt/godo-tracker/share/"
            "config_schema.hpp` from `production/RPi5/systemd/install.sh`).",
        )
    text = _CPP_SCHEMA_PATH.read_text(encoding="utf-8")
    rows = _parse_source(text)
    if len(rows) != EXPECTED_ROW_COUNT:
        raise ConfigSchemaError(
            f"parsed {len(rows)} rows from {_CPP_SCHEMA_PATH}, expected {EXPECTED_ROW_COUNT}",
        )
    _CACHE = rows
    return rows


def schema_to_json(rows: tuple[ConfigSchemaRow, ...]) -> list[dict[str, object]]:
    """Project a schema tuple to a JSON-serialisable list-of-dicts.

    Field shape matches the C++ ``apply_get_schema`` JSON output exactly
    (modulo dict key ordering, which Python preserves on insertion).
    """
    return [
        {
            "name": r.name,
            "type": r.type,
            "min": r.min_d,
            "max": r.max_d,
            "default": r.default_repr,
            "reload_class": r.reload_class,
            "description": r.description,
        }
        for r in rows
    ]


def reset_cache_for_tests() -> None:
    """Clear the module cache. ONLY for tests that swap the source file."""
    global _CACHE
    _CACHE = None
