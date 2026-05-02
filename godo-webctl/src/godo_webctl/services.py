"""
Thin wrappers around `systemctl` and `journalctl` for B-LOCAL.

Per CODEBASE.md invariant (m): subprocess argv is built as a Python LIST
(no f-string interpolation, no shell). The whitelist of allowed service
names is a constant, NOT user input. Reviewer T2 will fail any test that
asserts on a shell-string instead of the literal list.

Reboot/shutdown go through the same convention via `system_reboot` /
`system_shutdown`.

Track B-SYSTEM PR-2: adds `service_show()` + transition-state pre-flight
gate on `control()`. Pure helpers (`parse_systemctl_show`, `redact_env`)
are extracted so unit tests can exercise them without spawning subprocess.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Final

from .protocol import (
    ENV_REDACTION_PATTERNS,
    REDACTED_PLACEHOLDER,
    SYSTEM_SERVICES_FIELDS,
)

# Whitelist — operator may only act on these units. Adding a new
# service name is an explicit code change, not a runtime knob.
#
# issue#14 Patch C2 (2026-05-02): `godo-mapping@active` joins the
# whitelist so the System tab's services-overview block can render
# its status alongside the other three. The polkit rule already
# grants start/stop/restart for it (round-1 systemd PR-2). The SPA
# disables the action buttons for this row at the UI layer with the
# tooltip "Map > Mapping 탭에서 제어" — operator may still curl the
# action endpoint directly (same path Map > Mapping uses).
ALLOWED_SERVICES: Final[frozenset[str]] = frozenset({
    "godo-tracker",
    "godo-webctl",
    "godo-irq-pin",
    "godo-mapping@active",
})

ALLOWED_ACTIONS: Final[frozenset[str]] = frozenset({"start", "stop", "restart"})

# subprocess timeout for systemctl/journalctl. systemctl status is fast
# (<100 ms typically); 10 s is a generous ceiling that still surfaces a
# truly stuck unit as 504.
SUBPROCESS_TIMEOUT_S: Final[float] = 10.0

# Argv literal for system reboot/shutdown. `+0` = immediate; the systemd
# default 90 s grace already handles in-flight requests.
SHUTDOWN_REBOOT_ARGV: Final[list[str]] = ["shutdown", "-r", "+0"]
SHUTDOWN_HALT_ARGV: Final[list[str]] = ["shutdown", "-h", "+0"]

# BLOCKING_TRANSITION_STATES: limited to {activating, deactivating}; no
# service in ALLOWED_SERVICES defines `ExecReload=`. Adding a service
# with reload semantics requires extending this set + integration test
# in the same PR (Mode-A S7 fold).
BLOCKING_TRANSITION_STATES: Final[frozenset[str]] = frozenset({"activating", "deactivating"})

# `--property=` argv passed to `systemctl show`. Order is irrelevant on
# the wire; matches `ServiceShow` field order for readability.
ALLOWED_PROPERTIES: Final[tuple[str, ...]] = (
    "Id",
    "ActiveState",
    "SubState",
    "MainPID",
    "ActiveEnterTimestampMonotonic",
    "MemoryCurrent",
    "Environment",
    "EnvironmentFiles",
)


class ServicesError(Exception):
    """Base for module errors."""


class UnknownService(ServicesError):
    """Requested svc is not in `ALLOWED_SERVICES`."""


class UnknownAction(ServicesError):
    """Requested action is not in `ALLOWED_ACTIONS`."""


class CommandTimeout(ServicesError):
    """The subprocess exceeded `SUBPROCESS_TIMEOUT_S`."""


class CommandFailed(ServicesError):
    """The subprocess returned non-zero. Carries `returncode` + `stderr`."""

    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(f"exit {returncode}: {stderr.strip()}")
        self.returncode = returncode
        self.stderr = stderr


class ServiceTransitionInProgress(ServicesError):
    """`control()` pre-flight gate hit — the unit is in a blocking
    transition state. Carries the transition kind ("starting" or
    "stopping") and the service name so the handler can pick the
    right Korean detail string."""

    def __init__(self, transition: str, svc: str) -> None:
        super().__init__(f"{svc} is {transition}")
        self.transition = transition
        self.svc = svc


@dataclass(frozen=True)
class ServiceShow:
    """One row of `/api/system/services` payload. Field order matches
    `protocol.SYSTEM_SERVICES_FIELDS` exactly."""

    name: str
    active_state: str
    sub_state: str
    main_pid: int | None
    active_since_unix: int | None  # derived from ActiveEnterTimestampMonotonic
    memory_bytes: int | None  # MemoryCurrent (None if [not set])
    env_redacted: dict[str, str]
    env_stale: bool  # True when any EnvironmentFile= mtime > active_since_unix


def _check_service(svc: str) -> None:
    if svc not in ALLOWED_SERVICES:
        raise UnknownService(svc)


def _check_action(action: str) -> None:
    if action not in ALLOWED_ACTIONS:
        raise UnknownAction(action)


def is_active(svc: str) -> str:
    """Returns the raw status word from `systemctl is-active`. Common
    values: ``active``, ``inactive``, ``failed``, ``activating``."""
    _check_service(svc)
    argv = ["systemctl", "is-active", "--no-pager", svc]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandTimeout(str(e)) from e
    # `is-active` exits 0 for active and non-zero for everything else;
    # the status word is on stdout in either case.
    return proc.stdout.strip() or "unknown"


def list_active() -> list[dict[str, object]]:
    """Return one record per allowed service with its current status."""
    out: list[dict[str, object]] = []
    for svc in sorted(ALLOWED_SERVICES):
        try:
            status = is_active(svc)
        except CommandTimeout:
            status = "timeout"
        out.append({"name": svc, "active": status})
    return out


def control(svc: str, action: str) -> str:
    """Run `systemctl <action> <svc>`. Returns the new status from
    `is_active`. Raises `UnknownService`/`UnknownAction` for whitelist
    misses, `CommandTimeout` on subprocess timeout, `CommandFailed` on
    non-zero exit, `ServiceTransitionInProgress` when the unit is mid-
    transition (start/restart on `activating` or stop on `deactivating`)."""
    _check_service(svc)
    _check_action(action)
    # Pre-flight gate. Reads ActiveState directly via `is_active`, NOT
    # via `system_services.snapshot()` (the cache is operator-poll only;
    # control must be authoritative).
    state = is_active(svc)
    if action in {"start", "restart"} and state == "activating":
        raise ServiceTransitionInProgress("starting", svc)
    if action == "stop" and state == "deactivating":
        raise ServiceTransitionInProgress("stopping", svc)
    argv = ["systemctl", action, "--no-pager", svc]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandTimeout(str(e)) from e
    if proc.returncode != 0:
        raise CommandFailed(proc.returncode, proc.stderr)
    return is_active(svc)


def journal_tail(svc: str, n: int) -> list[str]:
    """`journalctl -u <svc> -n <n> --no-pager --output=cat`. Returns the
    lines as a list (newline-stripped). ``n`` must be positive."""
    _check_service(svc)
    if n <= 0:
        raise ValueError(f"n must be positive: {n}")
    argv = [
        "journalctl",
        "-u",
        svc,
        "-n",
        str(n),
        "--no-pager",
        "--output=cat",
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandTimeout(str(e)) from e
    if proc.returncode != 0:
        raise CommandFailed(proc.returncode, proc.stderr)
    return [line for line in proc.stdout.splitlines() if line]


def system_reboot() -> None:
    """`shutdown -r +0`. Returns when the request was accepted (the actual
    reboot is async)."""
    try:
        proc = subprocess.run(
            SHUTDOWN_REBOOT_ARGV,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandTimeout(str(e)) from e
    if proc.returncode != 0:
        raise CommandFailed(proc.returncode, proc.stderr)


def system_shutdown() -> None:
    """`shutdown -h +0`. Returns when the request was accepted."""
    try:
        proc = subprocess.run(
            SHUTDOWN_HALT_ARGV,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandTimeout(str(e)) from e
    if proc.returncode != 0:
        raise CommandFailed(proc.returncode, proc.stderr)


# --- Track B-SYSTEM PR-2: pure helpers + service_show ---------------------


def parse_systemctl_show(stdout: str) -> dict[str, str]:
    """Parse the `KEY=VALUE\\n` body of `systemctl show --property=...`.

    `systemctl show` emits one `KEY=VALUE` per line. Values may contain
    `=`, spaces, and (for `Environment=`) systemd-quoted tokens. Empty
    keys / lines are skipped. Repeated keys keep the last value seen
    (systemd never repeats the queried properties in practice; this is
    defence-in-depth)."""
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key:
            out[key] = value
    return out


def _parse_environment_value(raw: str) -> dict[str, str]:
    """Parse the value of `Environment=` (one logical line) into a dict.

    systemd serializes `Environment=` as space-separated `KEY=VALUE`
    tokens; tokens whose VALUE contains spaces / quotes are wrapped in
    `"..."` (POSIX shell-style). Backslash and `\\n` literals follow
    systemd's `serialize.c::write_string` rules; we only need to recover
    the unquoted KEY=VALUE pairs (the SPA renders the value verbatim,
    redaction-substituted at the KEY level)."""
    if not raw:
        return {}
    env: dict[str, str] = {}
    i = 0
    n = len(raw)
    while i < n:
        # Skip leading whitespace.
        while i < n and raw[i] == " ":
            i += 1
        if i >= n:
            break
        # Read one token. If it starts with `"`, read until the matching
        # unescaped `"`. Otherwise read until the next unescaped space.
        if raw[i] == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                c = raw[i]
                if c == "\\" and i + 1 < n:
                    # systemd-style escape: \" → ", \\ → \, \n → newline.
                    nxt = raw[i + 1]
                    if nxt == "n":
                        buf.append("\n")
                    elif nxt == "t":
                        buf.append("\t")
                    else:
                        buf.append(nxt)
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                buf.append(c)
                i += 1
            token = "".join(buf)
        else:
            buf2: list[str] = []
            while i < n and raw[i] != " ":
                c = raw[i]
                if c == "\\" and i + 1 < n:
                    nxt = raw[i + 1]
                    if nxt == "n":
                        buf2.append("\n")
                    elif nxt == "t":
                        buf2.append("\t")
                    else:
                        buf2.append(nxt)
                    i += 2
                    continue
                buf2.append(c)
                i += 1
            token = "".join(buf2)
        # Token: split on the FIRST `=`. Tokens without `=` are skipped
        # (malformed; should never happen for a healthy unit).
        if "=" not in token:
            continue
        k, _, v = token.partition("=")
        if k:
            env[k] = v
    return env


def redact_env(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of `env` with values substituted to
    `REDACTED_PLACEHOLDER` for keys whose name contains any of
    `ENV_REDACTION_PATTERNS` (case-insensitive substring match).

    The redaction is defence-in-depth: the SSOT is the systemd unit-file
    authoring discipline that keeps secrets out of plain env vars.
    False-positives (`MOST_KEY_BUNDLES`) are accepted — safe direction."""
    out: dict[str, str] = {}
    for key, value in env.items():
        upper = key.upper()
        if any(pat in upper for pat in ENV_REDACTION_PATTERNS):
            out[key] = REDACTED_PLACEHOLDER
        else:
            out[key] = value
    return out


