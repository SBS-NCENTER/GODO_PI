# Project Progress

> **Purpose**: preserve cross-session, cross-machine context so the project can be resumed identically on Mac or Windows.
>
> **Conventions**:
>
> - Append a new block to "Session log" at the end of each session (newest first, dates in YYYY-MM-DD).
> - When a decision becomes firm, move it to "Decisions".
> - Track open items in "Next up" and remove them once resolved.
> - Detailed technical analyses live in dedicated reference documents; keep only pointers here.

---

## Current phase

**Phase 4-1 — RT hot path closeout → Phase 4-2 entry**. The code landed 2026-04-24 (16/16 hardware-free tests green, Mode-B APPROVE-WITH-NOTES plus a follow-up cleanup commit `49f874d`). The remaining Phase 4-1 work is host-side: run `scripts/setup-pi5-rt.sh`, apply the FreeD wiring + boot-config per `production/RPi5/doc/freed_wiring.md`, re-measure `godo_jitter` with RT privileges, and verify an end-to-end run against a loopback UDP listener. After those pass, Phase 4-2 (LiDAR + AMCL + cold-path deadband) becomes the active phase.

Earlier phases:
- Phase 0 (RPLIDAR C1 deep dive) completed 2026-04-20.
- Phase 1 (Python prototype) scaffolded 2026-04-22; several empirical measurements are still open (see Next up). Hardware-free gates of `godo_smoke` indirectly cover the "is the C1 healthy on RPi 5" question through live bring-up 2026-04-24.
- Phase 3 (RPi 5 C++ scaffold + `godo_smoke`) completed 2026-04-23.

---

## Decisions

### Project scope

- Use the RPLIDAR C1 to measure the crane base's world (x, y) at a user-triggered 1-shot moment.
- Add the resulting (dx, dy) offset to the FreeD X/Y, then send as UDP to Unreal Engine.
- Z / Pan / Tilt / Roll / Zoom / Focus are trusted to the crane's own sensors and are out of scope.
- Error tolerance: 1–2 cm; tighter is better.

### Physical setup

- The RPLIDAR is mounted at the **pan-axis center**, so its world (x, y) is invariant under pan; only its yaw rotates.
- Unknowns to solve: `(x, y, yaw)` — a standard 2D SLAM/localization problem.
- Origin = base location at calibration time; must be re-settable.
- People move below LiDAR height, so they are largely out of the LiDAR's field of view.
- SHOTOKU Ti-04VR is a **three-wheels steering** dolly. Operational rule: **wheels always parallel** — the base does not rotate, only translates.
- The crane base **cannot enter the chroma set** (floor protection). Movable area = staff space + between the two doors.

### Algorithm direction (confirmed 2026-04-21)

- **Yaw handling**: Approach B — **AMCL outputs (x, y, yaw) 3-DOF simultaneously**. The LiDAR's yaw is inferred from how walls/features line up against the pre-built map. No separate yaw-correction step.
- **Localization**: O3 first (pre-built map + AMCL), then O4 extension (retro-reflector markers). The marker layer is gated on the Phase 1 measurement of C1 marker distinguishability.
- **SHOTOKU FreeD Pan semantics**: **base-local** (the pan-head encoder, relative to the dolly). Because the wheels-parallel rule keeps dolly yaw constant, the base-local reading is effectively world-frame in practice. We only merge (dx, dy); Pan is not touched.
- **Uses of LiDAR yaw**: (1) as the 3-DOF state variable inside AMCL, (2) as a safety tripwire — if yaw drifts more than 2° from the last known baseline, set a UDP warning flag and raise an operator alert.

### Software stack (confirmed 2026-04-21)

