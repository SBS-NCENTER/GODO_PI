"""
Track B Phase 1 measurement instrument tests.

10 cases covering happy path, divergence, transport failures, dry run,
N=1 stdev safety (F4), tracker-death streak (F10), default-out path
resolution (F11), parent-dir mkdir (F13), shots validation (F14), and a
negative shots case.

3 structural pins:
- csv_header_byte_exact      — CSV_HEADER literal pin
- no_godo_webctl_runtime_import — runtime imports must NOT pull in
  godo_webctl (test-time conftest sys.path inject is fine)
- local_fields_match_protocol_mirror — _LAST_POSE_FIELDS_LOCAL ==
  godo_webctl.protocol.LAST_POSE_FIELDS via test-time import
"""

from __future__ import annotations

import csv
import importlib
import math
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# Same N7 anchor as the production scripts. We can import the script as a
# module because conftest.py also injects this dir into sys.path.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import _uds_bridge  # noqa: E402
import repeatability as R  # noqa: E402


# Build a canonical successful get_last_pose JSON reply with a fixed seed.
def _ok_pose_reply(
    *,
    x: float = 1.234567,
    y: float = -2.345678,
    yaw: float = 42.5,
    xy_std: float = 0.012,
    yaw_std: float = 0.05,
    iters: int = 12,
    converged: int = 1,
    forced: int = 1,
    mono_ns: int = 1234567890,
    valid: int = 1,
) -> bytes:
    return (
        f'{{"ok":true,"valid":{valid},"x_m":{x:.6f},"y_m":{y:.6f},'
        f'"yaw_deg":{yaw:.6f},"xy_std_m":{xy_std:.9g},'
        f'"yaw_std_deg":{yaw_std:.9g},"iterations":{iters},'
        f'"converged":{converged},"forced":{forced},'
        f'"published_mono_ns":{mono_ns}}}\n'
    ).encode("ascii")


_OK_PING = b'{"ok":true}\n'
_OK_IDLE = b'{"ok":true,"mode":"Idle"}\n'
_OK_LIVE = b'{"ok":true,"mode":"Live"}\n'
_OK_ONESHOT = b'{"ok":true,"mode":"OneShot"}\n'
_OK_GENERIC = b'{"ok":true}\n'


def _queue_one_shot_sequence(
    server: Any,
    *,
    pose_reply: bytes | None = None,
    final_idle: bool = True,
) -> None:
    """Queue the 4 replies a single shot consumes:
    1. set_mode("OneShot")  → ok
    2. get_mode             → Idle (immediate)
    3. get_last_pose        → pose_reply (default: happy-path)
    4. (next-shot ping or terminator) — caller queues these
    """
    server.reply(_OK_GENERIC)
    if final_idle:
        server.reply(_OK_IDLE)
    server.reply(pose_reply if pose_reply else _ok_pose_reply())


# --- Helpers for invoking R.main on a fake server ---------------------------


def _make_args(
    *,
    socket_path: Path,
    out: Path,
    shots: int = 1,
    interval_s: float = 0.0,
    dry_run: bool = False,
    uds_timeout_s: float = 0.5,
    oneshot_timeout_s: float = 5.0,
) -> list[str]:
    args = [
        "--socket", str(socket_path),
        "--out", str(out),
        "--shots", str(shots),
        "--interval-s", str(interval_s),
        "--uds-timeout-s", str(uds_timeout_s),
        "--oneshot-timeout-s", str(oneshot_timeout_s),
    ]
    if dry_run:
        args.append("--dry-run")
    return args


# --- Tests -----------------------------------------------------------------


def test_csv_header_byte_exact() -> None:
    """Pin: CSV_HEADER must contain idx, timestamp_unix, then the wire
    field order — never a column reorder by accident."""
    assert R.CSV_HEADER == (
        "idx", "timestamp_unix",
        "valid", "x_m", "y_m", "yaw_deg",
        "xy_std_m", "yaw_std_deg",
        "iterations", "converged", "forced",
        "published_mono_ns",
    )


