# Smoke + three-way comparison workflow

This document describes the bring-up procedure for the RPi 5 host and the
three-way CSV comparison against the Python prototype. Written for Phase 3.

The flow exists to close the "`pyrplidar` is unofficial for C1" caveat
recorded in `SYSTEM_DESIGN.md §10.1` and `PROGRESS.md` Next-up #7.

---

## Goal

Obtain three independent CSV captures of the **same static position**,
produced by:

1. SLAMTEC's stock `ultra_simple` CLI (SDK default, C++)
2. `godo_smoke` in this project (same SDK, our writer)
3. Python `scripts/capture.py --backend sdk` and `--backend raw` in the
   `prototype/Python/` project

Then diff / statistically compare the CSVs to confirm:

- The C++ path produces the same sample stream as the SDK reference.
- The C++ writer produces bytes identical to the Python writer (pinned
  by `test_csv_parity` at CI time).
- The Python `raw` backend and the SDK agree to within the documented
  noise envelope.

---

## Pre-flight

- RPi 5 on Debian 13 Trixie, wired to the RPLIDAR C1 via the CP2102
  adapter (USB-A on the Pi side).
- `/dev/ttyUSB0` visible to the `ncenter` user (`dialout` group).
- The crane / test rig is stationary for the duration of the three
  captures (same position, same orientation).
- Network: RPi reachable by SSH so the Python captures (on the same Pi or
  on Mac / Windows) can run against the same physical setup if you own
  only one C1 unit; otherwise split between hosts.

---

## Capture 1 — stock `ultra_simple`

```sh
cd production/RPi5/external/rplidar_sdk
make -j"$(nproc)"
./output/Linux/Release/ultra_simple --channel --serial /dev/ttyUSB0 460800 \
    | tee ~/ultra_simple_<ts>.log
```

Convert the stdout log to a CSV with the same column set as our writer:

```text
frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag
```

(Quick-and-dirty `awk` / Python one-liner; the stdout format is
documented in `app/ultra_simple/main.cpp` at the pinned SHA.)

---

## Capture 2 — `godo_smoke`

```sh
cd production/RPi5
scripts/build.sh
scripts/run-pi5-smoke.sh --port /dev/ttyUSB0 --frames 100 \
    --tag threeway_godo
```

Artefacts land at:

```text
out/<ts>_threeway_godo/data/<ts>_threeway_godo.csv
out/<ts>_threeway_godo/logs/<ts>_threeway_godo.txt
```

---

## Capture 3 — Python prototype

```sh
cd prototype/Python
uv sync
uv run python scripts/capture.py --backend sdk --port /dev/ttyUSB0 \
    --frames 100 --tag threeway_sdk
uv run python scripts/capture.py --backend raw --port /dev/ttyUSB0 \
    --frames 100 --tag threeway_raw
```

Artefacts:

```text
prototype/Python/data/<ts>_sdk_threeway_sdk.csv
prototype/Python/data/<ts>_raw_threeway_raw.csv
```

---

## Comparison

```sh
cd prototype/Python
uv run python scripts/analyze.py --mode compare \
    --csv data/<ts>_sdk_threeway_sdk.csv \
    --other-csv data/<ts>_raw_threeway_raw.csv \
    --out out/threeway_py/
```

Then repeat for each pair:

```text
┌──────────────────────┬─────────────────────┬────────────────────────────┐
│ Pair                 │ Expected outcome    │ Action on divergence       │
├──────────────────────┼─────────────────────┼────────────────────────────┤
│ ultra_simple ↔ godo  │ statistically equal │ review godo_smoke parser   │
│ godo_smoke ↔ py sdk  │ per-sample identity │ see `test_csv_parity`      │
│ py sdk ↔ py raw      │ within noise band   │ re-run Phase 1 noise tests │
└──────────────────────┴─────────────────────┴────────────────────────────┘
```

---

## What gets archived

- The three CSVs and their session logs live under
  `production/RPi5/out/<ts>_<tag>/` (C++ side) and
  `prototype/Python/{data,logs}/` (Python side).
- If the comparison is the reference for a formal test session, promote
  the godo_smoke run:

```sh
scripts/promote_smoke_to_ts.sh out/<ts>_threeway_godo TS7 \
    "three-way comparison, studio empty, static"
```

This moves the directory out of the `out/` bring-up area and into
`test_sessions/TS7/` at the repo root; see
[`.claude/memory/project_test_sessions.md`](../../../.claude/memory/project_test_sessions.md)
for the distinction.
