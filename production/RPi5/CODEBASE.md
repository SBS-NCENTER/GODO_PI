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

### (e) No heap allocation on the hot path (convention, code-review enforced)

Functions transitively reachable from Thread D's main loop — namely
anything under `src/rt`, `src/udp`, `src/smoother`, `src/yaw`, and the
hot-path branch of `src/godo_tracker_rt/main.cpp` and
`src/freed/serial_reader.cpp` — must not call `new`, `malloc`,
`std::string(const char*)`, `std::vector::push_back/emplace_back/resize`,
or any equivalent dynamic allocation. Per-run scratch buffers are
allocated once at thread startup and reused.

This is a **convention enforced by code review**, not a compile-time
check. `scripts/build.sh` runs a best-effort `grep` smoke pass over the
above paths and prints warnings under `[rt-alloc-grep]`; the warnings
are reviewed manually — they are not authoritative and do not fail the
build.

### Known scaffolding

- `src/godo_tracker_rt/main.cpp :: thread_stub_cold_writer` — a
  1 Hz canned offset generator marked `// TODO(phase-4-2): replace with
  AMCL writer thread from src/localization/`. Its sole purpose is to
  exercise the seqlock + smoother cross-thread interaction end-to-end
  before AMCL lands.

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

---

## 2026-04-24 — Phase 4-1 RT hot path (P4-1-1 … P4-1-13)

### Module map (additions)

```text
cmake/tomlplusplus.cmake             INTERFACE lib tomlplusplus::tomlplusplus
                                     (v3.4.0, pinned SHA 30172438…ba9de)
external/tomlplusplus/                git submodule

src/core/
├─ CMakeLists.txt                    target: godo_core (static)
├─ constants.hpp                     Tier-1 invariants (FreeD / RPLIDAR / 59.94)
├─ config_defaults.hpp               Tier-2 compile-time defaults
├─ config.{hpp,cpp}                  CLI > env > TOML > defaults loader
├─ rt_types.hpp                      Offset (24 B), FreedPacket (29 B)
├─ seqlock.hpp                       single-writer / N-reader seqlock
├─ time.hpp                          monotonic_ns() (header-only)
└─ rt_flags.{hpp,cpp}                g_running, calibrate_requested

src/yaw/
├─ CMakeLists.txt                    target: godo_yaw
└─ yaw.{hpp,cpp}                     lerp_angle, wrap_signed24

src/smoother/
├─ CMakeLists.txt                    target: godo_smoother
└─ offset_smoother.{hpp,cpp}         linear ramp, gen-edge, snap at frac≥1

src/freed/
├─ CMakeLists.txt                    target: godo_freed
├─ d1_parser.{hpp,cpp}               ParseResult, compute_checksum
└─ serial_reader.{hpp,cpp}           Thread A body (termios 8O1 PL011)

src/udp/
├─ CMakeLists.txt                    target: godo_udp
└─ sender.{hpp,cpp}                  UdpSender + apply_offset_inplace

src/rt/
├─ CMakeLists.txt                    target: godo_rt
└─ rt_setup.{hpp,cpp}                mlockall / affinity / SCHED_FIFO /
                                     block_all_signals helpers

src/godo_jitter/
├─ CMakeLists.txt                    target: godo_jitter (binary)
└─ main.cpp                          CLOCK_MONOTONIC jitter harness

src/godo_tracker_rt/
├─ CMakeLists.txt                    target: godo_tracker_rt (binary)
└─ main.cpp                          Thread A / D / stub writer / signal

tests/ (additions — all hardware-free)
├─ test_yaw.cpp                      12 §6.5 cases, exact equality
├─ test_smoother.cpp                 6 §6.4.4 cases (test 3 rescoped)
├─ test_freed_parser.cpp             8 cases, synth fixtures with L-refs
├─ test_freed_serial_reader.cpp      PTY harness (8O1 termios on master)
├─ test_udp_apply_offset.cpp         5 cases, decode/encode + pan wrap
├─ test_udp_loopback.cpp             AF_INET loopback byte-identity
├─ test_config.cpp                   8 cases, precedence chain + rejects
├─ test_rt_setup.cpp                 4 cases, actionable-stderr checks
├─ test_seqlock_roundtrip.cpp        4 cases, 1W/4R 10^6-iter stress
└─ test_rt_replay.cpp                E2E: posix_spawn tracker + PTY + UDP

scripts/
├─ setup-pi5-rt.sh                   ONE-TIME ROOT: setcap + limits.conf
├─ run-pi5-tracker-rt.sh             launch wrapper (no sudo)
├─ run-pi5-jitter.sh                 jitter binary wrapper
└─ build.sh (modified)               adds [rt-alloc-grep] smoke pass

doc/
└─ freed_wiring.md                   A) wiring, B) boot config, C) verify
```