- **Hardware**: Raspberry Pi 5 (Debian 13 Trixie, 8 GB RAM, 32 GB microSD).
- **No ROS 2 at runtime** — the RPi 5 does not run ROS 2 during operation.
- **Docker is used only for map building** — an `ubuntu:24.04` + `ros2 jazzy` + `slam_toolbox` container is spun up once, then shut down. Only the resulting `.pgm` and `.yaml` files are committed to the repo.
- **Production application**: a single native C++ binary (`godo-tracker`) that subsumes the legacy Arduino's FreeD→UDP role. Dependencies:
  - `rplidar_sdk` (official C++ driver)
  - `Eigen` (linear algebra)
  - In-house AMCL (~500–1000 LOC)
  - PGM map loader (~tens of LOC)
  - `systemd` service for boot
- **59.94 fps UDP sending** is realized via `SCHED_FIFO` + CPU pinning + `mlockall` + `clock_nanosleep(TIMER_ABSTIME)`, aiming for p99 jitter < 200 µs — comparable to the Arduino. A PREEMPT_RT kernel is not required.
- **Arduino R4 WiFi**: the existing FreeD→UDP firmware is retained as a **rollback card**. On RPi 5 failure, swapping the cable reverts to the Arduino.
- **Python (UV)**: used only for Phase 1 measurement / Phase 2 algorithm prototyping; not part of the production binary.

See [RPLIDAR/RPLIDAR_C1.md](./doc/RPLIDAR/RPLIDAR_C1.md) for the supporting evidence.

---

## Next up

### Phase 4-1 closeout (host-side, no further code needed)

1. **Run `scripts/setup-pi5-rt.sh` on the RPi 5 as root** — applies `setcap cap_sys_nice,cap_ipc_lock+ep` to `godo_tracker_rt` and `godo_jitter`, appends `@godo - rtprio 99` + `@godo - memlock unlimited` to `/etc/security/limits.conf` (idempotent), verifies `dialout` group membership on the user running the tracker.
2. **Apply the FreeD wiring + boot config** per `production/RPi5/doc/freed_wiring.md`:
   - YL-128 VCC → Pi 3V3 (pin 1), GND → pin 6, TXD → pin 10 (GPIO15 / UART0 RX); RXD unused.
   - `/boot/firmware/config.txt`: `enable_uart=1`, `dtparam=uart0=on`.
   - `/boot/firmware/cmdline.txt`: remove `console=serial0,115200`.
   - Reboot; `stty -F /dev/ttyAMA0 38400 parenb parodd cs8 -cstopb` must succeed.
3. **Re-measure `godo_jitter` with RT privileges** — `scripts/run-pi5-jitter.sh --duration-sec 60 --cpu 3 --prio 50`. Record p50/p95/p99/max in a new `test_sessions/TS<N>/jitter_summary.md` and amend PROGRESS.md. This is the baseline that will be compared against the SYSTEM_DESIGN.md p99 < 200 µs design goal in Phase 5.
4. **End-to-end verification** — launch `godo_tracker_rt` and a loopback `tcpdump -i any -n udp port 6666 -X` listener; confirm FreeD packets flow at ~60 Hz with non-zero Pan/X/Y after the stub cold writer fires its canned offset.
5. **IRQ inventory** — fill in `production/RPi5/doc/irq_inventory.md` by enumerating xHCI and eth IRQs on the target (`grep -E "xhci|eth" /proc/interrupts`) and proposing `smp_affinity_list` values that keep CPU 3 clean.

### Phase 4-2 — cold path + integration (queued)

- Promote `src/godo_smoke/lidar_source_rplidar` to a reusable `src/lidar/` component (keep `godo_smoke` binary intact as a bring-up tool).
- Port AMCL from the Phase 2 Python reference to `src/localization/`. Add `libeigen3-dev` to the apt prereqs.
- Implement the **cold-path deadband filter** (SYSTEM_DESIGN.md §6.4.1) in Thread C: drop new poses within ±10 mm / ±0.1° of `last_written` unless `calibrate_requested` bypasses the filter.
- Wire the real cold-path writer into `godo_tracker_rt/main.cpp`, replacing the `// TODO(phase-4-2)` stub thread.
- systemd unit `godo-tracker.service` with `Type=simple`, `Restart=on-failure`, `CPUAffinity=0-3`, `CPUSchedulingPolicy=fifo`, `CPUSchedulingPriority=50`.
- Hardware watchdog wiring: `/etc/systemd/system.conf` → `RuntimeWatchdogSec=10s`.
- Document the Arduino rollback procedure (README + operator card).