def test_no_godo_webctl_runtime_import() -> None:
    """Runtime scripts MUST NOT pull in godo_webctl. The conftest
    injects sys.path for test-time only; this asserts the runtime
    modules themselves stay decoupled."""
    # Spawn a fresh subprocess to avoid pollution from this test
    # process (which has godo_webctl on sys.path via conftest).
    result = subprocess.run(
        [
            sys.executable, "-c",
            (
                "import sys, importlib;\n"
                "import repeatability;  # noqa: E402\n"
                "import _uds_bridge;     # noqa: E402\n"
                "import pose_watch;      # noqa: E402\n"
                "loaded = [m for m in sys.modules if "
                "m == 'godo_webctl' or m.startswith('godo_webctl.')]\n"
                "print(loaded)\n"
                "sys.exit(1 if loaded else 0)\n"
            ),
        ],
        cwd=str(_SCRIPT_DIR),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"godo_webctl imported at runtime: {result.stdout!r} {result.stderr!r}"
    )


def test_local_fields_match_protocol_mirror() -> None:
    """conftest.py injects godo-webctl/src into sys.path so this
    test-time import works. Runtime drift between the two mirrors is
    caught here; combined with test_protocol.py's regex pin against
    the C++ source, the chain is closed: C++ source ⟷ protocol.py ⟷
    _uds_bridge.py."""
    from godo_webctl import protocol as P
    assert _uds_bridge._LAST_POSE_FIELDS_LOCAL == P.LAST_POSE_FIELDS


# --- Behavioural tests ------------------------------------------------------


def test_happy_path_3_shots(fake_uds_server: Any, tmp_path: Path) -> None:
    """3 shots → 3 CSV rows + a header. Each shot needs:
    set_mode → ok, get_mode → Idle, get_last_pose → ok pose."""
    server = fake_uds_server
    server.reply(_OK_PING)        # initial ping
    server.reply(_OK_IDLE)        # initial get_mode
    for _ in range(3):
        _queue_one_shot_sequence(server)

    out = tmp_path / "out.csv"
    args = _make_args(socket_path=server.path, out=out, shots=3)
    rc = R.main(args)
    assert rc == 0
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 3
    for row in rows:
        assert int(row["valid"]) == 1
        assert float(row["x_m"]) == pytest.approx(1.234567)


def test_diverged_shot(fake_uds_server: Any, tmp_path: Path) -> None:
    """One shot with converged=0 still writes a row (verbatim) and
    emits a stderr warning."""
    server = fake_uds_server
    server.reply(_OK_PING)
    server.reply(_OK_IDLE)
    _queue_one_shot_sequence(
        server,
        pose_reply=_ok_pose_reply(converged=0),
    )
    out = tmp_path / "out.csv"
    args = _make_args(socket_path=server.path, out=out, shots=1)
    rc = R.main(args)
    assert rc == 0
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 1
    assert int(rows[0]["valid"]) == 1
    assert int(rows[0]["converged"]) == 0


def test_connection_refused(tmp_path: Path) -> None:
    """No server bound to the socket path → exit 2."""
    out = tmp_path / "out.csv"
    args = _make_args(
        socket_path=tmp_path / "nonexistent.sock",
        out=out,
        shots=1,
    )
    rc = R.main(args)
    assert rc == 2


def test_dry_run(fake_uds_server: Any, tmp_path: Path) -> None:
    """--dry-run probes tracker (ping + get_mode) then exits 0 without
    triggering any shots. Output CSV is still created (header only)."""
    server = fake_uds_server
    server.reply(_OK_PING)
    server.reply(_OK_IDLE)
    out = tmp_path / "out.csv"
    args = _make_args(
        socket_path=server.path, out=out, shots=10, dry_run=True,
    )
    rc = R.main(args)
    assert rc == 0
    rows = list(csv.DictReader(out.open()))
    assert rows == []   # header written, no data rows


