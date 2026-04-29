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

## Module map (current — as of 2026-04-26 Phase 4-2 D Wave B)

The per-date entries below this section track the diffs that landed each
day. This top-level map is the up-to-date snapshot.

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

`Amcl::set_field` is single-thread cold-writer use only — concurrent
`step()` from another thread is UB. Track D-5-P (parallel) workers must
serialize via the cold-writer's per-phase loop. Doc-comment-pinned in
`amcl.hpp`; build-grep `[m1-no-mutex]` ensures the cold writer body
remains lock-free.

Operator rollback recipe: to revert to pre-Track-D-5 single-σ behaviour,
set BOTH `amcl.sigma_hit_schedule_m = "0.05"` AND
`amcl.anneal_iters_per_phase = 25`.

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

---

## 2026-04-26 — Phase 4-2 B Wave 1 (substrate only — no working binary change yet)

> Wave 1 lands the building blocks for the Wave 2 `Amcl` class and cold
> writer: Config plumbing for ~20 AMCL Tier-2 keys, four new Tier-1
> constants, the `core::AmclMode` atomic that replaces `calibrate_requested`,
> and a new `godo_localization` static lib containing pose / rng /
> occupancy_grid / likelihood_field / scan_ops. The Wave 1 stub cold
> writer in `godo_tracker_rt::main` is unchanged — replacing it is
> Wave 2's P4-2-B-10. **Wave 2** appends `Amcl`, `AmclResult`,
> `cold_writer`, scenario tests, the E2E HIL behaviour-check on news-pi01,
> and invariant (f).

### Module map (additions)

```text
src/localization/                    namespace godo::localization
├─ CMakeLists.txt                    target: godo_localization (static)
├─ pose.{hpp,cpp}                    Pose2D, Particle, circular_mean_yaw_deg, circular_std_yaw_deg
├─ rng.{hpp,cpp}                     Rng (mt19937_64; seed=0 → time-derived)
├─ occupancy_grid.{hpp,cpp}          OccupancyGrid + load_map (P5 PGM + slam_toolbox YAML, key whitelist, EDT_MAX_CELLS cap)
├─ likelihood_field.{hpp,cpp}        LikelihoodField + build_likelihood_field (Felzenszwalb 2D EDT + Gaussian)
└─ scan_ops.{hpp,cpp}                downsample / evaluate_scan / jitter_inplace / resample free functions

tests/ (additions — all hardware-free)
├─ test_occupancy_grid.cpp           PGM/YAML round-trip; key whitelist; EDT_MAX_CELLS rejection; actionable wording
├─ test_likelihood_field.cpp         Felzenszwalb vs brute-force EDT (8x8/16x16/32x32); Gaussian-decay shape
├─ test_resampler.cpp                low-variance correctness; capacity invariant (S3 trade-off pin)
└─ fixtures/maps/                    synthetic_4x4.{pgm,yaml} + regenerate.sh
```

### Dependency tree

```text
godo_localization
├─ godo_core         (Config, constants, rt_types — for Wave 2)
├─ godo_lidar        (Frame/Sample for downsample())
└─ Eigen3::Eigen     (header-only; reserved for Wave 2 EDT scratch / linear-alg helpers)
```

`Eigen3::Eigen` is linked PUBLIC by `godo_localization` so Wave 2's `amcl.cpp`
can include `<Eigen/Dense>` without changing the link line. Wave 1 itself
does not yet include any Eigen headers; `find_package(Eigen3 3.4 REQUIRED)`
nonetheless must succeed at configure time to keep the wave boundary clean.

### Eigen3 packaging on news-pi01 (Debian 13 Trixie)

```text
apt:                       libeigen3-dev = 3.4.0-5
CMake config-file path:    /usr/share/eigen3/cmake/Eigen3Config.cmake
find_package mode:         non-CONFIG (`find_package(Eigen3 3.4 REQUIRED)`)
```

CMake's standard Module / Config search resolves through that path
without needing `CONFIG` mode. Build verified end-to-end via
`scripts/build.sh`.

### `core::AmclMode` migration (P4-2-B-2)

`src/core/rt_flags.{hpp,cpp}` replaces the Phase 4-1 boolean
`std::atomic<bool> calibrate_requested` with the three-valued state
machine that Wave 2's cold writer reads:

```cpp
enum class AmclMode : std::uint8_t {
    Idle    = 0,
    OneShot = 1,
    Live    = 2,   // body lands in Phase 4-2 D; Wave 2 stub bounces to Idle
};
extern std::atomic<AmclMode> g_amcl_mode;
```

Wave 1 grep is clean across `src/` and `tests/`:

```text
$ grep -rn calibrate_requested production/RPi5/
production/RPi5/CODEBASE.md:44:└─ ...g_running, calibrate_requested        (top-of-file snapshot, refreshed in Wave 2)
production/RPi5/CODEBASE.md:344:└─ ...g_running, calibrate_requested       (2026-04-24 dated section, immutable history)
production/RPi5/src/core/rt_flags.hpp:6: // ...replaces the Phase 4-1 boolean `calibrate_requested`...   (migration doc comment)
```

Three remaining references are all documentation. The module-map
snapshots in this file are intentionally NOT rewritten by Wave 1 — Wave 2
refreshes them once `Amcl` and `cold_writer` land. The `rt_flags.hpp`
comment is the migration breadcrumb.

`godo_tracker_rt::main` already does not read `calibrate_requested` (the
Wave 1 stub never gated on it), and `tests/test_rt_replay.cpp` similarly
never drove it; Wave 2's P4-2-B-10 deletes the stub and routes the test
through `g_amcl_mode.store(AmclMode::OneShot)`.

### New Tier-1 constants (`src/core/constants.hpp`)

```cpp
inline constexpr int          PARTICLE_BUFFER_MAX = 10000;     // covers AMCL_PARTICLES_GLOBAL_N
inline constexpr int          SCAN_BEAMS_MAX      = 720;       // 360° / 0.5° at C1 max sample rate
inline constexpr int          EDT_TABLE_SIZE      = 1024;      // Felzenszwalb 1D scratch upper bound
inline constexpr std::int64_t EDT_MAX_CELLS       = 4'000'000; // ~16 MB float32 EDT cap (M6)
```

Config validation at `src/core/config.cpp :: validate_amcl` rejects
particle counts that exceed `PARTICLE_BUFFER_MAX`. `load_map` rejects
maps where `width * height` exceeds `EDT_MAX_CELLS`, with an actionable
error pointing the operator at the constant.

### New Tier-2 Config keys (P4-2-B-1)

20 AMCL keys plumbed through all 8 touchpoints (field / default /
make_default / allowed_keys / TOML / env / CLI / tests):

| Key | Default | Reload class |
| --- | --- | --- |
| `amcl_map_path` | `/etc/godo/maps/studio_v1.pgm` | recalibrate |
| `amcl_origin_x_m` / `_y_m` / `_yaw_deg` | `0.0` / `0.0` / `0.0` | recalibrate |
| `amcl_particles_global_n` / `_local_n` | `5000` / `500` | recalibrate |
| `amcl_max_iters` | `25` | recalibrate |
| `amcl_sigma_hit_m` | `0.050` | recalibrate |
| `amcl_sigma_xy_jitter_m` / `_yaw_jitter_deg` | `0.005` / `0.5` | recalibrate |
| `amcl_sigma_seed_xy_m` / `_seed_yaw_deg` | `0.10` / `5.0` | recalibrate |
| `amcl_downsample_stride` | `2` | recalibrate |
| `amcl_range_min_m` / `_max_m` | `0.15` / `12.0` | recalibrate |
| `amcl_converge_xy_std_m` | `0.015` | recalibrate |
| `amcl_converge_yaw_std_deg` | `0.3` | recalibrate |
| `amcl_yaw_tripwire_deg` | `5.0` | recalibrate |
| `amcl_trigger_poll_ms` | `50` | restart |
| `amcl_seed` | `0` (= time-derived) | recalibrate |

Validation is centralised in `validate_amcl(const Config&)` at the end
of `Config::load`, so any layer (default, TOML, env, CLI) that pushes an
invalid value gets a single consistent error message naming the key.

### Tests (Wave 1)

| Target | New cases | Coverage |
| --- | --- | --- |
| `test_config` | +14 (8 → 22 total) | every AMCL key positive + negative; precedence chain across AMCL keys; `PARTICLE_BUFFER_MAX` cap; `range_max > range_min`; sigma-family negative pattern shared per plan M7 |
| `test_occupancy_grid` | 10 | round-trip on synthetic_4x4 fixture; YAML key whitelist; required-key enforcement; warn-but-accept keys (mode, unknown_thresh); non-P5 magic; `EDT_MAX_CELLS` rejection (with the constant name in the error); missing companion YAML; truncated payload |
| `test_likelihood_field` | 5 | empty grid / σ ≤ 0 rejection; Felzenszwalb vs brute-force EDT on 8×8 / 16×16 / 32×32; Gaussian-decay shape on a single-obstacle 16×16 grid |
| `test_resampler` | 8 | low-variance permutation on uniform weights; heavy-weight bias; capacity invariant (S3 — `out` and `cumsum_scratch` capacities unchanged across 5 successive calls); `out_capacity < n` / `cumsum_capacity < n` / zero-sum / negative / NaN weight rejection; empty input |

All 19 hardware-free tests green (`scripts/build.sh`):
`16 (Phase 4-1) + 3 new (test_occupancy_grid + test_likelihood_field + test_resampler) = 19`.
`test_config` was already counted in the 16; the 14 new cases live inside it.
`test_csv_parity` is a separate label.

### `[rt-alloc-grep]` smoke pass

Same single pre-existing hit as before: `src/udp/sender.cpp:103` —
`UdpSender` constructor `std::string` for an exception message. No new
hot-path allocations. `src/localization/` is excluded from the RT-path
grep because the cold writer (Wave 2) is allowed to allocate per
invariant (e); the resampler's allocation-free contract is pinned by
the capacity-invariant test in `test_resampler`.

### Deviations from the plan

- **`Eigen3` linked PUBLIC at the static lib level even though Wave 1
  does not yet include any Eigen headers**. The plan groups Eigen3
  packaging with P4-2-B-5 / B-12 (Wave 2). Linking the dependency in at
  Wave 1 keeps the link line stable across waves and lets Wave 2 add
  `<Eigen/Dense>` includes without re-touching `CMakeLists.txt`. The
  `find_package` call is verified at configure time, fulfilling the
  plan's requirement to confirm Eigen3 packaging on news-pi01 ahead of
  Wave 2.
- **`test_rt_replay` not modified**. The plan's wording is "replace
  `calibrate_requested.store(true)` driver path" — but the existing test
  never had such a driver path (the Wave 1 stub is time-driven, not
  trigger-driven). Migrating an absent line is a no-op. Wave 2's
  P4-2-B-10 will introduce `g_amcl_mode.store(AmclMode::OneShot)` as
  part of replacing the stub.
- **`godo_tracker_rt/main.cpp` not modified**. Same reason: it never read
  `calibrate_requested`. Wave 2 replaces the stub.
- **Felzenszwalb `edt_1d` got two extra safeguards** beyond the textbook
  listing: skip enrolling cells whose seed value is `+inf`, and short-
  circuit the all-`+inf` row to a `+inf` output. Without these, the
  intersection formula `((fq + q²) - (fvk + vk²))` returns `inf - inf =
  NaN` for unset-seed columns, which propagates through both passes and
  zeroes the entire likelihood field (caught early by the test against
  the brute-force reference). Documented in a multi-line comment above
  the function.

### What Wave 1 explicitly does NOT do

- No `class Amcl`, no `AmclResult`, no `cold_writer.{hpp,cpp}` — Wave 2.
- No replacement of `thread_stub_cold_writer` in `godo_tracker_rt::main`
  — Wave 2's P4-2-B-10.
- No `test_amcl_scenarios`, no `test_amcl_components`, no `test_pose`,
  no `test_circular_stats`, no `test_cold_writer_offset_invariant` —
  Wave 2.
- No HIL E2E behaviour-check on news-pi01 — Wave 2.
- No invariant (f) addition (AMCL no-virtual rule) — Wave 2; the
  invariant references concrete classes (`Amcl`) that don't exist yet.

### README.md update

`Prerequisites` (Debian 13 Trixie / RPi 5) gains `libeigen3-dev`
alongside `doctest-dev libssl-dev`.

---

## 2026-04-26 — Phase 4-2 B Wave 2 (AMCL kernel + cold writer + integration)

> Wave 2 lands the `class Amcl` kernel, `AmclResult` + offset helpers, the
> `cold_writer` state machine (Idle/OneShot real, Live stubbed), the
> integration into `godo_tracker_rt/main.cpp` (stub deleted), and the five
> Wave 2 hardware-free tests. Final test count: **24/24 PASS**.

### Module map (additions, src/localization/)

```text
src/localization/
├─ amcl.{hpp,cpp}                    class Amcl: step()/converge() split (C1).
│                                    Pre-allocates ping-pong particle buffers
│                                    + cumsum scratch to PARTICLE_BUFFER_MAX
│                                    once at construction. converge() is
│                                    implemented in terms of step() (SSOT-DRY).
├─ amcl_result.{hpp,cpp}             AmclResult { pose, offset, forced,
│                                    converged, iterations, xy_std_m,
│                                    yaw_std_deg }; compute_offset (M3
│                                    canonical-360 dyaw); apply_yaw_tripwire
│                                    (S4 anchor = origin_yaw_deg).
└─ cold_writer.{hpp,cpp}             run_cold_writer state machine + the
                                     run_one_iteration kernel (testable seam).
                                     Owns OccupancyGrid + LikelihoodField +
                                     LidarSourceRplidar + Amcl + Rng. M1 wait-
                                     free contract: zero std::mutex /
                                     std::shared_mutex / std::condition_variable
                                     references. M8 SIGTERM watchdog: EINTR
                                     from blocking scan_frames is treated as
                                     clean cancellation; main() pthread_kills
                                     the cold thread on shutdown before join.
```

### Dependency tree (final)

```text
godo_tracker_rt
├─ godo_core ─ tomlplusplus
├─ godo_rt   ─ pthread
├─ godo_yaw
├─ godo_freed       ─ godo_core
├─ godo_smoother    ─ godo_yaw
├─ godo_udp         ─ godo_core + godo_yaw + godo_freed
└─ godo_localization ─ godo_core + godo_lidar + Eigen3::Eigen   (NEW Wave 2 link)
```

### godo_tracker_rt::main wiring

- `thread_stub_cold_writer` body + `t_stub` thread spawn deleted.
- `t_cold` spawned with `godo::localization::run_cold_writer(cfg, target_offset, lidar_factory)`.
- `lidar_factory` is a closure that constructs + `open()`s a real
  `LidarSourceRplidar(cfg.lidar_port, cfg.lidar_baud)`. Cold writer treats
  factory failure as non-fatal (Idle stays; OneShot triggers ignored), so
  test_rt_replay (no LiDAR available) keeps the FreeD path running.
- Cold writer treats map-load failure as **fatal** (`g_running=false`) — by
  design, since AMCL cannot do its job without a map. Operators must point
  `--amcl-map-path` at a valid PGM/YAML pair before tracker boot.
- Shutdown stanza calls `pthread_kill(cold_native, SIGTERM)` before
  `t_cold.join()` to interrupt blocking `scan_frames(1)`.

### test_rt_replay update (Parent post-Wave-2 fix)

