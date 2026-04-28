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


# ---- Track D: get_last_scan ---------------------------------------------


def test_get_last_scan_happy(fake_uds_server) -> None:
    fake_uds_server.reply(
        b'{"ok":true,"valid":1,"forced":1,"pose_valid":1,"iterations":7,'
        b'"published_mono_ns":42,"pose_x_m":1.5,"pose_y_m":2.0,'
        b'"pose_yaw_deg":45.0,"n":2,"angles_deg":[0.0,0.5],'
        b'"ranges_m":[1.0,1.5]}',
    )
    c = UdsClient(fake_uds_server.path)
    resp = c.get_last_scan(timeout=2.0)
    assert resp["ok"] is True
    assert resp["valid"] == 1
    assert resp["n"] == 2
    assert resp["angles_deg"] == [0.0, 0.5]
    assert resp["ranges_m"] == [1.0, 1.5]


def test_get_last_scan_server_rejected_propagates(fake_uds_server) -> None:
    """Server replies err=unknown_cmd (e.g. tracker too old to know
    Track D); client surfaces UdsServerRejected with the err code."""
    from godo_webctl.uds_client import UdsServerRejected

    fake_uds_server.reply(b'{"ok":false,"err":"unknown_cmd"}')
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsServerRejected) as ei:
        c.get_last_scan(timeout=2.0)
    assert ei.value.err == "unknown_cmd"


def test_get_last_scan_response_too_large_raises(fake_uds_server) -> None:
    """Wider read cap (32 KiB) still has an upper bound; > 32 KiB
    without newline → response_too_large."""
    fake_uds_server.reply_raw(b"x" * 33000)  # exceed LAST_SCAN_RESPONSE_CAP
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsProtocolError) as ei:
        c.get_last_scan(timeout=2.0)
    assert "response_too_large" in str(ei.value)


# ---- PR-DIAG: get_jitter / get_amcl_rate --------------------------------


def test_get_jitter_happy(fake_uds_server) -> None:
    fake_uds_server.reply(
        b'{"ok":true,"valid":1,"p50_ns":4567,"p95_ns":12345,'
        b'"p99_ns":45678,"max_ns":123456,"mean_ns":5678,'
        b'"sample_count":2048,"published_mono_ns":1234}',
    )
    c = UdsClient(fake_uds_server.path)
    resp = c.get_jitter(timeout=2.0)
    assert resp["ok"] is True
    assert resp["valid"] == 1
    assert resp["p50_ns"] == 4567
    assert resp["sample_count"] == 2048


def test_get_jitter_sends_canonical_bytes(fake_uds_server) -> None:
    fake_uds_server.reply(b'{"ok":true,"valid":0}')
    c = UdsClient(fake_uds_server.path)
    c.get_jitter(timeout=2.0)
    assert fake_uds_server.captured == [b'{"cmd":"get_jitter"}\n']


def test_get_jitter_server_rejected_propagates(fake_uds_server) -> None:
    from godo_webctl.uds_client import UdsServerRejected

    fake_uds_server.reply(b'{"ok":false,"err":"unknown_cmd"}')
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsServerRejected) as ei:
        c.get_jitter(timeout=2.0)
    assert ei.value.err == "unknown_cmd"


def test_get_amcl_rate_happy(fake_uds_server) -> None:
    fake_uds_server.reply(
        b'{"ok":true,"valid":1,"hz":9.987654,'
        b'"last_iteration_mono_ns":1234,"total_iteration_count":42,'
        b'"published_mono_ns":1234}',
    )
    c = UdsClient(fake_uds_server.path)
    resp = c.get_amcl_rate(timeout=2.0)
    assert resp["ok"] is True
    assert resp["valid"] == 1
    assert resp["hz"] == 9.987654
    assert resp["total_iteration_count"] == 42


def test_get_amcl_rate_sends_canonical_bytes(fake_uds_server) -> None:
    fake_uds_server.reply(b'{"ok":true,"valid":0}')
    c = UdsClient(fake_uds_server.path)
    c.get_amcl_rate(timeout=2.0)
    assert fake_uds_server.captured == [b'{"cmd":"get_amcl_rate"}\n']


def test_get_amcl_rate_server_rejected_propagates(fake_uds_server) -> None:
    from godo_webctl.uds_client import UdsServerRejected

    fake_uds_server.reply(b'{"ok":false,"err":"unknown_cmd"}')
    c = UdsClient(fake_uds_server.path)
    with pytest.raises(UdsServerRejected) as ei:
        c.get_amcl_rate(timeout=2.0)
    assert ei.value.err == "unknown_cmd"
