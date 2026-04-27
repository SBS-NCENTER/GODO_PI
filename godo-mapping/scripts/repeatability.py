#!/usr/bin/env python3
"""
Track B Phase 1 measurement instrument — drives the production
`godo_tracker_rt` through N consecutive OneShot calibrations from a
stationary base, captures each AMCL pose + convergence diagnostics, and
emits an incrementally-written CSV plus terminal summary statistics.

Usage:
    python3 godo-mapping/scripts/repeatability.py [-h] [--shots N]
        [--interval-s F] [--out PATH] [--socket PATH]
        [--uds-timeout-s F] [--oneshot-timeout-s F] [--dry-run]

Exit codes:
    0    success
    1    CLI argument validation failed (e.g. shots < 1)
    2    initial UDS socket unreachable
    3    tracker not in Idle on entry (busy with Live or OneShot)
    4    set_mode("OneShot") rejected by the tracker
    5    CSV file open / write error
    6    SIGINT before the first shot (no rows written)
    7    tracker-death streak: 3 consecutive UDS failures (F10)
    130  SIGINT after at least one row written (POSIX 128 + SIGINT)

Failure semantics — the harness writes a sentinel CSV row for transient
shot-level failures (Idle-poll timeout, valid=false, transient UDS) so
the operator can see which shots failed inline. See plan v2 §"Failure
modes and CSV semantics".
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import signal
import socket
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import Any, Final, IO

# `_uds_bridge` lives next to this file. The runtime path resolution is
# Python's standard "module next to script" — see N7 cwd-anchor pattern.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _uds_bridge import _LAST_POSE_FIELDS_LOCAL, UdsBridge  # noqa: E402

# --- Tier-1 constants ------------------------------------------------------
DEFAULT_SHOTS: Final[int] = 100
"""Default shot count per session. 100 strikes a balance between statistical
power and operator patience: ~5 minutes of test wall time at the default
interval, enough samples for a meaningful 95th-percentile bound."""

DEFAULT_INTERVAL_S: Final[float] = 2.0
"""Default seconds between OneShot triggers. The cold writer takes ~1 s for
converge() at 5000 particles × 25 iters; 2 s gives the tracker headroom +
keeps the AMCL particle cloud's RNG state from being contiguous-time."""

DEFAULT_SOCKET: Final[str] = "/run/godo/ctl.sock"
"""SSOT match for `cfg.uds_socket` in production/RPi5/src/core/config.cpp."""

UDS_TIMEOUT_S: Final[float] = 1.0
"""Per-syscall UDS timeout. The tracker's per-connection SO_RCVTIMEO is 1 s
(production/RPi5/src/core/constants.hpp UDS_CONN_READ_TIMEOUT_SEC); we
match that floor so we surface server-side timeouts as our own."""

ONESHOT_WAIT_TIMEOUT_S: Final[float] = 15.0
"""Hard ceiling on how long we wait for `get_mode == Idle` after sending
`set_mode OneShot`. 15 s = 5×3 σ above the typical 1 s converge() at
nominal AMCL params; failures past this are diagnostic, not stochastic."""

IDLE_POLL_INTERVAL_S: Final[float] = 0.1
"""Sleep between `get_mode` polls during the Idle-wait loop. 100 ms is
fast enough for human-scale UX (operator sees "in progress" feedback)
without flooding the tracker."""

PERCENTILE: Final[float] = 95.0
"""Summary statistic alongside mean/stdev/min/max. 95th percentile of the
per-shot deviation from the mean — communicates the worst-case for the
field-integration test in a single number."""

MAX_TRACKER_DEATH_STREAK: Final[int] = 3
"""F10 — consecutive UDS connection failures before we abort with exit 7.
Three back-to-back EPIPE/ECONNRESET/ECONNREFUSED/ENOENT means the tracker
likely died (systemctl restart may be needed); continuing past this
fills the CSV with sentinels and wastes operator time."""

# Derived bound — keep loop counts capped so a wedged tracker can't hang.
_MAX_POLLS: Final[int] = int(ONESHOT_WAIT_TIMEOUT_S / IDLE_POLL_INTERVAL_S)

