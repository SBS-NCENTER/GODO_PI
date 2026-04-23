# RPi5 production CODEBASE

Structural / functional change log for `/production/RPi5`. See
[`../../CLAUDE.md §6`](../../CLAUDE.md) for the update policy and
[`../../PROGRESS.md`](../../PROGRESS.md) for cross-session state.

---

## Scope

Phase 3 bring-up scaffold. Ships one binary (`godo_smoke`) and the five
test targets that pin the invariants below. **Does not** implement
AMCL, FreeD receive, or 59.94 fps UDP send — those arrive in Phase 4.

---

## Module map

```text
CMakeLists.txt                       C++17, warnings-as-errors, doctest, OpenSSL::Crypto
cmake/rplidar_sdk.cmake              ExternalProject wrapping the upstream SDK Makefile,
                                     pinned SHA 99478e5f…36869

src/godo_smoke/
├─ CMakeLists.txt                    target: godo_smoke
├─ main.cpp                          setlocale("C") → parse → open → scan → close
├─ args.{hpp,cpp}                    variant<Args, ParseHelp, ParseError>; no external dep
├─ sample.hpp                        Sample, Frame, validate() — Python frame.py parity
├─ timestamp.{hpp,cpp}               monotonic_ns, utc_timestamp_{compact,iso}
├─ csv_writer.{hpp,cpp}              snprintf-based, fopen("wb"), byte-identical to Python
├─ session_log.{hpp,cpp}             chunked EVP SHA-256, log body matches Python schema
└─ lidar_source_rplidar.{hpp,cpp}    concrete (NO virtual) RPLIDAR C1 driver wrapper

tests/
├─ CMakeLists.txt                    test target source lists are split per invariant (b)
├─ lidar_source_fake.{hpp,cpp}       duck-typed twin; class name deliberately different
├─ test_csv_writer_writes.cpp        production write path; includes csv_writer.hpp
├─ test_csv_writer_readback.cpp      stdlib-only parse; include path excludes ../src/godo_smoke
├─ test_csv_parity.cpp               cmp against Python prototype via `uv run`
├─ test_session_log.cpp              SHA-256 known-good vectors + full field coverage
├─ test_args.cpp                     CLI parsing boundaries
├─ test_sample_invariants.cpp        validate() + LidarSourceFake shape
└─ test_lidar_live.cpp               hardware-required; LABELS "hardware-required"

scripts/
├─ build.sh                          cmake config + build + hw-free ctest gate
├─ run-pi5-smoke.sh                  wrapper for godo_smoke with sensible defaults
└─ promote_smoke_to_ts.sh            move out/<ts>_<tag>/ → test_sessions/TS<N>/

doc/
└─ smoke.md                          three-way comparison workflow

out/                                 runtime captures; contents gitignored
external/
└─ rplidar_sdk/                      git submodule, pinned SHA
```

---

## Data contracts

### `Sample` (sample.hpp)

```cpp
struct Sample {
    double   angle_deg;     // [0, 360)     strict < 360
    double   distance_mm;   // >= 0         (0 = invalid per SLAMTEC PDF Fig 4-5)
    uint8_t  quality;       // [0, 255]
    uint8_t  flag;          // bit 0 = S (start-of-frame)
    int64_t  timestamp_ns;  // >= 0         monotonic capture clock
};
```

### CSV dump (`out/<ts>_<tag>/data/*.csv`)

Byte-identical to `prototype/Python/src/godo_lidar/io/csv_dump.py`.
Header:

```text
frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag
```

- `angle_deg` formatted `%.6f` (Q6 resolution = 1/64 deg ≈ 0.0156).
- `distance_mm` formatted `%.3f` (Q2 resolution = 0.25 mm).
- Integer columns `%d` / `%lld`.
- Single-comma delimiter, no quoting, LF terminator, UTF-8 no BOM.
- File opened with `fopen(path, "wb")` so CRLF translation cannot
  corrupt the stream on non-POSIX hosts; see invariant (c).

### Session log (`out/<ts>_<tag>/logs/*.txt`)