def _parse_environment_files_paths(value: str) -> list[str]:
    """Parse the value of `EnvironmentFiles=...` from `systemctl show`.

    Format per `systemd.exec(5)`: a space-separated list where each
    entry is either a bare path or `path (option=value, ...)`. Multiple
    `EnvironmentFile=` directives in the unit are concatenated into one
    `EnvironmentFiles=` line by systemctl. We strip the parenthesised
    options and return only absolute paths.

    Example input:
      `/etc/godo/tracker.env (ignore_errors=yes) /etc/godo/extra.env`
    Output:
      `['/etc/godo/tracker.env', '/etc/godo/extra.env']`
    """
    if not value:
        return []
    out: list[str] = []
    for tok in value.split():
        if tok.startswith("("):
            continue
        # Some shell-like outputs append a comma between entries; tolerate.
        tok = tok.rstrip(",")
        if tok.startswith("/"):
            out.append(tok)
    return out


def _read_envfile(path: str) -> dict[str, str]:
    """Parse a systemd-style envfile (`EnvironmentFile=` target).

    Per `systemd.exec(5)`: shell-like `KEY=VALUE` per line, `#` comments,
    blank lines allowed, no shell variable expansion, surrounding
    matched quotes are stripped. We do NOT filter to GODO_*: the operator
    chose to put a key in `/etc/godo/*.env`, so it is operationally
    relevant by definition. `redact_env` still masks secret-shaped
    keys via the standard pattern list.

    Returns empty dict on read errors (file missing, EPERM, OSError) —
    the caller treats that as "no envfile-derived overrides".
    """
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if not key:
                    continue
                value = value.strip()
                # Strip matching surrounding single or double quotes.
                if (
                    len(value) >= 2
                    and value[0] == value[-1]
                    and value[0] in ('"', "'")
                ):
                    value = value[1:-1]
                out[key] = value
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError):
        return {}
    return out


