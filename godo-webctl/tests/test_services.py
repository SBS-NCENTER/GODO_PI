"""
T2: services.py — subprocess wrappers must build argv as LITERAL LISTS.

Every test that asserts a `subprocess.run` call uses
`mock.assert_called_once_with([...], ...)` with the exact list, NOT a
shell string. A writer who accidentally passed `f"shutdown -r +0"`
must fail these tests.
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from godo_webctl import services as S


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> mock.MagicMock:
    p = mock.MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---- whitelist enforcement ----------------------------------------------


def test_unknown_service_rejected_by_is_active() -> None:
    with pytest.raises(S.UnknownService):
        S.is_active("not-a-godo-service")


def test_unknown_service_rejected_by_control() -> None:
    with pytest.raises(S.UnknownService):
        S.control("not-a-godo-service", "start")


def test_unknown_action_rejected() -> None:
    with pytest.raises(S.UnknownAction):
        S.control("godo-tracker", "purge")


def test_unknown_service_rejected_by_journal_tail() -> None:
    with pytest.raises(S.UnknownService):
        S.journal_tail("not-a-godo-service", 5)


def test_journal_tail_rejects_non_positive_n() -> None:
    with pytest.raises(ValueError):
        S.journal_tail("godo-tracker", 0)


# ---- is_active argv literal --------------------------------------------


def test_is_active_invokes_systemctl_with_literal_argv() -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(stdout="active\n")
        result = S.is_active("godo-tracker")
    m.assert_called_once_with(
        ["systemctl", "is-active", "--no-pager", "godo-tracker"],
        capture_output=True,
        text=True,
        timeout=S.SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    assert result == "active"


@pytest.mark.parametrize("status", ["active", "inactive", "failed", "activating"])
def test_is_active_parses_known_status_words(status: str) -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(stdout=status + "\n")
        assert S.is_active("godo-tracker") == status


def test_is_active_subprocess_timeout_raises_command_timeout() -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.side_effect = subprocess.TimeoutExpired(cmd=["systemctl"], timeout=10.0)
        with pytest.raises(S.CommandTimeout):
            S.is_active("godo-tracker")


# ---- control argv literal ----------------------------------------------


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_control_invokes_literal_argv(action: str) -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        # PR-2: control() now does (1) pre-flight is_active, (2) the
        # action, (3) post-action is_active. Pre-flight returns a benign
        # state so the transition gate doesn't trip.
        m.side_effect = [
            _proc(stdout="inactive\n"),  # pre-flight is_active
            _proc(returncode=0),  # the action
            _proc(stdout="active\n"),  # post-action is_active
        ]
        S.control("godo-webctl", action)
    # The action call is the 2nd argv (index 1).
    assert m.call_args_list[1] == mock.call(
        ["systemctl", action, "--no-pager", "godo-webctl"],
        capture_output=True,
        text=True,
        timeout=S.SUBPROCESS_TIMEOUT_S,
        check=False,
    )


def test_control_failed_returncode_raises_command_failed() -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        # Pre-flight returns inactive (gate ok), then action fails.
        m.side_effect = [
            _proc(stdout="inactive\n"),
            _proc(returncode=1, stderr="boom"),
        ]
        with pytest.raises(S.CommandFailed) as ei:
            S.control("godo-tracker", "start")
        assert ei.value.returncode == 1


# ---- journal_tail argv literal -----------------------------------------


def test_journal_tail_invokes_literal_argv() -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(stdout="line1\nline2\n")
        lines = S.journal_tail("godo-tracker", 7)
    m.assert_called_once_with(
        [
            "journalctl",
            "-u",
            "godo-tracker",
            "-n",
            "7",
            "--no-pager",
            "--output=cat",
        ],
        capture_output=True,
        text=True,
        timeout=S.SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    assert lines == ["line1", "line2"]


# ---- system_reboot / system_shutdown argv literal (T2) -----------------


def test_system_reboot_invokes_literal_argv_no_shell_string() -> None:
    """T2: literal LIST. A writer who builds `f'shutdown -r +0'` must
    fail this test."""
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=0)
        S.system_reboot()
    m.assert_called_once_with(
        ["shutdown", "-r", "+0"],
        capture_output=True,
        text=True,
        timeout=S.SUBPROCESS_TIMEOUT_S,
        check=False,
    )


def test_system_shutdown_invokes_literal_argv() -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=0)
        S.system_shutdown()
    m.assert_called_once_with(
        ["shutdown", "-h", "+0"],
        capture_output=True,
        text=True,
        timeout=S.SUBPROCESS_TIMEOUT_S,
        check=False,
    )


def test_system_reboot_failure_raises_command_failed() -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=1, stderr="permission denied")
        with pytest.raises(S.CommandFailed):
            S.system_reboot()


# ---- list_active --------------------------------------------------------


def test_list_active_returns_one_record_per_allowed_service() -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(stdout="active\n")
        items = S.list_active()
    names = {item["name"] for item in items}
    assert names == set(S.ALLOWED_SERVICES)
    assert all(item["active"] == "active" for item in items)


# --- Track B-SYSTEM PR-2 — pure helpers + transition gate ----------------


def test_parse_systemctl_show_basic() -> None:
    raw = (
        "Id=godo-tracker.service\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "MainPID=1234\n"
        "ActiveEnterTimestampRealtime=1714397472000000\n"
        "MemoryCurrent=53477376\n"
        "Environment=GODO_LOG_DIR=/var/log/godo\n"
    )
    out = S.parse_systemctl_show(raw)
    assert out["Id"] == "godo-tracker.service"
    assert out["ActiveState"] == "active"
    assert out["SubState"] == "running"
    assert out["MainPID"] == "1234"
    assert out["ActiveEnterTimestampRealtime"] == "1714397472000000"
    assert out["MemoryCurrent"] == "53477376"
    assert out["Environment"] == "GODO_LOG_DIR=/var/log/godo"


def test_parse_systemctl_show_skips_blank_and_keyless_lines() -> None:
    raw = "ActiveState=active\n\n=garbage\nSubState=running\n"
    out = S.parse_systemctl_show(raw)
    assert out == {"ActiveState": "active", "SubState": "running"}


def test_parse_systemctl_show_environment_with_spaces_quotes_equals() -> None:
    """Reserve corner cases for `_parse_environment_value`: quoted values
    that contain spaces, `=`, and embedded shell-style escapes."""
    raw = 'GODO_LOG_DIR=/var/log/godo "JWT_SECRET=ab=cd ef" PATH=/usr/bin'
    env = S._parse_environment_value(raw)
    assert env["GODO_LOG_DIR"] == "/var/log/godo"
    assert env["JWT_SECRET"] == "ab=cd ef"
    assert env["PATH"] == "/usr/bin"


def test_parse_systemctl_show_environment_with_backslash_and_newline_escapes() -> None:
    """S1 fold corpus: backslash-and-newline rules per systemd's
    `serialize.c::write_string`. systemd serializes `\\\\` as the literal
    two-char `\\\\` and `\\n` as a literal `n` after `\\`."""
    raw = 'PATH=/usr/bin\\:/bin "HEADER=line1\\nline2"'
    env = S._parse_environment_value(raw)
    # Outside of quotes the backslash escape consumes the next char.
    # `\\:` → `:` (the ":" is preserved verbatim because we drop the `\`).
    # The exact unescape policy here is defence-in-depth — the SPA renders
    # the value verbatim, redaction-substituted at KEY level.
    assert "PATH" in env
    assert "HEADER" in env
    # The newline-escape rule: `\\n` decodes to a real newline.
    assert "\n" in env["HEADER"]


def test_parse_systemctl_show_environment_empty() -> None:
    assert S._parse_environment_value("") == {}


def test_parse_systemctl_show_environment_token_without_equals_skipped() -> None:
    # A token with no `=` cannot be a KEY=VALUE pair; we drop it rather
    # than synthesizing a None value.
    raw = "stray_token GOOD_KEY=ok"
    env = S._parse_environment_value(raw)
    assert env == {"GOOD_KEY": "ok"}


@pytest.mark.parametrize(
    "key, expected_redacted",
    [
        ("DB_PASSWORD", True),
        ("API_TOKEN", True),
        ("JWT_SECRET", True),
        ("AWS_CREDENTIALS_FILE", True),
        ("PASSWD_HASH", True),
        ("ROOT_KEY", True),
        # Case-insensitive: lower-case + mixed.
        ("api_token", True),
        ("MyPassword", True),
        # Control: benign keys that survive unmodified (T2 fold).
        ("GODO_LOG_DIR", False),
        ("PATH", False),
        ("HOME", False),
    ],
)
def test_redact_env_six_substring_patterns(key: str, expected_redacted: bool) -> None:
    env = {key: "raw-value"}
    out = S.redact_env(env)
    if expected_redacted:
        assert out[key] == "<redacted>"
    else:
        assert out[key] == "raw-value"


def test_redact_env_case_insensitive_all_six_patterns() -> None:
    env = {
        "secret_a": "v1",
        "Secret_b": "v2",
        "SECRET_c": "v3",
        "key_lower": "v4",
        "Token_mixed": "v5",
        "PASSWORD_upper": "v6",
        "passwd_lower": "v7",
        "credential_lower": "v8",
    }
    out = S.redact_env(env)
    for k in env:
        assert out[k] == "<redacted>", f"{k} should be redacted"


def test_redact_env_preserves_unrelated_keys() -> None:
    env = {"GODO_LOG_DIR": "/var/log/godo", "PATH": "/usr/bin"}
    out = S.redact_env(env)
    assert out == env


def test_service_show_returns_dataclass_shape() -> None:
    """Build a stub `systemctl show` output and verify ServiceShow fields."""
    stdout = (
        "Id=godo-tracker.service\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "MainPID=1234\n"
        "ActiveEnterTimestampRealtime=1714397472000000\n"
        "MemoryCurrent=53477376\n"
        'Environment=GODO_LOG_DIR=/var/log/godo "JWT_SECRET=hunter2"\n'
    )
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=0, stdout=stdout)
        show = S.service_show("godo-tracker")
    assert show.name == "godo-tracker"
    assert show.active_state == "active"
    assert show.sub_state == "running"
    assert show.main_pid == 1234
    # Realtime ms / 1000 = unix seconds. 1714397472000000 / 1_000_000.
    assert show.active_since_unix == 1714397472
    assert show.memory_bytes == 53477376
    assert show.env_redacted["GODO_LOG_DIR"] == "/var/log/godo"
    assert show.env_redacted["JWT_SECRET"] == "<redacted>"


def test_service_show_handles_memory_not_set() -> None:
    stdout = (
        "Id=godo-tracker.service\n"
        "ActiveState=inactive\n"
        "SubState=dead\n"
        "MainPID=0\n"
        "ActiveEnterTimestampRealtime=0\n"
        "MemoryCurrent=[not set]\n"
        "Environment=\n"
    )
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=0, stdout=stdout)
        show = S.service_show("godo-tracker")
    assert show.main_pid is None  # MainPID=0 surfaces as None
    assert show.active_since_unix is None  # 0 → None (not actively running)
    assert show.memory_bytes is None  # [not set] → None
    assert show.env_redacted == {}


def test_service_show_unknown_service_rejected() -> None:
    with pytest.raises(S.UnknownService):
        S.service_show("not-a-godo-service")


def test_service_show_invokes_argv_with_property_list() -> None:
    """T2 discipline: the `--property=` argument joins the ALLOWED_PROPERTIES
    tuple. Pin that exact argv shape so a future writer who reorders the
    tuple gets a visible diff."""
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=0, stdout="ActiveState=active\n")
        S.service_show("godo-tracker")
    expected_property_arg = (
        "--property=Id,ActiveState,SubState,MainPID,"
        "ActiveEnterTimestampRealtime,MemoryCurrent,Environment"
    )
    m.assert_called_once_with(
        ["systemctl", "show", "--no-pager", expected_property_arg, "godo-tracker"],
        capture_output=True,
        text=True,
        timeout=S.SUBPROCESS_TIMEOUT_S,
        check=False,
    )


@pytest.mark.parametrize("action", ["start", "restart"])
def test_control_raises_transition_in_progress_when_activating_and_start(action: str) -> None:
    with (
        mock.patch("godo_webctl.services.is_active", return_value="activating"),
        pytest.raises(S.ServiceTransitionInProgress) as ei,
    ):
        S.control("godo-tracker", action)
    assert ei.value.transition == "starting"
    assert ei.value.svc == "godo-tracker"


def test_control_raises_transition_in_progress_when_deactivating_and_stop() -> None:
    with (
        mock.patch("godo_webctl.services.is_active", return_value="deactivating"),
        pytest.raises(S.ServiceTransitionInProgress) as ei,
    ):
        S.control("godo-tracker", "stop")
    assert ei.value.transition == "stopping"
    assert ei.value.svc == "godo-tracker"


def test_control_does_not_block_start_on_deactivating() -> None:
    """Anti-monotone: only matching transition+action combos block.
    A `start` while the unit is `deactivating` should NOT raise the
    transition exception — systemd will queue the start naturally."""
    # is_active called twice (pre-flight + post-action); subprocess.run
    # for the systemctl <action> call.
    with (
        mock.patch("godo_webctl.services.is_active", side_effect=["deactivating", "active"]),
        mock.patch("godo_webctl.services.subprocess.run") as m,
    ):
        m.return_value = _proc(returncode=0)
        result = S.control("godo-tracker", "start")
    assert result == "active"


def test_control_does_not_block_stop_on_activating() -> None:
    """Anti-monotone partner: stop while activating proceeds."""
    with (
        mock.patch("godo_webctl.services.is_active", side_effect=["activating", "inactive"]),
        mock.patch("godo_webctl.services.subprocess.run") as m,
    ):
        m.return_value = _proc(returncode=0)
        result = S.control("godo-tracker", "stop")
    assert result == "inactive"


def test_control_pre_flight_does_not_use_system_services_cache() -> None:
    """S2 fold: control() must NOT touch the cached snapshot. The cache
    is operator-poll only; control needs an authoritative read."""
    with (
        mock.patch("godo_webctl.system_services.snapshot") as snap_mock,
        mock.patch("godo_webctl.services.is_active", side_effect=["active", "active"]),
        mock.patch("godo_webctl.services.subprocess.run") as m,
    ):
        m.return_value = _proc(returncode=0)
        S.control("godo-tracker", "restart")
    assert snap_mock.call_count == 0