Field order mirrors the Python `SessionLogWriter`. The C++ log body is
**not** byte-identical to Python — only the CSV is (invariant (d) scopes
the parity to samples). SHA-256 over the CSV is computed with chunked
`EVP_DigestUpdate` in 64 KiB blocks; one-shot `EVP_Digest()` is
forbidden (ties back to the Python `hashlib.sha256().update()`
incremental path).

---

## Invariants

Invariants (a) and (b) are **pinned by tests** — breaking them is a
compile or test-run failure. Invariants (c) and (d) are **conventions
enforced by code review** — they describe design intent that tests
cannot economically assert.

### (a) No ABC — duck-typed implementations

`LidarSourceRplidar` (production) and `LidarSourceFake` (tests) share no
base class. Their APIs match structurally; class names differ
deliberately so no test can silently substitute the wrong type. Per
`prototype/Python/src/godo_lidar/capture/sdk.py` lines 39–45 and
`PROGRESS.md` "no ABC" rule: duck typing is the project standard when
fewer than three implementations exist. Any `virtual` keyword in
`src/godo_smoke/*.hpp` is a review-blocking defect.

### (b) Test-include split

`tests/test_csv_writer_readback` has an include path that intentionally
excludes `src/godo_smoke/`. A `#include "csv_writer.hpp"` in that file
must fail to compile. This prevents the read-back test from smuggling
production-defined constants into what must remain a contract-level
check on bytes and column names.

### (c) Hot-path allocation is justified for this scope

`CsvWriter::write_frame` MAY allocate (`std::snprintf` into a reused
string buffer; `std::fwrite` to a buffered `FILE*`). This is acceptable
because `godo_smoke` is a user-triggered capture tool, not the
real-time tracker. It is NOT the pattern for the Phase 4 godo-tracker
Thread D. The RT-safe writer utility will be extracted in Phase 4 when
the actual constraints (SCHED_FIFO, mlockall, no-malloc hot path) are
present. Binary mode (`"wb"`) keeps byte output identical on any host,
preventing Windows CR translation from breaking the parity test.

### (d) Threading locale

`main()` calls `std::setlocale(LC_ALL, "C")` at startup. Child threads
inherit this LC state by POSIX semantics. No thread inside the Phase 4
tracker may call `setlocale`; doing so would corrupt decimal formatting
in concurrent capture threads. Session-log byte identity with Python is
**not** enforced (scope-out); only the CSV is.

---

## Where do I look when…

| Need | Where |
| --- | --- |
| I want to add a second concrete LiDAR source (e.g. official UDP) | Create `lidar_source_udp.{hpp,cpp}` with a class called `LidarSourceUdp`; do NOT inherit from `LidarSourceRplidar`. Link it into the relevant target's source list. See invariant (a). |
| The CSV schema needs a field | Update `csv_writer.{hpp,cpp}`, update `test_csv_writer_writes.cpp` expected strings, update `test_csv_writer_readback.cpp` header literal, update `prototype/Python/src/godo_lidar/io/csv_dump.py` + its tests, run `test_csv_parity`. All four must change in the same commit. |
| The session log needs a field | Update `session_log.{hpp,cpp}`, update `test_session_log.cpp` expected substrings. Python parity is NOT required; document the deviation in this file. |
| I'm diagnosing a build failure around the SDK | `cmake/rplidar_sdk.cmake` wraps `external/rplidar_sdk/sdk/Makefile`. The SHA check is best-effort only — a divergent HEAD produces a warning, not an error. Run `make -C external/rplidar_sdk/sdk` by hand to isolate. |
| I'm running on a new host | `doctest-dev` (Debian) or `doctest` (Homebrew); `libssl-dev`; a POSIX toolchain; `uv` for the parity test. |

---

## First-time setup smoke check

```sh
cd production/RPi5
git submodule update --init --recursive
sudo apt install doctest-dev libssl-dev
scripts/build.sh
```

Expect `ctest -L hardware-free` to report every listed test green. If
`test_csv_parity` is skipped, install `uv` and ensure `prototype/Python/`
has been synced (`uv sync`).

---

## 2026-04-23 — Initial scaffold (Plan B v2, P3-1…P3-10)

### Added

