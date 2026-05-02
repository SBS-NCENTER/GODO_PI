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

from .constants import (
    MAPPING_CONTAINER_STOP_TIMEOUT_S,
    MAPPING_IMAGE_TAG_DEFAULT,
    MAPPING_RUNTIME_DIR_DEFAULT,
)


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
    maps_dir: Path
    health_uds_timeout_s: float
    calibrate_uds_timeout_s: float
    jwt_secret_path: Path
    users_file: Path
    spa_dist: Path | None
    chromium_loopback_only: bool
    # PR-DIAG: filesystem path os.statvfs() targets when computing disk
    # usage in resources.snapshot(). Override via
    # GODO_WEBCTL_DISK_CHECK_PATH for tests + alternate deployments.
    disk_check_path: Path
    # Track B-CONFIG (PR-CONFIG-β): tracker writes a sentinel here when
    # a `restart`/`recalibrate`-class config edit lands. Webctl reads
    # via `restart_pending.is_pending()`. Override via
    # GODO_WEBCTL_RESTART_PENDING_PATH.
    restart_pending_path: Path
    # Single-instance pidfile lock target. ``__main__.main()`` acquires
    # ``fcntl.flock`` on this file BEFORE ``uvicorn.run``. Tests override
    # via GODO_WEBCTL_PIDFILE so they never touch /run/godo. Path MUST
    # live on a local FS — tmpfs /run/godo is the project default; NFS
    # is unsupported (flock semantics differ).
    pidfile_path: Path
    # issue#12: source TOML for the webctl-owned ``[webctl]`` section
    # (``pose_stream_hz`` / ``scan_stream_hz``). Tracker writes this
    # file via atomic-rename; webctl reads it via
    # ``webctl_toml.read_webctl_section``. Tests override via
    # GODO_WEBCTL_TRACKER_TOML_PATH so they point at a tmp_path fixture
    # instead of ``/var/lib/godo/tracker.toml``.
    tracker_toml_path: Path
    # issue#14: mapping pipeline runtime directory. webctl writes
    # ``<dir>/active.env`` + ``<dir>/state.json`` here. /run is tmpfs;
    # webctl creates the dir at runtime (M2 fix — no install-time seed).
    mapping_runtime_dir: Path
    # issue#14: Docker image tag passed via the systemd envfile. Default
    # ``godo-mapping:dev`` matches what `docker build` emits.
    mapping_image_tag: str
    # issue#14: docker binary location. /usr/bin/docker on Debian/Trixie.
    # Tests override via GODO_WEBCTL_DOCKER_BIN to point at a fake path.
    docker_bin: Path
    # issue#14 Maj-1: webctl-side mapping.stop() polling deadline (seconds).
    # Sourced from the [webctl] section of tracker.toml via
    # webctl_toml.read_webctl_section; env override
    # GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S overrides the TOML value.
    # Pairs with `webctl.mapping_systemd_stop_timeout_s` (in the unit
    # file, sed-substituted by install.sh) and
    # `webctl.mapping_docker_stop_grace_s` (in the unit file's
    # `docker stop --time=` argument). Ordering invariant:
    #     docker_grace < systemd_timeout < webctl_timeout
    # is enforced inside `webctl_toml.read_webctl_section` at startup.
    # The raw constant `MAPPING_CONTAINER_STOP_TIMEOUT_S` in
    # `constants.py` is the FALLBACK default (35 s); runtime code reads
    # this `Settings` field.
    mapping_webctl_stop_timeout_s: float


