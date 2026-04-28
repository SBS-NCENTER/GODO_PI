"""
PR-DIAG — journalctl tail wrapper for the Diagnostics page.

Allow-list reuses ``services.ALLOWED_SERVICES`` (NOT a parallel list —
SSOT discipline; drift impossible). The webctl-specific constraints
are the per-call line cap (``LOGS_TAIL_MAX_N``) and the n-validation
behaviour (``ValueError`` on n <= 0; clamp on n > cap).

Argv is built as a literal Python list — never a shell string —
mirroring ``services.py`` invariant (m). Subprocess timeout reuses
``services.SUBPROCESS_TIMEOUT_S`` so the operator UX is consistent
with other systemd-adjacent endpoints.

Exception types: ``UnknownService`` / ``CommandTimeout`` / ``CommandFailed``
are RE-EXPORTED from ``services`` so callers (app.py) catch the same
class regardless of which module raised. Drift catch in
``test_logs.py::test_exception_types_are_services_aliases``.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Final

from . import services as services_mod
from .constants import LOGS_TAIL_MAX_N

# Re-exports — callers import from logs.py, but the underlying class is
# the canonical one in services.py. Drift impossible by construction.
UnknownService = services_mod.UnknownService
CommandTimeout = services_mod.CommandTimeout
CommandFailed = services_mod.CommandFailed

ALLOWED_SERVICES: Final[frozenset[str]] = services_mod.ALLOWED_SERVICES

logger = logging.getLogger("godo_webctl.logs")


def tail(unit: str, n: int) -> list[str]:
    """Return the last ``n`` journald lines for ``unit`` as a list of
    strings (newline-stripped, empty lines dropped).

    Raises:
        UnknownService: ``unit`` is not in ``ALLOWED_SERVICES``.
        ValueError: ``n <= 0``.
        CommandTimeout: subprocess exceeded ``services.SUBPROCESS_TIMEOUT_S``.
        CommandFailed: subprocess returned non-zero.

    ``n > LOGS_TAIL_MAX_N`` is clamped to the cap (logged at WARN).
    """
    if unit not in ALLOWED_SERVICES:
        raise UnknownService(unit)
    if n <= 0:
        raise ValueError(f"n must be positive: {n}")
    if n > LOGS_TAIL_MAX_N:
        logger.warning(
            "logs.tail_n_clamped: requested=%d cap=%d unit=%s",
            n,
            LOGS_TAIL_MAX_N,
            unit,
        )
        n = LOGS_TAIL_MAX_N

    argv: list[str] = [
        "journalctl",
        "--no-pager",
        "-n",
        str(n),
        "-u",
        unit,
        "--output=cat",
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=services_mod.SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandTimeout(str(e)) from e
    if proc.returncode != 0:
        raise CommandFailed(proc.returncode, proc.stderr)
    return [line for line in proc.stdout.splitlines() if line]
