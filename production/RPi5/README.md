# production/RPi5/

Phase 3 C++ production scaffold for the GODO Raspberry Pi 5 host.

**Status**: bring-up scaffold only. The binary shipped here is
`godo_smoke` — a hardware-smoke / three-way-comparison tool, **not** the
final `godo-tracker`. The tracker's integration (FreeD receive, AMCL,
UDP send @ 59.94 fps) lands in Phase 4.

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
