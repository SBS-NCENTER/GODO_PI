"""
Track B Option C — pose_watch.py tests.

4 cases:
- happy_path_3_ticks_text_format: 3 successful polls produce 3 lines.
- reconnect_after_tracker_death: server goes silent for 3 ticks then
  resumes; watcher prints DISCONNECTED then continues.
- sigint_clean_exit: SIGINT mid-loop exits 0 within ~200 ms.
- format_json_one_line_per_tick: --format json emits valid JSON lines.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import _uds_bridge  # noqa: E402
import pose_watch as PW  # noqa: E402


def _ok_pose_reply(
    *,
    valid: int = 1,
    x: float = 1.0,
    y: float = 2.0,
    yaw: float = 90.0,
    iters: int = 7,
    converged: int = 1,
    forced: int = 0,
) -> bytes:
    return (
        f'{{"ok":true,"valid":{valid},"x_m":{x:.6f},"y_m":{y:.6f},'
        f'"yaw_deg":{yaw:.6f},"xy_std_m":0.005,"yaw_std_deg":0.1,'
        f'"iterations":{iters},"converged":{converged},"forced":{forced},'
        f'"published_mono_ns":1000}}\n'
    ).encode("ascii")


def test_happy_path_3_ticks_text_format(
    fake_uds_server: Any
) -> None:
    """3 successful polls → 3 text-format lines."""
    server = fake_uds_server
    for _ in range(3):
        server.reply(_ok_pose_reply())

    captured: list[str] = []
    sigint_event = {"fired": False}
    bridge = _uds_bridge.UdsBridge(str(server.path), timeout_s=0.5)

    # End the loop after 3 successful prints.
    def print_fn(line: str) -> None:
        captured.append(line)
        if len(captured) >= 3:
            sigint_event["fired"] = True

    rc = PW._watch_loop(
        bridge, interval_s=0.0,
        formatter=PW._format_text,
        print_fn=print_fn,
        sigint_event=sigint_event,
        once=False,
    )
    assert rc == 0
    assert len(captured) == 3
    for line in captured:
        # Spot-check: text format has the "x=" / "y=" / "yaw=" tokens.
        assert "x=" in line
        assert "y=" in line
        assert "yaw=" in line
        assert "iter=" in line


def test_reconnect_after_tracker_death(
    fake_uds_server: Any
) -> None:
    """Server goes silent for several ticks then resumes; the watcher
    prints exactly one DISCONNECTED sentinel and recovers."""
    server = fake_uds_server
    # 2 successful polls, then silence, then 1 more successful poll.
    server.reply(_ok_pose_reply())
    server.reply(_ok_pose_reply())

    captured: list[str] = []
    sigint_event = {"fired": False}
    bridge = _uds_bridge.UdsBridge(str(server.path), timeout_s=0.2)

    # Disable replies after the second success → simulate tracker death.
    success_count = 0
    resumed = False

    def print_fn(line: str) -> None:
        nonlocal success_count, resumed
        captured.append(line)
        if line.startswith("DISCONNECTED"):
            # On the first DISCONNECTED, queue a fresh reply + re-enable.
            if not resumed:
                resumed = True
                server.enable_replies()
                server.reply(_ok_pose_reply())
        else:
            success_count += 1
            if success_count == 2:
                # Trigger the death scenario.
                server.disable_replies()
            elif success_count >= 3:
                sigint_event["fired"] = True

    # Reduce the backoff schedule to keep the test fast.
    rc = PW._watch_loop(
        bridge, interval_s=0.0,
        formatter=PW._format_text,
        print_fn=print_fn,
        sigint_event=sigint_event,
        once=False,
        reconnect_backoff=(0.05, 0.05, 0.05),
    )
    assert rc == 0
    # Exactly one DISCONNECTED sentinel; subsequent silent failures
    # don't re-emit it (state-machine collapses repeats).
    disconnected = [line for line in captured if line.startswith("DISCONNECTED")]
    assert len(disconnected) == 1
    # 3 successful pose lines (2 before the death + 1 after recovery).
    pose_lines = [line for line in captured if line.startswith("20")]   # "2026-..."
    assert len(pose_lines) == 3


def test_sigint_clean_exit() -> None:
    """SIGINT delivered to a running pose_watch.py exits 0 within ~200 ms.
    Spawned as a subprocess against an unreachable socket so the watcher
    is parked in the reconnect-loop when the signal arrives."""
    # Use an unreachable socket — the watcher will spend its life in the
    # backoff sleep, which is broken into 100 ms slices for SIGINT response.
    proc = subprocess.Popen(
        [
            sys.executable,
            str(_SCRIPT_DIR / "pose_watch.py"),
            "--socket", "/tmp/godo-pose-watch-nonexistent.sock",
            "--interval", "0.1",
            "--format", "text",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait long enough for the first DISCONNECTED line to appear.
    time.sleep(0.5)
    # Send SIGINT and time the join.
    t0 = time.monotonic()
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=1.0)
        pytest.fail("pose_watch.py did not exit within 2 s of SIGINT")
    elapsed = time.monotonic() - t0
    assert proc.returncode == 0, f"exit={proc.returncode}"
    # 200 ms target per plan; allow generous CI slack while still
    # detecting "blocks forever" regressions.
    assert elapsed < 1.0, f"too slow: {elapsed:.3f}s"


def test_format_json_one_line_per_tick(
    fake_uds_server: Any
) -> None:
    """--format json emits one valid JSON object per tick on a single line."""
    server = fake_uds_server
    server.reply(_ok_pose_reply(x=3.14, yaw=180.0, iters=42, forced=1))

    captured: list[str] = []
    sigint_event = {"fired": False}
    bridge = _uds_bridge.UdsBridge(str(server.path), timeout_s=0.5)

    def print_fn(line: str) -> None:
        captured.append(line)
        sigint_event["fired"] = True

    rc = PW._watch_loop(
        bridge, interval_s=0.0,
        formatter=PW._format_json,
        print_fn=print_fn,
        sigint_event=sigint_event,
        once=True,
    )
    assert rc == 0
    assert len(captured) == 1
    line = captured[0]
    # Single line — no embedded newlines.
    assert "\n" not in line
    # Valid JSON.
    obj = json.loads(line)
    assert obj["valid"] == 1
    assert obj["x_m"] == pytest.approx(3.14)
    assert obj["yaw_deg"] == pytest.approx(180.0)
    assert obj["iterations"] == 42
    assert obj["forced"] == 1
    assert "wall_time_iso" in obj
