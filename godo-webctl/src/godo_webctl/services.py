"""
Thin wrappers around `systemctl` and `journalctl` for B-LOCAL.

Per CODEBASE.md invariant (m): subprocess argv is built as a Python LIST
(no f-string interpolation, no shell). The whitelist of allowed service
names is a constant, NOT user input. Reviewer T2 will fail any test that
asserts on a shell-string instead of the literal list.

Reboot/shutdown go through the same convention via `system_reboot` /
`system_shutdown`.
"""

from __future__ import annotations

import subprocess
from typing import Final

# Whitelist — operator may only act on these three units. Adding a new
# service name is an explicit code change, not a runtime knob.
ALLOWED_SERVICES: Final[frozenset[str]] = frozenset({"godo-tracker", "godo-webctl", "godo-irq-pin"})

ALLOWED_ACTIONS: Final[frozenset[str]] = frozenset({"start", "stop", "restart"})

# subprocess timeout for systemctl/journalctl. systemctl status is fast
# (<100 ms typically); 10 s is a generous ceiling that still surfaces a
# truly stuck unit as 504.
SUBPROCESS_TIMEOUT_S: Final[float] = 10.0

# Argv literal for system reboot/shutdown. `+0` = immediate; the systemd
# default 90 s grace already handles in-flight requests.
SHUTDOWN_REBOOT_ARGV: Final[list[str]] = ["shutdown", "-r", "+0"]
SHUTDOWN_HALT_ARGV: Final[list[str]] = ["shutdown", "-h", "+0"]


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
    non-zero exit."""
    _check_service(svc)
    _check_action(action)
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
