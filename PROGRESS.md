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

**Phase 4-1 — RT hot path closeout COMPLETE 2026-04-25 → Phase 4-2 entry**. The code landed 2026-04-24 (16/16 hardware-free tests green, Mode-B APPROVE-WITH-NOTES plus follow-up cleanup `49f874d`). Host-side bring-up complete on news-pi01: FreeD wiring + boot-config (live 60 PPS), `setup-pi5-rt.sh` + `ncenter` limits.conf, end-to-end `godo_tracker_rt` → 127.0.0.1:6666 loopback verified at 60 PPS, IRQ inventory + recommended pinning, and the **four-step CPU 3 isolation stack measured** (SCHED_FIFO 50 → +IRQ pin → +`isolcpus=3` → +`rcu_nocbs=3`). Final production-config jitter on this idle dev host: **p99 = 12.7 µs, max = 28.6 µs**, ~160× better than SCHED_OTHER baseline and ~16× under the 200 µs design goal. `nohz_full=3` is in cmdline as design-intent marker but ignored by the stock RPi Debian Trixie kernel (`CONFIG_NO_HZ_FULL=n`); custom kernel build not justified. See `test_sessions/TS5/jitter_summary.md` for the per-step contribution table. Phase 4-2 (LiDAR + AMCL + cold-path deadband + persisted IRQ pin) is now the active phase.

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
- **Uses of LiDAR yaw**: (1) as the 3-DOF state variable inside AMCL.

### Operating modes (clarified 2026-04-26)

CLAUDE.md §1 prior wording — *"user-triggered 1-shot, not continuous tracking"* — was incomplete. There are **4 user-triggered actions**, all on-demand (no autonomous mode):

| # | Action | Trigger | Implementation phase |
| --- | --- | --- | --- |
| 1 | Initial / re-do mapping | Operator (Docker) | SYSTEM_DESIGN.md §4 |
| 2 | Map editing (remove moved fixtures) | Operator (webctl) | Phase 4.5 |
| 3 | **1-shot calibrate** (high-accuracy) | GPIO button / HTTP `/api/calibrate` | **Phase 4-2 B (current)** |
| 4 | **Live tracking** (low-accuracy, toggle) | GPIO button / HTTP `/api/live` | **Phase 4-2 D** |

The smoother + 60 Hz hot path (Phase 4-1) was designed primarily around mode (4): Live mode publishes new `Offset`s at ~10 Hz from the cold writer; the smoother interpolates so UE renders at a steady 59.94 fps. **Mode (3) inherits the smoother as a side-benefit** — operator-triggered jumps become smooth ~500 ms ramps. If only mode (3) existed, the smoother would be optional. The architecture exists because mode (4) needs it, mode (3) gets it for free.

Trigger primitive: `std::atomic<godo::rt::AmclMode> g_amcl_mode` (replaces the Phase 4-1 `std::atomic<bool> calibrate_requested` per Phase 4-2 B). Three-state machine: `Idle` ↔ `OneShot` ↔ `Live` (mode 4 body deferred to Phase 4-2 D; current build stubs the `Live` branch).

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

### Phase 4-1 closeout — DONE 2026-04-25

All host-side bring-up steps complete. See per-step session log entry below. The remaining items below have moved to Phase 4-2 because they are code/systemd integration, not measurement.

> Carried into Phase 4-2:
> - **Persisted IRQ pinning** via systemd unit (currently runtime-only via `.claude/tmp/apply_irq_pin.sh`). Design: a `/etc/godo/irq-pinning.conf` lists device patterns + target affinity, so adding new devices is a config edit (not a code change).
> - **Tracker-startup IRQ pin** for ttyAMA0 (irq 125) — PL011 only registers after the first `open()`, so the pin must run AFTER `godo_tracker_rt` starts. Use `ExecStartPost=` or move the pin into the tracker binary.
> - **GUI / 터치스크린 IRQ list extension** — production runs with monitor + keyboard + mouse + touchscreen (model TBD, ETA ~2 days from 2026-04-25). When the touchscreen is connected, identify its interface (USB-HID via xhci already pinned, or I²C via irq 163/164 needs pinning) and extend the IRQ list to include `v3d_core0/hub` (165/166), `vc4 hdmi/crtc/hvs` (167-181), `codec` (185), and any I²C touch IRQ. Mechanism is identical; only the device pattern list changes.

### Phase 4-2 — cold path + integration (in progress)

