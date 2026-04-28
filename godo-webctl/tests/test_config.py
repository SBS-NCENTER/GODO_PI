"""Settings loader: defaults, overrides, malformed values."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from godo_webctl.config import (
    _DEFAULTS,
    _ENV_TO_FIELD,
    _PARSERS,
    ConfigError,
    Settings,
    load_settings,
)


def test_empty_env_uses_defaults() -> None:
    s = load_settings({})
    assert s.host == "127.0.0.1"
    assert s.port == 8080
    assert s.uds_socket == Path("/run/godo/ctl.sock")
    assert s.backup_dir == Path("/var/lib/godo/map-backups")
    assert s.map_path == Path("/etc/godo/maps/studio_v1.pgm")
    assert s.health_uds_timeout_s == 2.0
    assert s.calibrate_uds_timeout_s == 30.0
    assert s.jwt_secret_path == Path("/var/lib/godo/auth/jwt_secret")
    assert s.users_file == Path("/var/lib/godo/auth/users.json")
    assert s.spa_dist is None
    assert s.chromium_loopback_only is True


def test_defaults_match_settings() -> None:
    """SSOT pin: every _DEFAULTS key parses to its corresponding Settings field."""
    s = load_settings({})
    for env_key, default in _DEFAULTS.items():
        field = _ENV_TO_FIELD[env_key]
        parser = _PARSERS[env_key]
        assert getattr(s, field) == parser(default), (
            f"drift: {env_key} default={default!r} != Settings.{field}={getattr(s, field)!r}"
        )


def test_each_env_var_overrides_default() -> None:
    overrides = {
        "GODO_WEBCTL_HOST": "0.0.0.0",
        "GODO_WEBCTL_PORT": "9090",
        "GODO_WEBCTL_UDS_SOCKET": "/tmp/x.sock",
        "GODO_WEBCTL_BACKUP_DIR": "/tmp/b",
        "GODO_WEBCTL_MAP_PATH": "/tmp/m.pgm",
        "GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S": "0.5",
        "GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S": "5.0",
        "GODO_WEBCTL_JWT_SECRET_PATH": "/tmp/jwt",
        "GODO_WEBCTL_USERS_FILE": "/tmp/users.json",
        "GODO_WEBCTL_SPA_DIST": "/tmp/dist",
        "GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY": "false",
    }
    s = load_settings(overrides)
    assert s.host == "0.0.0.0"
    assert s.port == 9090
    assert s.uds_socket == Path("/tmp/x.sock")
    assert s.backup_dir == Path("/tmp/b")
    assert s.map_path == Path("/tmp/m.pgm")
    assert s.health_uds_timeout_s == 0.5
    assert s.calibrate_uds_timeout_s == 5.0
    assert s.jwt_secret_path == Path("/tmp/jwt")
    assert s.users_file == Path("/tmp/users.json")
    assert s.spa_dist == Path("/tmp/dist")
    assert s.chromium_loopback_only is False


def test_spa_dist_empty_string_is_none() -> None:
    """Empty value (operator left it commented out) → ``None`` so app.py
    falls back to the legacy static/index.html mount."""
    s = load_settings({"GODO_WEBCTL_SPA_DIST": ""})
    assert s.spa_dist is None


def test_chromium_loopback_only_rejects_ambiguous() -> None:
    with pytest.raises(ConfigError) as ei:
        load_settings({"GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY": "maybe"})
    assert "GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY" in str(ei.value)


@pytest.mark.parametrize(
    ("env_key", "bad_value"),
    [
        ("GODO_WEBCTL_PORT", "abc"),
        ("GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S", "x"),
        ("GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S", "nope"),
    ],
)
def test_malformed_value_raises_configerror_naming_field(
    env_key: str,
    bad_value: str,
) -> None:
    with pytest.raises(ConfigError) as ei:
        load_settings({env_key: bad_value})
    assert env_key in str(ei.value)
    assert bad_value in str(ei.value)


def test_settings_is_frozen() -> None:
    s = load_settings({})
    with pytest.raises(FrozenInstanceError):
        s.port = 9999  # type: ignore[misc]


def test_env_to_field_keys_match_defaults() -> None:
    assert set(_ENV_TO_FIELD.keys()) == set(_DEFAULTS.keys())
    assert set(_PARSERS.keys()) == set(_DEFAULTS.keys())


def test_settings_field_set_matches_env_to_field_values() -> None:
    field_names = {f.name for f in Settings.__dataclass_fields__.values()}
    assert field_names == set(_ENV_TO_FIELD.values())