### Phase 4-3 — `godo-webctl` minimal (queued, separate process)

- New top-level directory `/godo-webctl/` with `pyproject.toml` (UV).
- Three endpoints: `/api/health`, `/api/calibrate`, `/api/map/backup`.
- Unix-domain-socket JSON-lines client to the tracker (`/run/godo/ctl.sock`).
- systemd unit `godo-webctl.service` with `After=godo-tracker.service`, `Wants=godo-tracker.service`, `RuntimeDirectory=godo` (auto-cleans the UDS on crash).
- Single static `index.html` status page (no framework — React lands in Phase 4.5).

### Phase 4.5 — control-plane extensions (deferred to after Phase 5 field pass)

- `/api/config` GET/PATCH with the reload-class table (hot / restart / recalibrate) from SYSTEM_DESIGN.md §11.3.
- `/api/map/edit` — numpy/OpenCV-based editor for removing moving fixtures from the PGM.
- `/api/map/update` — trigger the Docker re-mapping workflow.
- React frontend with a settings page that exposes the `hot`-class tunables live.
- **Currently in Phase 4-1 state**: `test_rt_replay` narrows byte-for-byte assertion to type byte + cam_id + checksum because the stub cold writer is timing-non-deterministic. Phase 4-2's real AMCL writer makes the full-byte assertion practical — tighten the test there.

### Phase 5 — field integration (queued)

- In-studio integration with the crane + RPi 5 + Unreal Engine.
- Long-run stability test (≥ 8 h).
- Jitter comparison: post-`setup-pi5-rt.sh` RPi 5 numbers vs the legacy Arduino numbers (must measure the Arduino on the same bench).
- Operator's manual (bring-up sequence, daily preflight, triggers, rollback).

### Phase 1 items still pending (measurement, held)

- **Retro-reflector distinguishability test** — 3M tape at 0.5/2/5/10 m, angles 0/30/45/60/75°; thresholds marker Q ≥ 200, background ≤ 100. Decides whether O4 marker layer is viable.
- **Chroma-wall NIR reflectivity** — verify C1 effective range against the green / blue walls.
- **Floor tilt survey at TS5** — held by user 2026-04-24 pending studio access. Methodology ready at `doc/hardware/floor_tilt_survey_TS5.md`; leveling-mount decision gate depends on the result (`doc/hardware/leveling_mount.md`).
- **Noise characterization** — `uv run python scripts/analyze.py --mode noise` on 100+ static frames, per-direction variance, √N rule verification. Low priority now that the 3-way comparison (Phase 3 / 4-1 bring-up) has established the C1 behaves per spec on the RPi 5.

### Open questions (blockers)

- **Q6**: **resolved 2026-04-24** — trigger UX is both physical GPIO button + HTTP POST via `godo-webctl`, converging on a single `std::atomic<bool> calibrate_requested` primitive. See SYSTEM_DESIGN.md §6.1.3.
- **Q7**: **resolved 2026-04-21** — RPi 5 C++ binary receives FreeD, merges the offset, and sends UDP. Arduino retained as a rollback card.
- None open.

---

## Session log

### 2026-04-24 (close)

