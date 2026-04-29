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
        "ActiveEnterTimestampMonotonic=2430290856\n"
        "MemoryCurrent=53477376\n"
        "Environment=GODO_LOG_DIR=/var/log/godo\n"
    )
    out = S.parse_systemctl_show(raw)
    assert out["Id"] == "godo-tracker.service"
    assert out["ActiveState"] == "active"
    assert out["SubState"] == "running"
    assert out["MainPID"] == "1234"
    assert out["ActiveEnterTimestampMonotonic"] == "2430290856"
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
    """Build a stub `systemctl show` output and verify ServiceShow fields.

    `ActiveEnterTimestampMonotonic` is microseconds since system boot.
    Mock `time.monotonic()` and `time.time()` so the unix-epoch
    derivation is deterministic: if monotonic = 1100s and time = 1714398572,
    a service that entered active at boot+1000s (mono_us=1_000_000_000)
    has been up for 100s → unix = 1714398572 - 100 = 1714398472.

    `env_redacted` merges the unit's `Environment=` directive AND the
    contents of every `EnvironmentFile=`. envfile content is the
    operator-authored source-of-truth for overrides; reading it is
    safe (envfile is root:root 0644) AND captures keys that systemd
    inject into the cap-bearing process which we cannot read via
    /proc/<pid>/environ.
    """
    stdout = (
        "Id=godo-tracker.service\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "MainPID=1234\n"
        "ActiveEnterTimestampMonotonic=1000000000\n"
        "MemoryCurrent=53477376\n"
        'Environment=GODO_LOG_DIR=/var/log/godo "GODO_JWT_SECRET=hunter2"\n'
        "EnvironmentFiles=/etc/godo/tracker.env (ignore_errors=yes)\n"
    )
    # `/etc/godo/tracker.env` content — shell-style KEY=VALUE per line.
    envfile_text = (
        "# operator overrides\n"
        "GODO_AMCL_MAP_PATH=/var/lib/godo/maps/active.pgm\n"
        "GODO_UE_HOST=192.168.0.10\n"
        "\n"
        "# secret-shaped key gets redacted by redact_env\n"
        "GODO_API_TOKEN=hunter2\n"
    )
    with (
        mock.patch("godo_webctl.services.subprocess.run") as m,
        mock.patch("godo_webctl.services.time.monotonic", return_value=1100.0),
        mock.patch("godo_webctl.services.time.time", return_value=1714398572.0),
        mock.patch("builtins.open", mock.mock_open(read_data=envfile_text)),
        mock.patch("godo_webctl.services.os.path.getmtime", return_value=0.0),
    ):
        m.return_value = _proc(returncode=0, stdout=stdout)
        show = S.service_show("godo-tracker")
    assert show.name == "godo-tracker"
    assert show.active_state == "active"
    assert show.sub_state == "running"
    assert show.main_pid == 1234
    # Active for 100s; current unix - 100 = unix at activation.
    assert show.active_since_unix == 1714398472
    assert show.memory_bytes == 53477376
    # Directive-side keys preserved.
    assert show.env_redacted["GODO_LOG_DIR"] == "/var/log/godo"
    assert show.env_redacted["GODO_JWT_SECRET"] == "<redacted>"
    # envfile-derived keys merged in.
    assert show.env_redacted["GODO_AMCL_MAP_PATH"] == "/var/lib/godo/maps/active.pgm"
    assert show.env_redacted["GODO_UE_HOST"] == "192.168.0.10"
    # Secret-shaped envfile key redacted.
    assert show.env_redacted["GODO_API_TOKEN"] == "<redacted>"
    # envfile mtime=0 < active_since_unix → not stale.
    assert show.env_stale is False


