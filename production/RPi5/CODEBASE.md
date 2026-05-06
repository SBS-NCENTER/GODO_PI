# RPi5 production CODEBASE

Structural / functional change log for `/production/RPi5`. See
[`../../CLAUDE.md §6`](../../CLAUDE.md) for the update policy and
[`../../PROGRESS.md`](../../PROGRESS.md) for cross-session state.

---

## Scope

Phase 4-2 D landed. Currently ships **four binaries**:
- `godo_smoke` — Phase 3 bring-up tool (LiDAR capture → CSV / session log).
- `godo_jitter` — RT scheduling jitter measurement harness (Phase 4-1).
- `godo_tracker_rt` — production hot path: FreeD receive + offset apply +
  59.94 fps UDP send + AMCL cold writer with three-state machine (Idle /
  OneShot / Live) + GPIO + UDS operator-trigger surfaces.
- `godo_freed_passthrough` — wiring bring-up tool (FreeD serial → UDP
  forwarder, no offset, no RT privileges) (Phase 4-1 follow-up).

AMCL with EDT-based likelihood field, low-variance resampling, the
step()/converge() split, the cold-path deadband filter (§6.4.1), and the
operator GPIO/UDS trigger surfaces all live under `src/localization/`,
`src/gpio/`, and `src/uds/`. Live mode publishes through the deadband at
~10 Hz; OneShot is operator-triggered and bypasses the deadband
(`forced=true`). Phase 4-3 (`godo-webctl` HTTP/api endpoints) is the
natural follow-up — it will connect to the UDS server landed in 4-2 D.

---

## Module map

Top-level snapshot of the C++ tracker source tree. For per-week dated change-log entries, see the weekly archives at [`CODEBASE/`](./CODEBASE/).