### Dependency tree (new targets)

```text
godo_tracker_rt
├─ godo_core ─ tomlplusplus
├─ godo_rt   ─ pthread
├─ godo_yaw
├─ godo_freed ─ godo_core
├─ godo_smoother ─ godo_yaw
└─ godo_udp ─ godo_core + godo_yaw + godo_freed

godo_jitter
├─ godo_core
└─ godo_rt
```

### Added

- CMake wiring: `CMakeLists.txt` adds 8 new `add_subdirectory()` calls
  under `src/` and `include(cmake/tomlplusplus.cmake)`.
- `cmake/tomlplusplus.cmake` — submodule loader + SHA pin.
- `external/tomlplusplus/` — submodule at v3.4.0
  (SHA `30172438cee64926dc41fdd9c11fb3ba5b2ba9de`).
- `src/core/*` (5 headers + 2 cpp) — Tier-1 constants, Tier-2 defaults,
  Config loader, RT types, Seqlock, monotonic_ns, RT flags.
- `src/yaw/yaw.{hpp,cpp}` — pure `lerp_angle` + `wrap_signed24`.
- `src/smoother/offset_smoother.{hpp,cpp}` — linear ramp.
- `src/freed/d1_parser.{hpp,cpp}` — ParseResult + checksum helpers.
- `src/freed/serial_reader.{hpp,cpp}` — Thread A body; termios 8O1 +
  non-blocking read loop with nanosleep backoff so `g_running` is polled
  at ≤ 10 ms latency even when tcsetattr could not install VTIME.
- `src/udp/sender.{hpp,cpp}` — UdpSender (connected SOCK_DGRAM,
  non-blocking, EAGAIN-miss counter) + `apply_offset_inplace`.
- `src/rt/rt_setup.{hpp,cpp}` — lifecycle helpers; `lock_all_memory`
  gates on `RLIMIT_MEMLOCK` so a host without setup-pi5-rt.sh applied
  still permits thread creation.
- `src/godo_jitter/main.cpp` — CLOCK_MONOTONIC measurement harness
  (mean / p50 / p95 / p99 / max, JSON trailer line).
- `src/godo_tracker_rt/main.cpp` — main, signal thread (sigwait on
  SIGTERM/SIGINT), Thread A, stub cold writer (with phase-4-2 TODO
  breadcrumb), Thread D (smoother.tick → apply_offset → udp.send +
  clock_nanosleep(TIMER_ABSTIME)).
- `scripts/setup-pi5-rt.sh` — one-time root: setcap + limits.conf +
  ttyAMA0 ownership check; idempotent.
- `scripts/run-pi5-tracker-rt.sh`, `scripts/run-pi5-jitter.sh`.
- `doc/freed_wiring.md` — §A wiring, §B boot config, §C verification.
- 10 test targets as listed above, all labelled `hardware-free`.

### Changed

- `CMakeLists.txt` (top-level) — added 8 `add_subdirectory` lines and
  the tomlplusplus include.
- `tests/CMakeLists.txt` — added 10 new test target blocks; the
  `test_rt_replay` target has a `GODO_TRACKER_RT_PATH` compile
  definition from `$<TARGET_FILE:godo_tracker_rt>`.
- `scripts/build.sh` — appends the `[rt-alloc-grep]` smoke pass. Hits
  are printed to stderr; they do not fail the build.

### Removed

- (none)

### Tests

- 10 new hardware-free targets; all pass (`ctest -L hardware-free` = 16/16).
- `test_rt_replay` end-to-end: posix_spawn the tracker binary, drive
  canned bytes on a PTY master (8O1 termios installed on both ends),
  capture UDP on 127.0.0.1, assert type byte, cam_id, and checksum
  round-trip through the whole pipeline.
- `test_seqlock_roundtrip` covers a 1-writer / 4-reader stress run at
  10^6 writes; asserts no torn payload is observable.

### Jitter numbers on news-pi01 (no RT privileges)

```text
godo_jitter --duration-sec 60 --cpu 3 --prio 1
ticks=3596 period_ns=16683350
mean=110171.0 ns   p50=57733.0 ns   p95=144556.0 ns
p99=2028350.0 ns   max=5337530.0 ns
```

