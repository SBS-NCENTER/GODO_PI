"""Session log writer.

One text file per capture run, recording everything a later session (or AI
re-analysis without the hardware) needs to reproduce and verify the CSV.
Schema is pinned by SYSTEM_DESIGN.md §10.3.

The `csv_sha256` and `csv_byte_count` fields are computed after the CSV
file has been closed — the writer hashes the file on disk, not an in-memory
buffer, so any later corruption can be detected by recomputing.
"""

from __future__ import annotations

import hashlib
import platform
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CaptureParams:
    backend: str
    port: str
    baud: int
    rpm: int | None  # None → firmware default (sdk backend)
    frames_requested: int
    tag: str
    notes: str = ""


@dataclass
class RunStats:
    frames_captured: int = 0
    samples_total: int = 0
    duration_s: float = 0.0
    mean_quality: float = 0.0
    median_quality: float = 0.0
    dropped_frames: int = 0
    extra: dict[str, str] = field(default_factory=dict)


class SessionLogWriter:
    """Write a human-readable session log at the end of a capture run.

    Usage:

        log = SessionLogWriter(txt_path)
        log.write(params, stats, csv_path)

    `csv_path` must reference a file that has already been fully written
    and closed; the log hashes its bytes for integrity tracking.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def write(
        self,
        params: CaptureParams,
        stats: RunStats,
        csv_path: Path,
    ) -> None:
        sha256, byte_count = _hash_file(csv_path)
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# GODO Phase 1 capture session log",
            f"timestamp_utc   : {now_iso}",
            f"host            : {socket.gethostname()}",
            f"os              : {platform.platform()}",
            f"python          : {sys.version.split()[0]}",
            "",
            "## Capture parameters",
            f"backend         : {params.backend}",
            f"port            : {params.port}",
            f"baud            : {params.baud}",
            f"motor_rpm       : {params.rpm if params.rpm is not None else 'firmware-default'}",
            f"frames_requested: {params.frames_requested}",
            f"tag             : {params.tag}",
            f"notes           : {params.notes}",
            "",
            "## Run stats",
            f"frames_captured : {stats.frames_captured}",
            f"samples_total   : {stats.samples_total}",
            f"duration_s      : {stats.duration_s:.3f}",
            f"samples_per_sec : {_safe_rate(stats.samples_total, stats.duration_s):.1f}",
            f"mean_quality    : {stats.mean_quality:.2f}",
            f"median_quality  : {stats.median_quality:.2f}",
            f"dropped_frames  : {stats.dropped_frames}",
        ]
        for k, v in sorted(stats.extra.items()):
            lines.append(f"{k:16}: {v}")

        lines += [
            "",
            "## Artifact integrity",
            f"csv_path        : {csv_path}",
            f"csv_byte_count  : {byte_count}",
            f"csv_sha256      : {sha256}",
            "",
        ]
        self._path.write_text("\n".join(lines), encoding="utf-8")


def _hash_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(64 * 1024)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
    return h.hexdigest(), total


def _safe_rate(count: int, seconds: float) -> float:
    return count / seconds if seconds > 0 else 0.0