- **Mode-B review of the Phase 4-1 implementation** (commits `f28abe7..72f4c28`) returned **APPROVE-WITH-NOTES**: no must-fixes, four bounded should-fix items. All four folded into follow-up commit `49f874d`: (S1) `yaw::wrap_signed24` header comment now documents the dual use at pan re-encode AND X/Y re-encode (both protocol-mandated ±2^23 lsb folds); (S2) `freed::SerialReader` gates `O_NONBLOCK` on the `tcsetattr`-failure (PTY) path only — real PL011 ttys keep the blocking `read()` + VTIME=1 profile so production jitter is not perturbed by a userspace 10 ms nap; (S3) new deviation #5 in `production/RPi5/CODEBASE.md` documents that `test_rt_replay` narrows the plan's byte-for-byte UDP assertion to type + cam_id + checksum (the stub cold writer's phase is timing-dependent; Phase 4-2's real AMCL writer will make full-byte parity practical); (S4) magic literals `1000.0`, `64.0`, `32768.0` in `apply_offset_inplace` replaced with new derived constants `FREED_POS_LSB_PER_M` and `FREED_PAN_LSB_PER_DEG` in `core/constants.hpp`.
- **Nice-to-haves applied** in the same cleanup: `main.cpp` now uses the 3-arg POSIX `main(argc, argv, envp)` signature (drops the redundant `extern char** environ;`); startup stanza now matches SYSTEM_DESIGN.md §6.2 ordering (`mlockall` → `block_all_signals_process` → `setlocale`) so spec and code stay in lockstep.
- **Push**: all eight commits of the day shipped to `origin/main` at `SBS-NCENTER/GODO_PI`: `8363465 .. 49f874d` (the final commit is the Mode-B cleanup; `origin/main` is at `49f874d`).
- **New hardware reference directory** `/doc/hardware/RPi5/` with the official Raspberry Pi 5 product brief, mechanical drawing, RP1 peripherals manual, and the UART connector spec (all fetched from `pip.raspberrypi.com`). The full Pi 5 schematic is **not public** (unlike every prior Pi model); the product brief + RP1 peripherals cover every interface GODO touches. A condensed 40-pin pinout with GODO wiring notes lives in `doc/hardware/RPi5/README.md` for quick reference.

### 2026-04-24 (late)

