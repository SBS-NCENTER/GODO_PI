# Python CODEBASE

Structural / functional change log for `/prototype/Python`. See
[`../../CLAUDE.md §6`](../../CLAUDE.md) for the update policy.

---

## Module map

```text
pyproject.toml           UV-managed; deps = pyrplidar, pyserial, numpy, pandas, matplotlib; dev = pytest
.python-version          3.12

src/godo_lidar/
├─ __init__.py           Re-exports Frame, Sample
├─ frame.py              Sample (angle_deg ∈ [0,360), distance_mm ≥ 0, quality ∈ [0,255], flag, timestamp_ns)
│                        Frame (index, samples)
├─ capture/
│   ├─ __init__.py       Re-exports RawBackend, SdkBackend
│   ├─ raw_parser.py     PURE: decode_sample / decode_samples / build_request /
│                        build_motor_speed_request / SCAN_REQUEST / STOP_REQUEST /
│                        SCAN_RESPONSE_DESCRIPTOR. Stdlib + frame.py only.
│   ├─ raw.py            RawBackend: pyserial context-manager; startup = STOP → MOTOR → wait 500 ms → SCAN
│   └─ sdk.py            SdkBackend: pyrplidar wrapper; same public shape (duck-typed)
├─ io/
│   ├─ __init__.py       Re-exports CsvDumpWriter, CaptureParams, RunStats, SessionLogWriter, COLUMNS
│   ├─ csv_dump.py       stdlib csv.writer on hot path; module-level COLUMNS tuple
│   └─ session_log.py    .txt log with csv_sha256 / csv_byte_count (hashed after CSV closed)
└─ analyze.py            Flat module: load_csv, per_direction_variance, compare_backends,
                         reflector_histogram, polar_plot, quality_histogram

scripts/
├─ capture.py            CLI --backend {sdk,raw} --port COMn --frames N --tag STR --notes STR
│                        --rpm is RAW-BACKEND ONLY (C1 cmd 0xA8 not exposed by pyrplidar;
│                        passing --rpm with --backend sdk is a hard parser error)
└─ analyze.py            CLI --mode {noise,compare,reflector,chroma_nir,visualize} --csv PATH [--other-csv PATH] --out DIR

tests/
├─ test_frame.py         Sample boundary + validation (5 test functions)
├─ test_csv_dump.py      Header literal check, roundtrip via stdlib DictReader, empty-frame case
└─ test_raw_protocol.py  Fixtures hand-derived from SLAMTEC protocol v2.8 PDF (citations inline)

data/.gitkeep            Gitignored; CSV capture output lives here at runtime
logs/.gitkeep            Gitignored; session .txt logs live here at runtime
```

---

## Data contracts

### `Sample` (frame.py)

```python
Sample(angle_deg: float,      # [0, 360)  strict < 360
       distance_mm: float,    # >= 0      (0 = invalid per PDF Figure 4-5)
       quality: int,          # [0, 255]
       flag: int,             # [0, 255]  bit 0 = S (start-of-frame)
       timestamp_ns: int)     # >= 0      monotonic capture clock
```

### `Frame`

```python
Frame(index: int, samples: list[Sample])
```

`index` is assigned monotonically from 0 by the capture layer. The first
sample in a non-empty frame has `flag & 1 == 1` (S=1).

### CSV dump (data/*.csv)

Schema pinned in `io/csv_dump.py::COLUMNS`:

```text
frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag
```

- `angle_deg` formatted to 6 decimals (Q6 resolution = 1/64 deg ≈ 0.0156 deg).
- `distance_mm` formatted to 3 decimals (Q2 resolution = 0.25 mm).
- Line terminator: `\n`. UTF-8 encoding.

### Session log (logs/*.txt)

Schema pinned in `io/session_log.py::SessionLogWriter.write`. Sections:
header (timestamp_utc, host, os, python), capture parameters, run stats,
artifact integrity (`csv_path`, `csv_byte_count`, `csv_sha256`). SHA-256 is
computed on the on-disk file after it is closed.

---

## Where do I look when…