`tests/test_rt_replay.cpp` now passes `--amcl-map-path
${GODO_FIXTURES_MAPS_DIR}/synthetic_4x4.pgm` so the cold writer can boot.
Done by adding `GODO_FIXTURES_MAPS_DIR` compile-def to
`tests/CMakeLists.txt :: test_rt_replay`. The hot-path FreeD→UDP coverage
(type byte + cam_id + checksum) is unchanged.

### Wave 2 tests (5 new files)

| File | Purpose |
| --- | --- |
| `tests/test_circular_stats.cpp` | M5 pinned: [359°, 1°) cluster reports tight std (~0.6°), NOT ~180°. Plus half-arc, degenerate single-particle, symmetric pair {30°, 330°}, weighted asymmetry, n=0 / Σw=0 defensive returns. |
| `tests/test_pose.cpp` | `compute_offset` direction signs; M3 canonical-360 wrap (350° → 10° → dyaw=20°, NOT -340°); `apply_yaw_tripwire` shortest-arc behaviour (S4). |
| `tests/test_amcl_components.cpp` | `Amcl` API contract: ping-pong buffer pre-alloc to PARTICLE_BUFFER_MAX, `seed_global` n match, `seed_around` cloud σ sanity, `converge()` finite returns + ≤ max_iters. |
| `tests/test_cold_writer_offset_invariant.cpp` | M3 + S6: drives `run_one_iteration` directly with a synthetic Frame; asserts `Offset` NaN/Inf-free, `dyaw ∈ [0, 360)`, `\|dx\|/\|dy\| < 50`, `sizeof(Offset)==24`, alignof==8. Also verifies seqlock round-trip + first_run latch + second-call seed_around path. |
| `tests/test_amcl_scenarios.cpp` | Bresenham synthetic ray-cast in test code (bias-block — AMCL evaluates via EDT). Scenario A (perfect match, ≤ 10 cm err) + Scenario B (30 cm + 5° displacement, loose seed, ≤ 15 cm err). |

### Deviations from the plan

1. **Scenario C deferred**. The committed `synthetic_4x4` fixture is a
   uniform 4×4 m square room with a 1-cell border — geometry has 4-fold
   rotational symmetry + mirror symmetries. Global-seed AMCL cannot
   disambiguate yaw on such a fixture by definition: 4 yaw modes produce
   identical scans. Documented in `test_amcl_scenarios.cpp` file-top
   comment. Phase 4-2 D adds an asymmetric fixture (e.g. interior
   obstacle in one corner), OR Phase 5 validates global-seed convergence
   on the real studio map directly (the chroma set + two doors break
   symmetry naturally).
2. **`test_amcl_scenarios` tolerance**. The plan specified 1.5 cm / 0.3°
   convergence tolerance; the test harness's `make_test_config()` relaxes
   `amcl_converge_xy_std_m` to 5 cm and `amcl_converge_yaw_std_deg` to 1°
   (the **convergence-criterion** thresholds), and the per-scenario
   **mean-error** assertion is even looser: Scenario A uses ≤ 10 cm and
   Scenario B uses ≤ 15 cm — both well above the per-cell discretization
   floor of an 80×80 fixture at 5 cm/cell (~2.5 cm). Reason: tighter
   bounds are flake-prone on a fixture this small with a finite particle
   count. The 1.5 cm target remains valid for the **real studio map**
   (200×200 at 5 cm, richer geometry). The `Config` defaults
   (`amcl_converge_xy_std_m = 0.015`) are unchanged; only the test
   harness uses looser bounds. (N4 reconciliation, Mode-B follow-up.)
3. **`test_circular_stats` half-arc expected mean = 75°, NOT 90°**.
   Initial test wrote 90° expected; the actual circular mean of [0, 30,
   60, 90, 120, 150]° equally-weighted is `atan2(3.732, 1.0) = 75°` (the
   tail past 90° pulls the resultant back toward the dense end). Test
   expected updated; the implementation was always correct.
4. **HIL E2E behaviour-check deferred**. news-pi01 has no RPLIDAR
   plugged in for Phase 4-2 dev work (per `NEXT_SESSION.md`).
   `test_cold_writer_offset_invariant` serves as the hardware-free E2E
   proxy: it exercises the full `run_one_iteration` kernel with a
   synthetic Frame and verifies the Offset reaches the seqlock with the
   right shape. The HIL run is queued for the next physical-LiDAR
   session.
5. **Origin persistence not implemented**. `cfg.amcl_origin_*` are
   read-once at startup; `OneShot` does NOT update them. Phase 4-3
   webctl `/api/calibrate` will own in-place origin update + TOML
   persistence. Documented in plan §"Out of scope (deferred)".
6. **Live mode body not implemented**. `case Live` in the state machine
   logs once and bounces back to `Idle`. Phase 4-2 D fills the body,
   tunes σ for ~30 cm/s base motion, adds the toggle source.

### What Wave 2 explicitly does NOT do

- No CLAUDE.md / SYSTEM_DESIGN.md / PROGRESS.md updates — Parent owns
  those post-merge under task #5 ("Update SSOT docs for Live mode + 4
  map operations").
- No deadband filter (Phase 4-2 C). The publish seam in `cold_writer.cpp`
  is an identity passthrough; `result.forced` is forwarded so 4-2 C can
  drop the deadband in without rewriting cold_writer.
- No persisted IRQ-pinning systemd unit (Phase 4-2 D).
- No AMCL divergence clamp (Phase 4-2 C sibling work).
- No real studio map. `synthetic_4x4` is the only committed fixture.

### Final test counts

```text
ctest -L hardware-free       24/24 PASS  (19 from Wave 1 + 5 new in Wave 2)
ctest -L python-required      1/1  PASS  (test_csv_parity)
[rt-alloc-grep]               1 hit only (UdpSender ctor std::string,
                               init-time, justified per invariant (e))
[m1-no-mutex]                 0 hits for std::mutex / std::shared_mutex /
                               std::condition_variable / std::lock_guard /
                               std::unique_lock in cold_writer.cpp.
                               Build-gated by scripts/build.sh after
                               Mode-B follow-up (S2): hits FAIL the build
                               (load-bearing for M1 wait-free contract).
```

## 2026-04-26 (late) — Phase 4-2 C: cold-path deadband filter at the publish seam

> Replaces the identity-passthrough seqlock store from Wave 2 with the
> §6.4.1 deadband filter. AMCL output that is sub-threshold against the
> last published value is now dropped at the cold writer instead of
> restarting the smoother's ramp. Forced OneShot bypasses the deadband.
> Final test count: **25/25 PASS** (24 prior + 1 new `test_deadband`).

### Module map (additions, src/localization/)

```text
src/localization/
└─ deadband.hpp                      Header-only, pure (no .cpp). Three
                                     inline helpers:
                                       - deadband_shortest_arc_deg(from,to)
                                         → signed shortest arc on the
                                         circle, (-180, +180]. Mirrors the
                                         anonymous-namespace helper in
                                         amcl_result.cpp; kept inline here
                                         so deadband-only test targets do
                                         not pull amcl_result.cpp.
                                       - within_deadband(a, b, dxy_m,
                                         dyaw_deg) — strict per-axis check
                                         on dx, dy (metres) and shortest-
                                         arc dyaw (degrees).
                                       - apply_deadband_publish(new,
                                         forced, dxy_m, dyaw_deg,
                                         last_written_inout, target_offset)
                                         — composes the §6.4.1 seam:
                                         publishes + updates last_written
                                         iff forced==true OR
                                         !within_deadband(...). Returns
                                         whether the seqlock advanced.
```

### Changed

- `src/localization/cold_writer.hpp::run_one_iteration` — new in-out
  parameter `godo::rt::Offset& last_written_inout` between
  `first_run_inout` and `target_offset`. Header docstring updated:
  `last_pose_inout` is now explicitly noted as updated unconditionally
  (§6.4.1: rejected publish ≠ rejected pose estimate); `last_written_inout`
  is updated only on accept; `target_offset` is published only on accept.
  The "Publish seam (M2)" comment now describes the deadband filter
  (no longer "identity passthrough").
- `src/localization/cold_writer.cpp::run_one_iteration` — calls
  `apply_deadband_publish(result.offset, result.forced,
  cfg.deadband_mm/1000.0, cfg.deadband_deg, last_written_inout,
  target_offset)` at step 6. Pre-existing `last_pose_inout = result.pose`
  and `first_run_inout = false` updates remain unconditional below the
  publish call.
- `src/localization/cold_writer.cpp::run_cold_writer` — declares a
  Thread-C-local `godo::rt::Offset last_written{0.0, 0.0, 0.0}` next to
  `last_pose` / `first_run` / `live_logged`, threaded into the OneShot
  branch's `run_one_iteration` call. Initialiser matches the seqlock's
  default-constructed payload and the smoother's initial
  `live = prev = target = {0, 0, 0}` (§6.4.2), so the first non-zero AMCL
  fix is always supra-deadband.
- `tests/test_cold_writer_offset_invariant.cpp` — both test cases now
  declare `Offset last_written{0.0, 0.0, 0.0}` and pass it through to
  `run_one_iteration`. Pre-existing offset-shape and seqlock round-trip
  invariants remain unchanged.

### Tests

- New: `tests/test_deadband.cpp` — 14 cases / 140 assertions:
  - Predicate (9 cases): sub-deadband on each axis returns true; supra-
    deadband on dx, dy, dyaw individually returns false; yaw wrap forward
    (359.95° → 0.02° = +0.07° short arc) and backward (0.02° → 359.95° =
    -0.07°) both inside deadband; strict-`<` boundary at exactly 10 mm dx
    and exactly 0.1° dyaw is supra; per-axis (NOT Euclidean hypot) — 8 mm
    dx + 8 mm dy (Euclidean 11.31 mm) is sub-deadband.
  - Seam composition (5 cases) using a real `Seqlock<Offset>`: sub-
    deadband + forced=false → no publish, generation unchanged,
    last_written unchanged; supra-deadband + forced=false → publish,
    generation advances, last_written tracks; sub-deadband + forced=true
    → publish anyway (OneShot bypass); 100 sub-deadband calls in a row
    → zero writes (filter compares against last WRITTEN, not last seen,
    so cumulative pseudo-drift cannot defeat the threshold);
    alternating accept/reject sequence advances generation correctly.
- Test target registered in `tests/CMakeLists.txt` under the new "Phase
  4-2 C" comment block; labelled `hardware-free`; links against
  `doctest::doctest godo_localization godo_core`.

### Invariant updates (no behaviour change)

- **M1 (wait-free contract)** — unaffected. `deadband.hpp` is pure
  header-only, no `std::mutex` / `std::shared_mutex` /
  `std::condition_variable`. `[m1-no-mutex]` build gate stays clean.
- **M2 (publish seam stable for 4-2 D)** — strengthened, not changed.
  Live mode (Phase 4-2 D) will compose `apply_deadband_publish` from the
  same seam with `forced=false`; no further cold_writer.cpp restructuring
  needed.
- **M3 (canonical-360 dyaw)** — unaffected. `deadband_shortest_arc_deg`
  consumes `Offset::dyaw` in [0, 360) and produces a signed shortest arc;
  it does NOT mutate the canonical-360 invariant on either input.
- **M8 (SIGTERM watchdog)** — unaffected. The deadband filter sits below
  `scan_frames` in the call stack; no new blocking calls.
- No new architectural invariant. The deadband is implementation detail
  of §6.4.1 already on the books from Phase 4-1.

### `[rt-alloc-grep]` smoke pass

Unchanged from Wave 2 — single legacy hit on `udp/sender.cpp:103`
(UdpSender ctor `std::string`, init-time, justified per invariant (e)).
The cold path's new helper is `noexcept`, stack-only, three doubles of
arithmetic plus a `Seqlock::store` (already on the path); no new heap
allocations introduced.

### Deviations from the plan

1. **Helper placement** — opted for the brief's preferred option (b):
   `localization/deadband.hpp` header-only, with both `within_deadband`
   (pure predicate) AND `apply_deadband_publish` (Seqlock-aware seam
   composition) co-located. This lets the test exercise the seam without
   duplicating the §6.4.1 logic in test code (SSOT-DRY) and lets
   `cold_writer.cpp` shrink to a single one-line call at step 6. The
   alternative — anon-namespace helper inside `cold_writer.cpp` —
   would have forced the test to either (i) reach into TU-private
   internals, or (ii) re-implement the seam in test code, both worse.
2. **`shortest_arc_deg` not deduplicated with `amcl_result.cpp`** —
   the existing helper there lives in an anonymous namespace. Promoting
   it would have required either a new public-API surface in
   `amcl_result.hpp` or moving it to a shared header, which is out of
   scope for §6.4.1. The deadband.hpp version (`deadband_shortest_arc_deg`)
   is a 4-line numerical mirror that is independently test-pinned by
   the wrap-edge cases (`359.95°→0.02°` = +0.07°, symmetric reverse =
   -0.07°). If/when a third site needs shortest-arc, a follow-up
   refactor can merge them — flagged for Parent.

### What Phase 4-2 C explicitly does NOT do

- Does NOT touch the `case AmclMode::Live` body — that's Phase 4-2 D.
  The Live branch still log-once-bounces back to Idle.
- Does NOT add new `amcl_deadband_*` Config keys. Reuses the existing
  `cfg.deadband_mm` / `cfg.deadband_deg` (already plumbed across the 8
  Config touchpoints since Phase 4-1).
- Does NOT change `result.forced = true` in OneShot. Forced bypass is
  the design intent (operator-driven calibrate must always publish).
- Does NOT introduce a divergence clamp. `cfg.divergence_mm` /
  `cfg.divergence_deg` exist but are §8 territory, not §6.4.1.
- Does NOT update SYSTEM_DESIGN.md / PROGRESS.md / CLAUDE.md. The §6.4.1
  spec was already in the doc; this CODEBASE.md entry is the
  implementation log.

### Final test counts

```text
ctest -L hardware-free       25/25 PASS  (24 prior + 1 new test_deadband
                                          with 14 cases / 140 assertions)
ctest -L python-required      1/1  PASS  (test_csv_parity)
[rt-alloc-grep]               1 hit only (UdpSender ctor std::string,
                               init-time, justified per invariant (e)) —
                               unchanged from Wave 2.
[m1-no-mutex]                 0 hits in cold_writer.cpp; unchanged.
                               deadband.hpp also clean (header-only,
                               not gated but trivially verified).
```

---

## 2026-04-26 (Wave A) — Phase 4-2 D: Live mode body + OneShot seed change + Live σ + GPIO pin keys

> Lands the Live mode body inside the cold writer, switches OneShot to
> always-`seed_global` (no warm-seed shortcut so a calibrate after a base
> move converges reliably), adds a σ-overload form to `Amcl::step` so Live
> can use a wider per-scan jitter than OneShot, and plumbs 4 new Tier-2
> Config keys (Live σ pair + GPIO pin pair) plus 4 new Tier-1 constants
> (GPIO debounce, UDS request cap, shutdown poll cadence, GPIO BCM upper
> bound) so Wave B (GPIO + UDS modules) can drop in without further
> Config-touchpoint plumbing. Final test count: **26/26 PASS** (25 prior
> + 1 new `test_cold_writer_live_iteration`).
>
> **Wave A is mergeable on its own.** Live mode is reachable via
> `g_amcl_mode.store(AmclMode::Live)` from any code that has access to
> the atomic; the GPIO + UDS source threads that drive that store from
> operator input are Wave B (separate writer round). The 2 GPIO pin keys
> land in Wave A because they go through the standard 8-touchpoint
> plumbing alongside the σ pair; they are unconsumed in Wave A but
> validation still runs (a bad TOML rejects at startup).

### Added