def test_single_converged_shot_no_stdev_crash(
    fake_uds_server: Any, tmp_path: Path
) -> None:
    """F4 — a single shot must not crash the summary path. statistics.stdev
    raises on N<2; _summary returns NaN instead."""
    server = fake_uds_server
    server.reply(_OK_PING)
    server.reply(_OK_IDLE)
    _queue_one_shot_sequence(server)
    out = tmp_path / "out.csv"
    args = _make_args(socket_path=server.path, out=out, shots=1)
    rc = R.main(args)
    assert rc == 0

    summary = R._summary([1.0])
    assert summary is not None
    assert summary["mean"] == 1.0
    assert math.isnan(summary["stdev"])
    assert math.isnan(summary["p95_abs_dev"])
    assert summary["n"] == 1


def test_tracker_death_streak(
    fake_uds_server: Any, tmp_path: Path
) -> None:
    """F10 — 3 consecutive UDS failures → exit 7 with sentinel rows.
    Reproduce by queuing only the initial probe + first shot's replies;
    subsequent connections find an empty reply queue and hang (the fake
    server holds the conn open until stop). The client read times out
    on each, producing the 3-strike streak."""
    server = fake_uds_server
    server.reply(_OK_PING)
    server.reply(_OK_IDLE)
    # First shot consumes 3 replies (set_mode, get_mode, get_last_pose).
    _queue_one_shot_sequence(server)
    # No further replies queued → subsequent recv()s time out → streak.

    out = tmp_path / "out.csv"
    args = _make_args(
        socket_path=server.path, out=out, shots=10,
        interval_s=0.0, uds_timeout_s=0.2,
    )
    rc = R.main(args)
    assert rc == 7
    rows = list(csv.DictReader(out.open()))
    # 1 success + 3 sentinel rows before exit; 4th attempt triggers exit-7.
    assert len(rows) == 4
    assert int(rows[0]["valid"]) == 1
    for sentinel in rows[1:]:
        assert int(sentinel["valid"]) == 0


def test_default_out_path() -> None:
    """F11 — default --out resolves to <repo>/godo-mapping/measurements/
    repeatability_<ISO>.csv regardless of cwd."""
    p = R._compute_default_out()
    parts = p.parts
    assert "godo-mapping" in parts
    assert "measurements" in parts
    assert p.name.startswith("repeatability_")
    assert p.suffix == ".csv"
    # Repo-root anchor: no '..' or duplicates.
    assert ".." not in parts


def test_out_path_creates_parent(
    fake_uds_server: Any, tmp_path: Path
) -> None:
    """F13 — --out under a non-existent parent dir auto-creates it."""
    server = fake_uds_server
    server.reply(_OK_PING)
    server.reply(_OK_IDLE)
    _queue_one_shot_sequence(server)
    out = tmp_path / "deep" / "nested" / "out.csv"
    assert not out.parent.exists()
    args = _make_args(socket_path=server.path, out=out, shots=1)
    rc = R.main(args)
    assert rc == 0
    assert out.exists()
    assert out.parent.is_dir()


def test_shots_zero_rejected(tmp_path: Path) -> None:
    """F14 — --shots 0 → exit 1 with stderr 'shots must be >= 1'."""
    args = [
        "--socket", "/tmp/never-used.sock",
        "--out", str(tmp_path / "out.csv"),
        "--shots", "0",
    ]
    rc = R.main(args)
    assert rc == 1


def test_shots_negative_rejected(tmp_path: Path, capsys: Any) -> None:
    """--shots -5 → exit 1, stderr message present."""
    args = [
        "--socket", "/tmp/never-used.sock",
        "--out", str(tmp_path / "out.csv"),
        "--shots", "-5",
    ]
    rc = R.main(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "shots must be >= 1" in captured.err


def test_busy_tracker_returns_3(
    fake_uds_server: Any, tmp_path: Path
) -> None:
    """get_mode != Idle on entry → exit 3 with stderr 'tracker busy'."""
    server = fake_uds_server
    server.reply(_OK_PING)
    server.reply(_OK_LIVE)        # tracker is in Live mode
    out = tmp_path / "out.csv"
    args = _make_args(socket_path=server.path, out=out, shots=1)
    rc = R.main(args)
    assert rc == 3