# CSV header derived from the wire-protocol mirror. Adding the test-side
# audit columns (`idx`, `timestamp_unix`) before the wire fields keeps
# downstream pandas/Excel ingestion easy.
CSV_HEADER: Final[tuple[str, ...]] = (
    "idx",
    "timestamp_unix",
    *_LAST_POSE_FIELDS_LOCAL,
)


# --- Stats helpers ---------------------------------------------------------


def _summary(values: Sequence[float]) -> dict[str, float | int] | None:
    """Compute mean/stdev/min/max/p95_abs_dev. F4: returns NaN for stdev
    and p95 when N < 2 to avoid stdlib statistics raising. N=0 returns
    None so the caller can skip the line cleanly."""
    n = len(values)
    if n == 0:
        return None
    if n == 1:
        v = float(values[0])
        return {
            "mean": v,
            "stdev": float("nan"),
            "min": v,
            "max": v,
            "p95_abs_dev": float("nan"),
            "n": 1,
        }
    mean = statistics.fmean(values)
    stdev = statistics.stdev(values)
    abs_dev = sorted(abs(v - mean) for v in values)
    # Linear interpolation on sorted abs_dev. P95 of N points: the
    # 0.95*(N-1) index, with linear blend between the floor and ceil.
    rank = (PERCENTILE / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        p95 = abs_dev[lo]
    else:
        p95 = abs_dev[lo] + (abs_dev[hi] - abs_dev[lo]) * (rank - lo)
    return {
        "mean": mean,
        "stdev": stdev,
        "min": min(values),
        "max": max(values),
        "p95_abs_dev": p95,
        "n": n,
    }


def _print_summary(rows: Sequence[dict[str, Any]]) -> None:
    """Print a 4-column table (mean/stdev/min/max/p95) of x_m, y_m,
    yaw_deg, xy_std_m, yaw_std_deg, iterations across all valid rows."""
    valid = [r for r in rows if int(r.get("valid", 0)) == 1]
    print(f"\nSummary across {len(valid)}/{len(rows)} valid shots:")
    if not valid:
        print("  (no valid shots — nothing to summarise)")
        return
    fields = ("x_m", "y_m", "yaw_deg", "xy_std_m", "yaw_std_deg", "iterations")
    print(f"  {'field':<14} {'mean':>14} {'stdev':>14} {'p95_abs_dev':>14}")
    for fname in fields:
        values = [float(r[fname]) for r in valid if fname in r]
        s = _summary(values)
        if s is None:
            continue
        print(
            f"  {fname:<14} "
            f"{s['mean']:>14.6g} "
            f"{s['stdev']:>14.6g} "
            f"{s['p95_abs_dev']:>14.6g}"
        )


# --- CSV sink --------------------------------------------------------------


class _CsvSink:
    """Incremental CSV writer with parent-dir mkdir (F13) + per-row fsync."""

    def __init__(self, out_path: Path) -> None:
        self.out_path = out_path
        self._fp: IO[str] | None = None
        self._writer: csv.DictWriter[str] | None = None
        self._row_count = 0

    def open(self) -> None:
        # F13: create the parent directory if missing. The default
        # `measurements/` dir is committed via .gitkeep + .gitignore, but
        # operators may pass --out into a fresh location.
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self.out_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._fp,
            fieldnames=list(CSV_HEADER),
            quoting=csv.QUOTE_MINIMAL,
        )
        self._writer.writeheader()
        self._fp.flush()
        os.fsync(self._fp.fileno())

    def write(self, row: dict[str, Any]) -> None:
        if self._writer is None or self._fp is None:
            raise RuntimeError("_CsvSink.open() not called")
        # csv.DictWriter raises on extra keys; project to CSV_HEADER.
        proj = {k: row.get(k, "") for k in CSV_HEADER}
        self._writer.writerow(proj)
        self._fp.flush()
        os.fsync(self._fp.fileno())
        self._row_count += 1

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None
            self._writer = None

    @property
    def row_count(self) -> int:
        return self._row_count


# --- Harness body ----------------------------------------------------------