```text
CMakeLists.txt                       C++17, warnings-as-errors, doctest, OpenSSL::Crypto, Eigen3
cmake/rplidar_sdk.cmake              ExternalProject wrapping the upstream SDK Makefile,
                                     pinned SHA 99478e5f…36869
cmake/tomlplusplus.cmake             header-only INTERFACE lib at v3.4.0 (SHA 30172438…ba9de)

src/core/                            namespace godo::core, godo::rt
├─ CMakeLists.txt                    target: godo_core (static)
├─ constants.hpp                     Tier-1 invariants (FreeD / RPLIDAR / 59.94 Hz / AMCL bounds
│                                    + Phase 4-2 D: GPIO_DEBOUNCE_NS / UDS_REQUEST_MAX_BYTES
│                                    / SHUTDOWN_POLL_TIMEOUT_MS / GPIO_MAX_BCM_PIN)
├─ config_defaults.hpp               Tier-2 compile-time defaults (24 keys: 20 AMCL +
│                                    Phase 4-2 D Live σ pair + GPIO pin pair)
├─ config.{hpp,cpp}                  CLI > env > TOML > defaults loader
├─ rt_types.hpp                      Offset (24 B), FreedPacket (29 B)
├─ seqlock.hpp                       single-writer / N-reader seqlock
├─ time.hpp                          godo::rt::monotonic_ns (header-only)
└─ rt_flags.{hpp,cpp}                g_running, g_amcl_mode (AmclMode: Idle/OneShot/Live)

src/yaw/                             pure free functions, no state
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
└─ rt_setup.{hpp,cpp}                mlockall (RLIMIT_MEMLOCK gated) /
                                     affinity / SCHED_FIFO / signal helpers

src/lidar/                           namespace godo::lidar
├─ CMakeLists.txt                    target: godo_lidar (static lib)
├─ sample.hpp                        Sample, Frame, validate() — Python frame.py parity
└─ lidar_source_rplidar.{hpp,cpp}    concrete (NO virtual) RPLIDAR C1 driver wrapper

src/localization/                    namespace godo::localization (Phase 4-2 B)
├─ CMakeLists.txt                    target: godo_localization (static lib)
├─ pose.{hpp,cpp}                    Pose2D, Particle, circular_mean / std (M5)
├─ rng.{hpp,cpp}                     Rng (mt19937_64; seed=0 → time, !=0 → deterministic)
├─ occupancy_grid.{hpp,cpp}          OccupancyGrid + load_map (PGM P5 + slam_toolbox YAML)
│                                    + OCCUPIED_CUTOFF_U8 shared free/obstacle threshold
├─ likelihood_field.{hpp,cpp}        Felzenszwalb 2D EDT precompute + Gaussian conversion
├─ scan_ops.{hpp,cpp}                downsample / evaluate_scan / jitter_inplace / resample
├─ amcl.{hpp,cpp}                    class Amcl: step()/converge() split (NO virtual, inv. f);
│                                    Phase 4-2 D — step() has σ-overload form
│                                    (sigma_xy_m / sigma_yaw_deg) so Live can
│                                    use a different jitter σ than OneShot
├─ amcl_result.{hpp,cpp}             AmclResult + compute_offset (M3 canonical-360 dyaw)
├─ deadband.hpp                      header-only deadband filter at the publish seam
└─ cold_writer.{hpp,cpp}             Idle/OneShot/Live ALL real (Phase 4-2 D Wave A);
                                     OneShot ALWAYS seeds globally (no warm-seed shortcut);
                                     Live uses run_live_iteration with σ_live pair, publishes
                                     through the deadband (forced=false); on_leave_live
                                     re-arms the live-first-iter latch on every Live exit;
                                     M1 wait-free, M8 SIGTERM watchdog

src/gpio/                            namespace godo::gpio (Phase 4-2 D Wave B)
├─ CMakeLists.txt                    target: godo_gpio (static lib; links libgpiodcxx + libgpiod)
├─ gpio_source.hpp                   GpioCallbacks + LineIndex (header-only public API contract;
│                                    duck-typed twin spec for production + fake — invariant (a))
├─ gpio_source_libgpiod.hpp          GpioSourceLibgpiod (production driver)
└─ gpio_source_libgpiod.cpp          libgpiod v2 chip open + line request + edge wait_events
                                     loop with SHUTDOWN_POLL_TIMEOUT_MS poll; CLOCK_MONOTONIC
                                     event clock (M2); last-accepted debounce (M2); INT64_MIN
                                     sentinel so the first press is always accepted; exception
                                     wrap on open(); RAII close()

src/uds/                             namespace godo::uds (Phase 4-2 D Wave B)
├─ CMakeLists.txt                    target: godo_uds (static lib; godo_core only)
├─ json_mini.{hpp,cpp}               hand-rolled minimal JSON parser/serializer for the four
│                                    canonical message shapes (no nlohmann/json dependency);
│                                    rejects backslash escapes, unknown keys, duplicate keys,
│                                    trailing tokens
├─ uds_server.hpp                    UdsServer + ModeGetter / ModeSetter typedefs
└─ uds_server.cpp                    bind / listen(backlog=4) / chmod 0660 (M3) / poll(2)
                                     accept loop with SHUTDOWN_POLL_TIMEOUT_MS (M1: NO
                                     SO_RCVTIMEO on listen, NO pthread_kill from main);
                                     per-connection SO_RCVTIMEO 1 s; UDS_REQUEST_MAX_BYTES
                                     buffer cap; one client at a time, request → response →
                                     close

src/godo_smoke/                      namespace godo::smoke (capture-tool I/O)
├─ CMakeLists.txt                    target: godo_smoke (binary), links godo_lidar
├─ main.cpp                          setlocale("C") → parse → open → scan → close
├─ args.{hpp,cpp}                    variant<Args, ParseHelp, ParseError>; no external dep
├─ timestamp.{hpp,cpp}               monotonic_ns, utc_timestamp_{compact,iso}
├─ csv_writer.{hpp,cpp}              snprintf-based, fopen("wb"), byte-identical to Python
└─ session_log.{hpp,cpp}             chunked EVP SHA-256, log body matches Python schema

src/godo_jitter/
├─ CMakeLists.txt                    target: godo_jitter (binary)
└─ main.cpp                          CLOCK_MONOTONIC jitter harness

src/godo_tracker_rt/
├─ CMakeLists.txt                    target: godo_tracker_rt (binary; links godo_localization,
│                                    godo_gpio, godo_uds — Wave B)
└─ main.cpp                          Thread A (FreeD) / Thread D (UDP RT) / cold writer
                                     (godo::localization::run_cold_writer) / GPIO thread
                                     (Wave B) / UDS thread (Wave B) / signal handler;
                                     pthread_kill(SIGTERM) cold-writer kick before join (M8);
                                     NO pthread_kill for GPIO / UDS — both poll with
                                     SHUTDOWN_POLL_TIMEOUT_MS and self-exit on
                                     g_running.store(false) per Mode-A amendment M1

src/godo_freed_passthrough/
├─ CMakeLists.txt                    target: godo_freed_passthrough (binary)
└─ main.cpp                          single-thread FreeD-serial → UDP forwarder

tests/                               (see invariant (b) for source-list splits)
├─ CMakeLists.txt
├─ lidar_source_fake.{hpp,cpp}       godo::lidar::test::LidarSourceFake (duck-typed twin)
├─ test_csv_writer_writes.cpp        production write path; includes csv_writer.hpp
├─ test_csv_writer_readback.cpp      stdlib-only parse; include path excludes ../src/godo_smoke
├─ test_csv_parity.cpp               cmp against Python prototype via `uv run`
├─ test_session_log.cpp              SHA-256 known-good vectors + full field coverage
├─ test_args.cpp                     CLI parsing boundaries
├─ test_sample_invariants.cpp        validate() + LidarSourceFake shape
├─ test_lidar_live.cpp               hardware-required; LABELS "hardware-required"
├─ test_yaw.cpp                      12 §6.5 cases, exact equality
├─ test_smoother.cpp                 6 §6.4.4 cases
├─ test_freed_parser.cpp             8 cases, synth fixtures
├─ test_freed_serial_reader.cpp      PTY harness (8O1 termios on master)
├─ test_udp_apply_offset.cpp         5 cases, decode/encode + pan wrap
├─ test_udp_loopback.cpp             AF_INET loopback byte-identity
├─ test_config.cpp                   8 cases, precedence chain + rejects
├─ test_rt_setup.cpp                 4 cases, actionable-stderr checks
├─ test_seqlock_roundtrip.cpp        4 cases, 1W/4R 10^6-iter stress
├─ gpio_source_fake.hpp              godo::gpio::test::GpioSourceFake (duck-typed twin per
│                                    invariant (a); shared debounce-rule pin with production)
├─ test_gpio_source_fake.cpp         hardware-free; 6 cases — calibrate/live-toggle dispatch,
│                                    50 ms debounce, last-accepted bounce-burst, S5
│                                    OneShot-drop, per-line independence
├─ test_gpio_source_libgpiod.cpp     LABELS "hardware-required-gpio"; 2 cases — chip open +
│                                    line request + RAII close
├─ test_uds_server.cpp               hardware-free; 11 cases — set/get/ping round-trip,
│                                    parse_error / bad_mode / unknown_cmd, oversized close,
│                                    SIGTERM-via-g_running unblock < 200 ms, json_mini direct
└─ test_rt_replay.cpp                E2E: posix_spawn tracker + PTY + UDP

scripts/
├─ build.sh                          cmake config + build + hw-free ctest gate +
│                                    [rt-alloc-grep] smoke pass
├─ setup-pi5-rt.sh                   ONE-TIME ROOT: setcap + limits.conf
├─ run-pi5-smoke.sh                  wrapper for godo_smoke
├─ run-pi5-tracker-rt.sh             launch wrapper for godo_tracker_rt (no sudo)
├─ run-pi5-jitter.sh                 jitter binary wrapper
├─ run-pi5-freed-passthrough.sh      passthrough binary wrapper
└─ promote_smoke_to_ts.sh            move out/<ts>_<tag>/ → test_sessions/TS<N>/

doc/
├─ smoke.md                          three-way comparison workflow (godo_smoke)
├─ freed_wiring.md                   YL-128 → PL011 wiring, boot config, verification
├─ irq_inventory.md                  /proc/interrupts inventory + recommended pinning
├─ gpio_wiring.md                    Phase 4-2 D Wave B: BCM 16/20 pinout + libgpiod install
│                                    + permissions + debounce policy + UX notes (S5)
└─ uds_protocol.md                   Phase 4-2 D Wave B: socket / wire format / commands /
                                     errors / examples / same-uid caveat (M3)

out/                                 runtime captures; contents gitignored
external/
├─ rplidar_sdk/                      git submodule, pinned SHA 99478e5f…36869
└─ tomlplusplus/                     git submodule, v3.4.0 SHA 30172438…ba9de
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

`godo::lidar::LidarSourceRplidar` (production, `src/lidar/`) and
`godo::lidar::test::LidarSourceFake` (tests) share no base class. Their
APIs match structurally; class names differ deliberately so no test can
silently substitute the wrong type. Per
`prototype/Python/src/godo_lidar/capture/sdk.py` lines 39–45 and
`PROGRESS.md` "no ABC" rule: duck typing is the project standard when
fewer than three implementations exist. Any `virtual` keyword in
`src/lidar/*.hpp` or `src/godo_smoke/*.hpp` is a review-blocking defect.

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

### (f) AMCL has no virtual methods

Particle-filter component swap-out is by `Amcl` template parameter, NOT
by ABC. Reuses invariant (a)'s no-ABC philosophy across the localization
module. Pinned by `cold_writer.cpp`'s no-mutex / no-virtual posture and
by code review on `src/localization/`. Added 2026-04-26 with Wave 2.

### (g) Track D — `last_scan_seq` publisher seam (build-grep enforced)

Two new build-time greps enforce the Track D hot-path isolation contract
(added 2026-04-29 with Track D):

- **`[scan-publisher-grep]`** — only `src/localization/cold_writer.cpp`
  and `src/godo_tracker_rt/main.cpp` may contain `last_scan_seq.store(...)`
  references. main.cpp is allowed exactly ONE call (the boot-time
  sentinel-iterations init that mirrors `last_pose_seq`'s init pattern);
  any second call there or any reference outside this allow-list FAILS
  the build. The cold writer is the SOLE runtime publisher of LastScan;
  the Seqlock single-writer contract relies on this.
- **`[hot-path-isolation-grep]`** — Thread D's body in `main.cpp` (the
  SCHED_FIFO 59.94 Hz UDP send loop) MUST NOT reference `last_scan_seq`.
  An awk state machine extracts the body of `void thread_d_rt(...)` and
  greps for the seqlock identifier; any hit FAILS the build. Without
  this gate, a future refactor could couple the hot path to a 11 KiB
  seqlock copy.

Both greps live in `scripts/build.sh` alongside the existing
`[m1-no-mutex]` (cold writer wait-free) and `[rt-alloc-grep]` (hot path
no-heap) gates.

### (h) Track D — `LastScan` cross-language SSOT

`godo::rt::LastScan` (`core/rt_types.hpp`) is the canonical struct.
`uds/json_mini.cpp::format_ok_scan` mirrors the field order on the wire.
The Python mirror `godo-webctl/src/godo_webctl/protocol.py::
LAST_SCAN_HEADER_FIELDS` is regex-extracted from `rt_types.hpp` (NOT
from `format_ok_scan`) at test time — `rt_types.hpp` is the SSOT for
field NAMES; `format_ok_scan` is the SSOT for wire ORDER.

Editing any one of (struct decl, format string, Python tuple, TS tuple
in `lib/protocol.ts`) without the others fails one of:
- C++ `static_assert sizeof(LastScan) == 11568` (struct shape pin),
- `tests/test_protocol.py::test_last_scan_header_fields_match_cpp_source`
  (Python regex pin against rt_types.hpp),
- TS by-inspection during code review (per
  `godo-frontend/CODEBASE.md` invariant (l)).

### (i) PR-DIAG — jitter publisher seam (build-grep enforced)

`Seqlock<JitterSnapshot> jitter_seq` and `Seqlock<AmclIterationRate>
amcl_rate_seq` are owned by `main.cpp`. The SOLE writer is
`rt/diag_publisher.cpp::run_diag_publisher_with_clock` (and its
production wrapper `run_diag_publisher`). Build-grep
`[jitter-publisher-grep]` (`scripts/build.sh`) enforces this — any
`(jitter_seq|amcl_rate_seq)\.store\b` outside `rt/diag_publisher.cpp`
fails the build.

The publisher runs on `SCHED_OTHER` (no `pin_current_thread_to_cpu` or
`set_current_thread_fifo` inside `run_diag_publisher`) — code-review
enforced, no build grep. The seqlocks are reader-side from the UDS
server (`thread_uds`) and from the publisher itself (snapshot →
recompute → store). Mode-A N3 fold pins this as code-review-enforced
symmetrically with `last_pose_seq` / `last_scan_seq`.

### (j) PR-DIAG (Mode-A M2) — AMCL-rate publisher seam

`AmclRateAccumulator amcl_rate_accum` is owned by `main.cpp`. The SOLE
writer is `localization/cold_writer.cpp::run_one_iteration` +
`run_live_iteration` (each calls `amcl_rate_accum.record(...)` exactly
once at the top of its body). Build-grep `[amcl-rate-publisher-grep]`
(`scripts/build.sh`) enforces this — any `amcl_rate_accum\.record\b`
outside `cold_writer.cpp` fails the build.

The accumulator's internal storage is a `Seqlock<AmclRateRecord>` (a
trivially-copyable `{count, last_ns}` pair). Mode-A M1 fold pinned the
seqlock as the implementation primitive (over two atomics) to avoid
measurable Hz-skew under concurrent writer/reader.

**SINGLE-WRITER threading invariant** (Mode-B S3 fold): `record()` is a
load-then-store sequence; two concurrent writers would lose updates.
The build-grep enforces *file-level* exclusion (`record()` only in
`cold_writer.cpp`) but NOT thread-level. Today the cold writer body
runs on a single thread (Thread C); any future split that introduces a
parallel cold-writer worker MUST either (a) add a real CAS loop inside
`record()`, (b) wrap all `record()` callers in a mutex, or (c) split
the accumulator per-thread and merge at publish. Code-review-enforced;
no test pin.

### (k) PR-DIAG — hot-path jitter contract (build-grep enforced)

`thread_d_rt` (the SCHED_FIFO 59.94 Hz UDP send loop in `main.cpp`) MUST
record exactly one jitter sample per tick via `jitter_ring.record(...)`
and MUST NOT do anything else with the ring. Build-grep
`[hot-path-jitter-grep]` (`scripts/build.sh`) enforces:

- exactly 1 `jitter_ring\.` reference total inside `thread_d_rt`,
- 0 `jitter_ring\.snapshot` references (snapshot is reader-side; the
  publisher thread is the only legitimate caller),
- 0 references to `std::sort`, `compute_percentile`, `compute_summary`,
  `format_ok_jitter`, or `jitter_seq` (percentile machinery lives in
  `rt/jitter_stats.cpp`, called only from the publisher).

Mode-A M3 fold pinned this symmetric contract — the exact-1 + exact-0
shape catches future drift toward Thread D reading the ring or
publishing the seqlock directly.

### (l) tracker-pidfile-discipline

`godo_tracker_rt::main()` acquires `core::PidFileLock` on
`cfg.tracker_pidfile` (default `/run/godo/godo-tracker.pid`)
IMMEDIATELY after `Config::load` and BEFORE any thread spawn /
`Seqlock` allocation / device open. Mechanism:
`fcntl(F_SETLK, F_WRLCK)` (POSIX advisory; auto-released by the
kernel on FD close — process death, SIGKILL included). On contention:
log stderr `godo_tracker_rt: pidfile held by PID <pid> — refusing to
start`, return 1. Lock acquisition is on the boot path only; RT
threads NEVER touch the pidfile FD. Override via `--pidfile <path>`,
`GODO_TRACKER_PIDFILE`, or TOML key `ipc.tracker_pidfile`. Path MUST
live on a local FS — tmpfs `/run/godo` is the project default; NFS
is unsupported (POSIX advisory lock semantics differ). Mode-A M6
fold: dtor unlinks BEFORE close so a third process trying open-then-
lock sees ENOENT promptly. Pinned by `tests/test_pidfile.cpp` (6
cases incl. fork-does-not-inherit per TB4). UDS server bind is now
atomic-rename (bind-temp + `rename(2)`) — eliminates the
`unlink → bind` TOCTOU window; pinned by 2 new cases in
`tests/test_uds_server.cpp`. See CLAUDE.md §6 "Single-instance
discipline".

### (m) RPLIDAR CW → REP-103 CCW boundary at scan_ops.cpp:48

`scan_ops::downsample` is the **single** point of convention shift
between the RPLIDAR C1's clockwise-positive sensor angle (per
`doc/RPLIDAR/RPLIDAR_C1.md:128`) and the AMCL kernel's standard
REP-103 counter-clockwise math. The shift is one unary minus:
`b.angle_rad = static_cast<float>(-s.angle_deg * kDegToRad)`. From
that point on every consumer of `RangeBeam.angle_rad`
(`scan_ops::evaluate_scan`, future SLAM bridges) reads CCW and
applies `xs = r·cos(a); ys = r·sin(a)` with no further sign flips.

The wire format (`LastScan.angles_deg` published by
`cold_writer::fill_last_scan`) is **deliberately unchanged**: it
continues to emit raw CW degrees so the SPA's PR #30 negation
(`poseCanvasScanLayer.ts`) remains the single client-side
convention shift. C++ AMCL math and SPA rendering are decoupled;
the wire stays raw CW.

Pinned by `tests/test_amcl_components.cpp::TEST_CASE("scan_ops::
downsample — RPLIDAR CW 90° beam projects to LiDAR's right side
under fix")` — 7 sub-asserts including a 270° beam (left side) and
a yaw=45° rotation that exercises every term in the rotation matrix.
Anyone who undoes the negation in `scan_ops.cpp:48` thinking it's a
typo will break the test and CI will block them.

Audit closure (verified 2026-04-29 KST):

- **(a) Producers of raw CW**: `lidar_source_rplidar.cpp:152-164`,
  `sample.hpp` invariants — unchanged.
- **(b) Raw-CW consumers (passthrough)**: `cold_writer.cpp:62`,
  `csv_writer.cpp:95`, `sample.hpp:38-39`, all
  `test_csv_*` / `test_cold_writer_*` / `test_sample_invariants` —
  unchanged.
- **(c) AMCL-frame consumer**: `scan_ops.cpp:71` (`evaluate_scan`) —
  automatically correct after the boundary fix.
- **(d) Test fixtures self-consistent in CCW frame**:
  `test_amcl_scenarios.cpp:122` (`synth_beams`),
  `test_amcl_components.cpp:148-153` (cardinal beams) — unchanged.

HIL convergence-rate protocol: `production/RPi5/doc/convergence_hil.md`.

### (n) Track D-5 — coarse-to-fine sigma_hit annealing for OneShot AMCL

OneShot AMCL anneals σ_hit through `amcl.sigma_hit_schedule_m`; Live mode
uses the static `cfg.amcl_sigma_hit_m` field, rebuilt on every OneShot
completion. Phase k>0 reseeds via `cfg.amcl_particles_local_n` and
`cfg.amcl_sigma_seed_xy_schedule_m[k]` — operators changing these keys
affect BOTH Live AND OneShot phase k>0. RNG draw sequence is schedule-
length-dependent; tests assert tolerances, never bit-exact pose values.

Pinned by:
- `tests/test_amcl_scenarios.cpp::TEST_CASE("AMCL Scenario D — annealing
  recovers from global ambiguity")` — 3 sub-checks against an asymmetric
  in-memory grid. The asymmetry property itself is REQUIRE'd at the top
  of the test (Mode-A T1) so a future fixture tweak that re-symmetrizes
  the obstacle fails BEFORE running the algorithm-under-test.
- `tests/test_amcl_components.cpp::TEST_CASE("Amcl::set_field — swap to
  a narrower σ field changes scan likelihood by closed-form ratio")` —
  pins that `set_field` actually rebinds and that the EDT's σ→likelihood
  relationship is exp(-d²/(2σ²)).
- `tests/test_config.cpp` — 9 cases covering schedule round-trip,
  monotonicity, range bound, length-1 fallthrough, sentinel-aware
  seed_xy schedule, length mismatch, sigma_hit_m bound bump 1.0 → 5.0.

Empirical motivation: `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md`
(σ=0.05 default gives 0/10 convergence on TS5; schedule [1.0, 0.5, 0.2,
0.1, 0.05] anneals through the convergence cliff at σ≈[0.1, 0.2]).

**Auto-minima tracking (added 2026-04-29 23:20 KST)**: `converge_anneal`
returns the pose from the phase with MIN `xy_std_m` across the entire
schedule, not the final-phase pose. Patience-aware early break: 2
consecutive worse-than-best phases triggers stop (single-phase noise
bumps tolerated; second consecutive bump signals real over-tightening
into sub-cell discretization). The default schedule reaches σ=0.05 final
but auto-minima usually picks phase 2 (σ=0.2) where σ_xy is empirically
lowest on a 5cm-cell map (HIL k=10/10, σ_xy median 0.009m vs 0.036m
without minima tracking). Operator can SAFELY granularize the schedule
without worrying about over-tightening — algorithm finds its own stop.
The pattern generalizes per `.claude/memory/project_pipelined_compute_pattern.md`.

`Amcl::set_field` is single-thread cold-writer use only — concurrent
`step()` from another thread is UB. Track D-5-P (parallel) workers must
serialize via the cold-writer's per-phase loop. Doc-comment-pinned in
`amcl.hpp`; build-grep `[m1-no-mutex]` ensures the cold writer body
remains lock-free.

Operator rollback recipe: to revert to pre-Track-D-5 single-σ behaviour,
set BOTH `amcl.sigma_hit_schedule_m = "0.05"` AND
`amcl.anneal_iters_per_phase = 25`.

### (q) Live pipelined-hint kernel ownership

`run_live_iteration_pipelined` is the SOLE caller of
`converge_anneal_with_hint` from the Live cold-path branch. The legacy
`run_live_iteration` (Phase 4-2 D bare-`Amcl::step` body) is kept as the
rollback path, gated behind `cfg.live_carry_pose_as_hint = false`. Both
paths publish through the deadband; both call `amcl_rate_accum.record`;
neither is ever reached on the same Live tick (the `run_cold_writer`
loop branches on the cfg flag at the top of the Live case body).

**Hint-flag discipline (extends invariant (p))**: Live MUST NEVER touch
`g_calibrate_hint_*`. Consume-once clearing belongs to OneShot
(`run_one_iteration` end). `converge_anneal_with_hint` accepts the hint
pose + σ pair as parameters and does NOT read or write the global flag;
this lets it be reachable from both the OneShot wrapper
(`converge_anneal`, which DOES consult the flag) and the Live carry
path (which uses `last_pose` as the hint source) without a flag-clear
race.

**Cold-start guard**: a stack-local `bool last_pose_set` in
`run_cold_writer` gates the pipelined Live entry. Initialised to false;
flipped to true ONLY at the end of a successful `run_one_iteration`
call AND at the end of the first successful pipelined Live tick. The
guard is read in the Live case body (BEFORE the blocking scan) — when
`cfg.live_carry_pose_as_hint == true` AND `last_pose_set == false`, the
mode is bounced to Idle with an actionable stderr message. Reading the
flag is preferred over comparing `last_pose` to (0,0,0): a legitimate
OneShot result of (0,0,0°) is operator-allowed (calibration origin
defaults are 0).

**Rollback path latch (`live_first_iter`)**: the legacy
`live_first_iter` latch is consulted ONLY by the rollback path
(`run_live_iteration`); the pipelined path bypasses it entirely (its
signature does not even take the parameter). On every Live exit,
`on_leave_live` re-arms the latch so a subsequent rollback-path Live
re-entry seeds globally — this is unaffected by the pipelined path.
Tests pin both: the pipelined kernel's signature distinctness via
`static_assert(!std::is_same_v<decltype(pipelined), decltype(legacy)>)`,
and the round-trip "flag-on Live → Idle → flag-off Live: rollback's
seed_global still fires" via a public-surface integration check in
`test_cold_writer_live_pipelined.cpp` case (h).

**σ + schedule semantics**: `cfg.amcl_live_carry_sigma_xy_m` /
`amcl_live_carry_sigma_yaw_deg` are TIGHT (matched to inter-tick
crane-base drift, NOT padded for AMCL search comfort, per
`project_hint_strong_command_semantics.md`). `cfg.amcl_live_carry_schedule_m`
is SHORT (typically 3 phases) — basin lock is automatic at the carry-σ;
the wide-σ phases of OneShot's anneal would waste depth. Both keys
are Tier-2 Recalibrate-class so an operator can widen via tracker.toml
without rebuild if HIL shows wider drift.

**Bool-as-Int convention**: `live_carry_pose_as_hint` is the project's
first Bool flag in CONFIG_SCHEMA. Encoded as `Int` with `min=0`,
`max=1`, `default_repr="0"|"1"` until a future PR adds first-class
`ValueType::Bool`. New Bool keys SHOULD follow this convention.
TOML accepts both `true/false` (toml++ bool) AND `0/1` (toml++ int);
env + CLI accept `0/1/true/false` case-insensitively. The selector's
default ships OFF in this PR for HIL safety (`cfg.live_carry_pose_as_hint
= false`); a follow-up PR flips the compile-time default after operator
HIL approval.

Pinned by:
- `tests/test_cold_writer_live_pipelined.cpp` — 8 cases covering t=0
  hint source, t=1 carryover, σ-override propagation, deadband seam,
  Live re-entry post-OneShot, signature distinctness, round-trip
  rollback, and the no-touch hint-flag invariant on
  `converge_anneal_with_hint`.
- `tests/test_cold_writer_live_iteration.cpp` — explicit
  `cfg.live_carry_pose_as_hint = false` baseline pin (rollback path).
- `tests/test_amcl_scenarios.cpp::TEST_CASE("AMCL Scenario E — converge_anneal_with_hint
  stays in hint basin under tight σ")` — algorithmic pin that the
  hint-driven kernel converges within the hint basin under the issue#5
  default σ pair (0.05 m / 5°) and short schedule.
- `tests/test_config_schema.cpp::TEST_CASE("issue#5: Live-carry rows
  present (count went 42 → 46)")` — schema row presence + types.
- `tests/test_config.cpp` — 11 cases covering the four cfg keys'
  defaults, TOML / env / CLI round-trips, precedence, range bounds,
  schedule monotonicity, bool rejection, unknown-key rejection.

Empirical motivation: `.claude/memory/project_amcl_multi_basin_observation.md`
(Live mode drifts ~4 m without the carry-hint kernel),
`.claude/memory/project_hint_strong_command_semantics.md` (σ matches
physical drift, not AMCL search comfort),
`.claude/memory/project_pipelined_compute_pattern.md` (sequential ships
first; pipelined-parallel deferred),
`.claude/memory/project_calibration_alternatives.md` "Live mode hint
pipeline" anchor.

### (r) webctl-owned schema rows — Config carries them verbatim, tracker logic never reads them

issue#12 introduces a new ownership pattern for the
`CONFIG_SCHEMA[]` table: rows whose **runtime consumer is godo-webctl
rather than the tracker itself**. The current entries (5 total after
issue#14 Maj-1 fold) are:

1. `webctl.pose_stream_hz` — SSE pose stream cadence (Hz, default 30,
   range [1, 60]).
2. `webctl.scan_stream_hz` — SSE scan stream cadence (Hz, default 30,
   range [1, 60]).
3. `webctl.mapping_docker_stop_grace_s` — Docker SIGTERM→SIGKILL grace
   window (seconds, default 20, range [10, 60]). install.sh
   sed-substitutes the value into the `godo-mapping@.service` ExecStop
   line at install time.
4. `webctl.mapping_systemd_stop_timeout_s` — systemd unit
   TimeoutStopSec (seconds, default 30, range [20, 90]). install.sh
   sed-substitutes the value into the unit file.
5. `webctl.mapping_webctl_stop_timeout_s` — webctl-side `mapping.stop()`
   polling deadline (seconds, default 35, range [25, 120]). webctl
   reads the value into `Settings.mapping_webctl_stop_timeout_s` from
   `tracker.toml` at startup; `mapping.stop()` reads `cfg.<field>`
   instead of the legacy `MAPPING_CONTAINER_STOP_TIMEOUT_S` constant.

All five Restart class. Ordering invariant on the timing trio
(enforced by webctl's `webctl_toml.read_webctl_section`):
`docker_stop_grace_s < systemd_stop_timeout_s < webctl_stop_timeout_s`.
A misordered TOML payload raises `WebctlTomlError` at webctl startup
naming the offending key, so a manually-edited `tracker.toml` cannot
produce a SIGKILL-mid-rename ladder that loses the lifetime asset.

**Storage contract (Parent decision A1, post-Mode-A 2026-05-01 KST)**:
the keys are first-class `Config` fields (`int webctl_pose_stream_hz`,
`int webctl_scan_stream_hz`) wired through every existing config
machinery touchpoint:

1. `core/config_defaults.hpp` — Tier-1 constants
   `WEBCTL_POSE_STREAM_HZ_DEFAULT = 30`,
   `WEBCTL_SCAN_STREAM_HZ_DEFAULT = 30`.
2. `core/config_schema.hpp` — schema rows declare type, range, default,
   reload class. The row count moved 46 → 48 (issue#12) → 51 (issue#14
   Maj-1) in lockstep with the C++ `static_assert` and webctl's
   `EXPECTED_ROW_COUNT`.
3. `core/config.cpp` — `allowed_keys()` set, `apply_toml_file`,
   `apply_env`, `apply_cli`, `Config::make_default`. CLI / env / TOML
   precedence matches every other Tier-2 Int row.
4. `config/apply.cpp` — `apply_one` writes to the staging Config field;
   `read_effective` reads it back. `render_toml` emits a `[webctl]`
   section with the stored values; `apply_get_all` (`/api/config`)
   returns the actual stored value (NOT a default-zero sentinel).
5. webctl reads `/var/lib/godo/tracker.toml` directly via
   `godo_webctl/webctl_toml.read_webctl_section` to consume the value.

**The tracker never reads these fields in any logic path.** No cold
writer branch, no smoother tick, no AMCL kernel consults
`webctl_pose_stream_hz` or `webctl_scan_stream_hz`. They round-trip
through Config purely so the SPA's schema-driven Config tab works
uniformly across all 48 rows and so `render_toml` produces a
deterministic file the tracker can load + persist on the next edit.

**Why not a parallel `WEBCTL_CONFIG_SCHEMA[]` table?** Mode-A C1/C2/C3
showed the "schema-row-only, NOT Config-mapped" route (Plan §3 D1
Route 1) is architecturally infeasible — `apply_one` rejects unmapped
keys with `internal_error`, `read_effective` returns default-zero
sentinels for unmapped keys (so `render_toml` writes `0` and
`apply_get_all` reports `0`), and `apply_set` aborts before the
`restart_pending` flag can fire. A parallel schema table would have
required new SPA endpoints + a second mirror parser in webctl (~80 LOC
for cleanliness benefit not yet earned). Route 2 (Config-mapped) costs
~12 LOC of plumbing + a documented "no logic-path reader" invariant
and reuses every existing test pattern.

**Adding a new webctl-owned row** requires the same lockstep updates as
any other Tier-2 row PLUS a docstring note clarifying that no tracker
logic path reads the field. The `int` field on `Config` is a *storage
slot*, not a behavioural input.

Pinned by:

- `tests/test_config.cpp` — issue#12 cases for default wiring, TOML
  round-trip, env override, CLI override, unknown-key rejection.
- `tests/test_config_schema.cpp::TEST_CASE("issue#12: webctl.pose_stream_hz
  + webctl.scan_stream_hz rows present (count went 46 → 48)")` —
  schema row presence + types + default_repr.
- `tests/test_config_apply.cpp::TEST_CASE("apply_set webctl.pose_stream_hz:
  round-trips through render_toml")` — Mode-A C1+C2+C3 RESOLVED
  pin: `apply_set` succeeds, `render_toml` carries the value,
  `apply_get_all` reflects it.
- `tests/test_config_apply.cpp::TEST_CASE("apply_get_all returns 48 keys,
  alphabetical, valid JSON-ish")` — JSON round-trip emits non-zero
  stored values for both webctl rows.

Cross-link: webctl side covers the consumer half via
`godo-webctl/CODEBASE.md` invariant `(ac)`.

### (s) ParallelEvalPool ownership + worker pinning + M1 spirit (issue#11)

`ParallelEvalPool` lives in `src/parallel/` (separate TU from
`cold_writer.cpp`). Its 0..3 worker threads are pinned to CPU
`{0, 1, 2}` at ctor time; CPU 3 is forbidden by the
`project_cpu3_isolation.md` invariant (pool ctor throws
`std::invalid_argument` on CPU 3 in `cpus_to_pin`). The pool uses
`std::mutex` + `std::condition_variable` internally for dispatch-wake;
the cold writer M1 grep-invariant (`[m1-no-mutex]` in
`scripts/build.sh`) is preserved because the mutex is invisible to
`cold_writer.cpp`'s source text (pimpl pattern, line-based grep does
not expand includes).

M1's *spirit* (no blocking on seqlock store) is preserved because
**cold writer is NOT the wait-free publisher — only Thread D is** —
and the pool's dispatch+join blocks complete BEFORE
`target_offset.store()` fires. Pool ctor blocks ≤ 1 s on worker
readiness (M4); on timeout the pool boots in degraded inline-
sequential mode and the cold writer continues at sequential speed
(no Hz lift, no accuracy regression). **Range-proportional join
deadline** (`kJoinTimeoutBaseNs × max(1, range / kJoinTimeoutAnchorN)`,
base 50 ms anchored on N=500): steady-state Live N=500 → 50 ms;
OneShot first-tick / Live re-entry N=5000 → 500 ms (~2.5× safety
over plan §3.7's parallel ~190 ms projection). Flat 50 ms triggered
permanent fallback on the very first N=5000 dispatch (verified
2026-05-06 HIL); the range-proportional rule resolves the §3.7 / §4
self-inconsistency. Timeout flips the `degraded` flag for the rest
of the tracker process; the timeout path drains stragglers before
returning so caller-stack lambdas do not dangle. Worker stacks are
bounded to the default pthread size (8 MB × N) — total
`mlockall(MCL_FUTURE)` cost fits within the `rt_setup.cpp:31` 128 MiB
headroom for N ≤ 3.

**Bit-equality of parallel-vs-sequential `Amcl::step` output** depends
on `weighted_mean()` remaining a sequential summation
(`Amcl::weighted_mean()` body in `amcl.cpp`, pinned by
`tests/test_amcl_parallel_eval.cpp::case 1`). Do NOT parallelize
`weighted_mean` without re-deriving the IEEE 754 ordering proof and
updating the test.

**Diag publisher** samples `pool.snapshot_diag()` at 1 Hz cadence and
stores into `Seqlock<ParallelEvalSnapshot>`; UDS `get_parallel_eval`
reads it (`uds_protocol.md` §C.11).

**TOML key** `amcl.parallel_eval_workers` (Int [1, 3] default 3
Recalibrate-class) maps int → `cpus_to_pin` in `main.cpp`:
- `1 → {}` (inline rollback, bit-equal to pre-issue#11 sequential)
- `2 → {0, 1}`
- `3 → {0, 1, 2}` (production default)

Pinned by:
- `tests/test_parallel_eval_pool.cpp` — 9 unit cases covering
  lifecycle / 5000-particle bit-equality / 10⁵ stress / worker
  affinity / workers=1 fallback / range-proportional deadline timeout
  (Case 6: 100 ms fn over 16-element range → 50 ms base deadline) /
  concurrent-dispatch reject / healthy steady-state diag / CPU 3
  rejection at ctor.
- `tests/test_amcl_parallel_eval.cpp` — 5 integration cases pinning
  bit-equal `Amcl::step` output, `converge_anneal_with_hint` and
  `converge_anneal` equivalence within 1e-9, pool null-safety, and
  empty-cpus rollback bit-equality with the nullptr path.
- `tests/bench_amcl_converge.cpp` — wallclock regression band
  (parallel ≥ 1.5× at N=500 and ≥ 1.2× at N=5000 — CI-noise floors;
  standalone observed 2.86× / 1.76×; production isolcpus=3 expected
  ~3× per Phase-0 projection).
- `tests/test_diag_publisher.cpp` — pump end-to-end with synthetic
  pool getter.
- `tests/test_uds_server.cpp` — `get_parallel_eval` round-trip +
  byte-exact `format_ok_parallel_eval` shape.
- `tests/test_config.cpp` / `tests/test_config_schema.cpp` /
  `tests/test_config_apply.cpp` — TOML / env / CLI plumbing,
  forward-compat (missing key keeps default 3).

### Known scaffolding

- (Removed 2026-04-26 with Wave 2.) `thread_stub_cold_writer` and the
  matching `// TODO(phase-4-2)` breadcrumb were deleted when
  `godo::localization::run_cold_writer` was wired into
  `src/godo_tracker_rt/main.cpp`. The cold path now runs the real AMCL
  state machine (`Idle`/`OneShot` paths real, `Live` stubbed with a
  one-shot log + bounce back to `Idle` for Phase 4-2 D).

---

## Where do I look when…

| Need | Where |
| --- | --- |
| I want to add a second concrete LiDAR source (e.g. official UDP) | Create `src/lidar/lidar_source_udp.{hpp,cpp}` (namespace `godo::lidar`) with a class called `LidarSourceUdp`; do NOT inherit from `LidarSourceRplidar`. Add the .cpp to `src/lidar/CMakeLists.txt`'s `godo_lidar` source list. See invariant (a). |
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

## Change log

Entries are archived weekly under [`CODEBASE/`](./CODEBASE/) (ISO 8601 weeks, KST Mon–Sun). The master keeps invariants + Index only; per-week dated entries live in their archive file.

| Week | Date range (KST) | Archive |
| --- | --- | --- |
| 2026-W19 | 2026-05-04 → 2026-05-10 | [CODEBASE/2026-W19.md](./CODEBASE/2026-W19.md) |
| 2026-W18 | 2026-04-27 → 2026-05-03 | [CODEBASE/2026-W18.md](./CODEBASE/2026-W18.md) |
| 2026-W17 | 2026-04-20 → 2026-04-26 | [CODEBASE/2026-W17.md](./CODEBASE/2026-W17.md) |

---

## Quick reference links

- Project guide: [`CLAUDE.md`](../../CLAUDE.md) — operating rules + agent pipeline + deploy.
- Cross-stack scaffold: [`CODEBASE.md`](../../CODEBASE.md) (root) — module roles + cross-stack data flow.
- Backend design SSOT: [`SYSTEM_DESIGN.md`](../../SYSTEM_DESIGN.md) — RT path / AMCL / FreeD / 59.94 fps design.
- Sibling stacks:
  - Web control plane: [`godo-webctl/CODEBASE.md`](../../godo-webctl/CODEBASE.md) — drives this tracker via UDS at `/run/godo/ctl.sock`.
  - SPA: [`godo-frontend/CODEBASE.md`](../../godo-frontend/CODEBASE.md) — never reaches this binary directly; all traffic transits webctl.
- Project state: [`PROGRESS.md`](../../PROGRESS.md) (English) · [`doc/history.md`](../../doc/history.md) (Korean).
- Most recent shipping: [`CODEBASE/2026-W19.md`](./CODEBASE/2026-W19.md).
- README (build + deploy + smoke check): [`README.md`](./README.md).
- Embedded reliability checklist: [`doc/Embedded_CheckPoint.md`](../../doc/Embedded_CheckPoint.md).
- FreeD wiring (Phase 4-1 reference): [`production/RPi5/doc/freed_wiring.md`](./doc/freed_wiring.md).
