"""PR-DIAG — logs.tail() unit tests.

All subprocess calls are mocked; CI must run hermetic.
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from godo_webctl import logs


def _make_completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> mock.MagicMock:
    cp = mock.MagicMock(spec=subprocess.CompletedProcess)
    cp.stdout = stdout
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


def test_tail_happy_returns_split_lines() -> None:
    expected_argv = [
        "journalctl",
        "--no-pager",
        "-n",
        "5",
        "-u",
        "godo-tracker",
        "--output=cat",
    ]
    with mock.patch("godo_webctl.logs.subprocess.run") as m:
        m.return_value = _make_completed(stdout="line1\nline2\n\nline3\n")
        out = logs.tail("godo-tracker", 5)
    # Argv was a list (not a shell string), and contained the canonical
    # six-token shape.
    args, kwargs = m.call_args
    assert args[0] == expected_argv
    assert kwargs.get("timeout") == 10.0
    # Empty lines dropped.
    assert out == ["line1", "line2", "line3"]


def test_tail_unknown_unit_raises() -> None:
    with pytest.raises(logs.UnknownService):
        logs.tail("not-a-service", 5)


def test_tail_n_zero_raises_value_error() -> None:
    with pytest.raises(ValueError):
        logs.tail("godo-tracker", 0)


def test_tail_n_negative_raises_value_error() -> None:
    with pytest.raises(ValueError):
        logs.tail("godo-tracker", -3)


def test_tail_n_above_cap_clamps(caplog: pytest.LogCaptureFixture) -> None:
    """Mode-A TM3 — n > LOGS_TAIL_MAX_N is clamped server-side."""
    import logging

    caplog.set_level(logging.WARNING, logger="godo_webctl.logs")
    with mock.patch("godo_webctl.logs.subprocess.run") as m:
        m.return_value = _make_completed(stdout="ok\n")
        logs.tail("godo-tracker", 10000)
    args, _ = m.call_args
    argv = args[0]
    # `-n <value>` is a literal pair in the argv list; clamped to 500.
    assert "500" in argv
    assert any("clamped" in r.message for r in caplog.records)


def test_tail_subprocess_timeout_raises_command_timeout() -> None:
    with mock.patch("godo_webctl.logs.subprocess.run") as m:
        m.side_effect = subprocess.TimeoutExpired(cmd=["journalctl"], timeout=1.0)
        with pytest.raises(logs.CommandTimeout):
            logs.tail("godo-tracker", 5)


def test_tail_non_zero_exit_raises_command_failed() -> None:
    with mock.patch("godo_webctl.logs.subprocess.run") as m:
        m.return_value = _make_completed(returncode=3, stderr="boom")
        with pytest.raises(logs.CommandFailed) as ei:
            logs.tail("godo-tracker", 5)
    assert ei.value.returncode == 3
    assert "boom" in str(ei.value)


def test_tail_argv_is_list_not_shell() -> None:
    """Mode-A TM1 — argv MUST be a Python list of strings, never a
    shell-string. Inspect the captured call_args to assert this property
    directly (and not just by side effect)."""
    with mock.patch("godo_webctl.logs.subprocess.run") as m:
        m.return_value = _make_completed(stdout="")
        logs.tail("godo-webctl", 5)
    args, _ = m.call_args
    argv = args[0]
    assert isinstance(argv, list)
    assert all(isinstance(tok, str) for tok in argv)
    # Sanity: shell metacharacters never appear as a single token.
    assert all(";" not in tok and "&&" not in tok for tok in argv)


def test_logs_allow_list_is_services_allow_list() -> None:
    """Mode-A invariant (i): logs.ALLOWED_SERVICES IS services.ALLOWED_SERVICES,
    not a parallel definition. Drift impossible by construction."""
    from godo_webctl import services as services_mod

    assert logs.ALLOWED_SERVICES is services_mod.ALLOWED_SERVICES


def test_exception_types_are_services_aliases() -> None:
    """Mode-A: logs re-exports the exception classes; callers catching
    `logs.UnknownService` AND callers catching `services.UnknownService`
    must hit the same handler."""
    from godo_webctl import services as services_mod

    assert logs.UnknownService is services_mod.UnknownService
    assert logs.CommandTimeout is services_mod.CommandTimeout
    assert logs.CommandFailed is services_mod.CommandFailed
