"""UDS client behaviour against an in-thread fake server."""

from __future__ import annotations

from pathlib import Path

import pytest

from godo_webctl.uds_client import (
    UdsClient,
    UdsProtocolError,
    UdsTimeout,
    UdsUnreachable,
)


def test_ping_happy_returns_ok(fake_uds_server) -> None:
    fake_uds_server.reply(b'{"ok":true}')
    c = UdsClient(fake_uds_server.path)
    resp = c.ping(timeout=2.0)
    assert resp == {"ok": True}


@pytest.mark.parametrize("mode", ["Idle", "OneShot", "Live"])
def test_get_mode_returns_each_mode(fake_uds_server, mode: str) -> None:
    fake_uds_server.reply(f'{{"ok":true,"mode":"{mode}"}}'.encode())
    c = UdsClient(fake_uds_server.path)
    resp = c.get_mode(timeout=2.0)
    assert resp["mode"] == mode
    assert resp["ok"] is True


def test_set_mode_sends_canonical_bytes(fake_uds_server) -> None:
    fake_uds_server.reply(b'{"ok":true}')
    c = UdsClient(fake_uds_server.path)
    c.set_mode("OneShot", timeout=2.0)
    # Wire-byte-exact assertion (M4).
    assert fake_uds_server.captured == [b'{"cmd":"set_mode","mode":"OneShot"}\n']


def test_socket_missing_raises_unreachable(tmp_path: Path) -> None:
    c = UdsClient(tmp_path / "nope.sock")
    with pytest.raises(UdsUnreachable):
        c.ping(timeout=1.0)


def test_server_silent_raises_timeout(fake_uds_server) -> None:
    # No reply queued and no delay needed — server accepts then closes only
    # after the client times out. recv with no data + settimeout = TimeoutError.
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsTimeout):
        c.ping(timeout=0.2)


def test_server_replies_non_json_raises_protocol(fake_uds_server) -> None:
    fake_uds_server.reply(b"not-json")
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsProtocolError):
        c.ping(timeout=2.0)


def test_server_replies_ok_false_raises_server_rejected(fake_uds_server) -> None:
    """Mode-B SHOULD-FIX S3 — server-rejection is a distinct exception class
    so ``app.py`` can dispatch by ``except`` clause, not by string scraping."""
    from godo_webctl.uds_client import UdsServerRejected

    fake_uds_server.reply(b'{"ok":false,"err":"bad_mode"}')
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsServerRejected) as ei:
        c.set_mode("OneShot", timeout=2.0)
    assert ei.value.err == "bad_mode"


def test_buffer_full_no_newline_raises_protocol(fake_uds_server) -> None:
    """M3 case (h): server sends >=4096 bytes with no '\\n' → response_too_large."""
    fake_uds_server.reply_raw(b"x" * 5000)  # no newline anywhere
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsProtocolError) as ei:
        c.ping(timeout=2.0)
    assert "response_too_large" in str(ei.value)


def test_eof_before_newline_raises_unreachable(fake_uds_server) -> None:
    # No newline; server closes after sending some bytes.
    fake_uds_server.reply_raw(b'{"ok":true}')  # no '\n'
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsUnreachable) as ei:
        c.ping(timeout=2.0)
    assert "eof_before_newline" in str(ei.value)


def test_set_mode_rejects_unknown_mode_locally() -> None:
    c = UdsClient(Path("/tmp/unused.sock"))
    with pytest.raises(ValueError):
        c.set_mode("Calibrate", timeout=2.0)