| Need | Where |
| --- | --- |
| …I'm adding a new scan mode (express / ultra) | `capture/raw_parser.py`; extend with a new `decode_samples_express` and a companion descriptor constant. Do NOT change the standard-mode functions. |
| …the capture CSV schema needs a field | Add to `io/csv_dump.py::COLUMNS` AND `write_frame`; update the literal in `tests/test_csv_dump.py`; update the schema block in this file. |
| …I'm diagnosing "too many bad-check-bit warnings" | `capture/raw_parser.py::decode_sample` drops + warns; check logger output (`-v` or `-vv` on `scripts/capture.py`). Root causes listed in `doc/RPLIDAR/RPLIDAR_C1.md §5`. |
| …the session log is missing a stat | `io/session_log.py::RunStats` has an `extra: dict[str, str]` escape hatch. Add stable fields directly. |
| …a new analysis is needed | Add a function to `analyze.py`; expose via a new `--mode` in `scripts/analyze.py`. Keep it flat — no class hierarchy unless two modes share >50% logic. |
| …I want to swap `pyrplidar` for the official C++ SDK | That is the Phase 1 follow-up task below. Add a third backend module `capture/official_sdk.py` with the same public shape; route via `--backend official` in `scripts/capture.py`. |

---

## Phase 1 follow-up tasks (pending)

1. **Three-way comparison**: add an `official_sdk` backend that shells out
   to the official C++ `rplidar_sdk` `ultra_simple` CLI, parses its stdout,
   and yields `Frame`s in the same shape. Blocker: C++ build environment
   on Windows / RPi 5.  See `SYSTEM_DESIGN.md §10.1`.
2. Wire `per_direction_variance` results into a `--mode noise` report that
   explicitly verifies the √N prediction (the math is in place; the
   user-facing report is not).

---

## First-time setup smoke check (for the user)

On Windows, from this directory:

```powershell
uv sync                             # install deps into .venv/
uv run pytest                       # run unit tests (no hardware required)
uv run python scripts/capture.py --help
uv run python scripts/analyze.py --help
```

Expect `uv run pytest` to report green across `test_frame.py`,
`test_csv_dump.py`, `test_raw_protocol.py`. If any test fails, STOP and
re-open the test output — the failure is likely a real regression.

---

## 2026-04-21 — Phase 1 Python prototype scaffold

### Added

- `pyproject.toml` — UV project, Python ≥ 3.12, deps listed above.
- `.python-version` — pins 3.12 for UV.
- `.gitignore` — keeps `data/` / `logs/` content out of git while preserving `.gitkeep`.
- `README.md` — Windows-first quickstart (CP2102 driver, COM-port lookup, port-busy note, troubleshooting table).
- `src/godo_lidar/__init__.py` — re-exports `Frame`, `Sample`.
- `src/godo_lidar/frame.py` — `Sample` / `Frame` dataclasses with validation.
- `src/godo_lidar/capture/__init__.py` — re-exports `RawBackend`, `SdkBackend`.
- `src/godo_lidar/capture/raw_parser.py` — pure decoder derived from SLAMTEC protocol v2.8 PDF; `decode_sample`, `decode_samples`, `build_request`, `build_motor_speed_request`, request / descriptor constants.
- `src/godo_lidar/capture/raw.py` — `RawBackend`: pyserial + startup sequence (STOP → MOTOR → 500 ms settle → SCAN → descriptor → stream).
- `src/godo_lidar/capture/sdk.py` — `SdkBackend`: pyrplidar wrapper. Docstring carries the "unofficial for C1" caveat per reviewer finding #5.
- `src/godo_lidar/io/__init__.py` — re-exports CSV / log types.
- `src/godo_lidar/io/csv_dump.py` — `CsvDumpWriter` using stdlib `csv.writer` (pandas never on the hot path).
- `src/godo_lidar/io/session_log.py` — `SessionLogWriter` writes the `.txt` log and computes `csv_sha256` / `csv_byte_count` on the closed CSV.
- `src/godo_lidar/analyze.py` — flat analysis module (load_csv, per_direction_variance, compare_backends, reflector_histogram, polar_plot, quality_histogram).
- `scripts/capture.py` — CLI with `--backend sdk|raw`, `--frames`, `--tag`, etc.
- `scripts/analyze.py` — CLI with `--mode {noise,compare,reflector,chroma_nir,visualize}`.
- `data/.gitkeep`, `logs/.gitkeep` — keep the gitignored directories trackable.

### Tests