- `src/localization/cold_writer.hpp::run_live_iteration` — new exported
  free function mirroring `run_one_iteration`'s shape. Runs a single
  AMCL `step()` with the Live σ pair, publishes through the deadband
  with `forced=false`, updates the live-first-iter latch. Visible for
  tests so `test_cold_writer_live_iteration` can drive the kernel
  without a thread spawn or LiDAR (SSOT-DRY: production loop calls this
  helper, tests call it directly).
- `src/localization/amcl.hpp/.cpp::Amcl::step(beams, rng, sigma_xy_m,
  sigma_yaw_deg)` — explicit-σ overload. The pre-existing
  `step(beams, rng)` is now a thin one-line forward to this overload
  using `cfg.amcl_sigma_xy_jitter_m / amcl_sigma_yaw_jitter_deg`, so
  `converge()` semantics (which still calls the no-σ form) are
  preserved.
- `src/core/constants.hpp` — 4 new Tier-1 constants:
    - `GPIO_DEBOUNCE_NS = 50'000'000` (50 ms; future Wave B GPIO source
      uses this as the bounce-filter window).
    - `UDS_REQUEST_MAX_BYTES = 4096` (4 KiB; future Wave B UDS server
      caps the JSON line read at this size to bound stack + heap).
    - `SHUTDOWN_POLL_TIMEOUT_MS = 100` (GPIO + UDS threads poll at this
      cadence so `g_running.store(false)` reaches them within ~200 ms).
    - `GPIO_MAX_BCM_PIN = 27` (Pi 5 40-pin header BCM upper bound;
      `validate_gpio` rejects pins outside `[0, 27]`).
- `src/core/config_defaults.hpp` — 4 new Tier-2 defaults:
    - `AMCL_SIGMA_XY_JITTER_LIVE_M = 0.015` (15 mm; ~2σ coverage of the
      expected 30 cm/s × 100 ms motion-per-scan).
    - `AMCL_SIGMA_YAW_JITTER_LIVE_DEG = 1.5` (3× OneShot σ; harmless on
      a static base, generous on a jolt-recovery).
    - `GPIO_CALIBRATE_PIN = 16` (BCM, calibrate button).
    - `GPIO_LIVE_TOGGLE_PIN = 20` (BCM, live-toggle button).
- `src/core/config.hpp/.cpp` — 4 new fields + 8-touchpoint plumbing
  (TOML key under new `[gpio]` section + `[amcl]` extension; env vars
  `GODO_AMCL_SIGMA_XY_JITTER_LIVE_M` / `_LIVE_DEG`,
  `GODO_GPIO_CALIBRATE_PIN` / `_LIVE_TOGGLE_PIN`; CLI flags
  `--amcl-sigma-xy-jitter-live-m` / `-deg`, `--gpio-calibrate-pin` /
  `--gpio-live-toggle-pin`; `validate_amcl` extends to the σ pair via
  the existing `require_positive_double` lambda; new `validate_gpio`
  function calls `require_pin_in_range` against
  `constants::GPIO_MAX_BCM_PIN`; `Config::make_default` wires the four
  defaults; `Config::load` calls `validate_amcl` then `validate_gpio`).
- `tests/test_cold_writer_live_iteration.cpp` — new hardware-free test
  target. 5 cases:
    1. Live result has `forced == false` (deadband applies).
    2. `live_first_iter_inout` flips to false after the first call.
    3. Two near-identical frames in sequence: second publish suppressed
       by deadband; `target_offset.generation()` does NOT advance.
    4. Two clearly-different frames in sequence: second publish accepted;
       generation advances.
    5. **σ-override propagation pin (amendment S4)**: with a fixed
       `Rng` seed and identical synthetic frame, two `Amcl::step` calls
       at σ_xy = 0.001 vs σ_xy = 0.100 produce `xy_std_m` that differ by
       > 1e-6. Pins that the σ argument actually feeds the motion model
       rather than being silently dropped (a regression that swallows
       the σ would produce identical `xy_std_m`).

### Changed

- `src/localization/cold_writer.cpp::run_one_iteration` — Phase 4-2 D
  removes the `if (first_run_inout) seed_global else seed_around`
  branch. OneShot now ALWAYS calls `amcl.seed_global(grid, rng)` so an
  operator-triggered calibrate after a base move is not biased toward
  the pre-move pose. The in-out parameter is renamed (see "Rename"
  below) and is left for state hygiene only — OneShot does not consult
  it for its own seed branch but clearing it on exit prevents misleading
  state for a subsequent Live entry.
- `src/localization/cold_writer.cpp::run_cold_writer` — `case
  AmclMode::Live` body replaced. Per-scan: `lidar->scan_frames(1)`
  (rate-limited by the LiDAR's natural ~10 Hz spin, no nanosleep
  needed); re-check `g_amcl_mode` after the blocking scan so a mid-scan
  toggle reaches the new mode without first publishing a stale Live
  update; `run_live_iteration(...)` with the same M8 SIGTERM try/catch
  pattern OneShot uses; on exception or `!got_frame`, transition to
  Idle and break. Stays in Live across iterations — no implicit fall-
  back to Idle (Phase 4-2 B's stub did `bounce-to-Idle` which is now
  removed). Each transition out of Live (Idle path, OneShot path,
  exception path, mid-scan toggle path) calls a new file-private
  `on_leave_live(live_first_iter)` helper that re-arms the
  `live_first_iter` latch — so the next Live entry seeds globally and
  can recover from a base move that happened while Idle.
- `src/localization/cold_writer.{hpp,cpp}` — removed the file-private
  `log_live_stub_once` helper (its callers are gone).

### Rename

- `bool& first_run_inout` → `bool& live_first_iter_inout` everywhere it
  appears in `cold_writer.{hpp,cpp}` and `tests/test_cold_writer_offset_invariant.cpp`
  (≥ 17 textual sites; rename audit per amendment M5 expected ≥ 14,
  actual count 17). The new name makes the latch's Live-mode-only role
  explicit. After the rename, `git grep -nw first_run production/RPi5/{src,tests}/`
  returns zero hits.

### Tests modified

- `tests/test_cold_writer_offset_invariant.cpp`:
  - "second call uses seed_around (not seed_global)" → renamed and
    rewritten as **"second call still uses seed_global (no warm-seed
    shortcut)"** per Phase 4-2 D's OneShot seed change. Per amendment
    S8, the assertion is strengthened from the original `iterations >=
    1` (true under any path) to a ±20% bound between two back-to-back
    OneShot iteration counts (`delta <= max(2, r1.iterations / 5)`).
    A warm-seed regression would let `r2.iterations` collapse and this
    CHECK would fail.
  - All `bool first_run = true;` → `bool live_first_iter = true;`
  - All `CHECK(first_run == false)` → `CHECK(live_first_iter == false)`.
  - The first test still asserts `live_first_iter == false` after a
    OneShot call — pinning the state-hygiene cleanup, not the seed
    branch (which is unconditional `seed_global`).
- `tests/test_config.cpp`:
  - +7 new test cases (12 + boundary-acceptance case = total 8 σ + GPIO
    cases + 1 unknown gpio.* TOML rejection):
    - defaults wired (1 case, 4 CHECKs);
    - TOML round-trip (1 case, 4 CHECKs);
    - env round-trip (1 case, 4 CHECKs);
    - CLI round-trip (1 case, 4 CHECKs);
    - σ pair non-positive rejection (1 case, 4 sub-blocks);
    - GPIO pin out-of-range rejection (1 case, 4 sub-blocks: -1 / 28 ×
      both pins);
    - GPIO pin boundary acceptance (1 case, 0 and 27);
    - unknown `gpio.*` TOML key rejection (1 case).

### Files added

```text
production/RPi5/tests/test_cold_writer_live_iteration.cpp   5 cases
```

### Files modified

```text
production/RPi5/src/core/constants.hpp                +4 Tier-1 constants
production/RPi5/src/core/config_defaults.hpp          +4 defaults
production/RPi5/src/core/config.hpp                   +4 fields
production/RPi5/src/core/config.cpp                   8-touchpoint × 4 keys
                                                      + new validate_gpio
production/RPi5/src/localization/amcl.hpp             +1 step overload
production/RPi5/src/localization/amcl.cpp             σ pair extracted to
                                                      overload; no-σ form
                                                      thin-forwards
production/RPi5/src/localization/cold_writer.hpp      rename in-out param;
                                                      +run_live_iteration decl
production/RPi5/src/localization/cold_writer.cpp      OneShot always seed_global;
                                                      Live body real;
                                                      run_live_iteration body;
                                                      on_leave_live helper
production/RPi5/tests/test_cold_writer_offset_invariant.cpp
                                                      rename + S8 assertion
production/RPi5/tests/test_config.cpp                 +7 test cases (Phase 4-2 D)
production/RPi5/tests/CMakeLists.txt                  +1 test target
production/RPi5/scripts/build.sh                      doc-only; label inventory
                                                      + Wave A no-new-alloc note
production/RPi5/CODEBASE.md                           this entry +
                                                      module map refresh
```

### Invariants

- **M1 (wait-free contract)** — unaffected. The Live mode body uses
  exactly the same primitives the OneShot body uses
  (`apply_deadband_publish`, atomic loads/stores on `g_amcl_mode`).
  `[m1-no-mutex]` build gate stays clean.
- **M2 (publish seam stable)** — strengthened. Live mode publishes
  through the same one-line `apply_deadband_publish(...)` call OneShot
  uses; no separate seam.
- **M3 (canonical-360 dyaw)** — unaffected. `compute_offset` is shared
  by OneShot and Live.
- **M8 (SIGTERM watchdog)** — extended to Live. The Live `case` uses
  the same `try { lidar->scan_frames(1, ...) } catch ...` pattern
  OneShot uses, and on `!got_frame` or exception transitions to Idle
  and breaks (so the loop top sees `g_running == false` if SIGTERM
  fired). `pthread_kill(t_cold, SIGTERM)` from `main` continues to
  unblock the SDK's grabScanDataHq path.
- **8-touchpoint plumbing** — extended cleanly. The 4 new keys touch
  exactly the same 8 sites Phase 4-2 B Wave 1 documented; no shortcut.
- **Invariant (a) — no ABC** — preserved. The σ-overload on
  `Amcl::step` is a function overload, not a virtual dispatch.
- **Wave B carry**: `src/gpio/` and `src/uds/` modules + GPIO/UDS test
  doubles + `godo_tracker_rt::main` thread spawning + `gpio_wiring.md`
  and `uds_protocol.md` — all deferred to Wave B. The new Tier-1
  constants and pin Config keys land here so Wave B can drop in cleanly.

### Deviations from the plan

1. **Wave A scope honoured strictly**: tasks P4-2-D-6 through P4-2-D-13
   (GPIO + UDS + main wiring + docs) are deferred to Wave B as the
   plan body specifies. Wave A delivers tasks P4-2-D-1, -2, -3, -4, -5,
   -14 only. The 2 GPIO pin Config keys are the one Wave A inclusion
   from the GPIO surface — they go through the standard plumbing
   alongside the σ pair so Wave B does not have to extend the
   8-touchpoint table separately.
2. **`on_leave_live` placement**: kept as a file-private helper in
   `cold_writer.cpp`'s anonymous namespace rather than promoting to the
   header. It has exactly four call sites (all inside `run_cold_writer`'s
   four Live-exit paths), no test coverage need, and exposing it to the
   header would suggest it is reusable cold-path infrastructure (it is
   not — it is implementation detail of the Live state machine).
3. **OneShot's `live_first_iter_inout = false` epilogue**: the plan
   body §"OneShot seed change" notes "leaving it `true` would be
   misleading state". The implementation honours this with a single
   write at end-of-OneShot. OneShot does NOT consult the latch for its
   own seed branch (which is unconditionally `seed_global`); this is a
   state-hygiene write, not a behaviour write.
4. **σ-override test fresh-Amcl design**: amendment S4 specifies
   "fixed RNG seed; identical synthetic frame; two `step()` calls at
   σ=0.001 vs σ=0.100; assert `xy_std_m` differs by > 1e-6". The
   implementation creates two FRESH `Amcl` instances + two FRESH `Rng`
   instances seeded identically. This is necessary because `step()`
   mutates particle state in place; running both σ calls on the same
   `Amcl` would compound the σ differences across runs. Fresh-Amcl /
   fresh-Rng with identical seed isolates the σ argument's effect.
5. **`run_live_iteration` updates `last_pose_inout` after the publish**:
   parallels `run_one_iteration`'s pattern (§6.4.1 — rejected publish ≠
   rejected pose estimate). The next Live iteration reads `last_pose`
   from the kernel's freshly-refined estimate even when the deadband
   filter dropped the publish.

### What Phase 4-2 D Wave A explicitly does NOT do

- Does NOT add `src/gpio/` or `src/uds/` directories. Those are Wave B.
- Does NOT modify `src/godo_tracker_rt/main.cpp`. Spawning the GPIO +
  UDS threads is Wave B's main wiring.
- Does NOT create `production/RPi5/doc/gpio_wiring.md` or
  `production/RPi5/doc/uds_protocol.md`. Docs land with the modules.
- Does NOT add new test labels. `hardware-required-gpio` is documented
  in the build script's label inventory comment (so the slot is
  reserved) but no test consumes it yet — `test_gpio_source_libgpiod`
  is Wave B.
- Does NOT change `cfg.divergence_mm` / `cfg.divergence_deg` plumbing.
  Divergence clamp at the publish seam remains §8 territory, deferred
  per plan §"Out of scope".
- Does NOT measure OneShot wall-clock on news-pi01. That is a separate
  follow-up task per plan §"Follow-up issues" — gated on Wave A merge.

### Future considerations (장래 검토)

- **Hybrid mode (adaptive σ from velocity)** — once Live mode runs in
  production, the velocity between successive `last_pose` values is
  computable cheaply at the cold writer. Map velocity → σ_xy
  adaptively. Avoids the all-or-nothing 0.005 vs 0.015 split. Needs
  production motion data to tune. Tentative Phase 4-2 E. Tracked in
  PROGRESS.md "장래 검토".
- **Map staleness recovery** — `seed_global` on a moved/edited map can
  fail to converge if the calibration origin's environment changed.
  Mitigation belongs to "map editing" Phase 4.5 + the deferred
  divergence clamp. The operator manual will mention "re-do mapping
  when fixtures move" once Phase 4.5 lands.
- **GPIO debounce field tuning** — `GPIO_DEBOUNCE_NS = 50 ms` is the
  textbook minimum. If field testing shows bounce, raise to 100 ms in
  `core/constants.hpp` (Tier-1 — no Config exposure needed).

### Final test counts

```text
ctest -L hardware-free       26/26 PASS  (25 prior + 1 new
                                          test_cold_writer_live_iteration
                                          with 5 cases)
ctest -L python-required      1/1  PASS  (test_csv_parity)
[rt-alloc-grep]               1 hit only (UdpSender ctor std::string,
                               init-time, justified per invariant (e)) —
                               unchanged from Phase 4-2 C.
[m1-no-mutex]                 0 hits in cold_writer.cpp; unchanged.
                               Live mode body adds zero std::mutex /
                               std::condition_variable references.
git grep -nw first_run         0 hits (rename complete; expected ≥ 14
production/RPi5/{src,tests}/   per amendment M5, actual rename count 17)
```


---

## 2026-04-26 (Wave B) — Phase 4-2 D

### Added