def test_service_show_handles_memory_not_set() -> None:
    stdout = (
        "Id=godo-tracker.service\n"
        "ActiveState=inactive\n"
        "SubState=dead\n"
        "MainPID=0\n"
        "ActiveEnterTimestampMonotonic=0\n"
        "MemoryCurrent=[not set]\n"
        "Environment=\n"
        "EnvironmentFiles=\n"
    )
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=0, stdout=stdout)
        show = S.service_show("godo-tracker")
    assert show.main_pid is None  # MainPID=0 surfaces as None
    assert show.active_since_unix is None  # mono=0 → None (never active)
    assert show.memory_bytes is None  # [not set] → None
    assert show.env_redacted == {}
    assert show.env_stale is False  # never active → can't be stale


def test_service_show_unknown_service_rejected() -> None:
    with pytest.raises(S.UnknownService):
        S.service_show("not-a-godo-service")


# ---- _parse_environment_files_paths --------------------------------------


def test_parse_environment_files_paths_single_with_options() -> None:
    raw = "/etc/godo/tracker.env (ignore_errors=yes)"
    assert S._parse_environment_files_paths(raw) == ["/etc/godo/tracker.env"]


def test_parse_environment_files_paths_multiple() -> None:
    raw = "/etc/godo/a.env (ignore_errors=yes) /etc/godo/b.env"
    assert S._parse_environment_files_paths(raw) == [
        "/etc/godo/a.env",
        "/etc/godo/b.env",
    ]


def test_parse_environment_files_paths_empty() -> None:
    assert S._parse_environment_files_paths("") == []


# ---- _read_envfile --------------------------------------------------------


def test_read_envfile_basic() -> None:
    text = (
        "# header comment\n"
        "GODO_UE_HOST=192.168.0.10\n"
        "\n"
        "GODO_AMCL_MAP_PATH=/var/lib/godo/maps/active.pgm\n"
    )
    with mock.patch("builtins.open", mock.mock_open(read_data=text)):
        env = S._read_envfile("/etc/godo/tracker.env")
    assert env == {
        "GODO_UE_HOST": "192.168.0.10",
        "GODO_AMCL_MAP_PATH": "/var/lib/godo/maps/active.pgm",
    }


def test_read_envfile_strips_matching_quotes() -> None:
    text = 'GODO_QUOTED="value with spaces"\nGODO_SQ=\'singlequoted\'\nGODO_BARE=bare\n'
    with mock.patch("builtins.open", mock.mock_open(read_data=text)):
        env = S._read_envfile("/dev/null")
    assert env["GODO_QUOTED"] == "value with spaces"
    assert env["GODO_SQ"] == "singlequoted"
    assert env["GODO_BARE"] == "bare"


def test_read_envfile_missing_returns_empty() -> None:
    """envfile not present → empty dict (don't crash)."""
    with mock.patch("builtins.open", side_effect=FileNotFoundError):
        assert S._read_envfile("/etc/godo/missing.env") == {}


def test_read_envfile_no_godo_filter_intentional() -> None:
    """envfile parsing does NOT filter to GODO_* — the operator chose
    to put the key in the envfile, so it is operationally relevant by
    definition. `redact_env` masks secret-shaped keys downstream."""
    text = "FOO=bar\nGODO_X=ok\n"
    with mock.patch("builtins.open", mock.mock_open(read_data=text)):
        env = S._read_envfile("/dev/null")
    assert env == {"FOO": "bar", "GODO_X": "ok"}


# ---- _envfile_newer_than_process -----------------------------------------


def test_envfile_newer_than_process_true_when_mtime_after() -> None:
    """envfile mtime > process active_since_unix → stale."""
    with mock.patch("godo_webctl.services.os.path.getmtime", return_value=2000.0):
        assert S._envfile_newer_than_process(["/dev/null"], 1500) is True


def test_envfile_newer_than_process_false_when_mtime_before() -> None:
    with mock.patch("godo_webctl.services.os.path.getmtime", return_value=1000.0):
        assert S._envfile_newer_than_process(["/dev/null"], 1500) is False


def test_envfile_newer_than_process_false_when_no_active_since() -> None:
    """No active timestamp (oneshot pre-active or never started) → False."""
    assert S._envfile_newer_than_process(["/dev/null"], None) is False