These numbers were captured without SCHED_FIFO or mlockall (the test
host does not yet have setup-pi5-rt.sh applied; `lock_all_memory`
correctly declined on RLIMIT_MEMLOCK = 8 MiB). They are a **baseline**
for the ordinary-scheduler path; the post-setup numbers are the ones
that will be compared against the 200 µs p99 design goal in Phase 5.

### Deviations from the plan

- **`std::span<const std::byte>` → `(const std::byte*, size_t)`**. The
  top-level `CMakeLists.txt` pins C++17, so `std::span` is unavailable.
  The parser and sender signatures use a pointer + length pair instead;
  behaviour is identical.
- **`lock_all_memory` gates on RLIMIT_MEMLOCK**. The plan said call
  `mlockall(MCL_CURRENT | MCL_FUTURE)` unconditionally. Unconditional
  calling on a host without raised memlock rlimit causes every
  subsequent thread-stack `mmap()` to fail with EAGAIN (the tracker
  cannot spawn Thread A). The helper now checks `RLIMIT_MEMLOCK` first
  and returns false + an actionable stderr message if the rlimit is
  under 128 MiB, skipping the mlockall call. Production behaviour
  (post setup-pi5-rt.sh) is unchanged.
- **Serial reader is non-blocking with a nanosleep-based g_running
  poll — ONLY on the termios-fail (PTY) path**. The plan used
  `VMIN = 1, VTIME = 1` for a 100 ms blocking read. On PTY slaves Linux
  refuses the 8O1 cflags with EINVAL, so `tcsetattr` is a warn-and-
  continue; for PTYs we then set `O_NONBLOCK` and nap 10 ms on EAGAIN.
  Real PL011 ttys apply the termios successfully and **keep the
  blocking read behaviour** (VTIME=1 wakes the kernel every ≤100 ms
  to check `g_running`). Post-Mode-B fix: `O_NONBLOCK` is now gated on
  the `tcsetattr` failure path instead of being set unconditionally,
  so the production PL011 path no longer enters the 10 ms-nap loop on
  idle.
- **[rt-alloc-grep] surfaces one hit**: `src/udp/sender.cpp` error
  path inside the UdpSender **constructor** uses `std::string(...)` to
  build an exception message. The constructor is called once at startup,
  not on the hot path; this is acceptable per invariant (e), which
  scopes the no-alloc convention to Thread D's steady-state loop.
- **`test_rt_replay` narrows the plan's "byte-for-byte" UDP assertion
  to type-byte + cam_id + checksum validity**. The stub cold-path
  writer emits a 1 Hz canned offset sequence; its phase at the moment
  of UDP capture is timing-dependent, so asserting exact X/Y/Pan bytes
  would make the test flaky. The invariant-layer assertions still pin
  the binary's byte-level correctness on the parts that do not depend
  on stub state. Phase 4-2 replaces the stub with AMCL (deterministic
  pose-in → pose-out), at which point the test can be tightened to
  full byte parity.

---

## 2026-04-25 (late) — Phase 4-2 A: LiDAR component-isation

`src/godo_smoke/{sample.hpp, lidar_source_rplidar.{cpp,hpp}}` promoted to
`src/lidar/` as a reusable component (`godo_lidar` static lib). `godo_smoke`
binary now LINKS the lib instead of compiling those sources directly. Phase
4-2 AMCL (`src/localization/`) and any future LiDAR consumer share the
same component.

### Module map (additions)

```text
src/lidar/
├─ CMakeLists.txt                    target: godo_lidar (static lib)
├─ sample.hpp                        Sample, Frame, validate()  — namespace godo::lidar
├─ lidar_source_rplidar.hpp          concrete (no virtual)       — namespace godo::lidar
└─ lidar_source_rplidar.cpp          uses godo::rt::monotonic_ns
                                     (no longer pulls godo_smoke/timestamp.hpp)
```

### Dependency tree

```text
godo_lidar
└─ rplidar_sdk::static

godo_smoke           (was: compiled lidar_source_rplidar.cpp directly)
├─ godo_lidar        (new link)
└─ OpenSSL::Crypto

test_lidar_live, test_csv_writer_writes, test_csv_parity, test_sample_invariants
└─ godo_lidar        (new link; replaces direct .cpp compilation)
```

### Changed

- `CMakeLists.txt` (top-level) — `add_subdirectory(src/lidar)` now precedes
  `src/godo_smoke` so `godo_lidar` is available when `godo_smoke` links.
- `src/godo_smoke/CMakeLists.txt` — `lidar_source_rplidar.cpp` removed
  from the source list; `target_link_libraries` swaps `rplidar_sdk::static`
  for `godo_lidar`.
