"""Capture script — drives one of the two backends, writes CSV + session log.

Usage (Windows PowerShell example):

    uv run python scripts/capture.py --backend raw --port COM7 --frames 100 ^
        --tag bench1 --notes "static position A, empty room"

Artifacts:
    data/<timestamp>_<backend>_<tag>.csv
    logs/<timestamp>_<backend>_<tag>.txt

CSV is the sample-per-row dump; the txt file records host / params / stats /
csv integrity hash per SYSTEM_DESIGN.md §10.3.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from godo_lidar.io import CaptureParams, CsvDumpWriter, RunStats, SessionLogWriter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from godo_lidar.frame import Frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture LiDAR scans from RPLIDAR C1 and dump to CSV + session log."
        ),
    )
    parser.add_argument(
        "--backend",
        choices=("sdk", "raw"),
        required=True,
        help="sdk: pyrplidar (baseline); raw: pyserial + in-house parser",
    )
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port (Windows: COM7 etc.; Linux: /dev/ttyUSB0)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        required=True,
        help="Number of whole 360-degree frames to capture (>= 1)",
    )
    parser.add_argument(
        "--tag",
        required=True,
        help="Short slug for the output filenames, e.g. 'bench1', 'reflector_5m'",
    )
    parser.add_argument("--notes", default="", help="Operator notes for the log")
    parser.add_argument(
        "--rpm",
        type=int,
        default=None,
        help=(
            "Target motor RPM (raw backend only; default 600 → 10 Hz scan rate). "
            "Not supported on --backend sdk: pyrplidar does not expose the C1's "
            "MOTOR_SPEED_CTRL command (0xA8)."
        ),
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=460_800,
        help="Serial baud (default 460800 per RPLIDAR_C1.md §3)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory for the CSV output",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("logs"),
        help="Directory for the session .txt log",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable INFO-level logging (DEBUG with -vv)",
    )
    parser.add_argument(
        "-vv",
        dest="very_verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    args = parser.parse_args(argv)

    if args.frames < 1:
        parser.error("--frames must be >= 1")

    if args.backend == "sdk" and args.rpm is not None:
        parser.error(
            "--rpm is not supported on --backend sdk "
            "(C1 cmd 0xA8 is not exposed by pyrplidar). "
            "Use --backend raw for motor-speed control."
        )

    level = (
        logging.DEBUG
        if args.very_verbose
        else logging.INFO
        if args.verbose
        else logging.WARNING
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = f"{timestamp}_{args.backend}_{args.tag}"
    csv_path: Path = args.data_dir / f"{slug}.csv"
    log_path: Path = args.log_dir / f"{slug}.txt"

    backend = _make_backend(args)

    stats = RunStats()
    qualities: list[int] = []
    t0 = time.monotonic()
    with backend as lidar, CsvDumpWriter(csv_path) as writer:
        frames: Iterator[Frame] = lidar.scan_frames(args.frames)
        for frame in frames:
            writer.write_frame(frame)
            for s in frame.samples:
                qualities.append(s.quality)
            stats.frames_captured += 1
            stats.samples_total += len(frame.samples)
    stats.duration_s = time.monotonic() - t0
    if qualities:
        stats.mean_quality = statistics.fmean(qualities)
        stats.median_quality = float(statistics.median(qualities))

    params = CaptureParams(
        backend=args.backend,
        port=args.port,
        baud=args.baud,
        rpm=args.rpm,
        frames_requested=args.frames,
        tag=args.tag,
        notes=args.notes,
    )
    SessionLogWriter(log_path).write(params, stats, csv_path)

    print(f"CSV : {csv_path}")
    print(f"log : {log_path}")
    print(
        f"captured {stats.frames_captured} frames / "
        f"{stats.samples_total} samples in {stats.duration_s:.2f} s"
    )
    return 0


def _make_backend(args: argparse.Namespace) -> object:
    if args.backend == "sdk":
        from godo_lidar.capture.sdk import SdkBackend

        return SdkBackend(port=args.port, baud=args.baud)
    if args.backend == "raw":
        from godo_lidar.capture.raw import DEFAULT_RPM, RawBackend

        rpm = args.rpm if args.rpm is not None else DEFAULT_RPM
        return RawBackend(port=args.port, baud=args.baud, rpm=rpm)
    raise AssertionError(f"unreachable backend {args.backend!r}")


if __name__ == "__main__":
    raise SystemExit(main())