# Documented defaults — single source for code + README + systemd env-file.
_DEFAULTS: Final[dict[str, str]] = {
    "GODO_WEBCTL_HOST": "127.0.0.1",
    "GODO_WEBCTL_PORT": "8080",
    "GODO_WEBCTL_UDS_SOCKET": "/run/godo/ctl.sock",
    "GODO_WEBCTL_BACKUP_DIR": "/var/lib/godo/map-backups",
    "GODO_WEBCTL_MAP_PATH": "/etc/godo/maps/studio_v1.pgm",
    "GODO_WEBCTL_MAPS_DIR": "/var/lib/godo/maps",
    "GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S": "2.0",
    "GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S": "30.0",
    "GODO_WEBCTL_JWT_SECRET_PATH": "/var/lib/godo/auth/jwt_secret",
    "GODO_WEBCTL_USERS_FILE": "/var/lib/godo/auth/users.json",
    "GODO_WEBCTL_SPA_DIST": "",
    "GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY": "true",
    "GODO_WEBCTL_DISK_CHECK_PATH": "/",
    "GODO_WEBCTL_RESTART_PENDING_PATH": "/var/lib/godo/restart_pending",
    "GODO_WEBCTL_PIDFILE": "/run/godo/godo-webctl.pid",
    "GODO_WEBCTL_TRACKER_TOML_PATH": "/var/lib/godo/tracker.toml",
    "GODO_WEBCTL_MAPPING_RUNTIME_DIR": MAPPING_RUNTIME_DIR_DEFAULT,
    "GODO_WEBCTL_MAPPING_IMAGE_TAG": MAPPING_IMAGE_TAG_DEFAULT,
    "GODO_WEBCTL_DOCKER_BIN": "/usr/bin/docker",
    # issue#14 Maj-1 — Settings fallback default. Runtime value typically
    # comes from the [webctl] section of tracker.toml, but if Settings
    # is constructed without going through the TOML reader (tests, dev
    # scripts) this default keeps the field finite.
    "GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S": str(MAPPING_CONTAINER_STOP_TIMEOUT_S),
}

# Per-field parser. Same keys (in same order) as _DEFAULTS.
_PARSERS: Final[dict[str, Callable[[str], Any]]] = {
    "GODO_WEBCTL_HOST": str,
    "GODO_WEBCTL_PORT": int,
    "GODO_WEBCTL_UDS_SOCKET": Path,
    "GODO_WEBCTL_BACKUP_DIR": Path,
    "GODO_WEBCTL_MAP_PATH": Path,
    "GODO_WEBCTL_MAPS_DIR": Path,
    "GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S": float,
    "GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S": float,
    "GODO_WEBCTL_JWT_SECRET_PATH": Path,
    "GODO_WEBCTL_USERS_FILE": Path,
    "GODO_WEBCTL_SPA_DIST": _parse_optional_path,
    "GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY": _parse_bool,
    "GODO_WEBCTL_DISK_CHECK_PATH": Path,
    "GODO_WEBCTL_RESTART_PENDING_PATH": Path,
    "GODO_WEBCTL_PIDFILE": Path,
    "GODO_WEBCTL_TRACKER_TOML_PATH": Path,
    "GODO_WEBCTL_MAPPING_RUNTIME_DIR": Path,
    "GODO_WEBCTL_MAPPING_IMAGE_TAG": str,
    "GODO_WEBCTL_DOCKER_BIN": Path,
    "GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S": float,
}

# env-var name → Settings field name. Drift between this and the dataclass
# is caught by test_config.py::test_defaults_match_settings.
_ENV_TO_FIELD: Final[dict[str, str]] = {
    "GODO_WEBCTL_HOST": "host",
    "GODO_WEBCTL_PORT": "port",
    "GODO_WEBCTL_UDS_SOCKET": "uds_socket",
    "GODO_WEBCTL_BACKUP_DIR": "backup_dir",
    "GODO_WEBCTL_MAP_PATH": "map_path",
    "GODO_WEBCTL_MAPS_DIR": "maps_dir",
    "GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S": "health_uds_timeout_s",
    "GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S": "calibrate_uds_timeout_s",
    "GODO_WEBCTL_JWT_SECRET_PATH": "jwt_secret_path",
    "GODO_WEBCTL_USERS_FILE": "users_file",
    "GODO_WEBCTL_SPA_DIST": "spa_dist",
    "GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY": "chromium_loopback_only",
    "GODO_WEBCTL_DISK_CHECK_PATH": "disk_check_path",
    "GODO_WEBCTL_RESTART_PENDING_PATH": "restart_pending_path",
    "GODO_WEBCTL_PIDFILE": "pidfile_path",
    "GODO_WEBCTL_TRACKER_TOML_PATH": "tracker_toml_path",
    "GODO_WEBCTL_MAPPING_RUNTIME_DIR": "mapping_runtime_dir",
    "GODO_WEBCTL_MAPPING_IMAGE_TAG": "mapping_image_tag",
    "GODO_WEBCTL_DOCKER_BIN": "docker_bin",
    "GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S": "mapping_webctl_stop_timeout_s",
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