def _envfile_newer_than_process(
    envfile_paths: list[str],
    process_active_since_unix: int | None,
) -> bool:
    """True if any envfile's mtime is strictly later than the service's
    `ActiveEnterTimestamp`. Signals "envfile edited since the running
    process started — restart needed for the changes to take effect".
    Returns False when there is no active timestamp (oneshot pre-active,
    or service never started)."""
    if process_active_since_unix is None:
        return False
    for path in envfile_paths:
        try:
            mtime = int(os.path.getmtime(path))
        except (FileNotFoundError, OSError):
            continue
        if mtime > process_active_since_unix:
            return True
    return False


def _parse_int_or_none(raw: str) -> int | None:
    """Parse a non-negative integer value from a `systemctl show` field.
    Returns None on `[not set]`, empty string, or non-integer."""
    if not raw or raw == "[not set]":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def service_show(svc: str) -> ServiceShow:
    """Run `systemctl show --property=...` for one service and return
    a parsed `ServiceShow`. Raises `UnknownService` on whitelist miss,
    `CommandTimeout` on subprocess timeout, `CommandFailed` on non-zero
    exit."""
    _check_service(svc)
    argv = [
        "systemctl",
        "show",
        "--no-pager",
        f"--property={','.join(ALLOWED_PROPERTIES)}",
        svc,
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandTimeout(str(e)) from e
    if proc.returncode != 0:
        raise CommandFailed(proc.returncode, proc.stderr)
    props = parse_systemctl_show(proc.stdout)
    main_pid = _parse_int_or_none(props.get("MainPID", ""))
    # MainPID=0 means "no main process" — surface as None for the SPA.
    if main_pid == 0:
        main_pid = None
    # systemd 257 (Trixie) does NOT expose `ActiveEnterTimestampRealtime`
    # as a queryable property; the canonical property is
    # `ActiveEnterTimestampMonotonic` (microseconds since system boot,
    # same epoch as `clock_gettime(CLOCK_MONOTONIC)` and Python's
    # `time.monotonic()`). Convert to unix epoch using the kernel's
    # CLOCK_MONOTONIC ↔ CLOCK_REALTIME relationship measured RIGHT NOW
    # in this process. Race window between time.time() and
    # time.monotonic() reads is sub-microsecond — irrelevant at the
    # 1-second resolution the SPA renders.
    mono_us = _parse_int_or_none(props.get("ActiveEnterTimestampMonotonic", ""))
    if mono_us is not None and mono_us > 0:
        active_enter_mono_s = mono_us / 1_000_000.0
        elapsed_s = time.monotonic() - active_enter_mono_s
        active_since_unix = int(time.time() - elapsed_s)
    else:
        # mono_us is 0 or [not set] → unit was never active or has no
        # main-process lifecycle (oneshot pre-RemainAfterExit).
        active_since_unix = None
    memory_bytes = _parse_int_or_none(props.get("MemoryCurrent", ""))
    # Environment dict — union of the unit's `Environment=` directive
    # (rare in this project; almost always empty) and the contents of
    # every `EnvironmentFile=` the unit declares. We do NOT read
    # /proc/<MainPID>/environ because cap-bearing processes (e.g. the
    # tracker with CAP_SYS_NICE + CAP_IPC_LOCK) are kernel-marked
    # non-dumpable, blocking same-user environ reads — see PR-A
    # discussion. envfile content is the operator's documented
    # source-of-truth for the overrides, and `env_stale` below flags
    # the rare case where the envfile is newer than the running
    # process (so the SPA can render a "restart pending" indicator).
    env_raw = _parse_environment_value(props.get("Environment", ""))
    envfile_paths = _parse_environment_files_paths(props.get("EnvironmentFiles", ""))
    for envfile_path in envfile_paths:
        env_raw.update(_read_envfile(envfile_path))
    env_redacted = redact_env(env_raw)
    env_stale = _envfile_newer_than_process(envfile_paths, active_since_unix)
    return ServiceShow(
        name=svc,
        active_state=props.get("ActiveState", "unknown"),
        sub_state=props.get("SubState", ""),
        main_pid=main_pid,
        active_since_unix=active_since_unix,
        memory_bytes=memory_bytes,
        env_redacted=env_redacted,
        env_stale=env_stale,
    )


def _ensure_field_order_pin() -> None:
    """Internal — assert at import time that the dataclass fields match
    the wire-side `SYSTEM_SERVICES_FIELDS` tuple. Drift here would mean
    `system_services.snapshot()` and the SPA see different shapes."""
    declared = tuple(f.name for f in ServiceShow.__dataclass_fields__.values())
    assert declared == SYSTEM_SERVICES_FIELDS, (
        f"ServiceShow drift: dataclass={declared} protocol={SYSTEM_SERVICES_FIELDS}"
    )


_ensure_field_order_pin()
