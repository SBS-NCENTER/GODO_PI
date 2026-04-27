#!/usr/bin/env python3
"""
Track B Option C — continuous live-pose watch for a cmd-window operator.

Polls `get_last_pose` over UDS at a fixed interval, prints one line per
tick to stdout. Designed for "한 cmd 창 띄워두기" (keep an extra terminal
window open during shows) so the operator can see the AMCL pose drift /
re-converge live without committing to the heavier repeatability harness.

Usage:
    python3 godo-mapping/scripts/pose_watch.py [-h] [--socket PATH]
        [--interval F] [--format text|json] [--once]

Reconnect behaviour: on EPIPE/ECONNRESET/ECONNREFUSED/ENOENT the watcher
prints a single "DISCONNECTED" sentinel line, sleeps a backoff (1s, 2s,
4s, then 4s repeating), and retries forever. SIGINT cleanly exits 0
within ~200 ms.
"""

from __future__ import annotations

import argparse
import json
import signal
import socket
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any, Final

# `_uds_bridge` lives next to this file. Same N7 cwd-anchor as
# repeatability.py.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _uds_bridge import UdsBridge  # noqa: E402

# --- Tier-1 constants ------------------------------------------------------
DEFAULT_INTERVAL_S: Final[float] = 0.5
"""Default poll interval — 2 Hz. Frequent enough to feel live to a human
operator without saturating the tracker UDS thread."""

DEFAULT_SOCKET: Final[str] = "/run/godo/ctl.sock"
"""SSOT match for `cfg.uds_socket`."""

DEFAULT_FORMAT: Final[str] = "text"
"""text = one human-readable line; json = single-line JSON for log shipping."""

# F12 — reconnect backoff schedule. Increasing then capped at 4 s so the
# tracker can recover from a service restart without flooding logs but
# the operator's "wake-up" latency after a recovery stays under 5 s.
RECONNECT_BACKOFF_S: Final[tuple[float, ...]] = (1.0, 2.0, 4.0)

# Default UDS read timeout. Tracker's per-connection SO_RCVTIMEO is 1 s;
# we match that — a slower-than-1s reply means the tracker is wedged.
UDS_TIMEOUT_S: Final[float] = 1.0


# --- Formatters ------------------------------------------------------------


def _format_text(pose: dict[str, Any]) -> str:
    """One-line human-readable rendering. ANSI-clean (no escape codes)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    valid = int(pose.get("valid", 0))
    if valid != 1:
        return f"{ts}  valid=0  no AMCL pose published yet"
    x = float(pose["x_m"])
    y = float(pose["y_m"])
    yaw = float(pose["yaw_deg"])
    xy_std_mm = float(pose["xy_std_m"]) * 1000.0
    iters = int(pose["iterations"])
    converged = int(pose.get("converged", 0))
    forced = int(pose.get("forced", 0))
    mode_tag = "OneShot" if forced == 1 else "Live"
    status = "OK" if converged == 1 else "DIVERGED"
    return (
        f"{ts}  x={x:+.3f}  y={y:+.3f}  yaw={yaw:+.2f}  "
        f"std={xy_std_mm:.1f}mm  iter={iters:>3}  {mode_tag}  {status}"
    )


def _format_json(pose: dict[str, Any]) -> str:
    """One-line JSON rendering. Field order tracks `_LAST_POSE_FIELDS_LOCAL`
    plus a `wall_time_iso` prefix for log shipping."""
    out: dict[str, Any] = {
        "wall_time_iso": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        **pose,
    }
    return json.dumps(out, separators=(",", ":"), sort_keys=False)


# --- Poll loop -------------------------------------------------------------


def _watch_loop(
    bridge: UdsBridge,
    interval_s: float,
    formatter: Callable[[dict[str, Any]], str],
    *,
    print_fn: Callable[[str], None],
    sigint_event: dict[str, bool],
    once: bool = False,
    reconnect_backoff: Sequence[float] = RECONNECT_BACKOFF_S,
) -> int:
    """Main poll loop. Returns the exit code: 0 on clean exit, 130 on
    "ran but never produced any output" (signal early)."""
    backoff_idx = 0
    last_disconnected = False

    while not sigint_event.get("fired"):
        try:
            pose = bridge.get_last_pose()
        except (
            FileNotFoundError,
            ConnectionRefusedError,
            ConnectionResetError,
            BrokenPipeError,
            socket.timeout,
            OSError,
            ValueError,
        ) as e:
            if not last_disconnected:
                # First disconnect: print the sentinel + the cause so
                # the operator sees what went wrong.
                print_fn(f"DISCONNECTED  {type(e).__name__}: {e}")
                last_disconnected = True
            # Backoff schedule: index walks forward then sticks at the
            # last (longest) entry forever.
            wait = reconnect_backoff[
                min(backoff_idx, len(reconnect_backoff) - 1)
            ]
            backoff_idx += 1
            slept = 0.0
            while slept < wait and not sigint_event.get("fired"):
                step = min(0.1, wait - slept)
                time.sleep(step)
                slept += step
            continue

        # Successful read — reset the disconnect-state machine.
        if last_disconnected:
            backoff_idx = 0
            last_disconnected = False

        print_fn(formatter(pose))
        if once:
            return 0
        # Sleep in 100 ms slices for responsive SIGINT.
        slept = 0.0
        while slept < interval_s and not sigint_event.get("fired"):
            step = min(0.1, interval_s - slept)
            time.sleep(step)
            slept += step

    return 0


# --- main ------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pose_watch.py",
        description=(
            "Continuous live-pose watch for a cmd-window operator. Polls "
            "godo_tracker_rt's UDS get_last_pose at the configured "
            "interval; reconnects on tracker death."
        ),
    )
    parser.add_argument(
        "--socket", type=str, default=DEFAULT_SOCKET,
        help=f"UDS socket path (default: {DEFAULT_SOCKET})",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL_S,
        help=(
            f"seconds between polls (default: {DEFAULT_INTERVAL_S}; "
            "ignored when --once is set)"
        ),
    )
    parser.add_argument(
        "--format", type=str, choices=("text", "json"),
        default=DEFAULT_FORMAT,
        help=f"output format (default: {DEFAULT_FORMAT})",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="print one line then exit (smoke test mode)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.interval <= 0:
        sys.stderr.write("interval must be > 0\n")
        return 1

    formatter: Callable[[dict[str, Any]], str] = (
        _format_json if args.format == "json" else _format_text
    )

    sigint_event: dict[str, bool] = {"fired": False}

    def _on_sigint(_signo: int, _frame: FrameType | None) -> None:
        sigint_event["fired"] = True

    prev_int = signal.signal(signal.SIGINT, _on_sigint)
    prev_term = signal.signal(signal.SIGTERM, _on_sigint)
    try:
        bridge = UdsBridge(args.socket, timeout_s=UDS_TIMEOUT_S)
        return _watch_loop(
            bridge, args.interval, formatter,
            print_fn=lambda line: print(line, flush=True),
            sigint_event=sigint_event,
            once=args.once,
        )
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)


if __name__ == "__main__":
    sys.exit(main())