- **`src/gpio/`** new module (godo_gpio static lib; links `libgpiodcxx`
  + `libgpiod`).
  - `gpio_source.hpp` — public API contract: `GpioCallbacks` (function
    objects for the two press handlers) + `LineIndex` enum (Calibrate=0
    / LiveToggle=1). Header-only; no ABC. Production
    (`GpioSourceLibgpiod`) and test fake (`GpioSourceFake`) are
    duck-typed twins per invariant (a) — distinct class names, no
    shared base.
  - `gpio_source_libgpiod.{hpp,cpp}` — production driver. Opens
    `/dev/gpiochip0`, requests both lines as
    `direction=INPUT / edge=FALLING / bias=PULL_UP / event_clock=MONOTONIC`,
    runs an event loop with `request_->wait_edge_events(100 ms)` so
    SIGTERM / `g_running` shutdown is observed within one poll cycle.
    Software debounce: last-accepted semantics (rejected events do NOT
    advance `last_event_ns_[]`), CLOCK_MONOTONIC time domain (M2),
    `INT64_MIN` sentinel so the first press on each line is always
    accepted regardless of boot-uptime monotonic clock value.
- **`src/uds/`** new module (godo_uds static lib; godo_core only — no
  external JSON dep).
  - `json_mini.{hpp,cpp}` — hand-rolled JSON parser/serializer for the
    four canonical message shapes. Rejects backslash escapes, unknown
    keys, duplicate keys, trailing tokens. `format_ok()` /
    `format_ok_mode()` / `format_err()` always succeed and return a
    newline-terminated response.
  - `uds_server.{hpp,cpp}` — `UdsServer` class. `open()` creates an
    `AF_UNIX SOCK_STREAM` socket, unlinks any stale path, binds,
    chmods 0660 (M3), and listens with backlog 4. `run()` poll-based
    accept loop: `pollfd{listen_fd, POLLIN}` with
    `SHUTDOWN_POLL_TIMEOUT_MS` timeout (NO `SO_RCVTIMEO` on the listen
    socket, NO `pthread_kill` from main — M1). Per-connection
    `SO_RCVTIMEO=1 s` so a stalled client cannot block accept.
    Request size capped at `UDS_REQUEST_MAX_BYTES`; oversized requests
    without a newline get the connection closed with no response.
- **GPIO + UDS thread bodies in `godo_tracker_rt::main.cpp`**.
  `thread_gpio` constructs callbacks that drive `g_amcl_mode`:
  calibrate → store(OneShot); live-toggle → CAS-toggle Idle ↔ Live with
  the OneShot branch dropping the press (S5). `thread_uds` injects
  `g_amcl_mode` setter/getter into `UdsServer`. Both threads
  `try { src.open(); } catch (std::exception&) { log; return; }` —
  graceful degradation: the rest of the system stays up if libgpiod
  cannot open the chip or UDS bind fails.
