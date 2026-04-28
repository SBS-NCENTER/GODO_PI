"""
Settings loader for godo-webctl.

Pure stdlib: dataclass + env. No Pydantic, no TOML — surface is too small to
justify the extra dep. Tier-2 (operator-tunable) values come from
``os.environ`` with documented defaults; cast failures raise ``ConfigError``
naming the offending env var.

The three paired tables ``_DEFAULTS`` / ``_PARSERS`` / ``_ENV_TO_FIELD`` are
the SSOT for both code (``load_settings``) and tests
(``test_config.py::test_defaults_match_settings``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


class ConfigError(ValueError):
    """Raised when an env value cannot be parsed into its target type."""


def _parse_optional_path(raw: str) -> Path | None:
    """Empty string → ``None``; anything else → ``Path``."""
    return Path(raw) if raw else None


def _parse_bool(raw: str) -> bool:
    """Accept the obvious truthy/falsy tokens; reject ambiguity loudly."""
    s = raw.strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"not a boolean: {raw!r}")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    uds_socket: Path
    backup_dir: Path
    map_path: Path
    health_uds_timeout_s: float
    calibrate_uds_timeout_s: float
    jwt_secret_path: Path
    users_file: Path
    spa_dist: Path | None
    chromium_loopback_only: bool


# Documented defaults — single source for code + README + systemd env-file.
_DEFAULTS: Final[dict[str, str]] = {
    "GODO_WEBCTL_HOST": "127.0.0.1",
    "GODO_WEBCTL_PORT": "8080",
    "GODO_WEBCTL_UDS_SOCKET": "/run/godo/ctl.sock",
    "GODO_WEBCTL_BACKUP_DIR": "/var/lib/godo/map-backups",
    "GODO_WEBCTL_MAP_PATH": "/etc/godo/maps/studio_v1.pgm",
    "GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S": "2.0",
    "GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S": "30.0",
    "GODO_WEBCTL_JWT_SECRET_PATH": "/var/lib/godo/auth/jwt_secret",
    "GODO_WEBCTL_USERS_FILE": "/var/lib/godo/auth/users.json",
    "GODO_WEBCTL_SPA_DIST": "",
    "GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY": "true",
}

# Per-field parser. Same keys (in same order) as _DEFAULTS.
_PARSERS: Final[dict[str, Callable[[str], Any]]] = {
    "GODO_WEBCTL_HOST": str,
    "GODO_WEBCTL_PORT": int,
    "GODO_WEBCTL_UDS_SOCKET": Path,
    "GODO_WEBCTL_BACKUP_DIR": Path,
    "GODO_WEBCTL_MAP_PATH": Path,
    "GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S": float,
    "GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S": float,
    "GODO_WEBCTL_JWT_SECRET_PATH": Path,
    "GODO_WEBCTL_USERS_FILE": Path,
    "GODO_WEBCTL_SPA_DIST": _parse_optional_path,
    "GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY": _parse_bool,
}

# env-var name → Settings field name. Drift between this and the dataclass
# is caught by test_config.py::test_defaults_match_settings.
_ENV_TO_FIELD: Final[dict[str, str]] = {
    "GODO_WEBCTL_HOST": "host",
    "GODO_WEBCTL_PORT": "port",
    "GODO_WEBCTL_UDS_SOCKET": "uds_socket",
    "GODO_WEBCTL_BACKUP_DIR": "backup_dir",
    "GODO_WEBCTL_MAP_PATH": "map_path",
    "GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S": "health_uds_timeout_s",
    "GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S": "calibrate_uds_timeout_s",
    "GODO_WEBCTL_JWT_SECRET_PATH": "jwt_secret_path",
    "GODO_WEBCTL_USERS_FILE": "users_file",
    "GODO_WEBCTL_SPA_DIST": "spa_dist",
    "GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY": "chromium_loopback_only",
}


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build a ``Settings`` from the given env mapping (or ``os.environ``)."""
    import os

    src: Mapping[str, str] = env if env is not None else os.environ

    parsed: dict[str, Any] = {}
    for key, default in _DEFAULTS.items():
        raw = src.get(key, default)
        parser = _PARSERS[key]
        try:
            parsed[_ENV_TO_FIELD[key]] = parser(raw)
        except (ValueError, TypeError) as e:
            raise ConfigError(f"{key}: cannot parse {raw!r} as {parser.__name__}") from e
    return Settings(**parsed)