- **Phase 4-1 RT hot path landed** at `/production/RPi5/` via the full agent pipeline (planner Plan v2 with 6 must-fix + 4 should-fix items → reviewer Mode-A approval → writer). Two new binaries (`godo_tracker_rt`, `godo_jitter`), 7 new static libs (core, yaw, smoother, freed, udp, rt, plus an interface lib for tomlplusplus), and 10 new hardware-free test targets.
- **tomlplusplus v3.4.0** added as submodule at `production/RPi5/external/tomlplusplus` (SHA `30172438cee64926dc41fdd9c11fb3ba5b2ba9de`), wrapped by `cmake/tomlplusplus.cmake` as `tomlplusplus::tomlplusplus` INTERFACE target.
- **Config loader precedence chain** (CLI > env > TOML > defaults) with unknown-key rejection. TOML path from `GODO_CONFIG_PATH` env var, default `/etc/godo/tracker.toml`. All Tier-2 constants live in `src/core/config_defaults.hpp`; Tier-1 invariants (FreeD field offsets, checksum scheme, 59.94 Hz period) in `src/core/constants.hpp`. Magic-number ban enforced by review and by the `[rt-alloc-grep]` smoke pass appended to `scripts/build.sh`.
- **Seqlock + gen-edge smoother**: `src/core/seqlock.hpp` is single-writer / N-reader with 64-byte alignment (false-sharing guard, asserted by test). Writer bumps an atomic sequence before and after the payload write; even sequence numbers mean "consistent" and double as the smoother's update counter. `src/smoother/offset_smoother.cpp` uses `gen_new != target_g_` for edge detection (integer exact, not float equality), snaps `live ← target` by value-copy when `elapsed >= t_ramp_ns`, and uses `yaw::lerp_angle` for shortest-arc dyaw interpolation.
- **Yaw primitives** (`src/yaw/yaw.cpp`) are pure free functions. 12 pinned byte-identical tests per SYSTEM_DESIGN.md §6.5 — fixed-point identity at 0/90/180/270, endpoint stability at frac∈{0,1}, short-arc 359→1, aliased endpoints 0→360, and the 720° collapse documenting the `|b-a|<360` precondition.
- **FreeD D1 parser** (`src/freed/d1_parser.cpp`) reproduces the legacy Arduino checksum `(64 - sum(bytes[0:28])) & 0xFF` and the byte-layout from `XR_FreeD_to_UDP/src/main.cpp` L17-31 + L67-85 + L185-191. Non-D1 type bumps a monotonic atomic counter and logs once. `src/freed/serial_reader.cpp` opens the port read-only (crane is unidirectional; `open()` EBUSY prints a pointer to the boot-config §B fix), installs termios 8O1 + `TIOCEXCL`, and frames packets with the legacy memmove-based re-sync on mismatch.
- **UdpSender uses a connected SOCK_DGRAM** (so hot-path `send()` is cheaper than `sendto`); non-blocking with an EAGAIN-miss counter that logs once per 1000 consecutive misses. `apply_offset_inplace` decodes X/Y/Pan as signed-24 big-endian, adds `dx*64000 / dy*64000 / dyaw*32768` (metres → lsb and deg → lsb), re-encodes via `yaw::wrap_signed24`, and recomputes the checksum. All-zero packets are interpreted as "no FreeD received yet" and skipped with a one-shot log.
- **RT lifecycle helpers** (`src/rt/rt_setup.cpp`) gate `mlockall` on `RLIMIT_MEMLOCK` — a host without `setup-pi5-rt.sh` applied has a default 8 MiB memlock rlimit, which is below the 8 MiB-per-thread stack requirement. Without this gate, `MCL_FUTURE` silently causes every subsequent `pthread_create` to fail with EAGAIN. The helper now checks the rlimit first and returns false + actionable stderr if below 128 MiB. Production behaviour (after `setup-pi5-rt.sh`) is unchanged.
- **Hardware-UART wiring doc** at `production/RPi5/doc/freed_wiring.md` — §A wiring (YL-128 VCC from Pi 3V3 NOT 5 V; resistor dividers banned, with cite to the Arduino R4 framing-error lesson), §B boot config (`/boot/firmware/config.txt` adds `enable_uart=1` + `dtparam=uart0=on`; `/boot/firmware/cmdline.txt` drops `console=serial0,115200`), §C verification (stty 8O1 smoke test + optional GPIO14↔15 jumper loopback).
- **End-to-end replay test** (`test_rt_replay.cpp`) spawns `godo_tracker_rt` as a subprocess via `posix_spawn`, drives canned bytes down a PTY master (with 8O1 termios installed on both ends), captures UDP packets on a loopback ephemeral port, and verifies type byte + cam_id passthrough + checksum round-trip. PTY-based `test_freed_serial_reader` covers the memmove resync path (1-byte garbage prefix + valid packet).
- **Jitter numbers on news-pi01 without RT privileges** (baseline, not the design-goal path): `godo_jitter --duration-sec 60 --cpu 3 --prio 1` → `ticks=3596, mean=110 µs, p50=58 µs, p95=145 µs, p99=2028 µs, max=5338 µs`. These are with SCHED_OTHER (CAP_SYS_NICE absent on the test host). The post-`setup-pi5-rt.sh` numbers are the ones that will be compared against the 200 µs p99 design goal in Phase 5.
- **Build gate**: `scripts/build.sh` runs `ctest -L hardware-free` (16 tests green, incl. all 6 godo_smoke regressions) and appends a `[rt-alloc-grep]` smoke pass that scans `src/rt`, `src/udp`, `src/smoother`, `src/yaw`, `godo_tracker_rt/main.cpp`, and `freed/serial_reader.cpp` for `new` / `malloc` / `std::string(...)` / `vector::push_back`. One hit surfaced (UdpSender constructor error-path `std::string`); it is off-the-hot-path (init-time) and explicitly justified in `CODEBASE.md` invariant (e) deviations.
- **Known scaffolding**: `thread_stub_cold_writer` in `godo_tracker_rt/main.cpp` emits a canned offset sequence at 1 Hz. Tagged `// TODO(phase-4-2): replace with AMCL writer thread from src/localization/`. Its sole purpose is to exercise the seqlock + smoother + UDP pipeline end-to-end before LiDAR + AMCL land.