def _wait_for_idle(bridge: UdsBridge) -> bool:
    """Poll get_mode at IDLE_POLL_INTERVAL_S until it returns Idle or
    we exceed _MAX_POLLS. Returns True on Idle, False on timeout.
    Transient UDS errors during the poll are propagated."""
    for _ in range(_MAX_POLLS):
        mode = bridge.get_mode()
        if mode == "Idle":
            return True
        time.sleep(IDLE_POLL_INTERVAL_S)
    return False


def _execute_one_shot(bridge: UdsBridge, idx: int) -> dict[str, Any]:
    """Trigger one OneShot and return the resulting CSV row dict.
    Sentinel rows for failure modes have valid=0 and the offending
    shot index in `idx`. Tracker-death exceptions propagate to the
    caller (`run`) which counts the streak.

    F5 read-side: poll get_mode==Idle BEFORE get_last_pose. The C++ writer
    stores last_pose_seq with release ordering BEFORE g_amcl_mode=Idle, so
    observing Idle here implies the new pose is visible.
    """
    timestamp_unix = time.time()
    bridge.set_mode("OneShot")
    if not _wait_for_idle(bridge):
        sys.stderr.write(f"shot {idx}: timeout\n")
        return _sentinel_row(idx, timestamp_unix)
    pose = bridge.get_last_pose()
    if int(pose.get("valid", 0)) != 1:
        sys.stderr.write(f"shot {idx}: no published pose\n")
        return _sentinel_row(idx, timestamp_unix)
    if int(pose.get("converged", 0)) != 1:
        sys.stderr.write(f"shot {idx}: diverged\n")
        # Verbatim row: keep pose values for diagnostic, just log the warning.
    return {"idx": idx, "timestamp_unix": timestamp_unix, **pose}


def _sentinel_row(idx: int, timestamp_unix: float) -> dict[str, Any]:
    """Failure-mode CSV row: valid=0, all numeric fields blank-equivalent."""
    row: dict[str, Any] = {"idx": idx, "timestamp_unix": timestamp_unix}
    for name in _LAST_POSE_FIELDS_LOCAL:
        if name == "valid":
            row[name] = 0
        elif name == "iterations":
            row[name] = -1
        else:
            row[name] = ""
    return row


def _compute_default_out() -> Path:
    """F11 — return repo-anchored measurements/repeatability_<ISO>.csv.
    Testable surface (no time.time() injection needed in the test —
    isolation is via tmp_path)."""
    repo_root = Path(__file__).resolve().parents[1]
    iso = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return repo_root / "measurements" / f"repeatability_{iso}.csv"