def test_envfile_newer_than_process_handles_missing_envfile() -> None:
    """An envfile that no longer exists is silently skipped — don't crash."""
    with mock.patch(
        "godo_webctl.services.os.path.getmtime",
        side_effect=FileNotFoundError,
    ):
        assert S._envfile_newer_than_process(["/dev/null"], 1500) is False


def test_envfile_newer_than_process_any_path_triggers() -> None:
    """If ANY of multiple envfiles has a newer mtime, return True."""
    seq = iter([1000.0, 9999.0])

    def _fake_mtime(path: str) -> float:
        return next(seq)

    with mock.patch("godo_webctl.services.os.path.getmtime", side_effect=_fake_mtime):
        assert (
            S._envfile_newer_than_process(["/dev/null", "/dev/null"], 1500) is True
        )


# ---- service_show oneshot path -------------------------------------------


def test_service_show_oneshot_with_no_envfile_yields_clean_state() -> None:
    """oneshot godo-irq-pin (Type=oneshot + RemainAfterExit) reports
    MainPID=0 + empty Environment + no EnvironmentFiles. ServiceShow
    should round-trip with empty env_redacted + env_stale=False."""
    stdout = (
        "Id=godo-irq-pin.service\n"
        "ActiveState=active\n"
        "SubState=exited\n"
        "MainPID=0\n"
        "ActiveEnterTimestampMonotonic=500000000\n"
        "MemoryCurrent=[not set]\n"
        "Environment=\n"
        "EnvironmentFiles=\n"
    )
    with (
        mock.patch("godo_webctl.services.subprocess.run") as m,
        mock.patch("godo_webctl.services.time.monotonic", return_value=600.0),
        mock.patch("godo_webctl.services.time.time", return_value=1714398572.0),
    ):
        m.return_value = _proc(returncode=0, stdout=stdout)
        show = S.service_show("godo-irq-pin")
    assert show.main_pid is None
    assert show.env_redacted == {}
    assert show.env_stale is False


def test_service_show_env_stale_true_when_envfile_newer() -> None:
    """envfile mtime > active_since_unix → env_stale=True. Operator
    edited /etc/godo/tracker.env after the service started; the SPA
    will render a 'restart pending' indicator until the next start."""
    stdout = (
        "Id=godo-tracker.service\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "MainPID=1234\n"
        "ActiveEnterTimestampMonotonic=1000000000\n"
        "MemoryCurrent=53477376\n"
        "Environment=\n"
        "EnvironmentFiles=/etc/godo/tracker.env (ignore_errors=yes)\n"
    )
    envfile_text = "GODO_AMCL_MAP_PATH=/var/lib/godo/maps/active.pgm\n"
    # mock.monotonic=1100, time=1714398572 → active_since_unix=1714398472.
    # Set envfile mtime AFTER that → stale.
    with (
        mock.patch("godo_webctl.services.subprocess.run") as m,
        mock.patch("godo_webctl.services.time.monotonic", return_value=1100.0),
        mock.patch("godo_webctl.services.time.time", return_value=1714398572.0),
        mock.patch("builtins.open", mock.mock_open(read_data=envfile_text)),
        mock.patch(
            "godo_webctl.services.os.path.getmtime",
            return_value=1714400000.0,  # > 1714398472
        ),
    ):
        m.return_value = _proc(returncode=0, stdout=stdout)
        show = S.service_show("godo-tracker")
    assert show.env_stale is True
    assert show.env_redacted["GODO_AMCL_MAP_PATH"] == "/var/lib/godo/maps/active.pgm"


def test_service_show_invokes_argv_with_property_list() -> None:
    """T2 discipline: the `--property=` argument joins the ALLOWED_PROPERTIES
    tuple. Pin that exact argv shape so a future writer who reorders the
    tuple gets a visible diff."""
    with mock.patch("godo_webctl.services.subprocess.run") as m:
        m.return_value = _proc(returncode=0, stdout="ActiveState=active\n")
        S.service_show("godo-tracker")
    expected_property_arg = (
        "--property=Id,ActiveState,SubState,MainPID,"
        "ActiveEnterTimestampMonotonic,MemoryCurrent,Environment,EnvironmentFiles"
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
