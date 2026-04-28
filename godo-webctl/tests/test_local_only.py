"""
T5: 8 cases for the loopback gate.

We exercise the dependency directly by feeding a synthetic Starlette
``Request`` whose ``client.host`` we control. This avoids the cost of
spinning up a full FastAPI app per case and keeps the assertion sharp
(one cause, one effect)."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from godo_webctl.local_only import loopback_only


def _req(host: str | None, *, no_client: bool = False) -> Any:
    request = MagicMock()
    if no_client:
        request.client = None
    else:
        client = MagicMock()
        client.host = host
        request.client = client
    request.headers = {}
    return request


# ---- ALLOW cases ---------------------------------------------------------


def test_allow_ipv4_loopback() -> None:
    loopback_only(_req("127.0.0.1"))  # no raise


def test_allow_ipv4_loopback_alt_addr() -> None:
    # All of 127.0.0.0/8 is loopback per RFC 6890.
    loopback_only(_req("127.0.0.5"))


def test_allow_ipv6_loopback() -> None:
    loopback_only(_req("::1"))


# ---- DENY cases ----------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "192.168.1.50",  # private LAN
        "10.0.0.7",  # other private range
        "fc00::1",  # IPv6 ULA
        "fe80::1",  # IPv6 link-local
        "8.8.8.8",  # public IPv4
    ],
)
def test_deny_non_loopback(host: str) -> None:
    with pytest.raises(HTTPException) as ei:
        loopback_only(_req(host))
    assert ei.value.status_code == HTTPStatus.FORBIDDEN
    assert ei.value.detail == {"ok": False, "err": "loopback_only"}


def test_deny_when_request_client_is_none() -> None:
    with pytest.raises(HTTPException) as ei:
        loopback_only(_req(None, no_client=True))
    assert ei.value.status_code == HTTPStatus.FORBIDDEN


def test_deny_when_host_is_empty_string() -> None:
    with pytest.raises(HTTPException) as ei:
        loopback_only(_req(""))
    assert ei.value.status_code == HTTPStatus.FORBIDDEN


def test_x_forwarded_for_is_ignored_even_when_present() -> None:
    """X-Forwarded-For must NOT promote a non-loopback peer to loopback."""
    request = _req("192.168.1.50")
    request.headers = {"X-Forwarded-For": "127.0.0.1"}
    with pytest.raises(HTTPException) as ei:
        loopback_only(request)
    assert ei.value.status_code == HTTPStatus.FORBIDDEN