### 2026-04-23

- **Floor tilt survey + leveling mount scaffolding landed** at `/doc/hardware/` via the agent pipeline (planner Plan A v2 → reviewer Mode-A conditional approval → writer). Two methodology documents are now in the repo: `floor_tilt_survey_TS5.md` (hybrid 0.25 m / 0.5 m grid, DWL2000XY primary instrument, drift-gate + cross-observer protocol, TS5 session sequencing with 30 min buffers) and `leveling_mount.md` (budget-driven Tier 1 ≤ 0.06° / gray 0.06°–0.12° / Tier 2 > 0.12° thresholds, passive-shim vs. 2-axis-gimbal candidates with yaw-lock risk spec, post-install 5-point acceptance test). CLAUDE.md §5 directory tree updated with the `/hardware` branch (Unicode box-drawing, not a table). PROGRESS.md `Next up` #8 and #9 added; Phase 2 preparations now gated on item 9.2.
- **Field-dependent work remains pending**: #8 physical measurement at TS5, #8.4 analysis, #9.2 candidate selection, #9.3 `SYSTEM_DESIGN.md §1 / §8` update (Parent-led), #9.4 acceptance test. Raw inclinometer CSV is **not committed** (Reviewer Amendment N2) — only summary.json + heatmap.png + §5 fill-in will be committed post-session.

