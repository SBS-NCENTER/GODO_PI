# production/RPi5/

Phase 3 C++ production scaffold for the GODO Raspberry Pi 5 host.

**Status**: Phase 4-1 shipped. The RT hot path (`godo_tracker_rt`) is
integrated; AMCL / LiDAR / full cold path land in Phase 4-2.

Binaries in this tree:

- `godo_smoke` (Phase 3) — hardware-smoke / three-way-comparison tool.
- `godo_tracker_rt` (Phase 4-1) — 59.94 Hz UDP sender with FreeD serial
  in and a stub cold-writer that emits canned offsets. See
  [Phase 4-1: RT hot path](#phase-4-1-rt-hot-path) below.
- `godo_jitter` (Phase 4-1) — CLOCK_MONOTONIC jitter measurement.
- `godo_freed_passthrough` — minimal FreeD serial → UDP forwarder
  (no offset, no RT). First-plug wiring/UDP path verification before
  bringing up `godo_tracker_rt`. See [godo_freed_passthrough
  (bring-up)](#godo_freed_passthrough-bring-up) below.

See [`./doc/smoke.md`](./doc/smoke.md) for the bring-up workflow and
[`CODEBASE.md`](./CODEBASE.md) for the invariants the tests pin.

---

## Layout

```text
production/RPi5/
├─ CMakeLists.txt              ← top-level CMake
├─ README.md                   ← this file
├─ CODEBASE.md                 ← change log + invariants
├─ .gitignore
├─ cmake/
│   └─ rplidar_sdk.cmake       ← ExternalProject wrapping the SDK Makefile
├─ src/godo_smoke/             ← smoke binary source
│   ├─ CMakeLists.txt
│   ├─ main.cpp
│   ├─ args.{hpp,cpp}
│   ├─ sample.hpp
│   ├─ timestamp.{hpp,cpp}
│   ├─ csv_writer.{hpp,cpp}
│   ├─ session_log.{hpp,cpp}
│   └─ lidar_source_rplidar.{hpp,cpp}
├─ tests/                      ← doctest targets (hardware-free by default)
├─ scripts/
│   ├─ build.sh                ← configure + build + run the hw-free ctest gate
│   ├─ run-pi5-smoke.sh        ← convenience wrapper around godo_smoke
│   └─ promote_smoke_to_ts.sh  ← move an `out/<ts>_<tag>/` into `test_sessions/TS<N>/`
├─ doc/
│   └─ smoke.md                ← three-way comparison workflow
├─ out/                        ← runtime captures (gitignored contents)
└─ external/
    └─ rplidar_sdk/            ← git submodule, pinned SHA
```

---

## Prerequisites (Debian 13 Trixie / RPi 5)

```sh
sudo apt install doctest-dev libssl-dev cmake git make g++
```

Versions known to build:

- g++ 14.2 (Debian 14.2.0-19)
- CMake 3.31.6
- doctest 2.4.11-1 (apt)
- libssl3 / libssl-dev 3.5.5
- OpenSSL EVP API — chunked SHA-256 (64 KiB chunks) for session-log integrity

Serial access:

```sh
sudo usermod -aG dialout "$USER"   # log out / back in after this
```

Then plug the RPLIDAR C1 via the CP2102 adapter; it typically enumerates
as `/dev/ttyUSB0`.

---

## Build

```sh
scripts/build.sh                # default: RelWithDebInfo + hw-free ctest gate
scripts/build.sh Debug          # or an explicit build type
```

On first build CMake pulls the SDK submodule and invokes its upstream
Makefile. If the submodule is absent:

```sh
git submodule update --init --recursive
```

The SDK is pinned to SHA `99478e5fb90de3b4a6db0080acacd373f8b36869`
(2024-04-09 master HEAD; the project has no release tag covering the C1).
`cmake/rplidar_sdk.cmake` warns if HEAD diverges.

---

## Run the smoke capture

```sh
scripts/run-pi5-smoke.sh \
    --port /dev/ttyUSB0 \
    --frames 100 \
    --tag first_light \
    --notes "RPi 5 bring-up, static position A"
```

Outputs (with `<ts>` = UTC `YYYYMMDDThhmmssZ`):

```text
out/<ts>_first_light/
├─ data/<ts>_first_light.csv    ← one row per sample, byte-identical to the Python prototype
└─ logs/<ts>_first_light.txt    ← host / params / stats / csv SHA-256
```

---

## Tests

```sh
ctest --test-dir build -L hardware-free --output-on-failure
```

Targets:

- `test_csv_writer_writes` — production write path
- `test_csv_writer_readback` — structurally forbidden from including production headers
- `test_csv_parity` — byte-identity vs. Python prototype (skipped if `uv` is missing)
- `test_session_log` — chunked SHA-256 + full log body
- `test_args` — CLI parsing boundaries
- `test_sample_invariants` — Sample contract + LidarSourceFake duck-typed twin

The hardware-in-the-loop target is built but not run by the default gate:

```sh
ctest --test-dir build -L hardware-required --output-on-failure
```

---

## Three-way comparison workflow

See [`./doc/smoke.md`](./doc/smoke.md). Short form:

1. `ultra_simple` (SDK stock) → one CSV
2. `godo_smoke` (this project, same SDK) → one CSV
3. Python prototype `--backend sdk` and `--backend raw` → two CSVs

Analyse with `uv run python scripts/analyze.py --mode compare` in
`prototype/Python/`.

---

## Promotion

When a smoke capture is worth preserving as a formal Test Session:

```sh
scripts/promote_smoke_to_ts.sh out/20260423T153012Z_first_light TS7 \
    "C1 first light on RPi 5 bring-up"
```

This moves the directory to `<repo-root>/test_sessions/TS7/` and appends
a `## Promotion` block to the session log. The default `out/` content is
ad-hoc and **not** a test-session archive.

---

## Rollback

Failure mode: RPi 5 pipeline becomes unreliable during a shoot.

Rollback card is the existing Arduino R4 WiFi firmware under
[`/XR_FreeD_to_UDP/`](../../XR_FreeD_to_UDP/). Swap the FreeD cable from
the RPi back to the Arduino; no changes to the studio network are
required. The firmware stays untouched for exactly this reason
(see `CLAUDE.md §6 "Preserve existing assets"`).

---

## Phase 4-1: RT hot path

### One-time host setup

1. Wire the YL-128 MAX3232 converter to the Pi 5's PL011 UART0 and apply
   the boot-config changes from [`doc/freed_wiring.md`](./doc/freed_wiring.md).
   Reboot.
2. Build the tracker: `scripts/build.sh`.
3. As root, run `scripts/setup-pi5-rt.sh` once. This sets `cap_sys_nice`
   + `cap_ipc_lock` on the tracker binary and appends the rtprio /
   memlock rlimit entries to `/etc/security/limits.conf`.

### Run the tracker

```sh
scripts/run-pi5-tracker-rt.sh \
    --ue-host   10.1.2.3 \
    --ue-port   6666 \
    --freed-port /dev/ttyAMA0 \
    --t-ramp-ms 500
```

No sudo needed after the one-time setup — capabilities live on the
binary itself. All flags accepted by `Config::load` are available
(`--lidar-port`, `--rt-cpu`, `--rt-priority`, ...); see
[`src/core/config.hpp`](./src/core/config.hpp).

Configuration precedence (highest first):

1. CLI flags
2. Environment (`GODO_UE_HOST`, `GODO_UE_PORT`, ...)
3. TOML file at `GODO_CONFIG_PATH` or `/etc/godo/tracker.toml`
4. Compile-time defaults in `src/core/config_defaults.hpp`

### Measure jitter

```sh
scripts/run-pi5-jitter.sh --duration-sec 60 --cpu 3 --prio 50
```

Prints mean / p50 / p95 / p99 / max for `actual - scheduled_deadline`
deltas across the run, plus a JSON trailer line for log scraping.

### What Phase 4-1 does NOT do yet

- No LiDAR ingestion, no AMCL, no map. The cold-path writer is a stub
  that emits canned offsets at 1 Hz so the seqlock + smoother + UDP
  pipeline can be exercised before Phase 4-2 lands.
- No godo-webctl / UDS / HTTP API (Phase 4-3).
- Deadband filter defaults are declared in `config_defaults.hpp` but
  the filter itself arrives with AMCL in Phase 4-2.

---

## godo_freed_passthrough (bring-up)

Minimal FreeD serial → UDP forwarder. Single-thread, no offset, no
SCHED_FIFO / mlockall / cap_sys_nice. Use this for the first plug-in
of the YL-128 to confirm bytes flow end-to-end before the full RT
tracker is brought up.

### Run

```sh
scripts/run-pi5-freed-passthrough.sh \
    --port /dev/ttyAMA0 \
    --host 10.10.204.184 \
    --udp-port 50002
```

Defaults match the values shown above. Other flags: `--baud` (38400),
`--stats-sec` (1, set to 0 to disable per-second stats), `--quiet`.
On the stock Trixie image without the boot-config edits, the PL011
shows up as `/dev/ttyAMA10`; pass `--port /dev/serial0` (a symlink to
whichever ttyAMA<N> was assigned) to side-step the rename. The
recommended bring-up path is still to apply
[`doc/freed_wiring.md`](./doc/freed_wiring.md) §B and reboot, which
both renames the device to `/dev/ttyAMA0` and disables the kernel
serial console (otherwise getty owns the line and `open()` returns
EBUSY).

### What this binary does NOT do

- It does **not** apply the (dx, dy, dyaw) offset. Each verified D1
  packet is forwarded byte-identical. Use `godo_tracker_rt` for the
  full hot path.
- It does **not** maintain a 59.94 Hz cadence — packets are forwarded
  as they arrive (≤ 1 ms latency).
- It does **not** require `setup-pi5-rt.sh` or any RT capabilities.
