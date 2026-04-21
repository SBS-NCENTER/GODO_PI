"""Tests for `godo_lidar.io.csv_dump`.

Anti-bias note (reviewer finding #3): these tests intentionally do NOT
import `COLUMNS` from production. The expected header is duplicated here as
a literal string so that any reorder in production breaks the test.
"""

from __future__ import annotations

import csv
from pathlib import Path

from godo_lidar.frame import Frame, Sample
from godo_lidar.io.csv_dump import CsvDumpWriter

# Duplicated on purpose — see module docstring.
EXPECTED_HEADER_LINE = "frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag"


def _make_frame(index: int, n: int) -> Frame:
    samples = [
        Sample(
            angle_deg=(i * 0.72) % 360.0,
            distance_mm=1000.0 + i,
            quality=50 + i,
            flag=1 if i == 0 else 0,
            timestamp_ns=1_000_000 * (i + 1),
        )
        for i in range(n)
    ]
    return Frame(index=index, samples=samples)


def test_header_matches_literal_and_is_first_line(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    with CsvDumpWriter(path):
        pass

    with open(path, encoding="utf-8") as fh:
        first_line = fh.readline().rstrip("\n\r")
    assert first_line == EXPECTED_HEADER_LINE


def test_roundtrip_preserves_sample_contents(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    frame0 = _make_frame(index=0, n=5)
    frame1 = _make_frame(index=1, n=3)

    with CsvDumpWriter(path) as w:
        w.write_frame(frame0)
        w.write_frame(frame1)
        assert w.frames_written == 2
        assert w.samples_written == 8

    # Read back without the production COLUMNS tuple — use DictReader and
    # compare each field by its literal name.
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert len(rows) == 8

    # First row: frame0, sample 0.
    r0 = rows[0]
    assert r0["frame_idx"] == "0"
    assert r0["sample_idx"] == "0"
    assert r0["timestamp_ns"] == "1000000"
    assert float(r0["angle_deg"]) == 0.0
    assert float(r0["distance_mm"]) == 1000.0
    assert r0["quality"] == "50"
    assert r0["flag"] == "1"

    # Last row of frame0: sample_idx 4.
    r4 = rows[4]
    assert r4["frame_idx"] == "0"
    assert r4["sample_idx"] == "4"
    assert float(r4["angle_deg"]) == (4 * 0.72) % 360.0
    assert float(r4["distance_mm"]) == 1004.0

    # First row of frame1.
    r5 = rows[5]
    assert r5["frame_idx"] == "1"
    assert r5["sample_idx"] == "0"
    assert r5["flag"] == "1"


def test_empty_frame_writes_no_rows_but_header_present(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    empty = Frame(index=0)
    with CsvDumpWriter(path) as w:
        w.write_frame(empty)
        assert w.frames_written == 1
        assert w.samples_written == 0

    with open(path, encoding="utf-8") as fh:
        content = fh.read()

    # Header line plus a trailing newline → exactly one "\n" total when the
    # body is empty.
    assert content.startswith(EXPECTED_HEADER_LINE + "\n")
    assert content.count("\n") == 1
