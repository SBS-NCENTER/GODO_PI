"""CSV writer for captured LiDAR samples.

Hot-path writer uses the stdlib `csv.writer` — pandas is never involved on
the capture path (see SYSTEM_DESIGN.md §10.2). One row per LiDAR sample.

Column order MUST match the header documented in SYSTEM_DESIGN.md §10.3.
Tests in `test_csv_dump.py` assert the exact header string literally so
that a reorder here fails the test — the test does NOT import `COLUMNS`.
"""

from __future__ import annotations

import csv
from io import TextIOWrapper
from pathlib import Path
from types import TracebackType
from typing import Any, Final

from godo_lidar.frame import Frame

COLUMNS: Final[tuple[str, ...]] = (
    "frame_idx",
    "sample_idx",
    "timestamp_ns",
    "angle_deg",
    "distance_mm",
    "quality",
    "flag",
)


class CsvDumpWriter:
    """Write Frames as CSV rows. One row per Sample.

    Use as a context manager; the file is opened in 'w' mode with
    ``newline=""`` as required by the stdlib csv module.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh: TextIOWrapper | None = None
        self._writer: Any | None = None
        self._frames_written = 0
        self._samples_written = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def frames_written(self) -> int:
        return self._frames_written

    @property
    def samples_written(self) -> int:
        return self._samples_written

    def __enter__(self) -> CsvDumpWriter:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def open(self) -> None:
        if self._fh is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh, lineterminator="\n")
        self._writer.writerow(COLUMNS)

    def close(self) -> None:
        if self._fh is None:
            return
        self._fh.flush()
        self._fh.close()
        self._fh = None
        self._writer = None

    def write_frame(self, frame: Frame) -> None:
        writer = self._writer
        if writer is None:
            raise RuntimeError("CsvDumpWriter.open() must be called first")
        for sample_idx, s in enumerate(frame.samples):
            writer.writerow(
                (
                    frame.index,
                    sample_idx,
                    s.timestamp_ns,
                    # `repr` would be ambiguous; format with enough precision
                    # for the protocol's Q6/Q2 granularity.
                    f"{s.angle_deg:.6f}",
                    f"{s.distance_mm:.3f}",
                    s.quality,
                    s.flag,
                )
            )
        self._frames_written += 1
        self._samples_written += len(frame.samples)