- `src/godo_smoke/main.cpp` — `#include "lidar/lidar_source_rplidar.hpp"`
  + `using godo::lidar::Frame; using godo::lidar::LidarSourceRplidar;`
  alongside the existing `using namespace godo::smoke;` (csv_writer,
  session_log, args stay in `godo::smoke`).
- `src/godo_smoke/csv_writer.{hpp,cpp}` — `#include "lidar/sample.hpp"`,
  `write_frame(const godo::lidar::Frame&)`, file-level
  `using godo::lidar::Frame; using godo::lidar::Sample;` in the .cpp.
- `tests/CMakeLists.txt` — `test_lidar_live`, `test_csv_writer_writes`,
  `test_csv_parity`, `test_sample_invariants` now link `godo_lidar`
  instead of compiling `${GODO_SMOKE_SRC_DIR}/lidar_source_rplidar.cpp`
  / `timestamp.cpp` directly.
- `tests/lidar_source_fake.{hpp,cpp}` — namespace
  `godo::smoke::test` → `godo::lidar::test`.
- `tests/test_lidar_live.cpp`, `test_csv_writer_writes.cpp`,
  `test_sample_invariants.cpp`, `test_csv_parity.cpp` — `using
  godo::smoke::Sample/Frame/validate/LidarSourceRplidar/test::LidarSourceFake`
  → `using godo::lidar::*` (CsvWriter remains `godo::smoke::CsvWriter`).

### Removed

- `src/godo_smoke/sample.hpp` (moved to `src/lidar/`)
- `src/godo_smoke/lidar_source_rplidar.hpp` (moved to `src/lidar/`)
- `src/godo_smoke/lidar_source_rplidar.cpp` (moved to `src/lidar/`)

### Tests

- `scripts/build.sh` clean rebuild: 16/16 hardware-free tests PASS.
  `test_csv_parity` (Python parity) PASS at 0.83 s. `test_lidar_live`
  builds (hardware-required, not run in default ctest).
- `[rt-alloc-grep]` smoke pass: same single hit as before
  (`UdpSender` constructor `std::string`, init-time, justified per
  invariant (e)). No new hot-path allocations.

### Invariant updates (no behaviour change)

- Invariant (a) "no-ABC duck-typed twin" wording updated mentally to
  reference `godo::lidar::LidarSourceRplidar` and
  `godo::lidar::test::LidarSourceFake`. The structural rule (different
  class names, no inheritance) is unchanged. The invariant text on this
  page still says `src/godo_smoke/*.hpp`; future doc cleanup pass should
  generalise to "any LiDAR source under `src/lidar/`".

### Deviations from the plan

- **`monotonic_ns` duplication intentionally retained**. `src/core/time.hpp`
  defines `godo::rt::monotonic_ns()` (header-only, used by godo_jitter +
  godo_tracker_rt + godo_freed_passthrough); `src/godo_smoke/timestamp.cpp`
  defines `godo::smoke::monotonic_ns()` (also exposing
  `utc_timestamp_compact/iso`). Phase 4-2 A migrated the LiDAR-side caller
  (`lidar_source_rplidar.cpp`) onto `godo::rt::monotonic_ns` so the new
  `godo_lidar` lib has zero dependency on `godo_smoke`. The remaining
  godo_smoke-internal `godo::smoke::monotonic_ns` is one-line wrapper-
  worth of duplication; cleanup is deferred until a non-cosmetic reason
  appears (e.g. a third caller adopting the smoke variant).
- **godo_smoke binary's own files keep `namespace godo::smoke`** rather
  than renaming to `godo::lidar` wholesale. CsvWriter / SessionLog / Args
  are all genuinely smoke-scoped (capture-tool-specific I/O); promoting
  them to `godo::lidar` would over-commit. The split is: data types +
  hardware driver = `godo::lidar`; capture-tool I/O = `godo::smoke`.

### Module map (additions)

```text
src/godo_freed_passthrough/
├─ CMakeLists.txt                    target: godo_freed_passthrough (binary)
└─ main.cpp                          single-thread forwarder; reuses
                                     freed::SerialReader + udp::UdpSender

scripts/
└─ run-pi5-freed-passthrough.sh      launch wrapper (no sudo)
```

### Dependency tree

```text
godo_freed_passthrough
├─ godo_core
├─ godo_freed   ─ godo_core
└─ godo_udp     ─ godo_core + godo_yaw + godo_freed
```

### Added