- `tests/test_frame.py` — 5 test functions, covering valid construction, angle=360 rejection, out-of-range angles, out-of-range other fields, default-factory independence.
- `tests/test_csv_dump.py` — 3 test functions. Header asserted against a literal string constant defined inside the test file (not imported from production). Roundtrip uses stdlib `csv.DictReader`. Empty-frame case covered.
- `tests/test_raw_protocol.py` — 5 fixtures **hand-derived from the PDF** (each with inline section citation), plus multi-sample streaming / mixed-stream / descriptor / request-format / motor-request / length-error cases.

### Decisions deviating from the original planner draft

- Consolidated `analysis/*.py` into a single flat `analyze.py` (functions only).
- Consolidated the script list to two (`capture.py`, `analyze.py`) with flags.
- Dropped `capture/base.py` ABC — two implementations do not justify an abstract base.
- Dropped `scikit-learn` dependency.
- `pyrplidar` backend kept but labeled "SDK-wrapper backend" with honesty caveat in the module docstring.

---

## 2026-04-21 — Reviewer Mode-B fix-pass

### Changed

- `src/godo_lidar/capture/sdk.py` — removed the `set_motor_pwm` call from `SdkBackend.open()` / `.close()`. That call emitted A1-style cmd `0xF0`, which the C1 silently ignores (C1 uses cmd `0xA8` `MOTOR_SPEED_CTRL`, not exposed by pyrplidar). Dropped the `rpm` and `MOTOR_SETTLE_S` constants and the `rpm` constructor argument. Motor now spins at the firmware default. Module docstring documents the constraint.
- `scripts/capture.py` — `--rpm` default is now `None` (was `600`). If `--backend sdk` AND `--rpm` is supplied, `parser.error(...)` fails fast with the message documented in the reviewer finding. On `--backend raw`, `None` is resolved to `DEFAULT_RPM` from `capture/raw.py`. Help text now states the raw-backend-only constraint.
- `src/godo_lidar/analyze.py::load_csv` — schema check now imports `COLUMNS` from `godo_lidar.io.csv_dump` (single source of truth). Hardcoded duplicate dropped.
- `src/godo_lidar/capture/__init__.py` — module docstring rewritten to accurately describe eager re-exports (pyserial / pyrplidar are imported at package-import time); the previous "imported lazily" claim was false.
- `src/godo_lidar/io/session_log.py` — dropped `__enter__`/`__exit__` (decorative; the real work is in `.write()`). `CaptureParams.rpm` is now `int | None`, with `None` rendered as `firmware-default` in the log (used by the sdk backend).
- `src/godo_lidar/capture/raw_parser.py::decode_samples` — docstring now states the no-resync contract and the concrete caller-side rule: "> 10 consecutive C-bit failures within one chunk ⇒ restart the backend (STOP → MOTOR → wait → SCAN → descriptor)". Phase 1 stance: document, do not auto-fix.
- `src/godo_lidar/capture/raw.py` — replaced the magic formula `deadline_budget_s = 30.0 + frames * 0.2` with `expected_s = frames / 10.0; deadline_budget_s = max(30.0, expected_s * 2.0)` (C1 scans at ~10 Hz per RPLIDAR_C1.md §2).
- `src/godo_lidar/io/csv_dump.py` — `self._writer` annotated as `Any | None` (was `csv.writer | None` with a `# type: ignore`). `csv.writer` is a factory return type, not a nominal class; `Any | None` is honest.
- `scripts/capture.py` — replaced `with SessionLogWriter(log_path) as log: log.write(...)` with a direct `SessionLogWriter(log_path).write(...)`.
- `README.md` — documents the `--rpm sdk` hard-error; no other changes.

### Not changed (per reviewer's "do NOT touch" list)

- Test files (`test_frame.py`, `test_csv_dump.py`, `test_raw_protocol.py`) — the literal header constant in `test_csv_dump.py` remains intentionally duplicated to catch silent production drift.
- `pyproject.toml` / `.python-version` — no dependency changes in this pass.
- `open()` / `close()` explicit methods on `SdkBackend` / `RawBackend` / `CsvDumpWriter` — left as-is (reviewer flagged as minor).
- `# noqa: BLE001` in `sdk.py::scan_frames` `finally` — left as-is (nit).

### Tests

All 29 existing tests pass unchanged (`uv run pytest`). No new tests added — the changes remove code (motor-pwm call), tighten docstrings, and swap a duplicated-schema for an imported-schema; none introduce new code paths needing coverage. The production-drift canary in `test_csv_dump.py` continues to catch schema changes.