def run(args: argparse.Namespace, *, sigint_event: dict[str, bool]) -> int:
    """Main harness body. Returns the exit code; main() forwards."""
    out_path = Path(args.out) if args.out else _compute_default_out()
    sink = _CsvSink(out_path)
    try:
        sink.open()
    except OSError as e:
        sys.stderr.write(f"failed to open output CSV '{out_path}': {e}\n")
        return 5

    bridge = UdsBridge(args.socket, timeout_s=args.uds_timeout_s)

    # Initial reachability probe — ping is cheap and surfaces an
    # ENOENT/ECONNREFUSED before we modify tracker state.
    try:
        bridge.ping()
    except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError) as e:
        sys.stderr.write(f"tracker unreachable: {e}\n")
        sink.close()
        return 2
    except (OSError, ValueError) as e:
        sys.stderr.write(f"tracker unreachable: {e}\n")
        sink.close()
        return 2

    # Mode sanity check — running a OneShot during Live or another
    # OneShot would clobber an in-flight cycle and confuse the operator.
    try:
        mode = bridge.get_mode()
    except Exception as e:
        sys.stderr.write(f"tracker unreachable: get_mode failed: {e}\n")
        sink.close()
        return 2
    if mode != "Idle":
        sys.stderr.write(f"tracker busy: mode={mode}\n")
        sink.close()
        return 3

    if args.dry_run:
        sys.stderr.write(
            f"dry-run: would run {args.shots} shots @ {args.interval_s}s "
            f"interval, output {out_path}\n"
        )
        sink.close()
        return 0

    rows: list[dict[str, Any]] = []
    death_streak = 0

    for idx in range(1, args.shots + 1):
        if sigint_event.get("fired"):
            if not rows:
                sys.stderr.write("interrupted before first shot\n")
                sink.close()
                return 6
            break
        try:
            row = _execute_one_shot(bridge, idx)
            death_streak = 0
        except (
            FileNotFoundError,
            ConnectionRefusedError,
            ConnectionResetError,
            BrokenPipeError,
            socket.timeout,
        ) as e:
            sys.stderr.write(f"shot {idx}: UDS timeout: {e}\n")
            row = _sentinel_row(idx, time.time())
            death_streak += 1
        except ValueError as e:
            # Server-level error reply (e.g. bad_mode). Should never
            # happen for set_mode("OneShot") against the production
            # tracker, but surface as exit 4 if it does on shot 1.
            if idx == 1:
                sys.stderr.write(f"set_mode rejected: {e}\n")
                sink.close()
                return 4
            sys.stderr.write(f"shot {idx}: server error: {e}\n")
            row = _sentinel_row(idx, time.time())

        try:
            sink.write(row)
        except OSError as e:
            sys.stderr.write(f"CSV write failed: {e}\n")
            sink.close()
            return 5
        rows.append(row)

        if death_streak >= MAX_TRACKER_DEATH_STREAK:
            sys.stderr.write(
                "tracker likely died — check journalctl -u godo-tracker\n"
            )
            sink.close()
            return 7

        if idx < args.shots and not sigint_event.get("fired"):
            # Sleep in slices of IDLE_POLL_INTERVAL_S so SIGINT response
            # is bounded by 100 ms even with --interval-s 60.
            slept = 0.0
            while slept < args.interval_s and not sigint_event.get("fired"):
                step = min(IDLE_POLL_INTERVAL_S, args.interval_s - slept)
                time.sleep(step)
                slept += step

    sink.close()
    _print_summary(rows)
    print(f"\nWrote {sink.row_count} rows to {out_path}")
    if sigint_event.get("fired"):
        return 130
    return 0


# --- main ------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repeatability.py",
        description=(
            "Drive godo_tracker_rt through N OneShot calibrations from a "
            "stationary base; capture each pose + diagnostics to CSV."
        ),
    )
    parser.add_argument(
        "--shots", type=int, default=DEFAULT_SHOTS,
        help=f"number of OneShot iterations (default: {DEFAULT_SHOTS})",
    )
    parser.add_argument(
        "--interval-s", type=float, default=DEFAULT_INTERVAL_S,
        help=f"seconds between shots (default: {DEFAULT_INTERVAL_S})",
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help=(
            "output CSV path (default: <repo>/godo-mapping/measurements/"
            "repeatability_<ISO>.csv)"
        ),
    )
    parser.add_argument(
        "--socket", type=str, default=DEFAULT_SOCKET,
        help=f"UDS socket path (default: {DEFAULT_SOCKET})",
    )
    parser.add_argument(
        "--uds-timeout-s", type=float, default=UDS_TIMEOUT_S,
        help=f"per-syscall UDS timeout (default: {UDS_TIMEOUT_S})",
    )
    parser.add_argument(
        "--oneshot-timeout-s", type=float, default=ONESHOT_WAIT_TIMEOUT_S,
        help=(
            "max seconds to wait for get_mode==Idle after a OneShot trigger "
            f"(default: {ONESHOT_WAIT_TIMEOUT_S})"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="open CSV, probe tracker, then exit without triggering shots",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    # F14 — reject N < 1 with stderr message + exit 1.
    if args.shots < 1:
        sys.stderr.write("shots must be >= 1\n")
        return 1
    if args.interval_s < 0:
        sys.stderr.write("interval-s must be >= 0\n")
        return 1

    # Mutable container so the signal handler can flip the flag without
    # `nonlocal`. Tests inject a pre-built dict to assert shutdown
    # behaviour deterministically.
    sigint_event: dict[str, bool] = {"fired": False}

    def _on_sigint(_signo: int, _frame: FrameType | None) -> None:
        sigint_event["fired"] = True

    prev = signal.signal(signal.SIGINT, _on_sigint)
    try:
        return run(args, sigint_event=sigint_event)
    finally:
        signal.signal(signal.SIGINT, prev)


if __name__ == "__main__":
    sys.exit(main())