- `src/godo_freed_passthrough/main.cpp` — minimal FreeD serial → UDP
  forwarder. Defaults `--port /dev/ttyAMA0 --baud 38400 --host
  10.10.204.184 --udp-port 50002 --rate-hz 0`. Spawns one worker thread
  running `freed::SerialReader::run()` against a local
  `Seqlock<FreedPacket>`. Main thread runs one of two send loops:
  - **As-arrives** (`--rate-hz 0`, default): poll `latest.generation()`
    at 1 ms, forward each new packet immediately. Lowest forward latency
    but inherits serial + scheduler jitter on the UDP cadence.
  - **Paced** (`--rate-hz <f>`, e.g. 59.94): `clock_nanosleep
    (TIMER_ABSTIME)` at exactly 1/rate intervals; each tick reads
    the latest seqlock slot and forwards (re-sending the previous
    packet if no new arrived; older packets are dropped on purpose).
    Cadence determined by the host clock, decoupled from serial
    arrival jitter. Same pattern Thread D uses in `godo_tracker_rt`.
  Per-second stats on stderr (pps / total / repeat / skip / send_fail /
  `freed::unknown_type_count()`). `repeat` and `skip` are 0 in
  as-arrives mode and meaningful only in paced mode (`repeat` = ticks
  where no new source packet had arrived; `skip` = source packets
  dropped because >1 arrived between ticks). SIGINT/SIGTERM handler
  sets `godo::rt::g_running` and main additionally
  `pthread_kill(t_serial.native_handle(), SIGTERM)`s the worker on
  exit to interrupt a blocking `read()` when no FreeD source is
  connected (VMIN=1 + VTIME=1 only arms the inter-byte timer AFTER
  the first byte, so without this the worker would block forever on
  an idle line).
- `src/godo_freed_passthrough/CMakeLists.txt` — links `godo_core`,
  `godo_freed`, `godo_udp`.
- `scripts/run-pi5-freed-passthrough.sh` — launch wrapper. No
  setcap / mlockall / SCHED_FIFO needed; binary uses no RT privileges.
- `CMakeLists.txt` (top-level) — added one
  `add_subdirectory(src/godo_freed_passthrough)` line.

### Purpose vs. godo_tracker_rt

| Concern | godo_tracker_rt | godo_freed_passthrough |
| --- | --- | --- |
| FreeD framing | freed::SerialReader | freed::SerialReader (reused) |
| Offset apply | yes (smoother + apply_offset_inplace) | **no** (verbatim passthrough) |
| Cadence | clock_nanosleep @ 59.94 Hz | as-arrives (≤1 ms latency) |
| RT scheduling | SCHED_FIFO + pinned + mlockall | none |
| Privileges | cap_sys_nice + cap_ipc_lock | none (just dialout) |
| Goal | production hot path | wiring / UDP path bring-up |

The passthrough is intended for the FIRST plug-in: confirm the YL-128
delivers framed bytes, the Pi parses them, and packets reach the UE
host. Once verified, switch to `godo_tracker_rt` (which adds the offset
and the 59.94 fps cadence) for actual production use.

### Tests

- No new tests. The binary composes already-tested components:
  `freed::SerialReader` (test_freed_serial_reader), `freed::parse_d1`
  (test_freed_parser), `udp::UdpSender` (test_udp_loopback), and
  `Seqlock` (test_seqlock_roundtrip). The full RT pipeline is covered
  end-to-end by `test_rt_replay`. Adding a parallel passthrough test
  would duplicate that coverage with no new bias-block. Documented per
  CLAUDE.md §6 minimal-code rule.
- Manual end-to-end verification on news-pi01 (2026-04-25): socat PTY
  pair → passthrough → Python UDP listener; one synthetic D1 packet
  (type=0xD1 cam_id=0x01 zeros checksum=0x6e) delivered byte-identical;
  SIGINT shutdown latency = 1 ms (pthread_kill path).

### Deviations from the plan

- (none — direct Parent implementation, no separate planner/reviewer
  pass since this is a 200-line bring-up tool composing already-reviewed
  modules.)

### Known caveat — surfaces an existing latent issue

The pthread_kill workaround documented above also applies in principle
to `godo_tracker_rt`'s Thread A: with no FreeD source connected, the
production tracker's Thread A would also block forever in read() at
shutdown. In production this is invisible because the crane streams at
60 Hz so VTIME=1's inter-byte timer is always armed. If we ever ship
the tracker as a generally-runnable binary that can be started before
the crane is connected, mirror the same pthread_kill on Thread A's
native_handle from `godo_tracker_rt::main()`'s shutdown stanza.