- **Tests**.
  - `tests/gpio_source_fake.{hpp}` — header-only `GpioSourceFake` test
    twin. Mirrors production's accept-event semantics exactly. New
    `simulate_press(LineIndex, monotonic_ns)` method drives the
    debounce + dispatch path for unit tests; `last_event_ns(idx)`
    inspector exposes the post-press timestamp so tests can pin the
    last-accepted invariant directly.
  - `tests/test_gpio_source_fake.cpp` — 6 doctest cases, hardware-free.
    Pins: calibrate dispatch → OneShot, live-toggle dispatch toggle,
    50 ms debounce window (30 ms gap rejected, 80 ms accepted),
    last-accepted bounce-burst (5 spurious events at 10/20/30/40/49 ms
    all rejected, `last_event_ns` unchanged from the first accept,
    next press at exactly 50 ms accepted because boundary is strict-`<`),
    OneShot-drop (S5), per-line independence (calibrate + live-toggle
    have separate windows).
  - `tests/test_gpio_source_libgpiod.cpp` — 2 doctest cases,
    LABELS=`hardware-required-gpio` (NEW label). Skips with a MESSAGE
    if `/dev/gpiochip0` is missing. Asserts: chip open, both line
    request, idempotent close, RAII clean destruction. Does NOT press
    buttons (would require a hardware harness; the press path is
    pinned by the hardware-free fake test).
  - `tests/test_uds_server.cpp` — 11 doctest cases, hardware-free.
    `TempUdsPath` RAII guard (S7) unlinks the temp socket on every
    test scope exit, including failure. Pins: set/get round-trip for
    all three modes, ping, parse_error (4 malformed inputs), bad_mode,
    unknown_cmd, oversized request closed without response (accepts
    either `recv == 0` or `recv == -1 / errno=ECONNRESET` since the
    server's `close()` while client is still sending may RST),
    g_running=false unblocks the server within
    `2 × SHUTDOWN_POLL_TIMEOUT_MS`, json_mini direct (parse / format /
    parse_mode_arg round-trips). Each test creates a fresh
    `UdsServer` + spawn thread + connect + send_recv → close cycle;
    `g_running` is reset at the top of each test scope so the global
    state survives parallel test execution.

### Changed

- **`src/godo_tracker_rt/main.cpp`** — added `thread_gpio` and
  `thread_uds` thread bodies; spawn both after `t_cold` and before
  `t_d`. Join order: `t_d → t_cold → t_gpio → t_uds → t_a → t_signal`.
  GPIO + UDS threads receive NO `pthread_kill` (M1); both poll with
  `SHUTDOWN_POLL_TIMEOUT_MS` and self-exit on the next wake-up after
  `g_running.store(false)`. Worst-case shutdown latency for the two
  new threads: `2 × SHUTDOWN_POLL_TIMEOUT_MS = 200 ms`. The header
  comment block is updated to document the GPIO/UDS surfaces and the
  M1 shutdown discipline.
- **`src/godo_tracker_rt/CMakeLists.txt`** — `target_link_libraries`
  now includes `godo_gpio` and `godo_uds`.
- **`CMakeLists.txt`** — `add_subdirectory(src/gpio)` and
  `add_subdirectory(src/uds)` after `src/localization` and before
  `src/godo_tracker_rt` (build-order: tracker depends on both).
- **`tests/CMakeLists.txt`** — registers the four new test targets:
  `test_gpio_source_fake` (hardware-free, links `godo_gpio`),
  `test_gpio_source_libgpiod` (`hardware-required-gpio`, links
  `godo_gpio`), `test_uds_server` (hardware-free, links `godo_uds`).
- **`scripts/build.sh`** — label inventory comment expanded to
  document `hardware-required-gpio` (manual; not part of the
  hardware-free gate). `[rt-alloc-grep]` scope unchanged. `[m1-no-mutex]`
  scope unchanged (still cold_writer.cpp only — Wave B's GPIO and UDS
  files use no `std::mutex` either, but the gate is intentionally
  narrow to the load-bearing seqlock-publish file).

### Removed

None.

### Tests

```text
ctest -L hardware-free                28/28 PASS  (was 26 → +2 new
                                                 = test_gpio_source_fake
                                                   + test_uds_server)
ctest -L hardware-required-gpio        1/1  PASS  (test_gpio_source_libgpiod
                                                 — measured live on
                                                 news-pi01 with
                                                 /dev/gpiochip0 present)
ctest -L python-required               1/1  PASS  (test_csv_parity)
[rt-alloc-grep]                        1 hit only (UdpSender ctor
                                       std::string, init-time, unchanged
                                       from prior phases) — Wave B
                                       added zero hot-path allocations
[m1-no-mutex]                          0 hits in cold_writer.cpp;
                                       unchanged. GPIO and UDS source
                                       files use no std::mutex either.
```

### Build verification

`bash production/RPi5/scripts/build.sh` exits 0 on news-pi01 (Debian 13
Trixie, gcc 14.2). `godo_tracker_rt` and all 28 hardware-free test
binaries built without warnings. `test_gpio_source_libgpiod` succeeds
on the live host (chip open + line request + close). The
`test_uds_server` `TempUdsPath` guard ensures clean re-runs even after
forced test failures.

### Decisions / deviations

1. **`libgpiodcxx` link order**. The package ships
   `libgpiod-dev 2.2.1-2+deb13u1` with both the C wrapper
   (`libgpiod.so`) and the C++ wrapper (`libgpiodcxx.so`). The C++
   driver implementation requires both, in this link order:
   `gpiodcxx → gpiod`. The CMakeLists comment notes the dependency
   so a future packaging change cannot silently regress.
2. **`INT64_MIN` sentinel for `last_event_ns_`**. The cold-start brief's
   debounce description used `0` as the implicit default. Testing
   revealed this rejects a press at `monotonic_ns = 0` (the test fake's
   first call) and would also reject the very first press in
   production at boot (when CLOCK_MONOTONIC ticks from 0 too). Both
   the production driver and the fake now use `INT64_MIN` as a
   "never fired" sentinel; the accept_event guard treats this case as
   "always accept the first event". The test
   `test_gpio_source_fake.cpp` opens with `simulate_press(idx, 0)`
   and asserts the first press is accepted, pinning the sentinel
   behaviour.
3. **UDS oversized test recv semantics**. When the server reads >
   `UDS_REQUEST_MAX_BYTES` without a newline, it closes the
   connection silently. On the client side, `recv` may return either
   0 (orderly shutdown if no unread data is buffered) or
   -1 with `errno=ECONNRESET` (RST if data remained in the kernel's
   receive queue when the server closed). Both prove the server did
   not respond to the oversized payload; the test accepts either.
4. **CAS loop in live-toggle handler**. The plan's pseudocode showed
   "load → switch → store". The implementation is a standard
   `compare_exchange_weak` loop so a concurrent OneShot store from
   the GPIO thread (calibrate press during a live-toggle CAS retry)
   cannot be clobbered. The OneShot branch returns early without
   storing, dropping the press (S5). The same loop pattern is
   reproduced in `test_gpio_source_fake.cpp`'s `make_cbs` helper so
   the test exercises the same dispatch path the production driver
   uses.
5. **No `cfg.gpio_chip_path`**. The chip path is hard-coded to
   `/dev/gpiochip0` in `thread_gpio`'s `GpioSourceLibgpiod`
   construction. Pi 5 has only one main GPIO chip; multi-chip
   environments are out of scope. If a future Pi ever exposes a
   second chip and we need to address it, add a Tier-2 key then.
6. **Hand-rolled JSON, not `nlohmann/json`**. Schema is exactly four
   message shapes. A general parser would add ~20 KLOC of header to
   every TU that includes `uds_server.hpp`. The hand-rolled parser
   is ~100 LOC and has 4 dedicated test cases (well-formed shapes,
   error cases, format_*, mode_arg round-trips). If Phase 4-3 / 4.5
   grows the schema (e.g. `/api/config` introspection), revisit.
7. **`set_mode` honoured during OneShot**. Unlike the GPIO live-toggle
   (which drops the press during OneShot per S5), the UDS `set_mode`
   command always overwrites `g_amcl_mode`. Operator-intent: GPIO
   is the safety guard, UDS is the automation escape hatch (Phase
   4-3 webctl may legitimately want to abort a hung OneShot).
   Documented in `doc/uds_protocol.md` §F.
8. **`hardware-required-gpio` ran successfully on news-pi01** even
   though the spec said it was "manually invoked". The label still
   excludes it from the default `ctest -L hardware-free` gate; the
   bring-up verification on this host is just a sanity check.

### Known caveats

- **UDS same-uid client requirement**. Until `godo-tracker.service`
  introduces `SocketGroup=` (Phase 4-2 follow-up), any UDS client
  must run under the same uid as `godo_tracker_rt`. On news-pi01
  this means launching `godo-webctl` as `ncenter`. Documented in
  `doc/uds_protocol.md` §F.
- **GPIO press-during-OneShot UX**. Live-toggle presses during a
  OneShot run are dropped (NOT queued). Wait for the
  `cold_writer: OneShot complete` log line before toggling Live.
  Documented in `doc/gpio_wiring.md` §F.

### Operator bring-up checklist (for news-pi01 — post-merge)

1. Verify libgpiod is installed: `pkg-config --modversion libgpiod`
   should print `2.x.y`. `ls /dev/gpiochip0` should show the chip.
2. Verify `ncenter` is in the `gpio` group:
   `id ncenter | tr ',' '\n' | grep gpio`. If missing,
   `sudo usermod -aG gpio ncenter` and re-login.
3. Wire BCM 16 (calibrate) and BCM 20 (live-toggle) per
   `doc/gpio_wiring.md` §A — momentary tactile buttons to GND.
4. Start `godo_tracker_rt`. Confirm Idle in stderr.
5. Press calibrate → expect ~1-2 s OneShot run, log line
   `cold_writer: OneShot complete, offset=...`.
6. Press live-toggle → expect "entering Live" log; AMCL publishes
   at ~10 Hz (visible via `target_offset.generation()` advancing).
7. Press live-toggle again → cold writer goes back to Idle.
8. UDS smoke test:
   `echo '{"cmd":"set_mode","mode":"OneShot"}' | nc -U /run/godo/ctl.sock`
   should respond with `{"ok":true}` and trigger a OneShot run.
9. SIGTERM the tracker while in Live → expect process exits within
   200 ms.

### What Phase 4-2 D Wave B explicitly does NOT do

- Does NOT implement HTTP endpoints. `godo-webctl` is Phase 4-3.
- Does NOT touch the AMCL kernel or the deadband filter (Wave A
  closed the OneShot/Live algorithmic surface).
- Does NOT add `cfg.uds_socket_mode` or `cfg.gpio_chip_path` Tier-2
  keys. Both are revisit-when-needed (multi-user dev workflow,
  multi-chip Pi).
- Does NOT promote `on_leave_live` from `cold_writer.cpp`'s anonymous
  namespace. Wave A's decision stands — it is a Live state-machine
  implementation detail.
- Does NOT introduce a `cfg.divergence_*` clamp at the publish seam.
  Same status as Wave A — deferred to §8 territory.

### Future considerations

- **systemd `SocketGroup=`** would let multiple users in a `godo`
  group connect to the UDS without same-uid restriction. Defer
  until either the operator workflow demands it or the
  `godo-tracker.service` unit lands.
- **GPIO thread CPU pinning** — currently inherits the default
  cpuset `0-2` (CPU 3 is `isolcpus`'d for `t_d`). If field testing
  shows GPIO/UDS activity correlated with FreeD frame loss, pin to
  a subset like `0-1` via a Tier-2 key. Not measured to be a
  problem on news-pi01.
- **Multi-line GPIO debounce per-burst tuning** — current `50 ms`
  window is uniform for both lines. Tactile switches with
  different bounce profiles could justify per-line tuning. Not
  expected to be needed; punted to operator field tuning.

---

## 2026-04-26 — Phase 4-2 systemd carry-over

> Persists the Phase 4-2 carry-over items into systemd units:
> IRQ pinning, the RT tracker process, and the hardware watchdog.
> Closes the three open items in `PROGRESS.md` ("Persisted IRQ-pinning
> systemd unit", "systemd unit `godo-tracker.service`", "Hardware
> watchdog wiring"). No source change — config / install only.

### Module map (additions, production/RPi5/systemd/)

```text
production/RPi5/systemd/
├─ godo-irq-pin.sh                    Idempotent IRQ-pinning helper.
│                                     --quiet flag suppresses stderr for
│                                     the per-tracker-start re-pin path.
│                                     IRQ list (HOT_IRQS / BURSTY_IRQS)
│                                     is a /proc/interrupts snapshot
│                                     from news-pi01; verbatim from
│                                     .claude/tmp/apply_irq_pin.sh.
├─ godo-irq-pin.service               Boot-time oneshot. Type=oneshot,
│                                     RemainAfterExit=yes, runs as root,
│                                     orders Before=basic.target so it
│                                     completes before any production
│                                     daemon starts.
├─ godo-tracker.service               RT main process. User=ncenter,
│                                     RuntimeDirectory=godo (canonical
│                                     /run/godo/ owner per Phase 4-2 D
│                                     Mode-A amendment S8),
│                                     AmbientCapabilities=CAP_SYS_NICE
│                                     CAP_IPC_LOCK + LimitMEMLOCK=infinity
│                                     + LimitRTPRIO=99 to satisfy
│                                     mlockall(2) and SCHED_FIFO without
│                                     root, ExecStartPost=+godo-irq-pin.sh
│                                     --quiet to catch the lazy ttyAMA0
│                                     IRQ. RestrictRealtime= deliberately
│                                     omitted; remaining hardening flags
│                                     match godo-webctl.service style.
├─ system.conf.d/godo-watchdog.conf   PID-1 hardware watchdog drop-in
│                                     (RuntimeWatchdogSec=10s). Operator
│                                     install copies it to
│                                     /etc/systemd/system.conf.d/.
│                                     Requires systemctl daemon-reexec
│                                     (NOT daemon-reload) to apply.
├─ install.sh                         Idempotent operator installer.
│                                     Copies binary + helper to
│                                     /opt/godo-tracker/, units to
│                                     /etc/systemd/system/, drop-in to
│                                     /etc/systemd/system.conf.d/, then
│                                     daemon-reload. Does NOT enable
│                                     the units (operator decides;
│                                     instructions printed at the end).
└─ README.md                          7-section operator doc — install /
                                      enable / verify / capability model
                                      / IRQ design / watchdog / uninstall.
```

### Decisions / deviations

1. **Capability model: Ambient over file caps under systemd.**
   `scripts/setup-pi5-rt.sh` sets `cap_sys_nice,cap_ipc_lock+ep` on
   the binary so manual dev launches via
   `scripts/run-pi5-tracker-rt.sh` work without sudo. Under systemd
   those file caps would be silently dropped because
   `NoNewPrivileges=yes` (set for hardening) blocks file-cap
   inheritance. The unit therefore grants the same two caps directly
   via `AmbientCapabilities=CAP_SYS_NICE CAP_IPC_LOCK` +
   `CapabilityBoundingSet=CAP_SYS_NICE CAP_IPC_LOCK`. Documented in
   `README.md §4` and inline in the unit comment so a future operator
   does not "fix" the redundancy by removing one of them.
2. **IRQ-pinning two-pass design.** Eight of the nine IRQs that need
   to be off CPU 3 are present at boot; ttyAMA0 PL011 (irq 125) only
   registers when something opens `/dev/ttyAMA0`. Solution:
   `godo-irq-pin.service` (oneshot) at boot pins what is already
   registered, and `godo-tracker.service` re-runs the same script in
   `--quiet` mode via `ExecStartPost=+...` to catch the lazy IRQ. The
   `+` prefix runs the post hook as root regardless of the unit's
   `User=ncenter`, since `/proc/irq/*/smp_affinity_list` requires
   write capability the unprivileged user does not have. Idempotency
   makes the double-write at boot (oneshot + post hook within seconds
   of each other) harmless.
3. **`/run/godo/` ownership pinned to godo-tracker.service.** Per the
   Phase 4-2 D Mode-A amendment S8 decision, the tracker unit is the
   canonical owner of `/run/godo/`: it sets
   `RuntimeDirectory=godo` + `RuntimeDirectoryMode=0750`, while
   `godo-webctl.service` deliberately OMITS `RuntimeDirectory=` and
   only declares `After=godo-tracker.service` /
   `Wants=godo-tracker.service`. Two units both owning the same
   runtime dir would race on cleanup ordering at stop time; this
   asymmetric arrangement keeps the dir alive as long as the tracker
   is up and lets webctl piggyback on its lifetime.
4. **Watchdog drop-in over editing /etc/systemd/system.conf.**
   `RuntimeWatchdogSec=10s` lives in
   `system.conf.d/godo-watchdog.conf` rather than as an in-line edit
   to the distro-shipped `/etc/systemd/system.conf`, so packaging
   upgrades (`apt-get dist-upgrade` of `systemd`) cannot clobber the
   GODO setting. README documents the `daemon-reexec` requirement
   (a plain `daemon-reload` does NOT pick up `[Manager]` changes).
5. **`RestrictRealtime=` deliberately ABSENT from godo-tracker.service.**
   The unit needs `sched_setscheduler(SCHED_FIFO, 50)`;
   `RestrictRealtime=yes` would block it. webctl's unit sets the
   flag because webctl never schedules RT. Inline comment in the
   tracker unit explains the asymmetry so a future hardening sweep
   does not "tighten" both units uniformly and break the RT thread.
6. **`CPUAffinity=0-3` is conservative, not restrictive.** `t_d` is
   pinned to CPU 3 internally via `pthread_setaffinity_np`; the
   other tracker threads land on 0-2 (because `isolcpus=3` in the
   kernel cmdline excludes CPU 3 from the default cpuset for
   non-RT threads). Setting `CPUAffinity=0-3` documents the full
   allowed mask without changing scheduler behaviour. Inline comment
   in the unit captures this.
7. **`install.sh` does NOT enable the units.** The installer's job
   is to make the units installable; flipping them to `enable --now`
   is the operator's call (e.g. they may want to test `systemctl
   start` once before committing to boot autostart). Instructions
   are printed at the end of the install run.

### Known caveats

- **Build artefact path.** `install.sh` reads from
  `production/RPi5/build/src/godo_tracker_rt/godo_tracker_rt`. If
  the operator runs `scripts/build.sh` with a non-default build
  dir, they need to copy the binary manually or pass `--build-dir`
  to a future revision of the installer (not in scope for 4-2
  carry-over).
- **`/etc/godo/tracker.env` is optional.** The unit's
  `EnvironmentFile=-/etc/godo/tracker.env` line treats the file as
  optional (leading `-`). If the operator wants to override the
  Tier-2 keys baked into `core/config_defaults.hpp`, they create
  the file by hand; there is no `tracker.env.example` in this
  commit (Tier-2 keys are documented in `SYSTEM_DESIGN.md §11.2`
  and operators usually pass overrides via CLI flags from the env
  file, e.g. `GODO_AMCL_MAP_PATH=/etc/godo/maps/studio_v2.pgm`).
  Add a `.env.example` if Phase 5 field-test feedback wants it.
- **systemd-analyze verify runtime check.** Verifying
  `godo-tracker.service` from the repo working tree fails with
  `Command /opt/godo-tracker/godo_tracker_rt is not executable`
  because the install target does not yet exist on a fresh dev
  host. After install (or in a tmpdir staging fixture with stub
  binaries), `systemd-analyze verify` is clean (exit 0).

### Operator bring-up checklist (for news-pi01 — post-merge)

1. Build the binary: `bash production/RPi5/scripts/build.sh`.
2. Run the installer: `sudo bash production/RPi5/systemd/install.sh`.
3. Re-exec PID 1 to pick up the watchdog drop-in:
   `sudo systemctl daemon-reexec`.
4. Enable + start the units:
   `sudo systemctl enable --now godo-irq-pin.service godo-tracker.service`.
5. Verify per `production/RPi5/systemd/README.md §3`.
   - `systemctl status godo-tracker` → active (running).
   - `cat /proc/irq/106/smp_affinity_list` → `0-2`.
   - `cat /proc/irq/125/smp_affinity_list` → `0-2` (ttyAMA0 lazy).
   - `ps -L -o tid,comm,policy,rtprio -p $(pidof godo_tracker_rt)`
     → t_d shows policy=FF rtprio=50.
   - `journalctl -b 0 | grep -i watchdog` → "Using hardware
     watchdog 'Broadcom BCM2835 Watchdog timer'".
6. Smoke the operator path (calibrate button, UDS):
   - Press calibrate (BCM 16) → expect `OneShot complete` log line.
   - `echo '{"cmd":"set_mode","mode":"Idle"}' | nc -U /run/godo/ctl.sock`
     → `{"ok":true}`.

### Carry items for Parent

- **Legacy `.claude/tmp/apply_irq_pin.sh` is now superseded** by
  `production/RPi5/systemd/godo-irq-pin.sh`. The scratch copy in
  `.claude/tmp/` was a Phase 4-1 measurement throwaway; safe to
  delete in a follow-up commit. Not deleted in this commit so the
  diff stays scoped to "add the systemd carry artefacts".
- `PROGRESS.md` carry-over items "Persisted IRQ-pinning systemd
  unit", "systemd unit `godo-tracker.service`", and "Hardware
  watchdog wiring" can move to Done (Parent owns SSOT closeout).
- `SYSTEM_DESIGN.md §6` (RT design) may want a one-line
  cross-reference to `production/RPi5/systemd/README.md` once
  field-tested; not required for merge.

### What this commit explicitly does NOT do

- Does NOT modify `production/RPi5/src/` — config / install only.
- Does NOT delete the legacy `.claude/tmp/apply_irq_pin.sh`
  (separate cleanup commit).
- Does NOT modify `scripts/setup-pi5-rt.sh` — its setcap and
  /etc/security/limits.conf entries are still useful for non-systemd
  dev launches; the systemd unit just bypasses them.
- Does NOT add a `tracker.env.example` template — defer to Phase 5
  if operator feedback wants one.
- Does NOT touch `CLAUDE.md`, `PROGRESS.md`, or `SYSTEM_DESIGN.md` —
  Parent handles SSOT closeout.

## 2026-04-27 — Track B: `get_last_pose` UDS surface

### Added

- `src/core/rt_types.hpp::godo::rt::LastPose` — 56 B trivially-copyable
  pose snapshot (5 doubles + uint64 + int32 + 4 uint8). Field order is
  ABI-visible; mirrored by `format_ok_pose` in `src/uds/json_mini.cpp`
  and pinned via Python regex extraction at test time. Pinned by
  `static_assert(sizeof(LastPose) == 56)` and `alignof == 8`.
- `src/uds/json_mini.{hpp,cpp}::format_ok_pose(const LastPose&)` —
  hand-rolled JSON formatter with mixed precision: `%.6f` for pose
  fields (1 µm / 1 µdeg), `%.9g` for std fields (full mantissa),
  `%llu` for `published_mono_ns`. Worst-case reply < 512 B (pinned
  by `test_uds_server.cpp::format_ok_pose_reply_under_512_bytes`).
- `src/uds/uds_server.{hpp,cpp}` — new `LastPoseGetter` callback +
  `get_last_pose` command branch. Null callback returns
  `valid=0, iterations=-1` so clients distinguish "no pose yet" from
  "tracker down".
- `src/godo_tracker_rt/main.cpp` — declares `Seqlock<LastPose>
  last_pose_seq` (seeded with `iterations=-1`); threads it into the
  cold writer + UDS server.
- `tests/test_cold_writer_ordering.cpp` — single-file ordering pin
  for F5: `run_one_iteration` and `run_live_iteration` both publish
  to `last_pose_seq` before returning. Removing either publish call
  would leave `last_pose_seq.generation() == 0` and fail the test.
- `doc/uds_protocol.md §C.4` — `get_last_pose` documentation
  including the `xy_std_m = sqrt(weighted_var_x + weighted_var_y)`
  formula citation pointing to `amcl.cpp:272-300` (F18) and the
  precision-split rationale (F8).

### Changed

- `src/localization/cold_writer.{hpp,cpp}` — `run_one_iteration`,
  `run_live_iteration`, and `run_cold_writer` gain a
  `Seqlock<LastPose>&` parameter. Both kernels publish
  UNCONDITIONALLY (independent of the deadband decision). The
  OneShot success path stores `g_amcl_mode = Idle` AFTER the kernel
  has published — verbatim F5 comment cites the race rationale.
- `src/uds/uds_server.hpp` wire-protocol comment block — adds
  `get_last_pose` to the request/response shape table.
- `tests/test_uds_server.cpp` — 4 new cases:
  `get_last_pose returns valid=0 when no pose has been published`,
  `get_last_pose returns published pose verbatim`,
  `format_ok_pose — byte-exact shape on a default-zero LastPose`,
  `format_ok_pose reply size is under 512 bytes (F17 budget pin)`.
- `tests/test_cold_writer_offset_invariant.cpp` — 3 call sites
  updated to thread a stack-allocated `Seqlock<LastPose>` through
  `run_one_iteration` (F6).
- `tests/test_cold_writer_live_iteration.cpp` — 4 call sites
  updated to thread `Seqlock<LastPose>` through `run_live_iteration`
  (F6 — note the plan's "7 sites" total counts 1 production +
  prior call counts; the actual surviving test sites after Wave 2
  are 4 in this file).
- `tests/CMakeLists.txt` — registers `test_cold_writer_ordering`
  with `LABELS hardware-free`.

### Removed

- (none)

### Tests

- New: `test_cold_writer_ordering` (2 cases — OneShot publish + Live
  publish with `forced` flag distinction).
- New: 4 cases inside `test_uds_server`.
- Updated: `test_cold_writer_offset_invariant`,
  `test_cold_writer_live_iteration` — call-site cascade only,
  no contract change.
- ctest hardware-free label: 28 → 30 tests after Track B (29 in the
  default gate + 1 new ordering pin).

### Phase 4.5 follow-up candidates

- Add a `force=true` field to `set_mode` so an operator can panic-cancel
  a mid-OneShot run; the cold writer would re-check `g_amcl_mode`
  between converge() iterations. Not required for Wave B per
  `uds_protocol.md §F.4`.
- Stash a small ring of past `LastPose` snapshots so `get_last_pose`
  can serve a `--last-N` history without per-call AMCL iteration.
  Useful for the Phase 4.5 web UI; out of scope for Track B's
  OneShot-only repeatability harness.
- Promote `Seqlock<LastPose>` reads in `pose_watch.py`'s json mode to
  a single recv with deserialization in C++; current Python `json.loads`
  is fine for 2 Hz polling but may show up under high-frequency mass
  pose-dump experiments.

## 2026-04-29 — Track D: Live LIDAR overlay (Phase 4.5+ P0.5)

### Added

- `src/core/rt_types.hpp::godo::rt::LastScan` — 11 568 B fixed-size POD
  carrying anchor pose + flags + parallel `angles_deg[720]` /
  `ranges_m[720]` arrays. `static_assert sizeof == 11568` pins the
  layout. Trivially copyable (Seqlock<T> requirement).
- `src/core/constants.hpp` — `LAST_SCAN_RANGES_MAX = 720` (Tier-1,
  mirrors SCAN_BEAMS_MAX) + `JSON_SCRATCH_BYTES = 24576` (formatter
  scratch budget for `format_ok_scan` worst case).
- `src/uds/json_mini.{hpp,cpp}::format_ok_scan(const LastScan&)` —
  mirrors `format_ok_pose` shape; `%.4f` for ranges + angles, `%.6f`
  for pose anchors, truncation guards on every snprintf.
- `src/uds/uds_server.{hpp,cpp}` — `LastScanGetter` typedef + new
  `get_last_scan` cmd branch in `handle_one_request` + 5th constructor
  parameter. Null-callback returns `valid=0,n=0,iterations=-1`.
- `src/localization/cold_writer.{hpp,cpp}` — `run_one_iteration` and
  `run_live_iteration` now take a 12th `Seqlock<LastScan>&` parameter;
  both publish a snapshot UNCONDITIONALLY at the same seam where they
  publish LastPose (independent of deadband). New private helper
  `fill_last_scan` decimates frame samples with the same stride +
  range filter the AMCL beam pipeline uses.
- `src/godo_tracker_rt/main.cpp` — declares `Seqlock<LastScan>
  last_scan_seq`, seeds with `iterations=-1`, threads through
  `run_cold_writer` and `thread_uds`. UDS callback closure
  `[&last_scan_seq]() { return last_scan_seq.load(); }`.
- `tests/test_cold_writer_scan_publish.cpp` (NEW, 6 cases) — pins
  unconditional publish on OneShot/Live + deadband-suppressed-Offset
  paths, AMCL-aligned beam decimation, monotonic published_mono_ns,
  n=0 corner case.
- `tests/test_last_scan_seqlock_stress.cpp` (NEW, 1 case heavy) —
  1W/4R 100 000 iterations on `Seqlock<LastScan>`. Mode-A TB1 fold:
  positional torn-read invariant (`ranges_m[i] = i × 0.001`,
  `angles_deg[i] = i × 0.5`) — readers detect tearing from a single
  load alone, no sibling atomic.
- `tests/test_uds_server.cpp` — 5 new cases for the `get_last_scan`
  branch (null callback, published verbatim, concurrent set_mode,
  default-zero formatter shape, n=720 worst-case fits scratch).
- `scripts/build.sh` — two new build-greps:
  `[scan-publisher-grep]` (cold_writer.cpp + 1 init in main.cpp),
  `[hot-path-isolation-grep]` (thread_d_rt body free of last_scan_seq).
  Both fail the build on hits.

### Changed

- `tests/test_cold_writer_{offset_invariant,live_iteration,ordering}.cpp`
  — call-site cascade only (12th arg). No contract change.

### Tests

- ctest hardware-free label: 30 → 32 tests after Track D
  (`test_cold_writer_scan_publish` + `test_last_scan_seqlock_stress`).
- `test_uds_server` doctest case count: +5.

### Notes

- LastScan struct field order (`pose_x_m, pose_y_m, pose_yaw_deg,
  published_mono_ns, iterations, valid, forced, pose_valid, _pad0, n,
  _pad1, _pad2, angles_deg[], ranges_m[]`) is ABI-visible. Wire order
  in `format_ok_scan` re-orders to put flags + iterations + pose
  anchors before `n` so the array body sits at the tail; the Python
  mirror `LAST_SCAN_HEADER_FIELDS` matches the wire order. Drift between
  any of the four representations (struct, format string, Python
  tuple, TS interface) fails one of the pins.
- Hot path is fully insulated: the `[hot-path-isolation-grep]` build
  step verifies thread_d_rt's body has zero `last_scan_seq` references;
  the `[scan-publisher-grep]` step verifies only cold_writer.cpp +
  the boot init in main.cpp store into the seqlock. Track D adds
  zero work to Thread A (FreeD recv) or Thread D (UDP send 59.94 Hz).

---

## 2026-04-29 — PR-DIAG (Track B-DIAG) — Diagnostics page

### Added

- `src/core/rt_types.hpp` — new value types:
  - `struct JitterSnapshot` (64 B, 8-aligned, trivially copyable;
    p50/p95/p99/max/mean ns + sample_count + published_mono_ns + valid).
  - `struct AmclIterationRate` (40 B, 8-aligned, trivially copyable;
    hz + last_iteration_mono_ns + total_iteration_count +
    published_mono_ns + valid). Mode-A M2 fold renamed scan_rate →
    amcl_iteration_rate.
- `src/core/constants.hpp` — Tier-1 constants:
  - `JITTER_RING_DEPTH = 2048` (≈34 s @ 59.94 Hz).
  - `JITTER_PUBLISH_INTERVAL_MS = 1000`.
  - `AMCL_RATE_WINDOW_S = 5.0` (informational; window arithmetic is
    publisher-tick-differencing).
  - `JITTER_FORMAT_SCRATCH_BYTES = 512`,
    `AMCL_RATE_FORMAT_SCRATCH_BYTES = 256` for json_mini formatters.
- `src/rt/jitter_ring.{hpp}` — `class JitterRing`: lock-free 1W/1R
  fixed-size ring (`std::array<int64_t, 2048>`); writer is Thread D
  (`record`), reader is the diag publisher (`snapshot`).
- `src/rt/jitter_stats.{hpp,cpp}` — pure functions
  `compute_percentile(sorted, p)` + `compute_summary(data, &out)`
  (sorts in place, fills JitterSnapshot).
- `src/rt/amcl_rate.hpp` — `class AmclRateAccumulator` wrapping
  `Seqlock<AmclRateRecord>` (Mode-A M1 fold).
- `src/rt/diag_publisher.{hpp,cpp}` — non-RT publisher (SCHED_OTHER) +
  test-injectable `run_diag_publisher_with_clock` variant.
- `src/uds/json_mini.{hpp,cpp}` — `format_ok_jitter` + `format_ok_amcl_rate`
  with worst-case scratch budgets pinned by static_assert.
- `src/uds/uds_server.{hpp,cpp}` — `JitterGetter` / `AmclRateGetter`
  typedefs; `get_jitter` + `get_amcl_rate` cmd branches.
- `src/godo_tracker_rt/main.cpp` — declare `Seqlock<JitterSnapshot>` +
  `Seqlock<AmclIterationRate>`, `JitterRing`, `AmclRateAccumulator`;
  spawn `t_diag_publisher`; thread `jitter_ring` into Thread D and
  `amcl_rate_accum` into the cold writer; wire the four new UDS
  callbacks.
- `scripts/build.sh` — three new build greps:
  - `[hot-path-jitter-grep]` (Thread D body has exactly 1 `jitter_ring.`
    + 0 `jitter_ring.snapshot` + 0 percentile/seqlock-store references);
  - `[jitter-publisher-grep]` (only `rt/diag_publisher.cpp` may store
    into `jitter_seq` / `amcl_rate_seq`);
  - `[amcl-rate-publisher-grep]` (only `cold_writer.cpp` may call
    `amcl_rate_accum.record`).

### Changed

- `src/localization/cold_writer.{hpp,cpp}` — `run_one_iteration` /
  `run_live_iteration` / `run_cold_writer` signatures gain
  `AmclRateAccumulator& amcl_rate_accum`; both kernels call
  `amcl_rate_accum.record(monotonic_ns())` once at the top of their body.
- `src/godo_tracker_rt/main.cpp::thread_d_rt` — adds one
  `jitter_ring.record(now_ns - scheduled_ns)` per tick; computed against
  the pre-advance `next` deadline.
- `src/uds/uds_server.{hpp,cpp}` — constructor adds two more optional
  callback parameters (defaults nullptr); `handle_one_request` gains
  the two new cmd branches.

### Tests

- New: `tests/test_jitter_ring.cpp` (5 cases — round-trip, wraparound,
  capacity, monotonic counter, 1W/1R subset invariant).
- New: `tests/test_jitter_stats.cpp` (6 cases — p50 odd/even, p99 single,
  empty, content correctness incl. Mode-A TB2 [1,100,1000]→p50=100 pin,
  in-place sort + mean).
- New: `tests/test_amcl_rate.cpp` (4 cases — initial zero, advance,
  count-monotonic 1W/1R, last_ns advances).
- New: `tests/test_diag_publisher.cpp` (4 cases — virtual-clock tick
  publishes both seqlocks with TB2 content invariant; sleep_for=false
  exits; g_running=false skips body; empty ring ⇒ valid=0 sentinel).
- New: `tests/test_cold_writer_amcl_rate_records.cpp` (3 cases — OneShot
  / Live / triple-back-to-back accumulator increments).
- Modified: `tests/test_uds_server.cpp` — 6 new cases (get_jitter
  null/published/concurrent + format_ok_jitter byte-exact + fits-in-
  scratch; get_amcl_rate null/published + format_ok_amcl_rate
  byte-exact).
- Modified: `tests/test_cold_writer_*.cpp` (4 files) — accumulator
  declarations added at each test scope; kernel calls extended with
  `amcl_rate_accum` parameter.

### Mode-A folds applied (verbatim)

- M1: `AmclRateAccumulator` uses `Seqlock<AmclRateRecord>` (not two
  atomics). Pin: zero Hz-skew under concurrent record/snapshot.
- M2: `scan_rate` → `amcl_iteration_rate` everywhere (struct, JSON,
  endpoint, SPA UI). The metric measures AMCL iteration cadence; in
  Idle the LiDAR is parked and the rate is 0 Hz by design.
- M3: `[hot-path-jitter-grep]` asserts exactly 1 `jitter_ring\.`
  reference + 0 `jitter_ring\.snapshot` references inside thread_d_rt.
- N1: `JitterSnapshot` trailing pad commented as "1 (valid) + 3
  (pad0..pad2) + 4 (_pad3) = 8 B" so writer doesn't treat `_pad3` as
  semantic.
- N2: `JITTER_RING_DEPTH = 2048` overlap note (consecutive 1 s
  publishes share ~33/34 s of samples; sparkline evolves slowly).
- N3: `amcl_rate_seq` reader-only on `diag_publisher.cpp` is
  code-review-enforced (not build-grep), symmetric with last_pose_seq
  / last_scan_seq.
- N4: Resources `published_mono_ns` is informational (webctl monotonic
  clock); SPA freshness uses `_arrival_ms` per Track D Mode-A M2.
- TB1: writer fills `record(i)` for monotonic i; reader's snapshot
  values must lie in the writer's value domain (positional + arithmetic
  invariant from a single load).
- TB2: feeding `[1, 100, 1000]` into the ring then ticking the publisher
  must store p50=100 in jitter_seq.

### Build / test gate

All 41 ctest hardware-free targets pass; all 6 build greps clean:
`[rt-alloc-grep]` (warning-only — comment-line false positive),
`[m1-no-mutex]`, `[scan-publisher-grep]`, `[hot-path-isolation-grep]`,
`[hot-path-jitter-grep]`, `[jitter-publisher-grep]`,
`[amcl-rate-publisher-grep]`. Hot-path regression check (Phase 4-1
`godo_jitter` baseline rerun) deferred to manual smoke on news-pi01
per the plan's Definition of Done.

---

## 2026-04-29 — Track B-CONFIG (PR-CONFIG-α): C++ tracker config edit

### Added

**`src/core/config_schema.hpp` (NEW)** —
- `enum class ValueType { Int, Double, String }`,
  `enum class ReloadClass { Hot, Restart, Recalibrate }`.
- `struct ConfigSchemaRow { name, type, min_d, max_d, default_repr,
  reload_class, description }`.
- `inline constexpr std::array<ConfigSchemaRow, 37> CONFIG_SCHEMA` —
  alphabetical by `name`, wrapped in `// clang-format off` so the row
  shape stays one-line-per-row for the Python regex parser (β).
- `static_assert(CONFIG_SCHEMA.size() == 37)` (Mode-A M2).
- `find(name)`, `reload_class_to_string`, `value_type_to_string` helpers.

**`src/core/hot_config.{hpp,cpp}` (NEW)** — `struct HotConfig` with the
3 hot-class fields (`deadband_mm`, `deadband_deg`,
`amcl_yaw_tripwire_deg`) + `published_mono_ns` + `valid` + 7 B pad.
`static_assert(sizeof(HotConfig) == 40)` (Mode-A M1 fold dropped
`divergence_*`). `snapshot_hot(cfg)` is a pure free function.

**`src/config/validate.{hpp,cpp}` (NEW)** — `validate(key, value_text)`
returns `{ok, err, err_detail, parsed_double, parsed_string, row*}`.
Strict integer parse (rejects decimal/exponent forms); lenient double
parse; ASCII-only strings ≤ 256 chars.

**`src/config/atomic_toml_writer.{hpp,cpp}` (NEW)** — `write_atomic`
implements: `access(parent, W_OK)` (Mode-A S1) → `mkstemp(parent /
".tracker.toml.XXXXXX")` → `fchmod 0644` → write loop → `fsync` →
`close` → `rename`. On any failure the tmp file is unlinked.
`WriteOutcome` is a typed enum (`Ok | ParentNotWritable | MkstempFailed
| WriteFailed | FsyncFailed | RenameFailed`).

**`src/config/restart_pending.{hpp,cpp}` (NEW)** — `touch_pending_flag`,
`clear_pending_flag`, `is_pending`. Idempotent; logs but never throws.

**`src/config/apply.{hpp,cpp}` (NEW)** — central orchestrator.
- `apply_set(key, value, live_cfg, mtx, hot_seq, toml, flag)` →
  validate → lock mtx → clone Config → apply value → render TOML →
  atomic write → commit live_cfg → publish HotConfig (hot-class) OR
  touch flag (restart/recalibrate) → return `ApplyResult`.
- `apply_get_all(live_cfg, mtx)` → JSON dict of 37 keys, alphabetical.
- `apply_get_schema()` → JSON array of 37 schema rows.
- `render_toml(cfg)` → canonical TOML body, sectioned + alphabetical.

**`src/uds/uds_server.{hpp,cpp}` (extended)** — three new commands
wired through optional callbacks:
- `get_config`        → `ConfigGetter`        (returns JSON body string).
- `get_config_schema` → `ConfigSchemaGetter`  (pure, no live state).
- `set_config`        → `ConfigSetter`        (returns `ConfigSetReply`).
- New ctor parameters appended at the end (existing call sites still
  compile; null callbacks surface `config_unsupported`).
- `Request` struct extended with `key_arg` + `value_arg` for
  `set_config`'s 3-field shape `{cmd, key, value}`.

**`src/uds/json_mini.{hpp,cpp}` (extended)** — `format_ok_set_config`,
`format_ok_get_config`, `format_ok_get_config_schema`,
`format_err_with_detail`. The `detail` field carries the validator's
human-readable rejection reason; backslash + quote are escaped.

**`src/godo_tracker_rt/main.cpp` (extended)** — boot-time wiring:
1. `clear_pending_flag(restart_pending_flag)` after `Config::load()`
   succeeds and before any thread spawn (TM10 / TM11).
2. `Seqlock<HotConfig> hot_cfg_seq` initialised with
   `snapshot_hot(cfg)` + `published_mono_ns = monotonic_ns()`.
3. `Config live_cfg = cfg` + `std::mutex live_cfg_mtx` — the UDS
   thread is the SOLE writer of `live_cfg`.
4. `thread_uds` signature now also takes `live_cfg`, `live_cfg_mtx`,
   `hot_cfg_seq`, `toml_path`, `restart_pending_flag`. Three new
   callbacks wire to `apply_get_all` / `apply_get_schema` / `apply_set`.
5. `GODO_CONFIG_PATH` and `GODO_RESTART_PENDING_FLAG_PATH` env
   overrides (CLI flag deferred to PR-CONFIG-β).

**`scripts/build.sh` (3 new build greps)** —
- `[hot-path-config-grep]` — extracts the body BETWEEN the
  `while (godo::rt::g_running.load` line and the matching closing brace
  inside `void thread_d_rt(...)`. That subset MUST contain zero
  references to `cfg.`, `live_cfg`, `hot_cfg_seq`, or `HotConfig`.
- `[hot-config-publisher-grep]` — `hot_cfg_seq\.store\b` outside
  `src/config/apply.cpp` and `src/godo_tracker_rt/main.cpp` fails the
  build. The boot-time init is the lone main.cpp call site (allow-listed).
- `[atomic-toml-write-grep]` — `mkstemp` / `rename` calls in `.cpp`
  files outside `src/config/atomic_toml_writer.cpp` fail the build.

**`tests/test_config_schema.cpp` (NEW)** — 12 cases: row count = 37,
alphabetical ordering, name uniqueness, `find()` resolves every row,
`find()` returns nullptr for unknown / partial names, reload-class +
value-type round-trip, M2 fold pins (`t_ramp_ms` reload_class =
restart, live-σ description, seed-σ rows present), per-row sanity
(non-empty fields, exactly one dot, numeric range coherence).

**`tests/test_config_validate.cpp` (NEW)** — 22 cases: bad_key,
empty key, int happy / decimal-rejected / exponent-rejected /
empty-rejected / trailing-junk / range-below-min / range-above-max,
double happy (int form, float form, exponent form), double trailing
junk / range / range, string happy / empty / non-ASCII / control /
oversized, reload-class returns by row.

**`tests/test_atomic_toml_writer.cpp` (NEW)** — 9 cases: happy round-
trip, empty body, overwrite, missing parent → ParentNotWritable +
target absent + no tmp leftover (Mode-A TB2 (a)+(b)), read-only parent
chmod 0500 → ParentNotWritable + pre-bytes preserved + no tmp leftover,
exact body bytes, tmp-in-parent invariant (no leftovers, only the
target file present), file mode 0644, `outcome_to_string` round-trip.

**`tests/test_restart_pending.cpp` (NEW)** — 6 cases: touch creates,
clear removes, touch idempotent, clear ENOENT idempotent, missing flag
returns false, touch creates parent dir if missing.

**`tests/test_hot_config.cpp` (NEW)** — 3 cases: `sizeof == 40`
(Mode-A M1), `snapshot_hot` copies the three fields, deterministic.

**`tests/test_config_apply.cpp` (NEW)** — 12 cases: hot-class
publishes HotConfig + no flag touch; restart-class touches flag + no
HotConfig publish; recalibrate-class touches flag + no HotConfig
publish; bad_key leaves all state unchanged; bad_value leaves all state
unchanged; bad_type rejected; string field round-trips through TOML;
write-failed (parent missing) leaves live_cfg untouched;
`apply_get_all` returns 37 alphabetical keys; `apply_get_schema`
returns 37 rows with 3 reload-class values + 3 type values;
`render_toml` round-trips through `apply_set`; consecutive
restart-class edits keep flag; get-after-set reflects new value.

**`tests/test_set_config_e2e_ipc.cpp` (NEW)** — 7 cases: get_config_
schema returns valid JSON; get_config returns 37-key dict; set_config
hot-class round-trips wire / TOML / RAM / HotConfig + reply carries
class; set_config restart-class touches flag + reply class; set_config
bad_value surfaces detail field on the wire; set_config bad_key
surfaces unknown-key name; null callbacks return `config_unsupported`;
set_config without `key` returns `bad_payload`.

### Changed

- `src/core/CMakeLists.txt` — `godo_core` adds `hot_config.cpp`.
- Top-level `CMakeLists.txt` — `add_subdirectory(src/config)` between
  gpio and uds.
- `src/godo_tracker_rt/CMakeLists.txt` — links `godo_config`.
- `src/uds/uds_server.{hpp,cpp}` — ctor signature appended with
  `ConfigGetter`, `ConfigSchemaGetter`, `ConfigSetter` (all default
  nullptr); request-dispatch branches added.
- `src/uds/json_mini.{hpp,cpp}` — `parse_request` recognises `key` +
  `value` fields; new format helpers added.

### Removed

- (none)

### Invariants (additions)

#### (l) Track B-CONFIG — schema is the cross-language SSOT (code-review enforced)

`src/core/config_schema.hpp::CONFIG_SCHEMA[]` is the canonical 37-row
declaration of every operator-tunable Tier-2 key. The `// clang-format
off` block keeps one row per line so the Python mirror (β) and runtime
SPA fetch can rely on a stable shape. Adding a row requires:
1. New entry in `CONFIG_SCHEMA[]` (alphabetical by `name`),
2. Bump the `static_assert(CONFIG_SCHEMA.size() == ...)`,
3. Extend `read_effective` + `apply_one` in `config/apply.cpp` so
   the row reaches a real `Config` field,
4. Extend the corresponding env / CLI / TOML touchpoint in
   `core/config.cpp` if the row is new to `Config` itself.

The Python parity test (`tests/test_config_schema_parity.py`, β) and
SPA runtime fetch from `/api/config/schema` (γ) close the cross-
language loop.

#### (m) Track B-CONFIG — hot-config publisher seam (build-grep enforced)

`Seqlock<godo::core::HotConfig> hot_cfg_seq` is owned by `main.cpp`.
The SOLE production-runtime writer is
`config/apply.cpp::apply_set` (the UDS handler thread's call site,
under `live_cfg_mtx`). `main.cpp` is allowed exactly one extra
`hot_cfg_seq.store(...)` for boot-time init (idempotent; runs before
thread spawn, so it cannot race). Build-grep
`[hot-config-publisher-grep]` enforces this — any other `.cpp` file
under `src/` calling `hot_cfg_seq.store` fails the build.

PR-CONFIG-α does NOT yet wire cold_writer.cpp to read HotConfig; the
publish path is in place and tested via the seqlock generation count.
The cold-writer reader migration is pinned for a follow-up (PR-CONFIG-β
or its own tiny PR) so this α PR stays narrowly scoped to the
publisher / writer / wire surface.

#### (n) Track B-CONFIG — atomic TOML writer seam (build-grep enforced)

`config/atomic_toml_writer.cpp` is the SOLE owner of `mkstemp(2)` and
`rename(2)` calls (against any path) in `production/RPi5/src/`. Build-
grep `[atomic-toml-write-grep]` enforces this. Bypassing the atomic
writer (e.g. `std::ofstream` on tracker.toml) would defeat the
crash-safety contract pinned in TM3.

The same-filesystem precondition (`tmp_path.parent_path() ==
target_path.parent_path()`) is enforced at code level (the writer
composes the tmp template from `target_path.parent_path()`), not by a
runtime assert. Pinned by `tests/test_atomic_toml_writer.cpp::"tmp
file lives in the target's parent dir"`.

#### Hot-path config isolation (build-grep enforced — extension of (g))

The build grep `[hot-path-config-grep]` extracts the body BETWEEN the
`while (godo::rt::g_running.load` line and its matching closing brace
inside `void thread_d_rt(...)`. That subset MUST contain zero
references to `cfg.`, `live_cfg`, `hot_cfg_seq`, or `HotConfig`. Setup
BEFORE the while loop is allowed to read `cfg.rt_cpu` / `.rt_priority`
/ `.ue_host` / `.ue_port` / `.t_ramp_ns` once (those are restart-class
and captured at thread start by design).

### Tests

- New: 7 test files, ~71 hardware-free cases.
- Total ctest count: 41 → 43 (gain 2 hardware-free executables that
  bundle multiple test cases each — the ctest count in the build gate
  reflects executables, not individual cases).

### Build / test gate

All 43 ctest hardware-free targets pass (was 41); all 10 build greps
clean: pre-existing 7 (`[rt-alloc-grep]` warning-only,
`[m1-no-mutex]`, `[scan-publisher-grep]`, `[hot-path-isolation-grep]`,
`[hot-path-jitter-grep]`, `[jitter-publisher-grep]`,
`[amcl-rate-publisher-grep]`) + 3 new
(`[hot-path-config-grep]`, `[hot-config-publisher-grep]`,
`[atomic-toml-write-grep]`).

### Mode-A folds applied (verbatim)

- **M1** — `HotConfig` field set is 3 doubles + uint64 + uint8 + 7 B
  pad = 40 B exact (was 5 + … = 64 B). `divergence_*` dropped from
  HotConfig; `divergence_mm` / `divergence_deg` schema rows
  reclassified `restart`.
- **M2** — Schema row count 37 (not 35). Two seed-σ rows added
  (`amcl.sigma_seed_xy_m`, `amcl.sigma_seed_yaw_deg`). `t_ramp_ms`
  reload_class is `restart`. Live-σ row descriptions tightened.
- **M3** — Plan split into PR-CONFIG-α (this PR; Waves 0+1, C++ only)
  and PR-CONFIG-β (next; webctl + SPA + cross-language tests + docs).
- **S1** — `access(parent, W_OK)` early-detect added to atomic writer
  with typed `WriteOutcome::ParentNotWritable`.
- **S2** — `// clang-format off` around `CONFIG_SCHEMA[]`;
  `static_assert(N == 37)` C++-side.
- **TB2** — Atomic writer tests assert (a) target unchanged or absent
  and (b) no `.tracker.toml.*` tmp leftover for every failure case,
  not just return codes.

### Out of α scope (deferred to PR-CONFIG-β next session)

- `godo-webctl/src/godo_webctl/{config_schema, config_view,
  restart_pending}.py` — Python mirror + view helpers.
- `godo-webctl` `protocol.py` `CMD_GET_CONFIG / CMD_SET_CONFIG` constants.
- `godo-webctl/src/godo_webctl/app.py` — 3 new HTTP endpoints.
- `godo-frontend` `lib/protocol.ts` mirrors + Config.svelte route.
- `cold_writer.cpp` migration to read `HotConfig` per iteration.
- Cross-language schema-parity test (`test_config_schema_parity.py`).
- `FRONT_DESIGN.md §6.4 / §7 / §8` row-flip from "P1" to "(있음)".


## 2026-04-29 — Track B-CONFIG (PR-CONFIG-β): cold_writer HotConfig reader migration

### Added

- `tests/test_cold_writer_reads_hot_config.cpp` — pins that
  `run_one_iteration` consumes `hot_cfg_seq.load()` once at the head
  of every iteration and falls back to `cfg.deadband_*` /
  `cfg.amcl_yaw_tripwire_deg` when the seqlock payload's `valid==0`
  (boot sentinel). 4 cases: happy fallback, hot-publish honoured,
  mid-call republish takes effect on next iter, 100k-loop wait-free
  cost. Co-located with the existing cold-writer kernel tests.

### Changed

- `src/localization/cold_writer.{hpp,cpp}` — `run_one_iteration` and
  `run_live_iteration` now take a final
  `Seqlock<HotConfig>& hot_cfg_seq` parameter. The kernels load once
  per iteration; `cfg.deadband_mm` / `cfg.deadband_deg` /
  `cfg.amcl_yaw_tripwire_deg` reads in the deadband filter +
  yaw-tripwire branch are replaced with the seqlock payload's fields,
  with cfg-fallback on `hot.valid==0`. `run_cold_writer` threads the
  seqlock reference through to both kernels. The non-hot Config
  fields (origin, sigma_*, range_*, downsample_stride) continue to
  read directly from `cfg` because they are `restart`/`recalibrate`-
  class — changes take effect on next boot, not mid-iteration.
- `src/godo_tracker_rt/main.cpp` — `t_cold = std::thread(run_cold_writer,
  ..., std::ref(hot_cfg_seq), lidar_factory)` — one new ref-arg; rest
  of the boot sequence and ordering invariant unchanged.
- `tests/test_cold_writer_{amcl_rate_records, offset_invariant,
  ordering, live_iteration, scan_publish}.cpp` — every direct call to
  `run_one_iteration` / `run_live_iteration` extended with a
  `Seqlock<godo::core::HotConfig> hot_cfg_seq` declared local; the
  default-constructed payload's `valid==0` exercises the cfg-fallback
  path automatically. No assertion change in any of the existing test
  cases — they still pin the same invariants (offset shape, deadband
  filter, scan publish ordering).

### Test deltas

- New: `test_cold_writer_reads_hot_config` (4 cases).
- Changed: 5 existing cold-writer test files now thread the seqlock
  parameter through every kernel call (no behavioural change).

### Build greps

`[hot-path-config-grep]`, `[hot-config-publisher-grep]`,
`[atomic-toml-write-grep]` all stay green — Thread D continues to have
zero `cfg.` / `HotConfig` references, only `config/apply.cpp` +
`main.cpp` write to `hot_cfg_seq`, and only `atomic_toml_writer.cpp`
mkstemp/renames against `tracker.toml`. The new cold-writer reads of
`hot_cfg_seq.load()` are not on the publisher list (load is reader-
side wait-free).

### Invariants tightened

- (t-extended) The cold-writer kernel reads `HotConfig` ONCE per
  iteration at the head (before AMCL beam decimation). The deadband
  filter + yaw-tripwire then read the local `hot.*` snapshot, NOT the
  seqlock payload directly, so a mid-iteration republish does not
  cause partial visibility within a single AMCL kernel call. Pin:
  `test_cold_writer_reads_hot_config::"mid-call hot publish takes
  effect on next iter"`.

## 2026-04-29 — PR-1: Single-instance pidfile lock + UDS bind-atomic

### Added

- `src/core/pidfile.{hpp,cpp}` — `class PidFileLock` (RAII, owns the
  POSIX `fcntl(F_SETLK, F_WRLCK)` lock + the path lifetime). Throws
  `PidFileLockHeld` on contention (with diagnostic PID), or
  `PidFileLockSetupError` on parent-dir / open / fsync failures.
  Mode-A M6: dtor unlinks BEFORE close so a third process trying
  open-then-lock sees ENOENT promptly.
- `src/core/CMakeLists.txt` — `pidfile.cpp` added to `godo_core`.
- `src/core/config_defaults.hpp` — `TRACKER_PIDFILE_DEFAULT =
  "/run/godo/godo-tracker.pid"`.
- `src/core/config.{hpp,cpp}` — `Config::tracker_pidfile` field;
  CLI `--pidfile`, env `GODO_TRACKER_PIDFILE`, TOML
  `ipc.tracker_pidfile`.
- `tests/test_pidfile.cpp` — 6 doctest cases (acquire, cross-process
  contention, stale-PID-no-holder, dtor-order, fork-does-not-inherit
  per TB4, kill-diagnostic-is-not-lock-decision per M4).
- `tests/CMakeLists.txt` — `test_pidfile` target wired (hardware-free).

### Changed

- `src/godo_tracker_rt/main.cpp` — acquires `PidFileLock`
  IMMEDIATELY after `Config::load`, BEFORE any thread spawn /
  Seqlock allocation / device open. On `PidFileLockHeld` returns 1
  with documented stderr; on `PidFileLockSetupError` returns 1 with
  parent-dir diagnostic.
- `src/uds/uds_server.cpp` — `UdsServer::open` replaces
  `unlink → bind` with **bind-temp + atomic `rename(2)`**. Pattern:
  bind to `<socket_path>.<pid>.tmp`, then `rename` over the target.
  Eliminates the TOCTOU window where a concurrent process could race
  the bind() between our unlink() and bind(). Single-instance
  discipline (invariant (l)) gates the path on the pidfile lock —
  only one godo_tracker_rt is ever running, so the only TOCTOU at
  risk would be a manual `socat` racing the boot. Atomic rename
  closes that gap regardless.
- `tests/test_uds_server.cpp` — 2 new doctest cases: stale-socket
  bind succeeds, second `UdsServer::open()` on bound path. `<sys/stat.h>`
  added.
- `tests/test_rt_replay.cpp` — passes `--pidfile /tmp/...` to the
  spawned tracker so the test does not require `/run/godo`.
- `production/RPi5/CODEBASE.md` — new invariant `(l)
  tracker-pidfile-discipline`.

### Removed

- (none)

### Tests

- 45 → 46 hardware-free test executables (+1: `test_pidfile`). All
  green. `test_uds_server` gains 2 cases. `test_rt_replay` updated
  to pin pidfile to /tmp (no /run/godo dependency).

### Mode-A folds applied

- M1: tests under `production/RPi5/tests/` (plural, flat).
- M4: stale-PID is a lock-only decision; `kill(pid, 0)` is purely
  diagnostic.
- M6: C++ dtor unlinks BEFORE close.
- N3: invariant letter `(l)`.
- N7: `production/RPi5/systemd/godo-tracker.service` NOT modified.
- TB1: stale-PID test uses `0x7FFFFFFF`.
- TB4: doctest case 5 = fork-does-not-inherit-lock (POSIX fcntl).

## 2026-04-29 19:45 KST — Track D-3 (RPLIDAR CW → REP-103 CCW boundary fix)

### Why

Pre-fix HIL session (2026-04-29 19:20 KST, news-pi01 in TS5 chroma
studio) measured ~1 / 30 OneShot calibrate convergences. Root cause:
`scan_ops::downsample` was treating the RPLIDAR C1's clockwise-
positive sensor angle as REP-103 CCW (per
`doc/RPLIDAR/RPLIDAR_C1.md:128`), so every beam's `ys` term was
sign-flipped against the map. AMCL was fitting a vertically-mirrored
scan and the studio's partial long-axis symmetry occasionally let it
"converge" to a `(px, −py, −yaw)` mirror-image solution — most attempts
diverged off the map. SPA-side counterpart already shipped in PR #30;
this fix lands the C++ side without coordinated wire-format change.

### Added

- `src/localization/scan_ops.cpp::downsample()` — 5-line citation
  comment at the boundary (cites `doc/RPLIDAR/RPLIDAR_C1.md:128`,
  invariant (m), and the wire-format-stays-CW contract).
- `tests/test_amcl_components.cpp::TEST_CASE("scan_ops::downsample —
  RPLIDAR CW 90° beam projects to LiDAR's right side under fix")` —
  7 sub-asserts pinning the convention shift. Bias-block: world-frame
  endpoints are computed by hand, NOT by calling `evaluate_scan`, so
  a bug in the kernel cannot mask a bug in the convention shift.
  Step 5 plugs `a = beams[0].angle_rad` (post-downsample value, not
  `90·π/180` re-derived) so a shared bug cannot ride through. Step 6
  uses yaw=45° to exercise all four terms in the rotation matrix.
  Step 7 adds a SECOND beam at 270° (LiDAR left side) to pin both
  mirror directions.
- `doc/convergence_hil.md` — operator-driven HIL convergence-rate
  protocol with truth-pose extraction script and accept/marginal/fail
  decision table.

### Changed

- `src/localization/scan_ops.cpp:48` — `b.angle_rad = -s.angle_deg *
  kDegToRad` (was `+s.angle_deg * kDegToRad`). Net delta: 1 line of
  code, +5 lines of comment.
- `src/localization/scan_ops.hpp:21-26` — `RangeBeam.angle_rad` field
  comment now says "REP-103 CCW (post-conversion from raw RPLIDAR CW
  per scan_ops.cpp:48 — see invariant (m) in CODEBASE.md and
  doc/RPLIDAR/RPLIDAR_C1.md:128). The AMCL kernel converts to map
  frame using the particle's yaw with standard CCW math." Net delta:
  comment-only, no ABI change.

### Removed

- (none)

### Tests

- 45 → 45 hardware-free test executables (no new file). The new
  TEST_CASE lives inside the existing `test_amcl_components` binary;
  its assertion count went 30 → 37 (+7 sub-asserts in one new case,
  totalling 5 cases now in `test_amcl_components`). All existing
  cases unchanged and green.
- `test_amcl_scenarios::synth_beams` is self-consistent in CCW frame
  (its ray-cast and the AMCL evaluator share the same convention) so
  it does not exercise the bug and does not need flipping.
- `test_cold_writer_*` only assert ranges + counts on `angles_deg`,
  never signed values; all green unchanged.
- All four named build-greps clean: `[scan-publisher-grep]`,
  `[hot-path-isolation-grep]`, `[m1-no-mutex]`, `[rt-alloc-grep]`.

### Wire format unchanged (cross-language SSOT preserved)

- `cold_writer::fill_last_scan` continues to passthrough raw CW
  `s.angle_deg` to `LastScan.angles_deg`. The SPA's PR #30
  (`poseCanvasScanLayer.ts`) negates client-side; that contract
  stays valid. C++ AMCL math and SPA rendering are decoupled.

### Out of scope (deliberate)

- Tier-2 AMCL parameter retuning. Convergence basin shape changes
  after this fix; sigma / particle-count tuning is a separate Phase 2
  follow-up. Numeric trigger for retuning ticket: post-OneShot pose
  drift > 5 cm/s for > 2 s (≥ 4 consecutive 10 Hz `/api/last_pose`
  samples with `√(Δx² + Δy²) > 5 mm`). See plan §Risks R2.
- `lidar_source_rplidar.cpp` raw decoding (Option γ rejected: would
  break PR #30's wire contract and require coordinated SPA deploy).
- `godo-mapping` (Docker pipeline already correct via `rplidar_ros2`).
- `godo-frontend` (Track D-2 / PR #30 already covers SPA).
- `XR_FreeD_to_UDP/*` (read-only).

### Mode-A folds applied

- M1: §Test strategy step 6 endpoint corrected from `(4.0, 7.0)` to
  `(5.7071, 6.2929)` after switching from yaw=90° to yaw=45° (T2).
- M2: `scan_ops.hpp` is a comment-only modify (was claimed
  NO-CHANGE in the original plan; now consistent with the .cpp
  comment).
- M3: TEST_CASE step 5 plugs `a = beams[0].angle_rad`, not
  `90·π/180` re-derived. Bias-block.
- S1: hpp comment text pinned verbatim.
- S2: audit closure under invariant (m) names all four categories
  including `csv_writer.cpp:95` and `sample.hpp:38-39`.
- S3: HIL truth-pose extraction script spelled out
  (`x_truth = origin_x + col·resolution`,
  `y_truth = origin_y + (height − 1 − row)·resolution`).
- S4: Tier-2 retuning trigger numeric threshold pinned (5 cm/s
  for > 2 s).
- T1: second beam at 270° pins both mirror directions.
- T2: yaw=45° exercises all four rotation-matrix terms.
- N4: HIL doc filename is `convergence_hil.md` (no per-track prefix).

---

## 2026-04-29 22:30 KST — Track D-5 sigma_hit annealing (OneShot)

### Why

Post-Track-D-3 HIL on news-pi01 (TS5 chroma studio) measured 0/10
OneShot convergences with the production default `σ_hit = 0.05 m`.
Empirical sweep (`.claude/memory/project_amcl_sigma_sweep_2026-04-29.md`,
2026-04-29 21:00 KST) showed a sharp convergence cliff between σ=0.1
and σ=0.2: σ=1.0 gives 2/10 single-basin, σ=0.2 gives 9/10 across 3
basins, σ≤0.1 gives 0/10. Single-σ AMCL cannot find a workable
trade-off — this is fundamental to the likelihood field's geometry, not
a tuning problem.

Track D-5 anneals σ_hit through `[1.0, 0.5, 0.2, 0.1, 0.05]`: phase 0
(σ=1.0) globally seeds and locks the unique basin at wide σ; subsequent
phases narrow σ around the carried pose to refine to cm-scale precision.
Final-phase σ matches the production default so the SPA/UDS contract
surface is unchanged. Operator rollback recipe: set BOTH
`amcl.sigma_hit_schedule_m = "0.05"` AND
`amcl.anneal_iters_per_phase = 25` to get pre-Track-D-5 single-σ
behaviour.

### Added

- `src/localization/cold_writer.cpp` —
  - `converge_anneal()` (public via cold_writer.hpp): file-level
    anneal helper that rebuilds the LikelihoodField at each phase's σ
    via `Amcl::set_field`, seeds globally for phase 0 / `seed_around`
    for phase k>0, and runs up to `cfg.amcl_anneal_iters_per_phase`
    iters per phase with the existing convergence early-exit.
  - `rebuild_lf_for_live()` (file-static): restores the persistent
    LikelihoodField to `cfg.amcl_sigma_hit_m` at OneShot completion so
    Live re-entry sees the operator-controlled σ field (Q2 / Mode-A
    S4 fold).
- `src/localization/amcl.hpp` / `.cpp` — `Amcl::set_field` swap method
  + thread-safety doc comment (single-thread cold-writer use only;
  Mode-A M3) + `static_assert(std::is_nothrow_move_assignable_v<
  LikelihoodField>)` (Mode-A S4) + `field()` getter for tests.
- `src/core/config_defaults.hpp` — `AMCL_SIGMA_HIT_SCHEDULE_M`,
  `AMCL_SIGMA_SEED_XY_SCHEDULE_M`, `AMCL_ANNEAL_ITERS_PER_PHASE`.
- `src/core/config.{hpp,cpp}` — 3 new fields + 2 CSV parsers
  (`parse_csv_doubles_or_throw`, `parse_csv_doubles_with_sentinel_or_throw`)
  + TOML/env/CLI handlers + `validate_amcl` cross-field checks
  (length match, monotonicity, [0.005, 5.0] range, sentinel first).
- `src/core/config_schema.hpp` — 3 new rows alphabetical
  (`amcl.anneal_iters_per_phase`, `amcl.sigma_hit_schedule_m`,
  `amcl.sigma_seed_xy_schedule_m`) + `amcl.sigma_hit_m` upper bound
  bumped 1.0 → 5.0; `static_assert(CONFIG_SCHEMA.size() == 37)` →
  `== 40` (Mode-A M1 / N3).
- `src/config/apply.cpp` — schedule key handlers in
  `read_effective` / `apply_one` + cross-field validation in
  `apply_set` so operators get `bad_value` on length-mismatch /
  non-monotonic / out-of-range schedule edits.
- `tests/test_amcl_scenarios.cpp::TEST_CASE("AMCL Scenario D —
  annealing recovers from global ambiguity")` — 3 sub-checks against
  a programmatic 10×10 m asymmetric grid (L-shape + corner box +
  pillar + doorway gap). Asymmetry is REQUIRE'd at the test top via
  the 4-yaw scan-signature check (Mode-A T1) so a future fixture
  tweak that re-symmetrizes the obstacle fails BEFORE running the
  algorithm-under-test. Sub-check 2 wall-clock CHECK < 5 s
  (Mode-A S3).
- `tests/test_amcl_components.cpp::TEST_CASE("Amcl::set_field — swap
  to a narrower σ field changes scan likelihood by closed-form ratio
  (Track D-5)")` — ratio-based pin (Mode-A T5), not just sign.
- `tests/test_config.cpp` — 9 new cases (defaults, TOML round-trip,
  length-1 fallthrough, non-monotonic reject, out-of-range reject,
  empty reject, length mismatch reject, sentinel-first reject,
  iters_per_phase=0 reject, sigma_hit_m=1.5 accepted under bumped
  bound — Mode-A T4).
- `tests/test_config_schema.cpp` — 2 new cases pinning the 3 new
  rows + the 1.0 → 5.0 sigma_hit_m bound.

### Changed

- `src/localization/cold_writer.{cpp,hpp}::run_one_iteration` — now
  takes `LikelihoodField& lf_inout` and delegates to
  `converge_anneal`; rebuilds `lf` to `cfg.amcl_sigma_hit_m` before
  returning. Yaw tripwire stays OUTSIDE `converge_anneal` (Mode-A
  M6) — runs once on the final-phase result only; intermediate-phase
  poses are not tripwire candidates.
- `src/localization/cold_writer.cpp::run_cold_writer` — passes the
  persistent `lf` into `run_one_iteration`; defensive
  `rebuild_lf_for_live` recovery in the OneShot exception handler.
- `tests/test_cold_writer_*.cpp` (5 files) — updated `run_one_iteration`
  call sites for the new `lf_inout` parameter; added
  `cfg.amcl_sigma_hit_schedule_m = {0.05}` + `anneal_iters_per_phase
  = 1..5` overrides to keep tests fast under the new annealing
  default.
- `tests/test_config_apply.cpp` — assertion counts 36 → 39, first key
  changed to `amcl.anneal_iters_per_phase`.
- `godo-webctl/src/godo_webctl/config_schema.py` +
  `godo-webctl/tests/test_config_schema.py` +
  `tests/test_config_schema_parity.py` +
  `tests/test_config_view.py` +
  `tests/test_app_integration.py` — Python schema mirror: row count
  37 → 40 (cross-language SSOT preserved).

### Removed

- (none)

### Tests

- New: 12 hardware-free cases (1 in test_amcl_scenarios, 1 in
  test_amcl_components, 9 in test_config, 2 in test_config_schema)
  + Python parity row-count assertions updated. ctest -L hardware-free
  → 45/45 PASS.
- All 9 in-scope build-greps clean (`[m1-no-mutex]`,
  `[scan-publisher-grep]`, `[hot-path-isolation-grep]`,
  `[hot-path-jitter-grep]`, `[jitter-publisher-grep]`,
  `[amcl-rate-publisher-grep]`, `[hot-path-config-grep]`,
  `[hot-config-publisher-grep]`). The 2 documented advisories
  (`udp/sender.cpp:103`, `uds/uds_server.cpp:119`) are pre-existing
  carryover from PR #28/#27 and outside this PR's scope.

### Out of scope (deliberate)

- Pipelined-parallel implementation (Track D-5-P, separate plan).
- Live-mode annealing (Track D-5-Live, separate plan).
- Retuning `amcl_sigma_xy_jitter_m` / `_yaw_jitter_deg` (kept at
  5 mm / 0.5°).
- `godo-frontend` SPA — no changes; SSE contract unchanged.
- `XR_FreeD_to_UDP/*` — read-only.
- Any change to `cold_writer::fill_last_scan` or
  `lidar_source_rplidar.cpp` (PR #30/#31 wire contract).
- HIL operator validation (P4-D5-9) — runs post-merge per
  `doc/convergence_hil.md`; recorded in
  `test_sessions/TS5/track_d_5_post_anneal.md` after operator runs
  10 OneShot calibrations on news-pi01.

### Mode-A folds applied (per .claude/tmp/plan_track_d_5_sigma_annealing.md §8)

- M1: schema row count 37 → 40 (3 new rows).
- M2: 9 named build-greps enumerated in test gates (only the 2
  pre-existing advisories carry over).
- M3: `Amcl::set_field` thread-safety pin in `amcl.hpp` doc comment.
- M4: `seed_around` σ_xy from explicit `sigma_seed_xy_schedule_m`
  schedule (option b — decoupled from σ_hit*0.5 heuristic).
- M5: invariant (n) text mentions "Phase k>0 reseeds via
  `cfg.amcl_particles_local_n`" so operators understand the cross-
  mode key affects BOTH Live AND OneShot phase k>0.
- M6: yaw tripwire stays OUTSIDE `converge_anneal`; `cold_writer.cpp:128`
  fires it once on the final-phase result only.
- S1: operator rollback recipe documented (above).
- S2: invariant (n) calls out RNG draw sequence is schedule-length-
  dependent; tests assert tolerances, never bit-exact pose values.
- S3: Scenario D sub-check 2 wall-clock CHECK < 5 s.
- S4: `static_assert(std::is_nothrow_move_assignable_v<LikelihoodField>)`
  near `set_field` declaration.
- S5: change-log header timestamped `2026-04-29 22:30 KST`.
- T1: Scenario D asymmetry REQUIRE step at test top.
- T2: Sub-check 1 RNG seed pinned to 42 (verified to fail).
- T3: Sub-check 2 tolerance `xy_err < 0.10 m` (NOT 0.05).
- T4: `sigma_hit_m=1.5` accepted under bumped bound + bound test in
  test_config_schema.
- T5: `set_field` test ratio-based against closed-form
  exp(-d²·(1/(2σ_n²) - 1/(2σ_w²))).
- N3: invariant (n) text reflects "OneShot anneals σ_hit; Live uses
  the static cfg.amcl_sigma_hit_m field, rebuilt on every OneShot
  completion."
- N5: Sub-check 3 title is "Schedule length 1 runs single-phase
  annealing" + tolerance-only assertion.
