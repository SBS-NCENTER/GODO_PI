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
        # First call: action; second call: is_active follow-up.
        m.side_effect = [_proc(returncode=0), _proc(stdout="active\n")]
        S.control("godo-webctl", action)
    assert m.call_args_list[0] == mock.call(
        ["systemctl", action, "--no-pager", "godo-webctl"],
        capture_output=True,
        text=True,
        timeout=S.SUBPROCESS_TIMEOUT_S,
        check=False,
    )


def test_control_failed_returncode_raises_command_failed() -> None:
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=1, stderr="boom")
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