- `CMakeLists.txt` — C++17, warnings-as-errors, doctest + OpenSSL discovery.
- `cmake/rplidar_sdk.cmake` — ExternalProject wrapping the upstream Makefile at the pinned SHA, imported as `rplidar_sdk::static`.
- `src/godo_smoke/main.cpp` — `setlocale("C")`, arg parse, capture loop, session log, error propagation via `std::exception`.
- `src/godo_smoke/args.{hpp,cpp}` — `variant<Args, ParseHelp, ParseError>`; no argparse dep; boundary-checked.
- `src/godo_smoke/sample.hpp` — `Sample`, `Frame`, `validate()`; mirrors `prototype/Python/src/godo_lidar/frame.py`.
- `src/godo_smoke/timestamp.{hpp,cpp}` — `monotonic_ns`, `utc_timestamp_compact`, `utc_timestamp_iso`.
- `src/godo_smoke/csv_writer.{hpp,cpp}` — `snprintf`-based row formatter; `fopen("wb")`; reused `std::string` scratch.
- `src/godo_smoke/session_log.{hpp,cpp}` — chunked EVP SHA-256 (64 KiB), human-readable log body, RAII around `EVP_MD_CTX`.
- `src/godo_smoke/lidar_source_rplidar.{hpp,cpp}` — concrete RPLIDAR C1 driver; `open`/`close`/`scan_frames(n, cb)`; NO virtual methods.
- `src/godo_smoke/CMakeLists.txt` — `godo_smoke` executable; NDEBUG in Release / RelWithDebInfo; links `OpenSSL::Crypto` and `rplidar_sdk::static`.
- `tests/lidar_source_fake.{hpp,cpp}` — deterministic fake with a distinct class name (`LidarSourceFake`).
- `tests/test_csv_writer_writes.cpp` — 6 tests; production write path.
- `tests/test_csv_writer_readback.cpp` — 5 tests; stdlib-only parse; separate target with restricted include path (invariant (b)).
- `tests/test_csv_parity.cpp` — 1 test; conditional on `uv` + `uv.lock`.
- `tests/test_session_log.cpp` — 6 tests; SHA-256 known-good vectors (`""` and `"abc"`), chunked-path exercise, log field coverage, error propagation.
- `tests/test_args.cpp` — 10 tests covering defaults, help, valid flags, missing values, boundary values.
- `tests/test_sample_invariants.cpp` — 7 tests covering validate() boundaries and LidarSourceFake shape.
- `tests/test_lidar_live.cpp` — 1 test; LABELS `hardware-required`.
- `tests/CMakeLists.txt` — seven test targets; source lists split per invariant (b); `test_csv_parity` gated on `find_program(UV_EXE uv)`.
- `scripts/build.sh` — `cmake -B build` + `cmake --build` + `ctest -L hardware-free`.
- `scripts/run-pi5-smoke.sh` — wrapper for `godo_smoke` pointing at `out/`.
- `scripts/promote_smoke_to_ts.sh` — promotes a smoke run to `test_sessions/TS<N>/`; annotates session log with `promoted_from`.
- `doc/smoke.md` — three-way comparison workflow (ultra_simple ↔ godo_smoke ↔ Python prototype).
- `.gitignore` — `build/`, `out/*/`, submodule build products (defensive).
- `out/.gitkeep` — keeps the gitignored directory tracked.
- `external/rplidar_sdk/` — git submodule at SHA `99478e5f…36869`.

### Changed

- `README.md` — full rewrite: Prerequisites, Build, Run, Test, Rollback. Replaces the former one-paragraph placeholder.

### Tests

See "Added" above. Hardware-free targets pass by default; `test_lidar_live`
is built but tagged `hardware-required` and not run by `scripts/build.sh`.

### Deviations from the plan

- The SDK Makefile produces `libsl_lidar_sdk.a`, not `librplidar_sdk.a` as
  the plan stated. The CMake wrapper uses the correct filename. No
  downstream effect.
- P3-2b gate exercised `ultra_simple` with no arguments; it printed
  usage and exited with rc=1. This is a graceful exit and satisfies the
  gate's "clean exit or graceful error" criterion.
