"""
Loopback-only FastAPI dependency for ``/api/local/*``.

Checks the actual TCP peer IP (`request.client.host`) against the IPv4
loopback ``127.0.0.0/8`` and the IPv6 loopback ``::1``. Per CODEBASE.md
invariant (k) and reviewer T5, the test surface covers 8 cases:

    127.0.0.1                ALLOW
    ::1                      ALLOW
    192.168.x.x              DENY
    10.x.x.x                 DENY
    fc00::/7  (ULA)          DENY
    fe80::/10 (link-local)   DENY
    request.client is None   DENY
    X-Forwarded-For present  IGNORED — peer IP still authoritative

Reverse proxies are not part of our deployment, so we never honour
``X-Forwarded-For``. The ``cfg.chromium_loopback_only`` knob exists
purely so a future proxy-fronted topology can opt out, but the default
is True everywhere.
"""

from __future__ import annotations

import ipaddress
from http import HTTPStatus

from fastapi import HTTPException, Request


def _is_loopback(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback


def loopback_only(request: Request) -> None:
    """Raise 403 if the TCP peer is not loopback. Honors `request.client`
    being None (e.g. transports that don't set it) by denying."""
    client = request.client
    if client is None or not client.host:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail={"ok": False, "err": "loopback_only"},
        )
    if not _is_loopback(client.host):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail={"ok": False, "err": "loopback_only"},
        )