- **Phase 3 RPi 5 C++ scaffold landed** at `/production/RPi5/` via the full agent pipeline (planner → reviewer-A conditional approval → writer). Delivers the `godo_smoke` binary and three-way comparison workflow.
- **Toolchain**: Debian 13 Trixie aarch64, gcc 14.2, CMake 3.31.6, doctest 2.4.11 (apt `doctest-dev`), OpenSSL 3.5.5 (apt `libssl-dev`). `sudo apt install doctest-dev libssl-dev` was the only new host-side install this session.
- **RPLIDAR SDK submodule** added at `production/RPi5/external/rplidar_sdk` pinned to SHA `99478e5fb90de3b4a6db0080acacd373f8b36869` (2024-04-09 master HEAD — the project has no release tag covering the C1). `cmake/rplidar_sdk.cmake` wraps the upstream Makefile via `ExternalProject_Add(BUILD_IN_SOURCE)` and exposes the result as `rplidar_sdk::static`. P3-2b gate passed: standalone `make` succeeded, `ultra_simple` probe printed usage + clean exit, `git status --ignored` on the submodule is clean (the submodule's own `.gitignore` covers `obj/` and `output/`; outer `.gitignore` adds a defensive mirror).
- **Architecture**: no ABC, per `prototype/Python/src/godo_lidar/capture/sdk.py:39–45` precedent. `LidarSourceRplidar` (production) and `tests/LidarSourceFake` (tests) are duck-typed twins with deliberately different class names; each test target's source list picks one. Zero `virtual` in `src/godo_smoke/*.hpp`.
- **CSV byte-identity** with the Python prototype is enforced by `test_csv_parity`: the test constructs the same `Frame` in both languages, writes via C++ `CsvWriter` and Python `CsvDumpWriter`, and compares the two files byte-for-byte. Passes. `fopen(path, "wb")` prevents CRLF translation on non-POSIX hosts; `setlocale(LC_ALL, "C")` in `main()` pins numeric formatting.
- **Session-log hashing uses chunked EVP** (`EVP_DigestInit_ex` / `EVP_DigestUpdate` in 64 KiB chunks / `EVP_DigestFinal_ex`), matching the Python `hashlib.sha256().update()` streaming path. One-shot `EVP_Digest()` is forbidden per CODEBASE.md.
- **Test matrix**: six hardware-free targets (`test_csv_writer_writes`, `test_csv_writer_readback`, `test_csv_parity`, `test_session_log`, `test_args`, `test_sample_invariants`) all green on RPi 5. One hardware-required target (`test_lidar_live`) is built but not run by default; execute with `ctest -L hardware-required` once the C1 is plugged in. `scripts/build.sh` runs the configure + build + hardware-free ctest gate in one command.
- **Structural bias-block**: `test_csv_writer_readback` has an include path that excludes `src/godo_smoke/`. Any `#include "csv_writer.hpp"` in that file must fail to compile — guards against the test silently importing what it is supposed to be validating.
- **Documentation**: `production/RPi5/README.md` rewritten (Prerequisites, Build, Run, Test, Rollback). New `production/RPi5/doc/smoke.md` documents the three-way comparison flow (stock `ultra_simple` ↔ `godo_smoke` ↔ Python SDK / raw backends). New `production/RPi5/CODEBASE.md` pins four invariants: (a) no-ABC, (b) test-include-split, (c) hot-path allocation justification, (d) LC_ALL threading + session-log parity scope-out.
- **Smoke-area vs. test-session distinction** formalised: `production/RPi5/out/<ts>_<tag>/` is the bring-up archive (ad-hoc, gitignored); `scripts/promote_smoke_to_ts.sh` promotes a notable run to `<repo-root>/test_sessions/TS<N>/`, annotating the session log with `promoted_from:`. Recorded in `.claude/memory/project_test_sessions.md`.
- **Next physical action**: plug the C1 into the RPi 5 (`/dev/ttyUSB0`, 460800 bps), run `production/RPi5/scripts/run-pi5-smoke.sh --frames 100 --tag first_light`, then execute the matching captures for `ultra_simple` and the two Python backends at the same static position, and diff them per `production/RPi5/doc/smoke.md`.



- **Phase 1 Python scaffold complete** at `/prototype/Python/` via the full agent pipeline (planner → reviewer-A → writer → reviewer-B → fix pass). Ready for empirical capture.
- **SYSTEM_DESIGN.md §10 added**: two-backend acquisition framework (SDK-wrapper vs Non-SDK), library plan, CSV+TXT dump format, four-step test sequence (backend parity → noise → reflector → chroma NIR).
- **Backend framing corrected honestly**: `pyrplidar` is ❌ for official C1 support per RPLIDAR_C1.md §4, so the "SDK backend" is relabeled **SDK-wrapper backend** with an explicit caveat. The authoritative three-way comparison (adding the official `ultra_simple` CLI) is deferred as a Phase 1 follow-up (now item #7 in Next up).
- **Non-SDK backend implements standard scan mode only** (cmd `0xA5 0x20`, 5-byte sample layout per SLAMTEC v2.8 PDF). Express / Ultra / dense_boost are explicitly out of scope for Phase 1. Motor speed command is `0xA8 MOTOR_SPEED_CTRL` (RPM u16 LE) — C1 has no MOTOCTL pin per RPLIDAR_C1.md §6.
- **SDK-wrapper motor control limitation caught in review**: `pyrplidar` only exposes the A1-style `0xF0 SET_MOTOR_PWM` command, which the C1 ignores. The scaffold now hard-errors if `--rpm` is passed with `--backend sdk` — motor-speed-controlled runs must use the raw backend.
- **Every capture produces two artifacts** so future sessions can re-analyze without hardware: `data/<ts>_<backend>_<tag>.csv` (one row per sample) + `logs/<ts>_<backend>_<tag>.txt` (host/OS/backend/params/stats/operator notes + `csv_sha256` + `csv_byte_count`).
- **Test strategy bias-blocked**: `tests/test_raw_protocol.py` fixtures derived bit-by-bit from the SLAMTEC v2.8 PDF (inline citations); `tests/test_csv_dump.py` reads back via stdlib `csv.DictReader` with a literal header constant duplicated inside the test file (not imported from production). All 29 tests green.
- **Scaffold deliberately lean**: no `capture/base.py` ABC (2 backends don't justify it), one flat `analyze.py` module (not an `analysis/` package), two CLI scripts (`capture.py --backend {sdk,raw}`, `analyze.py --mode {...}`), no `scikit-learn` (Phase 1 reflector test is a threshold check). All per CLAUDE.md §6 minimal-code rule.

### 2026-04-21 (late)

- **Agent pipeline formalized**: three agents (planner / writer / reviewer) defined under `.claude/agents/`. Reviewer has two modes: Mode-A reviews plans, Mode-B reviews code. Writer owns tests (C1 option).
- **XR_FreeD_to_UDP copied into the GODO repo** as `/XR_FreeD_to_UDP/`. The inner `.claude/` folder was removed for cleanliness. The folder is **read-only** for every agent — strictly reference.
- **FreeD Pan semantics corrected**: after tracing the user's two scenarios, the Pan value is actually **base-local**, not world-frame as initially claimed. The design conclusion (no Pan correction while wheels stay parallel) is unchanged because dolly yaw is a physical constant; the reasoning is tighter now.
- **Base-rotation edge case logged**: if the base ever did rotate, `LiDAR_yaw − FreeD_Pan` reconstructs `base_yaw`, so auto-correction is a future option. MVP still warns and stops for simplicity and safety.
- **AMCL handles yaw for free**: because the map lives in world-frame coordinates, AMCL inherently outputs `(x, y, yaw)` together; no separate yaw-correction step is required. Documented this clarification.

### 2026-04-21 (early)

- **Algorithm direction finalized**: Approach B (3-DOF simultaneous estimation), O3 (map + AMCL) first, O4 (+markers) as a later extension.
- **SHOTOKU Ti-04VR research**: three-wheels steering dolly; VR data includes Pan / Tilt / Zoom / Focus / Camera X / Y / Z.
- **ROS 2 runtime banned**: no official ROS 2 binaries for Debian 13 Trixie. Runtime stays native C++; Docker is used only for one-time map building.
- **Language strategy**: Python (UV) for Phase 1–2, C++ for Phase 3 onward.
- **Mapping area constrained**: the crane base cannot enter the chroma set, so only the staff area + between the doors is mapped. Chroma walls act as stable background landmarks.
- **Windows-side Python test succeeded**: raw LiDAR data came out clean (close to RoboStudio quality) when the official SDK was used.
- **Phase 1 items broken down** into concrete measurement tasks in `PROGRESS.md`.

### 2026-04-20

- **Initial design session**.
- **CLAUDE.md** restructured into a nine-section guide.
- **Phase 0 completed**: [RPLIDAR/RPLIDAR_C1.md](./doc/RPLIDAR/RPLIDAR_C1.md) authored from the official SLAMTEC datasheet.
- Two PDFs (C1 datasheet v1.0, S&C-series protocol v2.8) saved to [RPLIDAR/sources/](./doc/RPLIDAR/sources/) for offline reference.
- `PROGRESS.md` created for cross-session, cross-machine continuity.

---

## Quick reference links

- Project guide: [CLAUDE.md](./CLAUDE.md)
- **End-to-end design**: [SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md)
- RPLIDAR C1 specs & analysis: [RPLIDAR/RPLIDAR_C1.md](./doc/RPLIDAR/RPLIDAR_C1.md)
- **Raspberry Pi 5 hardware reference**: [doc/hardware/RPi5/README.md](./doc/hardware/RPi5/README.md) — 40-pin pinout, GODO wiring (YL-128 → UART0), and the official Pi 5 PDFs in `sources/`.
- **Phase 4-1 FreeD wiring**: [production/RPi5/doc/freed_wiring.md](./production/RPi5/doc/freed_wiring.md) — authoritative pin-by-pin + boot config + verification procedure.
- **Session history (Korean)**: [doc/history.md](./doc/history.md) — date-organized session summaries for human readers.
- Embedded reliability checklist: [Embedded_CheckPoint.md](./doc/Embedded_CheckPoint.md)
- Legacy asset (now inside the repo): [/XR_FreeD_to_UDP/](./XR_FreeD_to_UDP/) — Arduino R4 WiFi FreeD→UDP converter. Serves as a FreeD D1 protocol reference and a rollback card. Its functionality is being absorbed by the RPi 5 binary.