- ✅ **A. LiDAR component-isation 완료 2026-04-25 (late)** — `src/godo_smoke/{sample.hpp, lidar_source_rplidar.{cpp,hpp}}` → `src/lidar/` (`godo_lidar` static lib, namespace `godo::lidar`). `godo_smoke` 바이너리는 새 lib에 link. `lidar_source_rplidar.cpp`는 `godo::rt::monotonic_ns` 사용으로 godo_smoke 의존성 제거. 16/16 hardware-free tests PASS. CODEBASE.md "2026-04-25 (late)" 섹션에 변경 기록 + invariant (a) duck-typed twin 룰은 그대로 유지 (이름만 `godo::lidar::test::LidarSourceFake`로 변경).
- ✅ **B. AMCL C++ port — OneShot mode 완료 2026-04-26** — `src/localization/` 새 모듈 (godo_localization static lib): `OccupancyGrid` + `load_map` (slam_toolbox PGM/YAML), `LikelihoodField` (Felzenszwalb 2D EDT), `Pose2D` + circular stats, `Rng`, `class Amcl` (step()/converge() split), `AmclResult`, `cold_writer` state machine (Idle/OneShot real, Live stubbed). `godo_tracker_rt/main.cpp` stub 제거 + `run_cold_writer` wired + SIGTERM watchdog. `core::AmclMode` enum이 `calibrate_requested` 대체. 24/24 hardware-free tests PASS (5 신규: circular_stats, pose, amcl_components, cold_writer_offset_invariant, amcl_scenarios). 새 invariant (f) 추가 (AMCL no-virtual). `[m1-no-mutex]` build-gate 추가 (cold_writer.cpp wait-free contract). 풀 파이프라인 (planner → reviewer-A → writer → reviewer-B + Mode-B follow-ups). 상세는 `production/RPi5/CODEBASE.md` Wave 1 + Wave 2 섹션, 계획서는 `.claude/tmp/plan_phase4_2_b.md` (post-merge 삭제 가능).
- ✅ **C. Cold-path deadband filter 완료 2026-04-26 (continued)** — 새 header-only 모듈 `src/localization/deadband.hpp` (3개 inline 헬퍼: `deadband_shortest_arc_deg`, `within_deadband` 순수 predicate, `apply_deadband_publish` 시임 컴포저). `cold_writer.cpp`의 publish 경로가 identity passthrough → `apply_deadband_publish(...)` 한 줄 호출로 교체. `Offset last_written` 가 `run_cold_writer`에 Thread-C-local 상태로 추가되어 `run_one_iteration` 까지 in-out 파라미터로 plumbed. **기존 `cfg.deadband_mm` / `cfg.deadband_deg`** 재사용 (별도 `amcl_deadband_*` 키 추가 안 함 — SSOT). 새 테스트 `test_deadband.cpp` 14 cases / 140 assertions: per-axis check (NOT Euclidean) pin, strict `<` boundary pin, yaw wrap symmetric (359.95° ↔ 0.02°), forced=true OneShot bypass, sub-deadband × 100회 slow-drift 방지 pin, 교대 accept/reject. 25/25 hardware-free tests PASS, `[m1-no-mutex]` clean, `[rt-alloc-grep]` baseline 변동 없음. Direct writer call (planner skip) — task가 SYSTEM_DESIGN.md §6.4.1로 완전히 명세되어 있어 brief 권장대로 진행. 부수적 housekeeping: `cold_writer.cpp` 미사용 include 3개 (`<chrono>`, `<thread>`, `<utility>`) 제거.
- ✅ **D. Live mode body 완료 2026-04-26 (continued)** — `cold_writer.cpp::case Live`의 stub을 실제 per-scan `step()` loop으로 교체 + GPIO/UDS 운영자 트리거 표면. **Wave A**: `Amcl::step` σ-overload 추가 (no-σ form은 thin forward, OneShot 의미 보존), 새 `run_live_iteration` free 함수 (testable seam, `run_one_iteration` mirroring), `case Live` body (per-scan scan_frames(1) → step → forced=false → apply_deadband_publish, 중간-scan toggle 재확인으로 stale Live publish 방지). **OneShot 시드 변경**: 항상 `seed_global` (warm seed_around branch 제거 — 베이스 1m 이동 후에도 항상 수렴, ~1s 트레이드). `first_run_inout` → `live_first_iter_inout` 리네임 (≥17 사이트, 매 Live 이탈 시 `on_leave_live` 헬퍼가 latch 재무장). 4개 신규 Tier-2 키 (σ pair `amcl_sigma_xy_jitter_live_m`/`_yaw_jitter_live_deg` + GPIO pin pair `gpio_calibrate_pin`/`_live_toggle_pin`) + 4개 신규 Tier-1 상수 (`GPIO_DEBOUNCE_NS`, `UDS_REQUEST_MAX_BYTES`, `SHUTDOWN_POLL_TIMEOUT_MS`, `GPIO_MAX_BCM_PIN`). **Wave B**: 새 `src/gpio/` 모듈 (libgpiodcxx 사용, last-accepted debounce + CLOCK_MONOTONIC) + `src/uds/` 모듈 (`poll(2)`-기반 accept loop — `SO_RCVTIMEO`는 `accept()`에 안 통함, hand-rolled JSON parser, ModeGetter/ModeSetter callback 주입). `godo_tracker_rt::main.cpp`에 `t_gpio` + `t_uds` 스레드 추가, GPIO/UDS 둘 다 `pthread_kill` 없이 `g_running.store(false)` + 100ms poll cycle로 self-exit. 4개 신규 테스트 (`test_cold_writer_live_iteration`, `test_gpio_source_fake`, `test_uds_server` hardware-free + `test_gpio_source_libgpiod` hardware-required-gpio NEW 라벨 — news-pi01 라이브 검증 1회). 새 docs `gpio_wiring.md` + `uds_protocol.md`. 28/28 hardware-free + 1/1 hardware-required-gpio PASS. 풀 파이프라인 (planner → reviewer-A APPROVE-WITH-NOTES (5 MUST + 8 SHOULD + 8 NIT, amendments 부록으로 fold) → writer Wave A + Wave B → reviewer-B APPROVE-WITH-NOTES (0 MUST + 5 SHOULD + 7 NIT, S1/S2/S4/N3/N4 즉시 fold + 나머지 carry). libgpiod-dev 설치 필요 (Mode-A N5 잘못 — runtime/dev 분리). 상세는 `production/RPi5/CODEBASE.md` Wave A + Wave B 섹션, plan은 `.claude/tmp/plan_phase4_2_d.md` (Mode-A amendments 부록 포함, post-merge 삭제 가능).
- ✅ **Phase 4-2 systemd carry 완료 2026-04-26 (continued)** — 3개 Phase 4-2 carry 항목을 단일 commit으로 마무리. 새 디렉토리 `production/RPi5/systemd/`에 `godo-tracker.service` (User=ncenter, RuntimeDirectory=godo, AmbientCapabilities=CAP_SYS_NICE+CAP_IPC_LOCK 으로 setcap 의존 제거, ExecStartPost로 ttyAMA0 lazy IRQ pin), `godo-irq-pin.service` (boot oneshot — eth0/USB/dma/mailbox/mmc/spi pinning), `godo-irq-pin.sh` (idempotent helper, `--quiet` 모드, news-pi01 /proc/interrupts 스냅샷 기반), `system.conf.d/godo-watchdog.conf` (RuntimeWatchdogSec=10s drop-in), `install.sh` (idempotent installer), 7-section operator README. setcap workflow은 non-systemd dev launch 용으로 유지. `.claude/tmp/apply_irq_pin.sh` 는 superseded (delete는 follow-up). systemd-analyze verify clean. Direct writer (no planner, no Mode-B) — Phase 4-2 C 패턴: 작은 + well-specified config-only 작업.
- Document the Arduino rollback procedure (README + operator card).

### Phase 4-3 — `godo-webctl` minimal (LANDED 2026-04-26)

- ✅ **Phase 4-3 완료 2026-04-26** — 새 top-level 디렉토리 `/godo-webctl/` (UV-managed Python). FastAPI app + uvicorn(workers=1). 3개 엔드포인트 (`GET /api/health` UDS get_mode round-trip, `POST /api/calibrate` UDS set_mode {OneShot}, `POST /api/map/backup` 원자적 두-단계 copy). 순수-stdlib UDS JSON-lines 클라이언트 + asyncio.to_thread 래핑. 7개 env-var-only Tier-2 설정 (TOML 안 씀). `protocol.py`가 C++ Tier-1을 미러링 (UDS 와이어 상수만 — file:line citation으로 SSOT pin, drift는 `test_protocol.py`로 catch). systemd unit (`User=ncenter` same-uid, `StateDirectory=godo`, `RuntimeDirectory=godo`는 deliberately 생략 — godo-tracker가 owner). Page Visibility API handbrake로 1Hz polling을 hidden tab에서 정지. 52/52 hardware-free pytest PASS, 1/1 hardware-required-tracker (news-pi01 bring-up까지 deferred). 풀 파이프라인 (planner → reviewer-A APPROVE-WITH-NOTES (5 MUST + 10 SHOULD + 10 NIT, amendments fold) → writer single-wave → reviewer-B APPROVE-WITH-NOTES (0 MUST + 3 SHOULD + 6 NIT, S1/S2/S3/N5 fold). Mode-A의 진짜 발견: D10 `MAP_PATH` stem convention이 tracker `.pgm`-with-suffix와 SSOT 불일치 (수정됨). Mode-B의 진짜 발견: app.py가 `UdsProtocolError` 메시지 string-startswith로 HTTP status 결정 → `UdsServerRejected` 서브클래스 분리 (수정됨). 상세는 `/godo-webctl/CODEBASE.md` + `/godo-webctl/README.md`, plan은 `.claude/tmp/plan_phase4_3.md` (Mode-A amendments 부록 포함, post-merge 삭제 가능).

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
- **Rigorous tracker_rt cadence validation** (per user 2026-04-25). The
  paced-mode passthrough proved the **seqlock-single-slot + clock_nanosleep**
  pattern delivers UE-side "그대로 멈춰라" cadence with serial bursts
  absorbed cleanly. `godo_tracker_rt` reuses the same pattern in
  Thread D but **adds the offset-apply path + SCHED_FIFO + AMCL writer
  feeding `target_offset`**. Validate that adding those layers does
  NOT regress the steady-60-Hz property:
    1. **Receiver-side cadence measurement** — capture UDP arrival
       timestamps at the UE host (`tcpdump -ttt` or in-engine timestamps),
       compute inter-arrival ms histogram. Target: p99 < 200 µs deviation
       from 16.683 ms (matches SYSTEM_DESIGN.md design goal).
    2. **Burst-absorption regression** — inject artificial source
       bursts (e.g. via the legacy passthrough → tracker_rt comparison
       on the same FreeD line). `skip` field on tracker_rt's stats
       must rise but its receiver-side cadence must stay flat.
    3. **Catch-up sanity** — preempt Thread D for >1 period
       (e.g. via `SIGSTOP` momentary), observe whether
       `clock_nanosleep(TIMER_ABSTIME)` snaps the next send to the
       next absolute deadline (good) or queues several back-to-back
       sends (bad — would arrive at UE as a burst).
    4. **Smoother integration** — the offset smoother runs on Thread D
       and could in principle stretch a tick. Time the
       `smoother.tick → apply_offset_inplace → udp.send` block in
       isolation and confirm worst-case execution stays < 50 µs even
       at hot ramp moments.
    5. **AMCL writer interference** — once Phase 4-2 lands the real
       AMCL writer thread, re-run #1 with AMCL active to verify the
       cold-path writer's seqlock writes do not stall Thread D
       readers (they shouldn't — the seqlock is wait-free for the
       reader; assert with a stress test similar to
       `test_seqlock_roundtrip`).

### 장래 검토 / future considerations (not blocking)

- **Hybrid mode — adaptive σ from LiDAR-derived velocity (tentatively Phase 4-2 E)**. The dual-mode static σ (OneShot 5 mm vs Live 15 mm) is correct for "static-or-not" but cannot distinguish slow Live motion (σ wasted on noise) from fast Live motion (σ insufficient to track). User raised the idea (2026-04-26): compute velocity from successive `last_pose` deltas at the cold writer (one derivative — robust; do NOT differentiate twice for acceleration — noise explodes), feed velocity into σ_jitter via a sigmoid or piecewise mapping. Practical risks: (1) feedback-loop stability (low velocity estimate → low σ → tight cloud → low velocity estimate; needs a static σ floor), (2) bootstrap (first 1–2 scans have no velocity history; default to Live σ), (3) tuning surface grows from 2 constants to a function — needs production motion data to tune, NOT a paper choice. CPU cost is negligible (one subtraction per scan). Gated on Phase 4-2 D Live mode running in production long enough to collect representative motion logs. If the simpler dual-mode proves sufficient in the field, Hybrid is over-engineering and should not land.
- **OneShot wall-clock measurement on news-pi01** — Phase 4-2 D landed `seed_global` on every OneShot (~5000 particles × 25 iters, no warm-seed shortcut). Operator UX target ≤ 2 s; if measured > 2 s, a follow-up tuning task drops `amcl_particles_global_n` to 3000 or `amcl_max_iters` to 15. Logged at `test_sessions/TS6/oneshot_wallclock.md` once measured.
- **`/dev/gpiochip0` Config key** (Mode-B N7) — currently hardcoded in `godo_tracker_rt::main.cpp`. Pi 5 always uses chip0 for the 40-pin header so this is operationally fine on news-pi01, but a future news-pi02 (different SBC, alternate GPIO controller) would need this as a Tier-2 key. Defer until cross-SBC support is on the roadmap.

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

Session blocks are archived weekly under [`PROGRESS/`](./PROGRESS/) (ISO 8601 weeks, KST Mon–Sun). The master keeps current state + Index only; per-week session blocks live in their archive file.

| Week | Date range (KST) | Archive |
| --- | --- | --- |
| 2026-W19 | 2026-05-04 → 2026-05-10 | [PROGRESS/2026-W19.md](./PROGRESS/2026-W19.md) |
| 2026-W18 | 2026-04-27 → 2026-05-03 | [PROGRESS/2026-W18.md](./PROGRESS/2026-W18.md) |
| 2026-W17 | 2026-04-20 → 2026-04-26 | [PROGRESS/2026-W17.md](./PROGRESS/2026-W17.md) |

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
