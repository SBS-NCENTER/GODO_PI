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
- **Uses of LiDAR yaw**: (1) as the 3-DOF state variable inside AMCL, (2) as a safety tripwire — if yaw drifts more than `cfg.amcl_yaw_tripwire_deg` from `cfg.amcl_origin_yaw_deg`, log a warning (Phase 4-3 wires a UDP warning bit).

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

### 2026-05-02 (late-night → cross-day — 21:30 KST 2026-05-02 → 00:50 KST 2026-05-03, seventeenth-session — issue#16 v0..v7 hot-fix series ships + issue#15 PR #70 in flight + cross-reboot HIL stress test passes)

Seventeenth-session followed directly from sixteenth-session's close (PR #68 docs merged 2026-05-02 16:30 KST). Operator drove issue#16 from feature merge through six iterative HIL hot-fixes (v2 → v7) over ~3 hours and 20 minutes, all squash-merged into PR #69. Each hot-fix narrowed a different race surface that prior fixes had not covered, exposing two distinct root-cause patterns in webctl's `mapping.status()` reconcile path. After PR #69 merged, operator stress-tested the full pipeline through an RPi reboot and 16+ mapping cycles (v7, v9..v16, plus earlier t-series); every map saved cleanly with intact `P5` PGM + YAML pair. issue#15 (Config tab domain grouping + edit-input bg swap) was bundled into PR #70 as a quick frontend-only follow-up before session-close, awaiting operator HIL.

**Notable structural revelation #1 — `status()` reconcile must distinguish transient docker states from "container gone"**: Operator t6 incident (22:54:47 KST 2026-05-02). A healthy mapping container ran for >5 minutes producing valid scan/odom data, but `state.json` was written as `Failed("webctl_lost_view_post_crash")` ~1 second after start. Root cause: `_docker_inspect_state` returns "created" between `docker run` and the entrypoint actually executing (typically <500 ms; observable from a 1 Hz `/api/mapping/status` polling loop on a cold container boot), but pre-v6 code collapsed any non-"running" inspect to the gone-branch. v6 fix added explicit transient handling: `if inspect in ("created", "restarting"): return s` BEFORE the gone-branch. The downstream cost of the bug was severe — once `state.json` was Failed, the SPA showed only an "Acknowledge" button whose handler runs `docker rm -f` (no SIGTERM grace, no entrypoint trap, no `map_saver_cli`); operator clicked it to clear the phantom banner and the still-healthy 5-min mapping container was killed mid-flight, t6.{pgm,yaml} never landed. Lesson: any reconcile between persisted state and an external probe MUST classify the probe's transient states explicitly — NOT treat "anything not the success-shape" as failure.

**Notable structural revelation #2 — `ExecStartPre` window race extends the same class of bug**: Operator t8 second-attempt incident (~14:36:43 UTC 2026-05-02). Even after v6 shipped, a second mapping ~2 s after a clean save hit `webctl_lost_view_post_crash` again. Root cause: the systemd unit's `ExecStartPre=/usr/bin/docker rm -f godo-mapping` runs BEFORE `ExecStart=docker run ...`, so for ~100-500 ms there is no container at all → `docker inspect` returns None ("No such object"). v6 only handled non-None transients ("created", "restarting"); inspect=None still landed on the gone-branch. v7 fix narrowed further: `if inspect is None and s.state == STARTING: return s` — `start()`'s own Phase-2 polling deadline (`MAPPING_CONTAINER_START_TIMEOUT_S`) is the authoritative Failed-writer for Starting; `status()` must NOT pre-empt it across the ExecStartPre window. Running + inspect=None still goes to the gone-branch (genuine crash signal); Stopping + inspect=None still resolves to Idle (clean stop signal). Lesson: state-machine transitions between persisted state + external probe must be expressed as explicit per-state-pair contracts, not a single "if not running, fail" cliff.

**Notable structural revelation #3 — Pre-check rows must enumerate every condition that gates Start, including residual systemd state**: Operator: "전부 정상으로 Pre-check가 나오는데, 막상 제작하면 잘 안되네요". The 6 pre-v7 rows (`lidar_readable`, `tracker_stopped`, `image_present`, `disk_space_mb`, `name_available`, `state_clean`) tracked LiDAR + tracker + image + disk + name + state.json, but a residual `failed`-state systemd unit (left over from a prior SIGKILL not cleared via `reset-failed`) was invisible to all of them. Same gap for a `godo-mapping` container hung in `exited` state without being removed. v7 added a 7th row `mapping_unit_clean` combining `systemctl is-failed godo-mapping@active` + `docker inspect godo-mapping`, with failure-detail strings (`systemd_unit_failed_run_reset_failed`, `container_lingering_<state>`) deterministically mapped to operator-actionable Korean tooltips on the SPA side (`PRECHECK_DETAIL_KO`). Lesson: the precheck panel is the operator's mental model of "what gates Start" — every gate that the backend enforces silently must be surfaced as a row, otherwise the panel actively misleads.

**Notable structural revelation #4 — Failed-state UX strings must clear when the underlying state heals**: After v6/v7 false-Failed events were acknowledged, the SPA's `lastError` red banner (containing strings like `mapping_already_active` from a prior 409 response) stayed painted under all-green precheck rows even though `state.json` was now Idle. Pre-v7 `MapMapping.svelte` only cleared `lastError` at the start of `onStart` / `onStop`; the Failed → 확인 → Idle transition didn't touch it. v7 fix: `$effect(() => { if (status?.state === MAPPING_STATE_IDLE) lastError = null; })`. Lesson: ephemeral error strings tied to a transition must clear on the inverse transition, not just on the next user action.

**Process violation + lesson — direct-to-main commit `8da6d5a`**: Parent committed the seventeenth-session NEXT_SESSION.md rewrite directly to `main` instead of via a PR. This is the same anti-pattern as twelfth-session's `dd348ba`. CLAUDE.md §8 deployment workflow assumes every change to main goes through a PR for HIL traceability + reversal-friendly history. NEXT_SESSION.md is a mechanical rewrite at session-close, but it still ships with the rest of the session's changes (per the cache-role rule in `feedback_next_session_cache_role.md`); bundling it into the chronicler PR is the right shape. Locked: chronicler skill's §0 pre-flight already mandates `git checkout main && git pull --rebase && git checkout -b docs/...` — Parent must extend the same discipline to the NEXT_SESSION.md rewrite step that precedes chronicler invocation. Memory entry candidate (Parent's territory): `feedback_next_session_via_pr.md` or extension of existing `feedback_check_branch_before_commit.md`.

**Notable operator workflow pattern — hot-fix series squash-merged into a single PR**: PR #69 absorbed 9 commits (base feat + v1..v8) over 6 hours. Each hot-fix was merged via squash, so `main` history is clean (one PR-per-line), but the commit messages within the PR provide the v0..v7 evolution log; per-stack `CODEBASE.md` change-log entries (timestamped 19:30 / 19:50 / 20:15 / 22:50 / 23:30 / 00:30 KST) capture the same evolution at a coarser granularity. Both layers survive the squash. Lesson: when iterating fast through HIL feedback, individual commit messages + per-stack CODEBASE.md entries form the durable audit trail; the squash-merge keeps `main` history readable.

**1 PR merged + 1 PR open this session**:

| PR | Issue | Title | State |
|---|---|---|---|
| #69 | issue#16 | mapping pre-check gate + cp210x driver recovery + ProcessTable refinement (v0..v7 hot-fix series) | merged 00:21 KST 2026-05-03 |
| #70 | issue#15 | Config tab domain grouping + edit-input bg swap | open 00:37 KST 2026-05-03 |

**Cross-cutting lessons + observations locked this session**:

- v0..v7 hot-fix series narrows a single bug class (`webctl_lost_view_post_crash` from over-aggressive reconcile) through three independent race surfaces: (a) docker "created" transient (v6), (b) ExecStartPre None window (v7), (c) systemd unit failed-state invisibility (v7 precheck row). Each fix is independently necessary; none is sufficient.
- Test counts grew 932 → 941 (non-hardware) across v6 + v7 with 5 new parametrized cases. `PRECHECK_CHECK_NAMES` cardinality bumped 6 → 7.
- Failed-recovery UI text "Acknowledge" → "확인" per operator request — matches surrounding 시작/정지/저장 vocabulary.
- Cross-reboot stress test (RPi reboot at 00:09:45 KST → 16+ mapping cycles, all clean): empirical confirmation that v0..v7 stack survives a full reboot + cold-container path. PGM/YAML integrity scan: all pairs intact, P5 magic verified.
- Out-of-band operator housekeeping (not in any PR): journald → persistent storage activated (`/var/log/journal/` created), `v11.pgm.tmp` orphan removed manually. The latter motivates issue#16.2 (automate `.tmp` cleanup).

**Open queue for next session** (priority order, operator-locked — Tier A explicitly deferred to eighteenth-session):

1. **★ Tier A bundle — issue#16.1 + issue#10**:
   - **issue#16.1 (NEW)** — t5 trap-timeout: `docker stop --time=20` grace can be shorter than the entrypoint trap's `map_saver_cli` cycle on long mapping sessions (operator t5 incident lost a 2h 5min mapping). Fix path: separate `mapping_stop_systemctl_timeout_s` (≥45 s; currently uses generic `SUBPROCESS_TIMEOUT_S=10s`) + bump schema-default ladder (docker_grace 20 → 30, systemd_timeout 30 → 45, webctl_stop_timeout 35 → 50). LOC ~30. Risk: data loss on long-running mapping.
   - **issue#10** — udev rule `/dev/rplidar` symlink (`idVendor=10c4 idProduct=ea60 serial=2eca2bbb4d6eef1182aae9c2c169b110`) → tracker.toml's `serial.lidar_port` flips from `/dev/ttyUSB0` to `/dev/rplidar`. Eliminates USB-renumbering ops bugs. LOC ~20 + 1 udev file.
2. **issue#15** — PR #70 awaiting operator deploy + HIL.
3. **issue#16.2 (NEW)** — preview `.tmp` cleanup (`v11.pgm.tmp` orphan motivated this; `preview_dumper.py:54-64` SIGTERM-during-fsync race). LOC ~10.
4. **issue#11** — Live pipelined-parallel multi-thread (architectural).
5. **issue#13 cont.** — distance-weighted AMCL likelihood (`r_cutoff` near-LiDAR down-weight).
6. **issue#4** — AMCL silent-converge diagnostic.
7. **issue#6** — B-MAPEDIT-3 yaw rotation.
8. **issue#17** — GPIO UART direct connection (on-demand only if issue#10 + issue#16 mitigations are insufficient).
9. **Bug B** — Live mode standstill jitter (analysis-first).
10. **issue#7** — boom-arm angle masking (contingent on issue#4).

**Next free issue integer: `issue#18`**.

### 2026-05-02 (cross-day — 21:30 KST 2026-05-01 → 16:00 KST 2026-05-02, sixteenth-session — issue#14 SPA mapping pipeline ships + System tab integration + map UX polish + PR #66 backup hotfix bundle + issue#16/#17 candidates surfaced)

Sixteenth-session followed directly from fifteenth's plan-authoring close. The 1393-line issue#14 plan went through Mode-A → REWORK (5 Critical + 8 Major findings, all mechanical) → in-place fold by Parent (no Planner re-spawn) → Writer round 1 → Mode-B → REWORK (Maj-1 stop-timing chain too tight against nav2 `map_saver_cli` non-atomic write + Maj-2 flock too wide) → Writer round 2 + System tab integration (operator UX request) → Mode-B C1 (Settings → TOML wire dead) + M1 (cross-trio invariant missing) + M2 (System tab admin endpoint bypassed mapping coordinator) → all folded → operator HIL through 4 mapping cycles (test_v1 → v4) → multiple post-HIL hot-fixes → PR #67 merge. PR #66 backup-endpoint phantom failure (deprecated `cfg.map_path` Track-E fallthrough) + Config tab numeric-input clearing UX bug were field-reported mid-session; bundled into a parallel hotfix PR with 4 cumulative commits (backup-flash banner, Apply no-op suppression, modified-key amber dot).

**Notable structural revelation #1 — CP2102N USB CDC stale state on tracker→mapping device handover**: HIL surfaced a hardware-level race that the Maj-2 flock narrowing alone could not resolve. After `godo_tracker_rt` cleanup (`drv->stop()` + 200 ms wait + `setMotorSpeed(0)` + close — verified clean), the cp210x USB CDC driver internal handle does NOT immediately release. The next `rplidar_node` (inside the mapping container) calling `SET_LINE_CODING` gets `-110 ETIMEDOUT` (`dmesg: cp210x ttyUSB1: failed set request 0x12 status: -110`); SDK reports `code 80008004` (RESULT_OPERATION_TIMEOUT). Empirical workaround: ~10 s wait between tracker stop and mapping start. Operator decision: **issue#16 (단기) — webctl pre-check gate + cp210x driver unbind/rebind**. **issue#17 (장기) — RPLIDAR C1 4-pin GPIO direct connection** (Pi 5 PL011 UART4, replaces USB CDC layer entirely). Documented in `doc/RPLIDAR/RPi5_GPIO_UART_migration.md` + memory `project_gpio_uart_migration.md`.

**Notable structural revelation #2 — Mode-B C1: env-only Settings field silently disables operator-tunable surface**: PR #67 round 2 added 3 new webctl-owned schema rows (`webctl.mapping_*_s` for Maj-1 stop-timing ladder). Mode-B caught that `Settings.mapping_webctl_stop_timeout_s` was loaded ONLY from env / defaults — operator could edit the value via Config tab → tracker writes via `render_toml` → webctl never re-reads it. Maj-1's "torn lifetime asset" guard would have reverted to 35 s deadline regardless of operator intent. Fix: new `_augment_with_webctl_section()` in `__main__.py` binds the TOML value to the live `Settings` instance (env precedence preserved). General lesson: any operator-tunable schema row whose runtime path uses a `Settings` field MUST have explicit `__main__` augmenter coverage. Unit pin: `tests/test_main_settings_augmenter.py` (6 cases: TOML override, env preservation, missing file, malformed, missing section, torn-ladder rejection).

**Notable structural revelation #3 — Mode-B M1: schema range overlap requires apply-time + load-time cross-trio enforcement**: Schema ranges `[10,60][20,90][25,120]` overlap by design (allow operator to nudge each row independently) but the ordering invariant `docker < systemd < webctl` must hold globally. Without enforcement, operator can save `docker=60, systemd=20` (each individually in range) → tracker writes torn trio → next webctl boot raises `WebctlTomlError` → crash loop, recoverable only via SSH + manual file edit. Fix: belt-and-suspenders enforcement at BOTH `apply.cpp::apply_set` (mirrors existing `amcl.sigma_hit_schedule_m` cross-field check pattern) AND `core/config.cpp::Config::load` (`validate_webctl_mapping_ladder` mirrors `validate_amcl` / `validate_gpio` pattern). Lesson: any cross-field invariant declared in schema description MUST be enforced at BOTH the operator-edit path (apply) and the boot-load path (Config::load).

**Notable structural revelation #4 — Map viewport must reference actual canvas, not `window.innerHeight`**: post-issue#13-cand (default SLAM resolution 0.05 → 0.025 m/cell) mapping containers emit 4× larger PGMs (e.g. 200×200 → 400×400). Operator HIL: "100% 기준 css 박스에서 아래 쪽이 애매하게 잘려. 위쪽은 아예 안잘리는데." Root cause: `_minZoom` was computed against `window.innerHeight` (full window) but actual map canvas is smaller (topbar / breadcrumb / Map header / sub-tab nav steal vertical). Auto-fit zoom sized for 1080 px window → actual canvas ~800 px → ~280 px overflow at the bottom; asymmetric clipping (top OK, bottom clipped) because map is center-anchored. Fix: `setMapDims` accepts optional `canvasW` / `canvasH` params; `MapUnderlay.svelte` defers the call into a `$effect` watching both `meta` (mapMetadata arrival) and `canvas` (`bind:this` binding), measures via `getBoundingClientRect`, passes through. Preserves `project_map_viewport_zoom_rules.md` Rule 2 spirit — only the candidate computation changed.

**3 PRs landed/queued this session**:

| PR | Issue | Title | State |
|---|---|---|---|
| #65 | docs | NEXT_SESSION cold-start cache rewrite for sixteenth | merged 23:37 KST 2026-05-01 |
| #66 | hotfix | backup uses active.pgm + Config input preserves empty + UX bundle (backup-flash, no-op suppression, amber dot) | merged 23:37 KST 2026-05-01 |
| #67 | issue#14 | SPA mapping pipeline + monitor SSE + Map > Mapping sub-tab + System tab integration + Maj-1/2 + Mode-B C1+M1+M2 + UX polish | merged ~17:00 KST 2026-05-02 |

**Cross-cutting lessons locked this session**:
- `feedback_ssot_following_discipline.md` (memory entry, in PR #67) — when multiple naming schemes exist for the same concept, follow the original/upstream SSOT verbatim. Don't paraphrase, alias, or invent parallel names. Reinforced via Mode-A C1 fix on issue#14 plan (`[main] serial_lidar_port` → `[serial] lidar_port`).
- `MAPPING_OPERATION_TIMEOUT_MS = 60000` constant (frontend) — long-running endpoints (`/api/mapping/start`, `/api/mapping/stop`) need explicit `apiPost` `timeoutMs` override; default 3 s aborts mid-flight while backend continues, producing the confusing UX "맵은 저장됐는데 request_aborted 떠".
- Map zoom rule extension: `_minZoom = min(viewportH/h, viewportW/w)` using actual canvas dims; first-load `_zoom = _minZoom` (auto-fit). Preserves `project_map_viewport_zoom_rules.md` Rule 2 (first-load only, NOT resize-tracking).

**Open queue for next session** (priority order, operator-locked):
1. **issue#16** — Mapping pre-check gate + cp210x auto-recovery + dockerd/containerd ProcessTable classification (operator HIL surfaced — tracker→mapping handover race + process classification refinement).
2. **issue#15** — Config tab domain grouping (collapsible sections by dotted-name prefix, frontend-only, ~80 LOC).
3. **issue#10** — udev `/dev/rplidar` symlink (small standalone; deprecated by issue#17 if ever shipped).
4. **issue#11** — Live pipelined-parallel multi-thread (architectural, sibling to issue#5 Live carry-hint).
5. **issue#13 cont.** — distance-weighted AMCL likelihood (`r_cutoff` near-LiDAR down-weight; algorithmic experiment).
6. **issue#4** — AMCL silent-converge diagnostic (now has fifteenth's HIL data as baseline).
7. **issue#6** — B-MAPEDIT-3 yaw rotation (frame redefinition, deferred).
8. **issue#17** — GPIO UART direct connection migration (on-demand, only if cp210x stale state still hurts ops post issue#16).
9. **Bug B** — Live mode standstill jitter ~5 cm widening (operator measurement data needed; not yet coded).

**Next free issue integer: `issue#18`**.

### 2026-05-01 (afternoon → evening — 14:30 KST → 20:30 KST, fifteenth-session — issue#5 Live pipelined-hint kernel ships + HIL spectacular + issue#12 latency defaults + issue#13-cand mapping resolution + frontend timestamps + issue#14 SPA mapping pipeline plan authored)

Fifteenth-session was a marathon afternoon-evening following directly from fourteenth's cold-start handoff (TL;DR #1: `issue#5 Live mode pipelined hint`). Operator drove two full-pipeline PRs to merge plus a 1393-line Plan for the next major feature (issue#14 SPA mapping pipeline). Two Mode-A REWORK cycles were triggered (planner overestimated architectural simplicity each time); both were resolved by Parent decisions during the same session without re-Planner spawn. HIL outcomes on PR #62 were the most spectacular this project has seen — Live drift collapsed from ~4 m to ±5 cm stationary / ±10 cm in motion; yaw drift from ~90° to ±1°. A σ tighten experiment (σ_xy 0.05 → 0.02) was empirically rejected mid-session, locking σ semantics in both directions (do not widen for AMCL search comfort, do not tighten beyond physical drift bounds).

**Notable structural revelation #1 — pipelined-hint kernel as one-shot-with-carry**: PR #62 reframed Live mode from "improve `Amcl::step` per-scan convergence depth" into "Live ≡ pipelined one-shot driven by `pose[t-1]` as hint, never bare `Amcl::step()`." The kernel now uses `converge_anneal_with_hint(hint=pose[t-1], σ=tight)` per Live tick, with σ matching physical inter-tick crane-base drift bound (operator-locked 0.05 m / 5°, NOT padded). Patience-2 early-break in the existing converge_anneal mechanism keeps the per-tick budget under 100 ms — empirically validated this session: 600 samples × 60 s showed iters mode 16/30, max 21, mean 15.7 (R1 budget SAFE). The architectural change touched 22 files across RPi5 + webctl + tests + docs (~1835 LOC); shipped default-OFF in PR #62 for HIL safety, then default-ON in PR #63's combined follow-up after operator HIL approval.

**Notable structural revelation #2 — map-cell quantization as the standstill jitter floor**: HIL after PR #62 deploy showed the Live carry-hint locked basin perfectly but published pose still oscillated ±2-3 cm at standstill. Operator probed σ tighten (σ_xy 0.05 → 0.02) hoping to crush the jitter; result was unambiguously worse — y range marginally narrowed (36 → 34 mm) but **yaw range expanded 2.5×** (0.338° → 0.844°), max yaw_std exploded 8.6× (0.224° → 1.925°), and 2/600 frames failed to converge. Particle-budget redistribution explanation: tightening σ_xy compresses the 5000-particle cloud's xy footprint, redistributing entropy into the yaw axis — particles wander into poor-yaw basins. The true floor is `04.29_v3.pgm` map resolution (0.050 m/cell × y range 36 mm = 0.73 cells); sub-cell jitter is irreducible given the current cell width. Operator immediately locked: σ stays at 0.05 / 5°. Floor breakers belong to issue#13-cand (map resolution 0.05 → 0.025; partial: PR #63's commit `3225149` halved the SLAM default for *future* maps) and a future distance-weighted likelihood experiment. Memory entry `project_hint_strong_command_semantics.md` extended with the σ-tighten experiment finding so future sessions reflexively reject the same tighten attempt.

**Operator-locked decisions this session (queue + memory)**:

1. **issue#5 default-flip in follow-up PR** — PR #62 shipped default-OFF (rollback safety); after HIL approval, PR #63 flipped `LIVE_CARRY_POSE_AS_HINT = false → true` and the schema row's `default_repr "0" → "1"`. Operator can revert via tracker.toml `amcl.live_carry_pose_as_hint = 0`.
2. **issue#12 latency defaults — smoother `t_ramp_ms` 500 → 100 ms**. Operator framing: "논리적으로 이게 맞으니까 이걸로 고정하는 것이 좋겠어. (SPA config에서 수정 가능하게끔)" Architecture is Live-primary (SYSTEM_DESIGN.md §6.4 design intent already documented this); 500 ms was a OneShot-comfort value over-spec'd for the dominant Live use case.
3. **issue#12 SSE pose+scan stream config-driven, default 30 Hz**. Operator: "지도 부분에만 적용." Two new `webctl.*` schema rows (`pose_stream_hz`, `scan_stream_hz`); other SSE streams (services, processes, resources_extended, diag) keep existing rates. Initial Mode-A finding: schema-row-only Route 1 was architecturally infeasible (`apply_set` rejects unmapped keys, `render_toml` writes 0, `apply_get_all` returns 0). Pivoted to Route α (Config-struct-mapped) — tracker stores in `Config` but never reads; webctl reads via `webctl_toml.read_webctl_section` of `/var/lib/godo/tracker.toml`. RPi5 invariant `(r)`, webctl invariant `(ac)`.
4. **issue#13-candidate (partial) — SLAM default resolution 0.05 → 0.025 m/cell**. PR #63 commit `3225149`. Existing maps untouched; future SLAM runs pick up the new default. AMCL adapts automatically (likelihood field is cell-based; ~4× memory on Pi 5 8 GB is fine).
5. **Frontend timestamp UX** — Map list + Backup list show `YYYY-MM-DD HH:MM` (was `HH:MM`). New `formatDateTime(unixSec)` helper alongside existing `formatTimeOfDay`; Dashboard alarm feed intentionally unchanged (alarms are recent, time-of-day suffices).
6. **issue#14 SPA mapping pipeline + monitoring (Plan-only)** — full feature spec for bringing SLAM mapping inside the SPA. 14 operator-locked decisions (L1-L14): system-level Mapping mode, tracker auto-stop on entry, LiDAR USB port shared via tracker's `serial.lidar_port`, Map sub-tabs (Overview/Edit/Mapping), regex `^[A-Za-z0-9._\-(),]+$` 1-64 chars, bind-mount `/var/lib/godo/maps/`, manual activation post-mapping, `godo-mapping@<name>.service` systemd template, dedicated Python ROS2 preview node @ 1 Hz, Docker socket via `usermod -aG docker ncenter`, polkit rule mirroring tracker's. Plan body (1393 lines) + Parent post-Plan amendment (S1-S6) for **SSE separation**: Mapping monitor SSE is Docker-only, RPi5 system stats keep their existing independent stream, no one-shot polling fallback, SPA Mapping strip splits into RPi5 (always live) + Docker (live ↔ "중단됨" frozen on close) regions. Mode-A deferred to sixteenth-session per operator's "Plan까지만 진행하자."

**Process notes — two Mode-A REWORK cycles, both Parent-resolved**:

- **PR #62 Mode-A**: ACCEPT-WITH-NITS (5 majors absorbed at intake). M1 dropped `share/config_schema.hpp` mirror task (file is install-time-generated, not tracked — same finding the chronicler recorded for PR #62 will catch in fifteenth too). M2 introduced `bool last_pose_set` cold-start guard (instead of comparing pose to (0,0,0), which could legitimately be a OneShot result). M3 documented Bool-as-Int convention. M4 added a fourth cfg key `amcl.live_carry_schedule_m` for separate Live schedule control. M5 added a round-trip rollback test case.
- **PR #63 Mode-A**: REWORK (3 critical architecture defects in Route 1 schema-row-only). Critical 1: `apply_one` rejects unmapped keys with `internal_error` → SPA edit path broken. Critical 2: `render_toml` writes 0 for unmapped keys → tracker.toml corrupted on every commit. Critical 3: `apply_get_all` returns 0 → SPA "current value" column wrong. Parent resolved with Route α (Config-struct-mapped) — same plan body, different ownership decision. No re-Planner spawn; Writer absorbed Parent decision A1-A10 directly.

**LiDAR USB swap incident (operational lesson)**: mid-session, the LiDAR USB-C cable disconnected and re-attached as `/dev/ttyUSB1` instead of `/dev/ttyUSB0` (the slot tracker config pointed at). dmesg confirmed at 16:15:45. Resolution: operator updated tracker.toml `serial.lidar_port = "/dev/ttyUSB1"` + restart. Long-term fix queued as **issue#10 — udev rule for stable LiDAR symlink (`/dev/rplidar` based on USB serial number `2eca2bbb4d6eef1182aae9c2c169b110`)**. Confirmed pre-existing for ~1 hour before the swap (multiple `set request 0x12 status: -110` errors in dmesg history); the swap event made it acute.

**2 PRs landed + 1 Plan authored this session**:

| PR / Plan | issue | Title | State |
|---|---|---|---|
| #62 | issue#5 | feat(rpi5): issue#5 — Live mode pipelined-hint kernel | merged (squash) |
| #63 | issue#5 follow-up + #12 + #13-cand | feat: issue#5 default-flip + issue#12 latency defaults + issue#13-cand mapping resolution + frontend timestamps | merged (squash) |
| Plan #14 | issue#14 | SPA Mapping pipeline + monitoring (1393 LOC + S1-S6 SSE-separation amendment) | authored to `.claude/tmp/plan_issue_14_mapping_pipeline_spa.md`; Mode-A deferred to sixteenth-session |

**Test count delta** (cumulative across PR #62 + PR #63):

- RPi5 ctest: 42 → 46 (+4 from `test_cold_writer_live_pipelined.cpp` 8 cases + Scenario E in `test_amcl_scenarios.cpp`); then unchanged through PR #63 (CONFIG_SCHEMA row count assertion bumped from 42 → 46 → 48 across the two PRs).
- webctl pytest: 681 → 683 → 716 (+33 via PR #63's `test_webctl_toml.py` 28 cases + new `test_sse.py` cadence-injection cases).
- Frontend vitest: 321 → 326 (+5 via `formatDateTime` cases in `format.test.ts`).
- Bundle delta: ~+0.5 kB gzip cumulative (formatDateTime + new Backup/MapListPanel imports).

**HIL acceptance achieved**:

- **PR #62 (issue#5)** spectacular: stationary ±5 cm xy / ±1° yaw, in motion ±10 cm xy. Multi-basin failure rate 0% across the HIL window. Operator quote: "완전 잘 맞아. 오히려 이전 상태가 힌트가 되서 그런지 튀는 증상 없이 계속 자기 위치를 찾아."
- **PR #63 (default-flip + smoother + SSE 30 Hz + frontend timestamps + mapping resolution)** verified end-to-end. Operator deployed via the §8 stack-deploy matrix with no rsync trailing-slash incident. webctl SSE 30 Hz visibly smoother on Map tab pose marker. Smoother 100 ms ramp ready for HIL but operator's tracker.toml still had explicit `t_ramp_ms = 500` override from prior sessions — flagged in PR #63 body for operator's tracker.toml cleanup.

**Open queue for sixteenth-session** (operator-locked priority order):

1. **issue#14 — SPA Mapping pipeline + monitoring** (P0, full pipeline). Plan authored this session (1393 lines + Parent SSE-separation amendment). Sixteenth-session begins with Mode-A → Writer (~2000 LOC across 4 stacks) → Mode-B → PR → multi-stack deploy → HIL Scenarios A-F.
2. **issue#10 — udev rule for stable LiDAR symlink** (acute after this session's USB swap). `/etc/udev/rules.d/99-rplidar.rules` matching `idVendor=10c4 idProduct=ea60 serial=2eca2bbb4d6eef1182aae9c2c169b110` → `SYMLINK+="rplidar"`; tracker.toml `serial.lidar_port = "/dev/rplidar"`. Small PR but eliminates a recurring class of operational bugs.
3. **issue#11 — Live pipelined-parallel multi-thread** (operator insight from PR #62 HIL: "OneShot처럼 정밀하게 + CPU pipeline like 계산"). With carry-hint locked basin, deeper schedule per tick is feasible if K-step distributed across cores 0/1/2 (CPU 3 RT-isolated). Reference: `project_pipelined_compute_pattern.md` "Why sequential ships first" — pipelined-parallel was the always-deferred follow-up.
4. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Memory: `project_calibration_alternatives.md` "Distance-weighted AMCL likelihood." Standalone single-knob algorithmic experiment; could ship before A/B/C alternatives.
5. **issue#4 — AMCL silent-converge diagnostic** (carryover; now has fifteenth's HIL data as comprehensive baseline).
6. **issue#6 — B-MAPEDIT-3 yaw rotation** (carryover; revisit two-point UX).
7. **issue#7 — boom-arm angle masking** (carryover; contingent on issue#4).

### 2026-05-01 (afternoon — 12:30 KST → 14:30 KST, fourteenth-session — issue#8 banner polling backstop + issue#9 mode action-hook + CLAUDE.md §8 Deployment + PR workflow + governance/operations bundle)

Fourteenth-session was a tight afternoon follow-up to thirteenth's cold-start handoff. The plan locked at session-start: small banner PR first (TL;DR #4 from cold-start cache), then issue#5 full pipeline. Operator course-corrected mid-session to also fold in **issue#9** as a natural extension of issue#8's polling territory, deferring issue#5 to next-session cold-start instead. Three PRs merged.

**Notable structural revelation — emergent vs explicit behaviour**: issue#9 originated as an operator HIL observation after PR #59 deploy: "godo-tracker가 응답하지 않습니다" tracker-down banner cleared almost instantly on Start/Restart click, consistent across multiple tries. Code-trace analysis disproved the obvious hypothesis (PR #59 directly speeds up tracker-down banner): PR #59's polling backstop touched the **separate** `restartPending` store; `mode.trackerOk` (the actual driver of the App.svelte tracker-down banner) was untouched. The observed speedup was an **emergent property** of mount-time polling-phase alignment after the hard-reload deploy. PR #60 made the same behaviour explicit and deterministic by mirroring PR #45 / PR #59's action-driven refresh pattern for `mode.ts` — `refreshMode()` exported, called alongside `refreshRestartPending()` in service-action handlers. Stop click now responds within HTTP RTT; Restart catches the transient unreachable window during the bounce; Start is still bounded by tracker boot time (a polling-cadence fix can't accelerate process startup). Lesson: operator-perceived "consistent fast behaviour" may be polling-phase coincidence, not designed determinism — when a behaviour is worth keeping, lock it explicitly.

**Operator-locked governance changes**:

1. **`issue#N / issue#N.M` labelling convention promoted from cache to SSOT** — the integer-and-decimal naming scheme had lived only in `NEXT_SESSION.md`'s "Naming convention reminder" section (cache). Operator: "이건 우리 claude.md에 지침 작성하자. 메모리가 너무 많으면 너가 참조하는 컨텍스트가 너무 많을 것 같아." Promoted into CLAUDE.md §6 as a §6-subsection. The shadow memory entry I had created (`feedback_issue_naming_scheme.md`) was deleted in favour of the CLAUDE.md home — fewer files to load on cold start.
2. **CLAUDE.md §8 Deployment + PR workflow** — operator wanted the deploy/HIL/merge pipeline procedure that's been ad-hoc across recent PRs (#54, #55, #56, #58, #59, #60) promoted into CLAUDE.md as a SSOT. Operator: "claude.md에 지침사항으로 정리해도 좋겠어. 내가 직접 확인하면서 해보려구." New §8 contains: (a) standard pipeline diagram (PR opened → fetch → build → deploy → HIL → merge → main sync), (b) **stack-deploy matrix** (frontend / webctl / RPi5 tracker / multi-stack each with build + deploy + service-restart commands), (c) **critical rsync trailing-slash trap** documenting both correct and broken forms, (d) HIL verification checklist, (e) merge etiquette, (f) pre-deploy traps cross-linked to existing memory.

**Live operator HIL surfaced two operational gotchas**:

- **rsync trailing-slash trap**: operator ran `sudo rsync -a --delete /home/ncenter/projects/GODO/godo-frontend/dist /opt/godo-frontend` (correct), then immediately followed with `sudo rsync -a --delete /home/ncenter/projects/GODO/godo-frontend/dist/ /opt/godo-frontend` (with trailing slash on source). The second form's `--delete` wiped the `dist/` subdirectory the first form had created, leaving SPA assets at `/opt/godo-frontend/{index.html,assets,...}` directly while webctl env-var pointed at `/opt/godo-frontend/dist/`. SPA broken, webctl returned 404 on `/`. Recovery: same correct command (no trailing slash) re-run; `--delete` cleaned up the misplaced top-level files and recreated `/opt/godo-frontend/dist/`. Documented in CLAUDE.md §8 with both forms shown side-by-side.
- **GitHub web UI default merge style**: operator merged PR #60 via the web UI instead of `gh pr merge --squash --delete-branch`. The web UI's default landed a merge commit (`315c631`) on top of the feature commit (`7dfcbd8`) — main got 2 commits where PR #58 / #59 got 1 squash commit each. Operator noted but no action taken; if a future session prefers single-commit-per-PR consistency, repo Settings → "Merge button" defaults can be adjusted, or the team can adopt `gh pr merge --squash` discipline.

**3 PRs landed this session**:

| PR | issue | Title | State |
|---|---|---|---|
| #58 | governance | docs: thirteenth-session memory bundle + cold-start refresh + CLAUDE.md §8 + issue#N labelling | merged (squash) |
| #59 | issue#8 | restart-pending banner polling backstop | merged (squash) |
| #60 | issue#9 | action-driven mode refresh hook | merged (web UI merge commit) |

PR #58 was a hybrid — its first commit (88b640b "memory bundle + cold-start refresh") was authored at end of thirteenth-session by operator; the next two (aa8ee99 issue#N labelling + 6295db8 §8 Deployment) were authored this session. All three squashed at merge into `cfef33c`.

**Test count delta** (cumulative across PR #59 + PR #60):

- Frontend vitest: 311 → 321 (+10 — issue#8 polling backstop tests in `restartPending.test.ts` + issue#9 mode store tests in new `mode.test.ts`).
- C++ ctest, webctl pytest: unchanged (frontend-only PRs).
- Bundle delta: ~+0.10 kB gzip (135.40 → 135.50 kB — store + import delta only).

**HIL acceptance achieved**:

- issue#8 (PR #59): operator confirmed banner clears within ~1–2 s on tracker action, no hard reload required across cfg-edit / action / idle paths. Deployed to news-pi01 via the §8 stack-deploy matrix (rsync trap recovered as noted).
- issue#9 (PR #60): operator confirmed tracker-down banner clears with consistent timing on Start/Restart. Quote: "지금 일관되게 ... 메시지 사라지는 속도가 start나 restart 버튼 누르자마자 일관된 타이밍으로 사라짐."

**Open queue for next session** (operator-locked priority — explicitly deferred to a clean cold-start condition):

1. **issue#5 — Live mode pipelined hint** (P0, full pipeline). Live ≡ pipelined one-shot driven by previous-pose-as-hint. Architectural impact comparable to issue#3 (PR #54). Operator-locked direction: `project_calibration_alternatives.md` "Live mode hint pipeline" section.
2. **Far-range automated rough-hint** (P0, after issue#5). Two-stage stage-1-rough → stage-2-AMCL-precise. Operator-locked direction: same memory file's "Automated rough-hint" section.
3. **issue#4 — AMCL silent-converge diagnostic**.
4. **restart-pending banner real fix** — superseded by PR #59 for the action-driven path; non-action paths (initial mount, idle polling) still need the polling/SSE guard flag.
5. **B-MAPEDIT-2 origin reset** (cosmetic).
6. **issue#6 — B-MAPEDIT-3 yaw rotation** (revisit two-point UX pattern).
7. **issue#7 — boom-arm angle masking** (optional, contingent on issue#4).

### 2026-05-01 (early morning → late morning — 00:00 KST → 12:18 KST, thirteenth-session — issue#3 pose hint UI + install fix + AMCL frame y-flip fix; production-critical latent bug surfaced & fixed)

Thirteenth-session shipped issue#3 pose hint UI (PR #54) as a full-pipeline PR — Planner → Reviewer Mode-A (1 Critical + 6 Must + 8 Should + 5 Nit) → Writer (6 commits) → Reviewer Mode-B (1 Critical + 4 Must + 10 Should + 5 Nit). Operator-locked UX directives during the run reshaped the plan twice: (1) **blended (A click+drag) + (B two-click) + C numeric companion** gesture (operator: "A, B 둘 다 같이 녹이는 것은 어때? C도 x,y numeric 옆에 yaw numeric 입력창 함께"), (2) **Live mode pose-hint deferred** to issue#5 (operator: "issue#6도 회전 중심 대신 지금처럼 두 점으로 해도 될 것 같은데... 이건 그때 가서 생각해보자"). HIL surfaced two **production-critical latent bugs** that had been masking each other for the entire project history.

**Production-critical revelation #1 — install ReadOnlyPaths**: SPA Config-tab PATCH always returned `write_failed`. Diagnosis: systemd unit's `ReadOnlyPaths=/etc/godo` + `ProtectSystem=strict` made the directory read-only from the tracker process's namespace view; `mkstemp + rename` for atomic TOML write failed with EROFS. Latent because nobody had used the SPA Config write path before issue#3 needed Tier-2 σ tuning. PR #55 moved tracker.toml default to `/var/lib/godo` (already in `ReadWritePaths` via `StateDirectory=godo`); install.sh new step `[6/8]` seeds an empty TOML + migrates existing `/etc/godo/tracker.toml` from a pre-fix install. Test isolation (PR #55 + #56) hardened `test_rt_replay` and `test_config` to mkstemp a per-process TOML and export `GODO_CONFIG_PATH`, preventing the developer-host runtime TOML from leaking into in-tree tests.

**Production-critical revelation #2 — AMCL y-flip frame bug**: Operator HIL after PR #54 deploy saw AMCL pose **point-reflected about canvas center** — (x, y, yaw) all mirrored. PGM walls and live LiDAR overlay had the same shape but offset by 180° canvas-center inversion. tracker restarts and σ adjustments did not perturb the pattern. Diagnosis (operator-driven, then code-traced): PGM raster is row-major top-row-first; ROS YAML `origin` is bottom-left; AMCL kernels (`Amcl::seed_global`, `evaluate_scan`) treated `cells[cy=0]` as bottom anchored at `(origin_x, origin_y)`. Pre-fix loader stored PGM bytes as-is, so `cells[cy=0]` was actually the TOP row — internal frame inverted. AMCL was self-consistent (likelihood + seed both used the inverted frame so convergence still worked) but its output poses lived in a frame mirrored against the YAML semantics. PR #56 row-flips the PGM payload at load time (option X over option Y because `build_likelihood_field`'s EDT pass would otherwise compute distances in the inverted frame, defeating any single lookup-side flip). Single-point fix; downstream EDT, likelihood, seed sampling, free-cell enumeration all read coherent bottom-first frame.

**Operator's debugging contribution was essential**: operator hypothesized "약간 yaw와 위치가 x축 대칭되어있는 듯한 느낌? 지금 보니 AMCL은 정상이고, 반환 좌표 방향이나 부호가 달라서 map pgm과 오버레이가 일치하지 않는 듯 한 느낌이라면?" before any code-trace had identified the y-flip. The hypothesis pointed directly at the convention mismatch we then confirmed in code.

**Operator-locked decisions this session**:

1. **Hint = strong command**, not weak prior. After PR #56 frame fix, σ sweep on a correct frame showed σ_xy ∈ {0.3, 0.4, 0.5} all kept hint dominant when hint was wrong. Operator's framing: "가까운 곳 두면 실제위치 우세. 이상한 곳 두면 먼 곳 우세. 일단 난 지금의 힌트도 좋은 것 같아. hint 안에 있을 때에는 정밀도가 저하되면 안 된다는 것이 내 생각" — locked σ defaults at 0.5 m / 20°. See `project_hint_strong_command_semantics.md`.
2. **Live mode = pipelined one-shot driven by previous-pose-as-hint**. Re-frames issue#5 from "make Live's per-scan step() deeper" to "Live ≡ pipelined one-shot, never bare step()". Live carry-over σ is tight (matches inter-tick crane-base drift, NOT padded). See `project_calibration_alternatives.md`.
3. **Far-range automated rough-hint** as production-friendly hint elimination path. Two-stage: stage 1 = rough (x, y, yaw) from far-range LiDAR features (range > ~3 m, where points are stable studio walls/corners); stage 2 = AMCL precise localization seeded by stage 1. Subsumes earlier approaches A (image match) / B (GPU features) / C (pre-marked landmarks) by adding the far-range pre-filter. Maps to AF analogy: stage 1 = phase detection, stage 2 = contrast detection, operator-click = manual focus override.

**Process violations + lessons**:

- **Production tracker.toml ↔ branch Config struct compatibility**: PR #56 deploy failed initially because `/var/lib/godo/tracker.toml` carried `amcl.hint_sigma_*_default` keys (PATCHed during PR #54 σ probing), but PR #56's main-based binary did not yet recognize those keys → `unknown TOML key` → exit 2 → systemd auto-restart loop. Pre-deploy hygiene rule in `feedback_toml_branch_compat.md`: when deploying any branch whose Config struct lacks a key already present in the runtime TOML, strip the key from TOML or stage the deploy.
- **Restart-pending banner stale recurrence**: PR #45 fixed the banner clearing after a service-restart action, but the banner re-locks on every fresh tab/page load until manually reloaded. Self-healing hypothesis from earlier dismissed; real fix needs polling/SSE guard flag on initial mount + after every server-side restart_pending mutation. Tracked in `project_restart_pending_banner_stale.md`. Small frontend follow-up PR.
- **PR merge-order mistake**: operator merged PR #54 (issue#3) before PR #56 (frame fix). Recoverable — rebased PR #56 on the new main, conflicts zero, force-pushed. Worth noting because the safer order would have been "frame fix first, then issue#3 σ work means anything." Lesson is in the operator's already-locked rule, not new memory.
- **Origin pick accumulation**: `04.29_v3.yaml` origin shifted from SLAM-original `[-10.855, -7.336, 0]` through 4 cumulative ADD picks to `[14.995, 26.164, 0]` over the prior twelfth-session. The frame fix works regardless of origin sign, but the cosmetic cleanup (resetting to a meaningful origin) is a deferred yaml edit.

**3 PRs landed this session**:

| PR | issue | Title | State |
|---|---|---|---|
| #54 | issue#3 | initial pose hint UI for AMCL multi-basin fix | merged |
| #55 | — | install fix — tracker.toml moved to /var/lib/godo for RW under sandbox | merged |
| #56 | — | AMCL row-flip PGM at load to match bottom-first cell convention | merged |

**Test count delta** (cumulative across the 3 PRs):

- C++ ctest hardware-free: 31 → 45 (+14, plus refactored existing). Highlights: 5000-round atomic-ordering torture test in `test_uds_server` for the issue#3 hint M3 release/acquire chain; consume-once + back-compat + second-OneShot-no-republish in `test_cold_writer_offset_invariant` for the seqlock + atomic-flag split.
- webctl pytest (excluding `-m hardware_tracker`): 671 → 683 (+12 — issue#3 CalibrateBody all-or-none + integration round-trips + byte-identical encoder pin).
- Frontend vitest: 299 → 311 (+12 — issue#3 PoseHintLayer state machine + numeric panel + TrackerControls "Calibrate from hint" gating + originMath yawFromDrag + apiPostCalibrate body anti-regression).

**HIL acceptance achieved**:
- frame fix (PR #56): 50% calibrate runs land in perfect alignment (test9-pattern), 45% close-to-perfect with mild yaw bias, ~5% complete miss (test11-pattern, gone when operator uses hint). Pre-fix: 100% mirror inversion.
- issue#3 hint UI (PR #54): operator-locked semantic — hint near true pose locks to true pose; hint far locks to hint. σ sweep 0.3 / 0.4 / 0.5 all sweet, default 0.5 m / 20° sticks. The remaining test11-class miss-rate is now operator-controlled (driven by hint placement quality, not AMCL randomness).

**Open queue for next session** (operator-locked priority):

1. **issue#5 — Live mode pipelined hint** (NEW shape per operator lock-in). Live = pipelined one-shot driven by previous-pose-as-hint. Replaces the simpler step()-with-prior design from prior memories. See `project_calibration_alternatives.md` "Live mode hint pipeline" section.
2. **Far-range automated rough-hint** (NEW direction per operator lock-in). Two-stage: far-range feature → rough hint → AMCL precise. Lower-cost than full image / GPU / landmark approaches because it pre-filters to high-information distant points.
3. **issue#4 — AMCL silent-converge diagnostic** (still useful — measures both issue#5 and the far-range automation). Now has thirteenth-session HIL data as baseline.
4. **restart-pending banner real fix** (small frontend PR). polling/SSE guard flag on initial mount + after server-side mutations.
5. **B-MAPEDIT-2 origin reset** (cosmetic). Reset `04.29_v3.yaml` origin to SLAM-original `[-10.855, -7.336, 0]` or operator-meaningful value.
6. **issue#6 — B-MAPEDIT-3 yaw rotation** (deferred — revisit per operator's earlier "그때 가서 생각해보자" framing now that hint UX is validated).
7. **issue#7 — boom-arm angle masking** (still optional, contingent on issue#4 measurements).

### 2026-04-30 (afternoon → late evening — 14:00 KST → 22:00 KST, twelfth-session — B-MAPEDIT-2 origin pick + B-MAPEDIT-2 minor cleanup + banner-refresh fix + PR β shared map viewport + β.5 Map Edit controls parity + branch-check feedback + issue#2.2 panClamp/pinch + issue#2.2 sensitivity hotfix + issue#2.3 Map Edit overlay/pan/pinch fix; AMCL multi-basin observation surfaced)

Twelfth-session shipped Phase 4.5 P2 / B-MAPEDIT-2 origin pick as a single full-pipeline PR (#43), then operator-driven follow-ups (#44 Minor cleanup, #45 banner-refresh fix, #46 shared map viewport with zoom UX uniform + Map Edit LiDAR overlay, #47 controls parity, #48 panClamp+pinch hotfix, #49 branch-check feedback memory, #50 Map Edit overlay/pan/pinch fix). 8 PRs across the session. Notable: PR β bundle was uncovered via HIL to have THREE different bugs not caught by Mode-A or Mode-B (panClamp formula inversion at high zoom, pinch zoom missing entirely, MapMaskCanvas duplicate map-layer hiding shared underlay) — operator's iterative deploy → use → fix cycle is the canonical bug-finder for layout-heavy refactors.

**Mid-session conceptual revelation**: operator surfaced a question whether Problem 1 (AMCL accuracy — runtime localization) and Problem 2 (frame redefinition — YAML metadata edit) were the same problem. Untangling them produced `feedback_two_problem_taxonomy.md`: they share the visualization (overlay) but require different tools. B-MAPEDIT-2/3 only address Problem 2; Problem 1 needs pose hint + AMCL diagnostics. test4/test5 HIL screenshots showed AMCL multi-basin yaw error (90° between one-shot and live for the SAME physical pose) — `project_amcl_multi_basin_observation.md` documents the observation and reprioritizes issue#3 (pose hint) as P0 over previously-queued issue#4 (diagnostic).

**Process violation + lesson**: Parent committed dd348ba (pinch-zoom sensitivity hotfix) directly to `main` after operator's `git checkout main` silently switched the shared-Pi working tree. Operator chose Option C (leave + lock the rule), and `feedback_check_branch_before_commit.md` is the structural witness — `git branch --show-current` before every commit, read `[branch <hash>]` in commit output before push.

**8 PRs landed/queued this session**:

| PR | Issue | Title | State |
|---|---|---|---|
| #43 | — | B-MAPEDIT-2 origin pick (dual GUI + numeric, ADD sign) | merged |
| #44 | — | B-MAPEDIT-2 minor cleanup (Mode-B M1 + M2) | merged |
| #45 | issue#1 | restart-pending banner refresh after service action | merged |
| #46 | issue#2 | shared map viewport + zoom UX + Map Edit LiDAR overlay | merged |
| #47 | issue#2.1 | Last pose card + Tracker controls on /map + /map-edit | open |
| #48 | issue#2.2 | panClamp single-case + pinch zoom (HIL hotfix) | merged + dd348ba sensitivity follow-up direct on main |
| #49 | — | branch-check-before-commit feedback memory | open |
| #50 | issue#2.3 | Map Edit overlay/pan/pinch (PR #46 HIL hotfix) | open |

Naming convention introduced this session: **`issue#N.M`** (operator-locked 2026-04-30 KST — Greek letters too hard to type). Sequential integers for independent PRs, decimal for follow-ups stacked on a parent. Memory: `feedback_layered_canvas_alpha_architecture.md` is referenced informally in PR #50 description but not as a standalone memory file (the lesson is "drop redundant opaque layers; alpha-aware compositing already works in Canvas API").

**Open queue for next session** (priority order, operator-locked):
1. issue#3 — initial pose hint UI (multi-basin direct fix, P0)
2. issue#4 — AMCL silent-converge diagnostic (measures issue#3 effect)
3. issue#5 — pipelined K-step Live AMCL (per-scan accuracy)
4. issue#2.4 — Map page common header layout (TrackerControls + LastPoseCard + ScanToggle promoted to sub-tab-independent region; Overview canvas/MapListPanel reorder; STACKED on PR #47)
5. issue#6 — B-MAPEDIT-3 yaw rotation (deferred until AMCL stable)
6. issue#7 — boom-arm angle masking (optional, contingent on δ result)
7. memory bundle save (this session-close)

### 2026-04-30 (late morning through early afternoon — 10:08 KST → 13:30 KST, eleventh-session — 4 PRs: B-MAPEDIT brush + 2 prod hotfixes + Map sub-tab refactor + hierarchical SSOT doc reorg)

Eleventh-session shipped Track B-MAPEDIT (brush-erase + auto-backup + restart-required) as a single PR through the full agent pipeline, caught **two prod regressions during HIL** that bypassed both writer self-checks and Mode-B review, then continued with two operator-driven follow-ups: a Map Edit sub-tab refactor (per HIL request) and a hierarchical SSOT doc reorg (root `CODEBASE.md` + `DESIGN.md` + cascade rule). Total: 4 PRs in one continuous session. The two HIL regressions are instances of the cross-language "tests pass + prod breaks" pattern first surfaced by PR-A2 in the prior session — second occurrence confirms it is a structural gap, not a one-off.

- **4 PRs merged on main** (final = `787c986`):
  - **PR #39 → main** (`feat(map-edit): B-MAPEDIT brush erase + auto-backup + restart-required`, +2876 / -20, 4 commits): Adds `POST /api/map/edit` (admin-gated multipart) + new SPA `/map-edit` route. Operator paints a circular brush over fixtures → auto-backup of active PGM/YAML → atomic in-place rewrite of masked pixels to canonical free value (254) → restart-pending sentinel touched. Three modules: `map_edit.py` (sole owner of mask→PGM transform; atomic mkstemp + os.replace mirroring `auth.py::_write_atomic`), extended `restart_pending.touch()` (webctl sets, tracker clears at boot — both run as `ncenter`), `app.py` orchestrates backup-first ordering. Frontend: `/map-edit` route + `MapMaskCanvas` component (sole owner of mask `Uint8ClampedArray`; logical PGM coords NOT CSS pixels — DPR-safe). Two new invariants: webctl `(aa)` map_edit-sole-ownership + frontend `(u)` MapMaskCanvas-sole-mask-state. Mode-A folded plan applied 14 items (M1-M3 mandatory + S1-S3 + T1-T4 + N1-N3); Mode-B verdict APPROVE-WITH-NITS (F1 dir-mode 0750→0755 folded as `ec3c6e8`; F2 mask_decode_failed naming deferred). Plan-time invariant letter `(y)` was stale; writer correctly shifted to `(aa)` after rechecking main.
  - **PR #40 → main** (`fix(B-MAPEDIT): prod hotfixes (multipart dep + alpha-tracks-paint)`, +138 / -5, 3 commits): Two regressions caught in 30 minutes of operator HIL on news-pi01.
    - **Fix 1 — `python-multipart` runtime dep missing**: `POST /api/map/edit` returned HTTP 500 with `AssertionError: The python-multipart library must be installed`. Starlette's `request.form()` requires it at runtime; dev `.venv` had it installed transitively (so 11/11 integration tests passed locally and CI), but prod `uv sync --no-dev` did not pull it. Both writer and Mode-B reviewer accepted the wrong claim ("Starlette 1.0 ships its own multipart parser") because the dev test green-light masked the env drift. Fix: pin `python-multipart>=0.0.9` as runtime dep + regen `uv.lock`.
    - **Fix 2 — `getMaskPng` alpha=255 for every pixel**: After Fix 1 unblocked the request, the FIRST Apply (single small brush stroke) nuked the entire active map to 100% FREE. Root cause: `MapMaskCanvas.svelte::getMaskPng()` set `img.data[off + 3] = 255` unconditionally for every pixel — painted AND unpainted. The backend decoder (`map_edit.py:177-181`) takes the alpha-as-paint branch first when the PNG has an alpha channel, so every unpainted pixel passed the "paint" test. Backup-first ordering rescued operator's work — `04.29_v3.pgm` restored from `/var/lib/godo/map-backups/20260430T031846Z/`. Fix: alpha tracks paint signal (unpainted → 0, painted → 255). Regression test added: spies `putImageData` inside `getMaskPng`'s temp canvas → asserts alpha at painted vs unpainted indices. Old test pass missed this because the canvas shim's `toBlob` returned a fixed 4-byte placeholder; the real mask round-trip (JS getMaskPng → PNG → backend Pillow decode) was never end-to-end.
  - **PR #41 → main** (`feat(frontend): Map Edit as Map page sub-tab`, +121 / -16, 1 commit): Operator HIL request 2026-04-30 12:30 KST after B-MAPEDIT shipped. Move `/map-edit` from a top-level sidebar entry to a sub-tab inside the Map page, mirroring System tab's Processes / Extended resources sub-tab idiom (PR-B). `Map.svelte` hosts the sub-tabs (Overview / Edit); URL-backed semantics (`/map` → Overview, `/map-edit` → Edit) so refresh + browser back-button + external bookmarks all keep working. `MapEdit.svelte` retains all data-testids; existing 6 unit + 3 e2e tests anchor unchanged. `MAP_SUBTAB_OVERVIEW` + `MAP_SUBTAB_EDIT` constants added; sidebar Map Edit row removed. Why URL-backed for Map but component-local for System: System sub-tabs are session-scoped views, Map's Edit is destination-scoped (operators get `/map-edit` URLs in chat, e2e specs hit it directly, post-Apply redirect lands on `/map`). Bundle delta +0.27 KB gzipped.
  - **PR #42 → main** (`docs: hierarchical SSOT reorg — root CODEBASE.md + DESIGN.md + cascade rule`, +484 / -39, 1 commit): Operator request 2026-04-30 11:50 KST. Two-level SSOT-doc hierarchy. New root `CODEBASE.md` (192 LOC) = three-stack overview + module roles per stack + cross-stack data flow diagram + links to per-stack files. New root `DESIGN.md` (70 LOC) = TOC + cross-doc orientation for `SYSTEM_DESIGN.md` and `FRONT_DESIGN.md`. The load-bearing piece is the **cascade-edit rule**: leaves are SSOT, root updates only when the family *shape* shifts (new stack / cross-stack arrow / top-level design doc); root files never duplicate leaf invariant text or design narrative. Reviewers (Mode-B) treat root-level update without a leaf counterpart, OR a leaf update that contradicts the root, as Critical. CLAUDE.md §3 Phases refreshed (was stuck at "Phase 1 ◄ current" — three sessions stale; now reflects Phase 4.5 P2 reality), §5 Directory structure adds the new root files + corrected per-stack invariant tail annotations, §6 extended with cascade rule + NEXT_SESSION cache-role rule (operator analogy: SSOT = RAM, NEXT_SESSION.md = cache; 3-step absorb routine — read → record → prune). Two new memory entries: `feedback_codebase_md_freshness.md` extended (+53 LOC) with the cascade rule; `feedback_next_session_cache_role.md` new (86 LOC). Zero code or test changes.

- **Side observation logged** (`.claude/memory/project_silent_degenerate_metric_audit.md`): when the map was 100% FREE, AMCL one-shot reported `σ_xy=0` (looked converged) while `pose.yaw` bounced 165° → 135° → 333° → 292° between ticks. Classic degenerate convergence: no likelihood gradient → all particles tie → variance collapses → metric trivially passes. 10 audit candidates listed across AMCL/FreeD/UE/webctl/systemd subsystems where similar "metric trivially passes when input degenerates" patterns could hide bugs. Scheduled to run after B-MAPEDIT-2 lands.

- **Operator decision captured into in-repo memory**: `.claude/memory/project_map_edit_origin_rotation.md` — Map Edit family spec recording the **dual-input rule**: every continuous correction value (B-MAPEDIT-2 origin pick + B-MAPEDIT-3 rotation) MUST support GUI click AND numeric entry side-by-side, not one or the other. GUI is for coarse exploration; numeric is for fine reproduction from a measured offset. Single-input proposals are flagged as regression in future plans. Operator decision 2026-04-30 11:35 KST when scoping B-MAPEDIT-2.

- **HIL verification on news-pi01 post-hotfix-deploy**:
  - `python-multipart==0.0.27` installed via `uv sync --no-dev` on `/opt/godo-webctl/.venv/`.
  - Frontend bundle rebuilt + redeployed to `/opt/godo-frontend/dist/` (`index-CPi2ceQe.js`).
  - PGM restored from auto-backup `20260430T031846Z` after the alpha-bug nuke.
  - Three successful Apply operations: two on real obstacles, one on empty space — every backup snapshot present (`20260430T031846Z` / `033105Z` / `033202Z` / `033221Z`); active PGM histogram healthy (1386 occupied / 5258 unknown / 5004 free, walls preserved); no yaw tripwire warnings post-restart.

- **Test deltas**:
  - Backend pytest 615 → 628 (+13 net from PR #39's +33 minus pre-existing slot accounting). PR #40 added 1 case via the alpha regression spy (still counted in frontend below). PR #41 + #42 zero test changes.
  - Frontend unit 197 → 204 (+6 from PR #39 mapEdit cases, +1 from PR #40 alpha regression). PR #41 + #42 zero test changes.
  - Frontend e2e 37 → 40 (+3 from PR #39 playwright cases).

- **Tooling milestones**:
  - **One-session 4-PR record extended.** Tenth session (prior) hit 4 PRs through the agent pipeline; eleventh session matched it but with a different shape — feature + hotfix + UX refactor + meta-docs reorg, all driven by HIL feedback rather than pre-planned scope. Demonstrates the pipeline holds under both "parallel feature surface" (tenth) and "serial HIL-driven" (eleventh) cadences.
  - **Cross-language drift gap formally classified as structural.** PR-A2 (tenth session) was the first occurrence; PR #40 Fix 1 (`python-multipart`) + Fix 2 (`getMaskPng` alpha) are the second + third. Common failure mode: dev test green + prod break. Mitigation candidates are now memory-pinned for follow-up (wire-shape SSOT pin retrospective + canvas-PNG round-trip CI).
  - **Hierarchical SSOT docs live.** Cascade-edit rule operator-locked. Mode-B reviewer mandate extended (root↔leaf contradictions are Critical). NEXT_SESSION.md cache-role rule pinned with the 3-step absorption routine.

- **Operator-prioritized next-session priority order** (refreshed 2026-04-30 13:30 KST close):
  1. **B-MAPEDIT-2 origin pick (dual-input GUI + numeric)** — top priority. ~150 LOC, spec at `.claude/memory/project_map_edit_origin_rotation.md`. Provisional `POST /api/map/origin` admin-gated, JSON body `{x_m, y_m, mode: "absolute"|"delta"}`. YAML `origin[0..1]` update only — no bitmap rewrite. Auto-backup of YAML; restart-pending sentinel.
  2. **Silent degenerate-metric audit** (Task #6) — 10 candidates listed. AMCL one-shot guard for low-information map (`entropy_of_likelihood_field < threshold` or similar) is the highest-severity item.
  3. **Wire-shape SSOT pin retrospective** — second-+ third-instance regression now demands action: regex-extract Python ERR_*/FIELDS tuples from C++ `json_mini.cpp::format_ok_*`, AND a canvas-PNG round-trip CI step that decodes a real `getMaskPng()` output through Pillow with the same alpha-as-paint semantics.
  4. **Admin password rotation** — small follow-up, `scripts/godo-webctl-passwd` to rotate default `ncenter`/`ncenter`. Local-only or SSH-shell-only per operator policy.
  5. **Deploy hygiene** — surfaced this session: post-merge deploy must rsync BOTH frontend dist AND webctl src. Currently README documents the manual rsync; consider scripting (`scripts/deploy-rpi5.sh`) so future sessions don't repeat the 405-on-stale-backend mistake.
  6. (deferred) B-MAPEDIT-3 rotation + GPU POC + Track D-5-Live + Track D-5-P + pipelined-pattern audit.
  7. (low priority) `test_jitter_ring` flake fix.

### 2026-04-30 (morning — 06:07 KST → 10:08 KST, tenth-session — 4 PRs landed: PR-A1 + PR-A2 + PR-B + PR-C)

Tenth-session ran the full agent pipeline four times in parallel for the System tab + Config tab feature set. Single-session record: **4 PRs merged on `main`** (5d3cb95, 9c52446, b701f83, 43e100c) plus a session-close docs commit. Operator did GH UI merges + news-pi01 deploy; Parent orchestrated planner → Mode-A → writer → Mode-B for the two larger PRs, direct-write for the two hotfixes.

- **4 PRs merged on main** (final = `5d3cb95`):
  - **PR #37 → main** (`fix(webctl): unwrap C++ tracker's keys envelope in /api/config (PR-A2)`, +72 / -17, 1 commit): Hotfix for a wire-shape drift bug latent since PR-CONFIG-β shipped. The C++ tracker emits `{"ok":true,"keys":{...}}` (per `json_mini.cpp:374`); the Python `project_config_view` only stripped `ok` and passed `keys` through unchanged → SPA's `current["amcl.foo"]` resolved to `undefined` → Config tab rendered "—" for every Tier-2 row even when the tracker was fully online. Latent because both unit + integration tests mocked the WRONG (flat) UDS reply. Fix: `project_config_view` unwraps `keys`, fixtures reshaped to actual C++ wire, `uds_client.get_config` docstring corrected. **No C++ changes** — the projection layer is the right bridge.
  - **PR #35 → main** (`fix(systemd): polkit rule for ncenter-group reboot/shutdown (PR-A1)`, +160 / -35, 1 commit): Operator HIL after PR-A merge surfaced HTTP 500 `subprocess_failed` on SPA System tab Reboot Pi / Shutdown Pi buttons. Root cause: PR-A's polkit rule only authorised `org.freedesktop.systemd1.manage-units` (start/stop/restart). The shutdown shim's reboot/power-off path goes through a different action family — `org.freedesktop.login1.{reboot,power-off}*`. Fix: second `polkit.addRule()` block in `49-godo-systemctl.rules` covering all six login1 variants (reboot / power-off, each in plain / -multiple-sessions / -ignore-inhibit form). install.sh + README §7 + production/RPi5/CODEBASE.md invariant `(o)` extended to the dual-rule shape; cross-language SSOT table 4 → 5 rows.
  - **PR #36 → main** (`feat(webctl,frontend): System tab process monitor + extended resources (PR-B)`, +4193 / -125, 3 commits squashed): Adds Processes + Extended resources sub-tabs to the System tab; both 1 Hz SSE-fed, both anon-readable. Processes lists every PID classified into `general` / `godo` / `managed` (bold + accent name styling for managed); sortable by CPU%; text-search + "GODO only" filter; duplicate-PID red banner (defense-in-depth on top of CLAUDE.md §6 pidfile locking). Extended resources renders per-core CPU bars + mem bar + disk bar (no GPU per operator decision — Trixie firmware regression on V3D `gpu_busy_percent`). Pure stdlib `/proc` + `/sys` parsers (no `psutil`, no `subprocess`, no `vcgencmd`). Cross-language SSOT pinned end-to-end: `test_godo_process_names_match_cmake_executables` regex-extracts `add_executable(<name>` from each `production/RPi5/src/*/CMakeLists.txt`. webctl invariant `(z)` + frontend invariant `(y)` claimed.
  - **PR #38 → main** (`feat(frontend): Config tab View/Edit safety gate + best-effort Apply (PR-C)`, +1466 / -108, 2 commits + 1 rebase-resolution commit): Adds a View / Edit safety gate on the Config page so the existing per-row blur-PATCH model can no longer fire by accident. Page-level `mode: 'view'|'edit'` state in `Config.svelte`; admin-gated EDIT button top-right; click EDIT → Cancel/Apply button group. Apply uses best-effort sequential PATCH via new `stores/config.ts::applyBatch(pending)` (loops all keys, never aborts mid-loop, single refresh + restartPending refresh post-loop). **Cancel never sends a PATCH** — client-side only; successfully-applied prior values persist on the tracker (memory: `project_config_tab_edit_mode_ux.md`). `(default: <row.default>)` muted hint under each row's Current. Korean tracker-inactive banner subscribed to existing `systemServices` store (no new endpoint). frontend invariant `(z)` claimed (post PR-B's `(y)`). Backend zero LOC.

- **Operator-driven design decisions captured into in-repo memory**:
  - `project_config_tab_edit_mode_ux.md` — PR-C operator-locked spec with state machine ASCII diagram + canonical t=0..t=6 Cancel-after-partial walkthrough. Explicitly documents WHY Cancel is client-side only (reverse-PATCH is dangerous + surprising) and WHY best-effort over all-or-nothing (atomic bulk would need C++ UDS verb; keys are operationally independent). Future maintainers reverting either decision should re-read this memory first.

- **Tooling milestones**:
  - First session running 4 parallel PRs through the agent pipeline. Background writer-agent pattern (planner → background writer → Mode-B) scaled cleanly; the only sequencing dependency was branch isolation (Parent committed PR-A1 + PR-A2 + PR-C on separate branches off `main` before kicking each writer, so no shared-tree conflicts).
  - PR-B's writer absorbed a 9-item Mode-A fold + 5-item Mode-B fold without re-review; PR-C's writer absorbed a 3+4+3-item Mode-A fold and a 5-item Mode-B fold the same way.
  - Mode-B identified a real UX bug in PR-C (`적용 중… (k/N)` always rendering `0/N` because the counter was set once and never incremented) — fixed in `94dc4a1` follow-up before merge by dropping the broken `(k/N)` from the label.

- **HIL verification on news-pi01 post-deploy**:
  - install.sh re-run → polkit count 13 → 14 (rule (a) manage-units + rule (b) login1.{reboot,power-off}*).
  - webctl source rsync to `/opt/godo-webctl/` + `systemctl restart godo-webctl` → `/api/health` returns `ok`.
  - frontend `npm run build` + rsync `dist/` to `/opt/godo-frontend/dist/` → SPA refreshed.
  - **Config tab**: 37 Tier-2 keys all show live values (PR-A2 effect — was "—"). `(default: ...)` hint under each row. EDIT button disabled for anon, enabled for admin (PR-C effect).
  - **System tab**: Processes / Extended resources sub-tabs visible. Process table classifies + bold-renders `godo_*` rows (PR-B effect). Reboot/Shutdown buttons return HTTP 200 (PR-A1 effect).

- **Test deltas**:
  - Backend pytest 521 → 615 (+94 net: +76 from PR-B `test_processes.py` + `test_resources_extended.py` + integration cases, +18 from PR-A2 reshape; 1 pre-existing flaky `test_atomic_write_c_concurrent_writers_serialise` unrelated).
  - Frontend unit 164 → 197 (+33: +18 from PR-B `processes.test.ts` + `resourcesExtended.test.ts` + `processTable.test.ts`, +15 from PR-C `config.test.ts` extension).
  - Frontend e2e unchanged at 37.

- **Operator-prioritized next-session priority order** (refreshed 2026-04-30 10:08 KST close):
  1. **B-MAPEDIT** (brush erase, ~950 LOC) — Mode-A folded plan ready (`.claude/tmp/plan_track_b_mapedit.md`).
  2. **B-MAPEDIT-2: origin pick** (~90 LOC bolt-on).
  3. **Pipelined-pattern audit** (Task #9 carryover).
  4. **Admin password rotation** (Task #6 from PR-A NEXT_SESSION; deferred from PR-B; defer further to a Local-only / SSH-shell-only flow per PR-C operator decision).
  5. (deferred) B-MAPEDIT-3 rotation + GPU POC + Track D-5-Live + Track D-5-P.
  6. (low priority) `test_jitter_ring` flake fix.

### 2026-04-30 (early morning — 00:00 KST → 06:07 KST, ninth-session marathon — PR-A full systemd switchover + operator service-management policy)

Single-PR session that started as a one-line polkit rule and grew into the full systemd switchover the operator had been working around for weeks. Multiple bug-fix arcs surfaced during HIL and were folded into the same PR — by the time the merge fired, the SPA System tab was fully populated end-to-end (uptime + memory + envfile + env_stale staleness badge + working Start/Stop/Restart buttons).

- **1 PR merged on main** (final = `dcded7c`):
  - **PR #34 → main** (`feat(systemd): switchover to systemd-managed services + polkit gate (PR-A)`, +1495 / −102 across 31 files, 3 commits squashed): Move production launch from `scripts/run-pi5-*.sh` to systemd-managed services. Adds the polkit rule (`production/RPi5/systemd/49-godo-systemctl.rules`) that lets `ncenter` invoke `systemctl start/stop/restart` on the three GODO units without sudo, unblocking the webctl admin endpoint that previously returned HTTP 500 `subprocess_failed`. Operator service-management policy adopted: `godo-irq-pin` + `godo-webctl` auto-start at boot; `godo-tracker` manual-start via the SPA System tab Start button (avoids any boot-time fail-loop risk on the heaviest RT process). Squash-merged ~06:00 KST as `dcded7c`. New invariants: production/RPi5 `(o) godo-systemctl-polkit-discipline`, frontend SPA addendum on env_stale + lastError UX.

- **PR-A diagnostic arc — 9 distinct bugs uncovered + folded into the same PR during HIL**:
  1. **Polkit rule installation** (the original PR-A scope): `services.control()` invokes `subprocess.run(["systemctl", action, "--no-pager", svc])` as the unprivileged `ncenter` user; systemd 257 + polkit 126 (Trixie) gate `manage-units` actions through polkit. Without the rule, every Start/Stop/Restart click → HTTP 500 `subprocess_failed`. The rule allows the matched triple `(unit, verb)` only — default-deny semantics elsewhere.
  2. **`scripts/run-pi5-*.sh` → systemd switchover scope expansion**: NEXT_SESSION.md / `project_system_tab_service_control.md` had described PR-A as "~120 LOC unit files + polkit", but the unit files had already shipped earlier (Apr 26). Actual PR-A scope was just the polkit rule + missing operational scaffolding. SSOT correction memory entry: `feedback_codebase_md_freshness.md`.
  3. **Operator service-management policy adoption**: User clarified the long-term ops model — SPA is the SOLE control plane for `start/stop/restart`; `scripts/run-pi5-*.sh` was a temporary stopgap while the System tab was incomplete. Policy: `godo-irq-pin` + `godo-webctl` auto-start at boot; `godo-tracker` manual-start. Memory entry: `project_godo_service_management_model.md`.
  4. **`/run/godo/` ownership flipped**: Per the new policy, webctl owns `/run/godo/` across reboots (was tracker-owned). Changes: `godo-webctl.service` adds `RuntimeDirectory=godo` + `RuntimeDirectoryMode=0750` + `RuntimeDirectoryPreserve=yes`; removes `Wants/After=godo-tracker.service` (must boot independently). `godo-tracker.service` adds matching `RuntimeDirectoryPreserve=yes` so the dir survives whichever stops first.
  5. **`godo-tracker.service` `ReadWritePaths` widened**: First systemd boot surfaced `restart_pending::clear` → ROFS warning. Was `ReadWritePaths=/run/godo`, now `ReadWritePaths=/run/godo /var/lib/godo`. + `MemoryAccounting=yes` on both tracker and webctl units (RT impact negligible — cgroup v2 memory.current is a kernel-side counter).
  6. **`/etc/godo/{tracker,webctl}.env` env templates seeded by `install.sh`**: `GODO_AMCL_MAP_PATH=/var/lib/godo/maps/active.pgm` (the C++ default `/etc/godo/maps/studio_v1.pgm` does not exist on news-pi01); `GODO_WEBCTL_HOST=0.0.0.0` (LAN/Tailscale access); `GODO_WEBCTL_SPA_DIST=/opt/godo-frontend/dist`. New `production/RPi5/systemd/godo-tracker.env.example`. `install.sh` now 6 steps including `[5/6] Seeding /etc/godo/tracker.env (preserves existing real .env)`.
  7. **`/boot/firmware/cmdline.txt` cgroup_enable=memory**: First HIL showed `MemoryCurrent=[not set]` despite `MemoryAccounting=yes` — root cause = RPi 5 firmware default kernel cmdline injects `cgroup_disable=memory`. Appended `cgroup_enable=memory` (kernel resolves explicit enable wins) → reboot → `cgroup.controllers` now includes `memory` → SPA renders live MemoryCurrent for tracker (76 MiB) + webctl (48 MiB). godo-irq-pin still null because `Type=oneshot + RemainAfterExit=yes` has no live cgroup post-exit (correct).
  8. **`godo-irq-pin.sh` device-name lookup**: Post-reboot HIL saw `godo-irq-pin.service` fail with `echo: write error: Operation not permitted` at line 40. Root cause = Linux IRQ numbers shift across reboots when device-registration order changes; the previous `pin()` call hit IRQ 183 which had moved from `107d004000.spi` to a kernel-fixed `pwr_button` GPIO (NO_BALANCE / fixed-affinity flag). Replaced hardcoded IRQ list with `/proc/interrupts` device-name lookup at runtime; tolerates EPERM on writes (logs and continues instead of failing the unit). SPI/eth0/USB/mmc all pin correctly post-reboot regardless of IRQ-number drift.
  9. **`services.py::ALLOWED_PROPERTIES` rename + envfile-based env display**: SPA was showing `—` for uptime AND empty Environment list. Two unrelated fixes: (a) `ActiveEnterTimestampRealtime` → `ActiveEnterTimestampMonotonic` (the Realtime variant is not exposed by systemd 257 — silently absent from `systemctl show` output); converted to unix epoch via `time.monotonic() + time.time()` reads — same `CLOCK_MONOTONIC` epoch. (b) Env display via `EnvironmentFile=` text content read instead of `/proc/<pid>/environ`. Cap-bearing tracker (CAP_SYS_NICE + CAP_IPC_LOCK ambient capabilities) is kernel-marked non-dumpable, so cross-process `/proc/*/environ` reads return EPERM even for the same user. envfile read avoids that gate entirely; new `_parse_environment_files_paths()` + `_read_envfile()` + `_envfile_newer_than_process()` helpers. New `env_stale: boolean` field on `ServiceShow` / `SystemServiceEntry` / `SYSTEM_SERVICES_FIELDS` (8 fields, was 7) — true when any envfile mtime is later than `active_since_unix`. `EnvVarsList.svelte` renders an amber "envfile newer — restart pending" badge.

- **Post-reboot HIL findings folded into the same PR (3 follow-up commits)**:
  - `71f2ef9 fix(spa): auto-dismiss + active-state clear for ServiceStatusCard lastError`: Original Track B-SYSTEM PR-2 wired auto-dismiss only for the 409 transition gate; every other error code (`subprocess_failed`, `request_aborted`, network failures) parked indefinitely until next user click. Operator-observed false-stale cases (webctl self-restart `subprocess_failed`, tracker restart outlasting fetch timeout = `request_aborted`) → widened auto-dismiss to ALL error codes (5 s, same `SERVICE_TRANSITION_TOAST_TTL_MS`) AND added a `$effect` that clears `lastError` immediately when a polling tick reports the service active and the SPA is not mid-action.
  - `c4f6cce fix(webctl): tier config schema path resolution + deploy hpp to /opt`: Operator opened SPA Config tab post-PR-A and saw an empty list. Root cause = `config_schema.py::_CPP_SCHEMA_PATH` hardcoded the dev-tree sibling layout (`<repo>/godo-webctl` next to `<repo>/production/RPi5`) which has no equivalent on production hosts (webctl is at `/opt/godo-webctl`, source tree was never deployed). Fix: (a) `_resolve_schema_path()` picks first available from (env var, dev tree, /opt fallback); env var wins so `/etc/godo/webctl.env` can override. (b) `install.sh` step `[1/6]` now installs `config_schema.hpp` to `/opt/godo-tracker/share/`. (c) `webctl.env.example` documents `GODO_WEBCTL_CONFIG_SCHEMA_PATH=/opt/godo-tracker/share/config_schema.hpp`. Re-running install.sh after a tracker rebuild refreshes both the binary AND the schema mirror in lock-step.

- **Operator architectural decisions captured as session memory**:
  - `feedback_codebase_md_freshness.md` — Every implementation task must update relevant CODEBASE.md before commit/merge/push. Drift (e.g. NEXT_SESSION.md describing PR-A as "~120 LOC unit files + polkit" when unit files had shipped weeks earlier) propagates confusion across sessions.
  - `project_godo_service_management_model.md` — SPA is the SOLE start/stop/restart UI; auto-start policy (irq-pin + webctl auto, tracker manual). Direct-script launches are dev/diagnostic only.

- **End-to-end HIL on news-pi01 post-reboot (verified all wire contracts)**:
  - `journalctl -u polkit | grep rules` → `Finished loading, compiling and executing 13 rules` (12 default + ours).
  - `systemctl is-active godo-irq-pin godo-webctl` → both auto-active; `godo-tracker` inactive (manual-start).
  - `systemctl start godo-tracker.service` AS `ncenter` (no sudo) → exit 0, active.
  - `POST /api/system/service/godo-tracker/{stop,start,restart}` AS admin → HTTP 200 `{"ok":true,"status":"<state>"}` (was HTTP 500 `subprocess_failed`).
  - `GET /api/system/services` returns `active_since_unix` + `memory_bytes` + `env_redacted` + `env_stale` for each service. Sample: tracker 75 MiB / webctl 48 MiB / irq-pin null (oneshot+RemainAfterExit, expected).
  - `sudo touch /etc/godo/tracker.env` → tracker `env_stale` flips to `true`; restart clears it.
  - SPA Config tab renders all 40 schema rows (4 hot + 14 restart + 22 recalibrate) post-`/opt/godo-tracker/share/` deploy.
  - Negative cases: 404 `unknown_service` (`godo-frobnicate`), 400 `unknown_action` (`purge`).

- **Test deltas**:
  - Backend pytest 502 → 521 (+19 net across new envfile-path / `_read_envfile` / `_envfile_newer_than_process` / oneshot env handling / env_stale integration; 1 pre-existing flaky `test_atomic_write_c_concurrent_writers_serialise` and 1 pre-existing /api/calibrate auth test failure — both unrelated to PR-A).
  - Frontend unit 165 → 164 (no net change, env_stale stub field threaded through existing tests).
  - Frontend e2e unchanged at 37 (env_stale: False threaded into stub corpus).

- **Operator-prioritized next-session priority order** (refreshed 2026-04-30 06:07 KST close):
  1. **PR-B: process monitor + extended resources** (~550 LOC) — `/api/system/processes` SSE with GODO whitelist + `duplicate_alert` flag if multiple PIDs match same expected name; `/api/system/resources/extended` (per-core CPU + GPU + mem + disk); SPA System sub-tab.
  2. **B-MAPEDIT** (brush erase, ~950 LOC) — Mode-A folded plan ready.
  3. **B-MAPEDIT-2: origin pick** (~90 LOC bolt-on, high-ROI).
  4. **Pipelined-pattern audit** (Task #9 carryover).
  5. (deferred) B-MAPEDIT-3 rotation + GPU POC + Track D-5-Live + Track D-5-P.
  6. (low priority) `test_jitter_ring` flake fix.

### 2026-04-29 (evening through midnight — 16:35 KST → 2026-04-30 00:30 KST, fourth-through-eighth-session marathon — Track D family + sigma annealing solves AMCL convergence)

Five-PR marathon spanning four-plus session boundaries. The afternoon-close (third-close above) had identified a SPA scan-overlay 5×-scale bug + suspected Y-flip; the marathon resolved that, then chased AMCL convergence through several misdiagnoses before isolating the actual root cause (sigma_hit tightness) and shipping coarse-to-fine annealing with auto-minima tracking. Final HIL: **k_post 10/10, σ_xy median 0.009m** (was 0/10 + 6.679m). Operator visual on `/map` confirms.

- **5 PRs merged on main** (final = `194599b`):
  - **PR #29 → main** (`fix(frontend): resolution-aware scan overlay (Track D scale + Y-flip)`, +1731 / −22, 21 files): Track D scale fix. SPA's `MAP_PIXELS_PER_METER = 100` constant deleted; introduced `mapMetadata` store fetching YAML resolution/origin + new `/api/maps/{name}/dimensions` endpoint (PGM header parse, no Pillow round-trip). PoseCanvas world↔canvas math now metadata-driven; image draws at native pixel size; reactive `$effect` re-fetches bitmap on `mapImageUrl` change (Mode-A M3 — fixes silent half-fix where preview swap painted new coords on old pixels). New invariants webctl `(y)` + frontend `(x)`. Mode-B APPROVE-WITH-FOLD; nit cleanup `b622b7c`. HIL visual confirmed scale + worldToCanvas Y orientation correct. Squash-merged ~10:23 KST as `ba9c53c`.
  - **PR #30 → main** (`fix(frontend): negate RPLIDAR CW angle + lift convergence gate`, +127 / −16, 5 files): Track D-2 short-circuit. SPA `projectScanToWorld` negates the angle to convert raw RPLIDAR CW (per `doc/RPLIDAR/RPLIDAR_C1.md:128`) → REP-103 CCW frame. Lifted Mode-A M3 `pose_valid !== 1` gate so operator can see scan shape pre-AMCL-convergence (chicken-and-egg removed). Scan SHAPE now traces studio walls per operator visual (test222.png). ~15 LOC, fully SSOT-specified, HIL-verified pre-merge → planner+Mode-B short-circuited per `feedback_pipeline_short_circuit.md`. Squash-merged ~10:55 KST as `07d6baf`.
  - **PR #31 → main** (`fix(tracker): negate RPLIDAR CW angle in scan_ops boundary (Track D-3)`, +136 / −3, 5 files): Track D-3 full pipeline. C++ AMCL counterpart of PR #30's SPA fix at `production/RPi5/src/localization/scan_ops.cpp:48` — single-line negation at the CW→CCW boundary; comment block + invariant `(m)` cite RPLIDAR_C1.md and the wire-format-stays-CW contract with PR #30. New TEST_CASE in `test_amcl_components.cpp` with 7 sub-asserts covering 90° (right side) and 270° (left side) beams at yaw=0 and yaw=45° — bias-block via hand-computed world endpoints, pose plugged via `a = beams[0].angle_rad` (Mode-A M3) so a downsample-and-test shared bug cannot ride through silently. New `production/RPi5/doc/convergence_hil.md` HIL protocol. Squash-merged ~14:00 KST as `29526c6`. **Important caveat**: Track D-3 was hypothesized as the root cause of 1-in-15 AMCL convergence per the original Mode-A plan; the 21:00 KST sigma sweep (below) showed it isn't. D-3 still merged as defensive math discipline.
  - **PR #32 → main** (`feat(tracker): coarse-to-fine sigma annealing for OneShot AMCL (Track D-5) + auto-minima tracking`, +1627 / −71, 30 files including the scope-additive ~60 LOC commit `7b5aec0`): the actual fix. Coarse-to-fine annealing through `cfg.amcl_sigma_hit_schedule_m` (default `"1.0,0.5,0.2,0.1,0.05"` paired with `cfg.amcl_sigma_seed_xy_schedule_m` default `"-,0.10,0.05,0.03,0.02"`); `Amcl::set_field` swap method with single-thread cold-writer doc-comment; `cold_writer.cpp::converge_anneal` rebuilds `LikelihoodField` per phase, seeds_global at phase 0 / `seed_around` for k>0, runs ≤ `cfg.amcl_anneal_iters_per_phase` iters per phase. **Auto-minima tracking** added 2026-04-29 23:20 KST after first HIL showed σ_xy stuck at 0.036m (5-phase schedule's final σ=0.05 over-tightens into sub-cell discretization on 5cm-cell maps): `converge_anneal` now tracks the best (min) `xy_std_m` across phases and returns THAT pose (not the final-phase pose). Patience-2 early break: 2 consecutive worse-than-best phases triggers stop, single-phase noise tolerated. Operator can SAFELY granularize the schedule without over-tightening — algorithm self-stops at empirical minimum. CODEBASE.md invariant `(n)`. Mode-A APPROVE-WITH-FOLD on initial; auto-minima added post-Mode-B as a follow-up commit. HIL: 5-phase default + auto-minima → k_post 10/10, σ_xy median 0.009m, single-basin (1.15, ~0, 173°) lock. Squash-merged ~14:20 KST as `c9b4ba8`.
  - **PR #33 → main** (`fix(freed-passthrough): default UDP target port 50002 → 50003 (hotfix)`, +12 / −6, 4 files): operator-reported regression — `godo_freed_passthrough` was sending FreeD UDP frames to `10.10.204.184:50002` but **port 50002 is reserved on the UE host for an existing listener**. Default landed at 50002 in `22b4097` (initial implementation), was fixed once previously, regressed back. Hotfix changes the compiled default to 50003 + adds an in-source NOTE so the next contributor doesn't undo. Squash-merged ~14:21 KST as `194599b`.

- **AMCL convergence diagnostic arc** (the marathon's central thread, 2026-04-29 19:20–23:30 KST — see `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md` for the empirical sweep + analysis):
  1. Post Track D-3+D-2 deploy (~19:20 KST): operator HIL still failing — k_post 0/10 across many calibrate attempts, σ_xy ~6.7m hovering at map center. Initially assumed remaining bug = map storage Y-orientation in `load_map`.
  2. Track D-4 attempt (~20:00 KST): row-flip rows in `occupancy_grid::load_map` so `cells[0..W]` = bottom-of-image. Built, restarted, probed → still 0/10 / σ ~6.7m. Then experimentally reverted Track D-3's negation (D-3-reverted + D-4-kept) → STILL 0/10 / σ ~6.7m. **Conclusion: neither D-3 nor D-4 affects convergence.** D-4 working-tree changes reverted; D-3 already merged kept (math discipline).
  3. Sigma sweep (~21:00 KST): empirically tested σ_hit ∈ {1.0, 0.5, 0.2, 0.1, 0.05} via tracker CLI override + `python3 /tmp/godo_amcl_probe.py` 10-trial probe. Results: σ=0.05 default 0/10 / σ_xy 6.679m; σ=0.1 0/10 (cliff); σ=0.2 9/10 / σ_xy median 0.006m but split across 3 basins; σ=0.5 3/10 / 2 basins; σ=1.0 2/10 / single basin. **Convergence cliff identified between σ=0.1 and σ=0.2; sigma_hit tightness was the actual root cause** — at σ=0.05, the 5000 random global particles can't find a useful seed within ±5cm of the right pose.
  4. Operator proposed coarse-to-fine annealing (~21:30 KST): wide σ to lock single basin → narrow to refine. Track D-5 plan written + Mode-A reviewed + Writer implemented + Mode-B approved. PR #32 default schedule `[1.0, 0.5, 0.2, 0.1, 0.05]`. HIL → k_post 0/10 / σ_xy median 0.036m. Annealing CONVERGED on the right basin every time but final phase σ=0.05 over-tightens into sub-cell discretization on the 5 cm-cell map. Manual override `[1.0, 0.5, 0.2]` → k_post 10/10 / σ median 0.012m.
  5. Operator proposed auto-minima tracking (~23:00 KST): schedule travels through the cliff; algorithm picks the σ that produced min σ_xy and returns THAT pose. Patience-2 early break absorbs single-phase noise. Implemented + HIL → k_post 10/10 / σ_xy median 0.009m on the FULL DEFAULT 5-phase schedule (now self-stopping at phase 2 σ=0.2). **The annealing schedule can be freely granularized without over-tightening.** Eight-session marathon close.

- **Operator architectural insights captured as session-spanning memory** (`.claude/memory/`):
  - `project_pipelined_compute_pattern.md` — Operator's variable-scope / CPU-pipeline analogy: at tick t, tier_k runs (t-k+1)th iteration. N tiers in parallel = K + N - 1 wallclock vs N×K sequential. Apply to AMCL annealing (Track D-5-P), Live tracker, FreeD smoother, map activate phased reload, phase 5 UE convergence-confidence monitor.
  - `project_amcl_sigma_sweep_2026-04-29.md` — empirical sweep + cliff identification.
  - `project_map_edit_origin_rotation.md` — Map Edit tab feature spec: brush erase (B-MAPEDIT, planned) + origin pick (~90 LOC, NEW, click-pixel-as-(0,0)) + rotation (~250 LOC, deferred). Origin pick has the highest immediate operator value (studio center as origin via pole-marker workflow).
  - `project_system_tab_service_control.md` — operator-prioritized P0 next session: systemd unit files + polkit so Start/Stop/Restart buttons actually work + live process list with duplicate-PID alert + CPU/GPU resource view.
  - `project_videocore_gpu_for_matrix_ops.md` — RPi 5 VideoCore VII GPU mostly idle; candidate offloads (rotation, EDT, AMCL particle weighting). Need baseline measurement + POC before integration.
  - `project_rplidar_cw_vs_ros_ccw.md` — D-2/D-3 hypothesis history; hypothesized as 1-in-15 root cause but sigma_hit was. D-2/D-3 kept as defensive measures.

- **Test deltas across the marathon**:
  - Backend pytest 491 → 502 (+11 net across PR #29 dimensions endpoint, PR #31 PgmHeaderInvalid, PR #32 sigma schedule + anneal config + Amcl::set_field).
  - Frontend unit 143 → 165 (+22 net, all from PR #29 — mapYaml + mapMetadata + poseCanvasScale + poseCanvasFreshness + poseCanvasImageReload).
  - Frontend e2e 36 → 37 (+1, PR #29 wheel-zoom regression case).
  - All hardware-free ctest 45/45 green throughout (one observed `test_jitter_ring` flake during D-5 build — RT timing-sensitive; not a regression; queued for low-priority follow-up).
  - All build-greps clean except 2 pre-existing carryovers (`udp/sender.cpp:103`, `uds/uds_server.cpp:119`) from PR #28/#27 — explicitly carved out in plan.

- **Operator-prioritized next-session priority order** (set 2026-04-29 24:00 KST close):
  1. **System tab service control + process monitor** — make Start/Stop/Restart actually work (systemd units + polkit, deferred from Task #32 across multiple sessions) + live process list with duplicate-PID alert + CPU/GPU resource view.
  2. **B-MAPEDIT** (brush erase, planned, Mode-A folded, ~950 LOC).
  3. **B-MAPEDIT-2: origin pick** (~90 LOC bolt-on, high-ROI).
  4. **Pipelined-pattern audit** (Task #9 carryover): SSE producer-consumer, FreeD smoother stages, UE 60Hz publish, map activate phased reload, AMCL Live tiered confidence.
  5. **B-MAPEDIT-3: rotation** + GPU POC (deferred, research-grade).
  6. **Track D-5-Live + Track D-5-P** (parallel pipelined annealing — research-grade follow-ups).
  7. (low priority) `test_jitter_ring` flake fix.

### 2026-04-29 (afternoon — 12:33–16:34 KST, third close — mapping fatal bug fix + service observability shipped + Track D scale bug discovered)

Two-PR session that landed (1) Phase 4.5 P2 service observability with admin-non-loopback action endpoint, and (2) a fatal mapping pipeline bug fix that had been silently producing single-frame maps for ~24h. Plus a high-impact diagnosis at session end of a SPA scan-overlay scaling bug that affects every map view.

- **2 PRs merged on main** (final = `f311218`):
  - **PR #27 → main** (`feat(p4.5): Track B-SYSTEM PR 2 — service observability`, 28 files / +2855 / −25): backend `system_services.py` (cached snapshot, 1 s TTL) + `services.py::ServiceShow` 7-field dataclass + `ServiceTransitionInProgress` exception → 409 Korean detail (`SERVICE_TRANSITION_MESSAGES_KO` per Korean-reading-convention 받침 rule per service: 트래커→가, 웹씨티엘→이, 아이알큐 핀→이) + `parse_systemctl_show` / `redact_env` pure helpers + new admin-non-loopback `POST /api/system/service/{name}/{action}` (mirrors `/api/system/reboot` pattern); frontend `ServiceStatusCard.svelte` (admin-gated action buttons via `$isAdmin`) + `EnvVarsList.svelte` (collapsible env, `(secret)` suffix on redacted) + `serviceStatus.ts` chip-class SSOT + `routes/System.svelte` 5th panel polling at 1 Hz with stale banner. Webctl invariants `(v)` system_services anon-readable + 1 s TTL + env redacted, `(w)` control() refuses start/restart on activating + stop on deactivating with 409 Korean detail, `(x)` `/api/system/service/{name}/{action}` admin-non-loopback. Frontend invariant `(t)` services panel polls at 1 Hz, no SSE. Test deltas: backend 431 → 491 (+60), frontend unit 111 → 143 (+32), e2e +3 cases. Mode-A folds M1-M6 + S1-S7 + N1-N5 + T1-T6 + §8 Option-C addendum (S1 activity_log + S2 504/500 exception mapping + TB1 monkeypatch target). Mode-B reproduced 491 pytest + 143 vitest green; ran live ROS 2 param verification independently. Squash-merged at ~13:25 KST as `49e0ede`.
  - **PR #28 → main** (`fix(mapping): replace static identity TF with rf2o laser odometry`, 7 files / +255 / −27): root-cause repair of single-fan PGM artifact. `godo-mapping/Dockerfile` adds second colcon overlay block (rf2o ros2 SHA-pinned `b38c68e46387b98845ecbfeb6660292f967a00d3`, package.xml format-1→3 sed patch in-Dockerfile, `--packages-select rf2o_laser_odometry` for incremental build); `launch/map.launch.py` deletes `static_odom_to_laser` block, adds `rf2o` Node with **byte-equal `name='rf2o_laser_odometry'`** matching YAML namespace (M1 critical fold — without this, ROS 2 param loader silently fails and rf2o boots with hardcoded `base_frame_id=base_link` / `init_pose_from_topic='/base_pose_ground_truth'` defaults, producing exact symmetric failure mode); explicit `{'use_sim_time': False}` pin (M2); `config/rf2o.yaml` Tier-2 (7 keys, all annotated); `slam_toolbox_async.yaml` makes upstream-default `minimum_travel_distance: 0.5` + `minimum_travel_heading: 0.5` explicit with comment citing slam_toolbox SSOT URL (M5 documentation-of-load-bearing-defaults); `verify-no-hw.sh --full` adds `ros2 pkg executables rf2o_laser_odometry` smoke (S4); godo-mapping invariant `(h)` `odom→laser` TF is rf2o-published, never static, plus Plan A/B/C decision tree for legitimate fallbacks. Mode-A folds M1-M5 + S1-S4 + N1. Mode-B reproduced docker build identical image SHA `92b3076da18e…`, ran live ROS 2 `ros2 param get /rf2o_laser_odometry base_frame_id` returning `String value is: laser` (override confirmed), audited all 7 source-declared rf2o parameters against YAML (zero unknown / zero missing). Squash-merged at ~16:00 KST as `f311218`.

- **Mapping bug timeline (KST)**:
  - **~14:30** — user opened `0429_2.pgm` as image, saw single fan-shape from one position despite walking + loop closure. ("이상하다, 분명 이동하면서 지도를 만들었는데...")
  - **~14:35** — statistical confirmation: 4 maps under `godo-mapping/maps/` showed 63-114 occupied pixels each (vs thousands expected); all single-fan signatures.
  - **~14:45** — root cause located at `launch/map.launch.py:44-50`: a static identity TF `odom→laser` (added 2026-04-28 to "close the TF chain" without external odom) silently lied to slam_toolbox about motion. slam_toolbox's `minimum_travel_distance: 0.5` (Jazzy default, not overridden in our YAML) gate fired against odom-derived motion = 0; only 1 scan ever integrated.
  - **~15:00** — Plan A chosen ("정석대로 가자"): rf2o_laser_odometry overlay build + launch rewrite. Plan written to `.claude/tmp/plan_mapping_pipeline_fix.md`, Mode-A folded.
  - **~15:30** — writer build-first gate passed (rf2o colcon `1 package finished [47.3s]`, no warnings).
  - **~15:45** — Mode-B reproduced + approved.
  - **~15:55** — HIL run 1 (`test_rf2o_v.pgm`, ~3 m walk, walkable area limit): occupied 1390 (13× the 107 broken baseline), free 51.7% (vs 5.7%), unknown 47% (vs 94%). User confirmed: "좋아 완전 맞아 저 장소 맞다" — rendered map matches actual studio geometry.
  - **~16:00** — PR #28 merged.
  - **~16:05** — HIL run 2 (`04.29_v3.pgm`, two-lap walk + loop closure): 2978 occupied / 60.7% free / 36.5% unknown. Map shape further refined.
  - **~16:20** — AMCL convergence test on `04.29_v3`: tracker started, calibrate run repeatedly. Converged ~1 in 15 attempts; non-converging cases drift completely outside studio. **Map quality is no longer the bottleneck** — Phase 2 hardware-gated levers (LiDAR pivot offset + AMCL Tier-2 tuning) now isolated as the next blocker.
  - **~16:30** — Track D scale bug discovered: scan-overlay renders at ~5× the PGM image size + suspected Y-flip (각도 틀어짐). Diagnosed as `MAP_PIXELS_PER_METER = 100` (`godo-frontend/src/lib/constants.ts:98`) hardcoding 0.01 m/cell while our slam_toolbox maps are 0.05 m/cell. PoseCanvas `:165-167` draws image as `naturalWidth × zoom` (no resolution scaling) while `worldToCanvas` `:120` uses the constant. Fix queued for next session as TL;DR #1.

- **Mid-session pivot — B-MAPEDIT pause + clean discard**: at ~13:00 KST a B-MAPEDIT writer pass had been kicked off and ran for ~50 min producing ~600 LOC of source + tests (map_edit.py + MapEdit.svelte + MapMaskCanvas.svelte + brushMask.ts + tests + CODEBASE.md edits + 21 file modifications). The writer reached the commit step but the user discovered the mapping bug while reviewing PGMs and interrupted. Per user direction ("일단 방금 작업했던거는 나중에 꼬일 것 같아. 아깝지만 clean시키고 매핑 먼저 가자"), the partial work was discarded clean (`git checkout .` + `git clean -fd .claude/worktrees/`) — no stash. B-MAPEDIT writer must re-run fresh in next session from the §8-Mode-A-folded plan at `.claude/tmp/plan_track_b_mapedit.md`.

- **CLAUDE.md §6 update**: added "Date + time stamps in date-bearing SSOT entries" rule. Going forward, all `PROGRESS.md` Session log entries / `doc/history.md` blocks / `CODEBASE.md` change-log entries / `NEXT_SESSION.md` close markers / `.claude/tmp/plan_*` Mode-A/B fold sections / `.claude/memory/*` date-bearing memories MUST carry KST (GMT+9) time alongside the date. The Pi 5 production host is on KST so `date` returns the right value directly; on Mac/Windows use `TZ='Asia/Seoul' date '+%Y-%m-%d %H:%M KST'`.

- **Cross-cutting test deltas** (this session):
  - webctl pytest: 431 → 491 (+60).
  - frontend vitest: 111 → 143 (+32).
  - frontend playwright: 33 → 36 (+3).
  - C++ ctest: unchanged this session (no tracker C++ touched in either PR).
  - Build greps: unchanged.

- **Live system on news-pi01** (2026-04-29 16:34 KST close):
  - main = `f311218`, webctl running PID 386478 (started 2026-04-29 12:11 KST).
  - Tracker test run during this session — currently **may still be running** in user's foreground terminal from the AMCL convergence test (~16:20 KST onward); next session start should `pgrep -af godo_tracker_rt` and either reuse or stop+restart.
  - godo-mapping container image rebuilt this session with rf2o overlay; image SHA `92b3076da18e…`.
  - Active map: now `04.29_v3.pgm` (real two-lap walk, replaces broken `0429_2.pgm` symlinks).
  - `/run/godo/`: still owned by ncenter from earlier session; survives until reboot only.
  - LAN-IP path blocked at SBS_XR_NEWS AP client-isolation; Tailscale `100.127.59.15` confirmed operational.
  - Tmux session `godo` (created Wed Apr 29 12:33 KST) currently still attached.

### 2026-04-29 (Phase 4.5 P0.5 + P1 — Track D + B-DIAG + B-CONFIG α+β shipped, P1 complete)

Massive single-session push: all four queued PRs delivered, reviewed, folded, merged. Phase 4.5 operator surface is now feature-complete through P1 (P2 = B-MAPEDIT / B-SYSTEM / B-BACKUP next session).

- **4 PRs landed on main** (final = `1fb8129` + post-merge fix `265f5f6`):
  - **PR #14 → main** (`Track D`): Live LIDAR overlay. C++ tracker `Seqlock<LastScan>` published in cold writer at the same publish seam as `LastPose`; `get_last_scan` UDS handler mirrors `get_last_pose` byte-for-byte; webctl `/api/last_scan` + `/api/last_scan/stream` SSE @ 5 Hz; SPA `lib/scanTransform.ts` + `stores/lastScan.ts` (refcounted, gated on overlay toggle so SSE never opens until operator flips on) + `<ScanToggle/>` + `PoseCanvas` 3rd canvas layer. Two NEW build-greps `[hot-path-isolation-grep]` + `[scan-publisher-grep]`. Mode-A 3 majors (wire schema parallel-`angles_deg[]` array, arrival-wall-clock freshness gate, `pose_valid` flag) + 2 test-bias folded; Mode-B 5 should-fix (S1 wire-order pin via format_ok_scan regex, S2 unused `<algorithm>`, S3 magic `0.001` → `MM_PER_M`, S4 comment honesty, TB-A torn-read distinctness via iteration marker) folded.
  - **PR #18 → main** (`B-DIAG`): Diagnostics page. Multiplexed `DiagFrame` SSE @ 5 Hz combining pose + jitter + amcl_rate + resources. New publisher thread `diag_publisher` running `SCHED_OTHER` with `try/catch` failure isolation (TM9). `JitterRing` lock-free 1W/1R + `JitterStats` percentile compute. Mode-A renamed `scan_rate` → `amcl_iteration_rate` (semantic honesty: metric measures AMCL iteration cadence, not raw LiDAR rate; in Idle the rate is 0 Hz by design). Three new build-greps `[hot-path-jitter-grep]` (symmetric writer/reader contract: 1 ref total in Thread D body + 0 snapshot refs) + `[jitter-publisher-grep]` + `[amcl-rate-publisher-grep]`. Journald subprocess (`logs.py`) with `services.ALLOWED_SERVICES` allow-list reuse + argv-list invocation + 504 timeout mapping. Mode-A 3 majors + 2 test-bias folded; Mode-B 3 should-fix (S1 Annotated `Query(le=...)` for native 422 instead of inside-handler ValidationError 500, S2 anon-200 list adds `/api/diag/stream` then reverts to dedicated SSE test per achievable-smoke argument, S3 `// SINGLE-WRITER ONLY` comment + invariant) + 1 test-bias (TB2 `ar.hz == doctest::Approx(2.0)` content pin) folded.
  - **PR #19 → main** (`PR-CONFIG-α`, C++ tracker only): 37-row Tier-2 schema in `core/config_schema.hpp` (`// clang-format off` + `static_assert(N == 37)`); `HotConfig` 40 B trivially-copyable struct (M1 fold dropped `divergence_*` after grep verified zero consumers); atomic TOML write protocol (`access(W_OK)` early-detect → `mkstemp` adjacent → write → `fsync` → `close` → `rename(2)`, tmp unlinked on every failure mid-sequence); `apply_set` + `apply_get_*` + `restart_pending` flag manager + 3 new UDS commands (`set_config` / `get_config` / `get_config_schema`); 3 new build-greps `[hot-path-config-grep]` (Thread D loop body) + `[hot-config-publisher-grep]` + `[atomic-toml-write-grep]`. Mode-A pushed back on the original ~2650 LOC single-PR plan and forced a 2-PR split (α C++ only, β webctl + SPA + cold_writer reader migration). Mode-A 3 majors (HotConfig fields, 35→37 row inventory, PR shape split) + 2 test-bias folded; Mode-B 0 majors + 1 should-fix (S1 TB2 deferral note for 4 unmocked WriteOutcome variants) + 3 nits folded.
  - **PR #20 → main** (`PR-CONFIG-β`, webctl + SPA + cold_writer reader migration + cross-language parity): Python `config_schema.py` regex-extracts `core/config_schema.hpp` BY REAL PATH (TB1 fold mirrors `LAST_POSE_FIELDS` precedent); `assert len(rows) == 37` parity pin; 4 new endpoints (`GET /api/config` anon, `GET /api/config/schema` anon w/ 60 s process cache, `PATCH /api/config` admin, `GET /api/system/restart_pending` anon); SPA `<ConfigEditor/>` 37-row table with reload-class indicators (✓ hot, red `!` restart, red `‼` recalibrate); `<RestartPendingBanner/>` Mode-A S5 differentiation (tracker ok + flag = "재시작 필요", tracker unreachable + flag = "시작 실패 — journalctl 확인"); single-mount banner invariant `(s)` in `App.svelte` with `Config.svelte` explicitly NOT rendering it; cold writer per-iteration reads `hot_cfg_seq.load()` instead of `cfg.deadband_*` (test_cold_writer_reads_hot_config 4 cases). Cross-language SSOT chain pinned at the real-path level.

- **Pipeline rigor**: every PR went through full multi-agent (planner → Mode-A → Parent fold → writer → Mode-B → Parent fold). Mode-A reviews caught 9 majors total across the 4 PRs (3 Track D + 3 B-DIAG + 3 B-CONFIG); Mode-B caught 0 must-fix blockers but 12 should-fix items (most folded inline, a few deferred to follow-up tracks with explicit notes). All 8 commits on main carry Co-Author-By trailer.

- **Stacked-PR merge mechanics surprise**: gh's `pr merge --rebase --delete-branch` deleted the head branch of #14 (`feat/p4.5-track-d-live-lidar`). PR #15 had base = that branch → GitHub auto-closed #15 on base-branch deletion. Same chain reaction down the stack. Worked around by recreating PRs #15/#16/#17 → #18/#19/#20 against main fresh after each upstream merge + `git push --force-with-lease` to rebase the head branches onto the new main. Audit trail moves to the new PR numbers; original PRs stay closed with cross-links in their descriptions. Lesson: with stacked PRs, retarget the next PR's base to main BEFORE merging the current one (gh's behavior is "close on base-deleted", not "auto-retarget").

- **Cross-cutting test deltas** (cumulative this session):
  - C++ ctest: 30 → 44 hardware-free targets (+14 test files, ~70 new TEST_CASEs).
  - webctl pytest: 256 → 386 (+130 cases).
  - frontend vitest: 47 → 99 (+52 cases).
  - frontend playwright: 14 → 28 (+14 cases).
  - Build greps: 3 → 10 clean (the 7 new greps lock down the publisher/reader seams that the new types require; `[rt-alloc-grep]` WARN-only line stays the pre-existing `udp/sender.cpp:103` `std::string(...)` cited at boot, no Track D/DIAG/CONFIG regression).

- **Post-merge LAN-browser hotfix** (commit `265f5f6`, after PR chain merged):
  - `stores/config.ts`: `Promise.all` → `Promise.allSettled` so the 37-row schema lands even when `/api/config` returns 503 (tracker unreachable). Without this the SPA showed an empty table on a tracker-down dev box.
  - `Sidebar.svelte`: dropped `{#if isAdmin}` gate around the `/config` nav row. Track F's read-anon / mutate-admin discipline was already enforced inside `<ConfigEditor>` via the `admin` prop; the Sidebar gate was a second check that hid the page from anon viewers entirely. Per user request ("로그인 하지 않은 상태에서도 config 페이지와 diagnostics 데이터는 모두 볼 수 있게 하는 것이 좋겠어").
  - `godo-mapping/maps/.gitignore`: added `.activate.lock` + `.active.*.tmp` (Track E webctl runtime artefacts).

- **Live system on news-pi01** (2026-04-29 close):
  - main = `265f5f6`, webctl reloaded with the new bundle (PID 2172257, `0.0.0.0:8080`).
  - SPA bundle `index-B1VL4OVo.js` (28.07 KB gzipped) serves Dashboard / Map (with Track D + Track E panels) / Diagnostics / Config / Local routes.
  - godo-tracker NOT running by design — banner expected, all UDS-dependent endpoints return 503 (`/api/last_pose`, `/api/system/jitter`, `/api/system/amcl_rate`, `/api/diag/stream`, `/api/config`).
  - Operator-facing endpoints answering 200: `/api/health`, `/api/maps`, `/api/maps/<name>/{image,yaml}`, `/api/system/resources`, `/api/system/restart_pending`, `/api/config/schema`, `/api/last_scan` (returns invalid sentinel; SPA gates rendering on `pose_valid`).
  - LAN-browser check via Tailscale (`100.127.59.15:8080`) confirmed working; LAN-IP path (`192.168.3.22:8080`) blocked at SBS_XR_NEWS AP client-isolation — known-environment limitation, not a code regression.

### 2026-04-28 evening (PR-B merge + Track E PR-13 delivered)

Continuation of the same calendar day after a brief SSH drop; backgrounded agents kept running. Two merge events bracket this session:

- **PR-B merged** (`main = 1f5f3c4`). User did not need a LAN-browser check — the SPA already worked end-to-end over Tailscale and over `http://192.168.3.22:8080/` from the dev box, so `gh pr merge 12 --rebase` ran cold. main now carries the full Phase 4.5 P0 surface: 14 endpoints + 2 SSE + JWT (PR-A) + 4 P0 SPA pages (PR-B) + Track F (anonymous reads, login-gated mutations) + 3a13e1a Mode-B fold + FRONT_DESIGN §8 Track D/E specs.
- **Track E (Multi-map management) — PR-13 created** at SBS-NCENTER/GODO_PI#13, branch `feat/p4.5-track-e-map-management`, 2 commits (`d7b9281` writer, `d4fe79d` Mode-B fold). 5 new endpoints (`GET /api/maps`, `GET /api/maps/<name>/{image,yaml}`, `POST /api/maps/<name>/activate`, `DELETE /api/maps/<name>`), atomic symlink swap (`os.symlink + os.replace` via `secrets.token_hex(8)` suffix, no `tempfile`), `flock(LOCK_EX)`-serialized activate with stale-tmp pre-sweep (M3), defence-in-depth `realpath` containment in every public `maps.py` function (M1, never `assert`), `cfg.map_path` → `cfg.maps_dir` soft migration with every-boot deprecation WARN (Q-OQ-E4), cache-key migration on `map_image.py` to `(realpath, target_mtime_ns)`, `MapListPanel.svelte` admin-gated SPA panel with 3-button `<ConfirmDialog/>` (extended N4 `secondaryAction` prop) and non-loopback hide of the `godo-tracker 재시작` button (M4). 256 pytest pass / 37 vitest pass / 14 playwright pass — all gates clean.
- **Pipeline**: full multi-agent — planner had landed yesterday → reviewer Mode-A APPROVE-WITH-NITS (5 majors + 6 nits + 3 test-bias + 8 positive — Parent folded all majors + N1/N2/N3/N4/N6 + TB1/TB2/TB3 + resolved Q-OQ-E4 every-boot, Q-OQ-E6 keep-`P0`-column inline before writer) → writer (`d7b9281`) → reviewer Mode-B APPROVE-WITH-NITS (1 major + 5 nits + 2 test-bias + 9 positive) → Parent folded the major (M4 hide-button vitest unit test using real Svelte 5 `mount` of `MapListPanel`) + 3 nits (activate/delete dot-traversal corpus parity + Q-OQ-E4 caplog pin + CODEBASE.md `test_maps.py` count fix) → 2nd commit `d4fe79d`. Skipped 4 Mode-B items intentionally (cfg.map_path dead-code branch, stub-server Track F drift on `/api/last_pose`/`/api/local/services`/`/api/activity`, e2e shared global stub state, concurrent-test 40 ms wall-clock budget) — all are deferred follow-ups, none block PR-13 merge.
- **Local plan/review artifacts** (gitignored throwaways): `.claude/tmp/plan_track_e_map_management.md` (Mode-A folded, ~52 KB), `.claude/tmp/review_mode_a_track_e.md`, `.claude/tmp/review_mode_b_track_e.md`. Durable record is the 30-files commit on PR-13 + this entry.
- **Branch state**: PR-13 awaiting LAN-browser check at the office tomorrow morning before merge. After merge, Track D (Live LIDAR overlay) is queued — design at FRONT_DESIGN §8, full pipeline next session.
- **Live system on news-pi01** unchanged from session start: webctl on `0.0.0.0:8080` foreground via `setsid`, JWT/users under `~/.local/state/godo/auth/`, no systemd unit installed. godo-tracker NOT running by design (banner expected).

### 2026-04-28 (Phase 4.5 P0 frontend — PR-A + PR-B + Track F + Track D/E specs)

Massive Phase 4.5 progress: end-to-end operator SPA from backend to working UI, plus two follow-up tracks scoped and one in flight.

- **PR-A (P4.5 backend foundations) — MERGED** (`main = 097d4a7`). 14 new HTTP endpoints + 2 SSE streams + JWT auth (HS256, 6h, bcrypt cost 12) + `users.json` corruption recovery (HTTP 503, app stays up) + `/api/local/*` loopback gate + `godo-local-window.service` Chromium kiosk unit. 174 hardware-free pytest pass + 1 hardware-skipped, ruff clean. Pipeline: planner → reviewer Mode-A (APPROVE-WITH-NITS, M1 + M2 + 9 nits — all folded inline by Parent before writer) → writer → reviewer Mode-B (APPROVE-WITH-NITS, B1 design-seam + 7 nits — Parent folded B1 + N-B1/2/3/6/7) → push → user merged. New module `constants.py` owns webctl-internal Tier-1 (`protocol.py` stays cross-language wire SSOT only); `MAX_RENAME_ATTEMPTS` relocated. New invariant (i)-(m) in `godo-webctl/CODEBASE.md`.
- **PR-B (P4.5 SPA + Mode-B fold + Track F) — OPEN at SBS-NCENTER/GODO_PI#12** (8 commits on `feat/p4.5-frontend-pr-b-spa`). New top-level `godo-frontend/` Vite + Svelte 5.20 SPA: 4 P0 pages (DASH/MAP/AUTH/LOCAL), 30-line custom hash router (svelte-spa-router@4 advertises Svelte 4), token-on-URL SSE per Q3, Confluence-style theme (light + dark toggle), 21 KB gzipped — 10× under the 200 KB target. 29 vitest unit + 11 playwright e2e against stub backend, eslint+prettier clean. Mode-B fold (one commit): map underlay 401 fix (auth-fetch + blob URL — `<img src=…>` cannot send Authorization), M1 SSE-polling-fallback never-stops bug, M2 PoseCanvas `$effect` read-write loop (`untrack()`), tracker-unreachable banner, dead-constant cleanup. Track F fold (one commit, see below) bundled in.
- **Track F (anonymous read access; login required only for mutations) — folded into PR-B**. User feedback during live SPA smoke: monitoring should not require login. Backend dropped `Depends(require_user)` from 7 read endpoints (`/api/last_pose`, `/api/last_pose/stream`, `/api/map/image`, `/api/activity`, `/api/local/services` GET, `/api/local/services/stream`, `/api/local/journal/<n>`); mutations stay `require_admin`. Frontend dropped the auth-redirect from `App.svelte`, added a `로그인` button to TopBar with `익명 열람 중` hint, distinguished anon (`제어 동작은 로그인 필요`) from viewer (`admin 권한 필요`) on Dashboard/Local. `api.ts` 401-redirect now only fires when caller had a token (anon callers see raw 401 without surprise navigation). New webctl invariant (n) documents the model + the SPA mirror; new parametrized backend test covers every mutation endpoint anon → 401. Live verified against the running webctl via curl.
- **Track D (Live LIDAR overlay) — designed in FRONT_DESIGN.md §8**. Operator request: visualize raw LiDAR scan as a toggleable overlay on B-MAP. tracker C++ adds `get_last_scan` UDS handler reading the existing AMCL-side seqlock (μs-level, hot-path 0 impact); webctl `/api/last_scan/stream` SSE @ 5 Hz; SPA `PoseCanvas` adds a 3rd layer + Map.svelte toggle. Estimated ~350 LOC + tests. Single-PR sized; queued after Track E.
- **Track E (Multi-map management) — planner output landed**. User request: list / activate / delete multiple `.pgm + .yaml` map versions through the SPA, no SSH. Architecture: `/var/lib/godo/maps/<name>.{pgm,yaml}` storage + `active.pgm`/`active.yaml` symlinks (atomic via `tempfile.mkstemp` + `os.symlink` + `os.replace` under `flock`). godo-tracker C++ change: ZERO (tracker reads whatever `active.pgm` resolves to at startup; activate triggers a "tracker restart required" prompt to operator). Plan at `.claude/tmp/plan_track_e_map_management.md` (~620 lines, exhaustive: path-traversal threat model with regex `^[a-zA-Z0-9_-]{1,64}$` + reserved `"active"`, atomic symlink swap protocol with crash-mid-swap test, concurrent-activate via `.activate.lock`, cache-invalidation fix for the `(realpath, target_mtime)` key, back-compat with existing `cfg.map_path`). Plan adjusted post-Track F: read endpoints anon, not `require_user`. Mode-A reviewer running in background; resume next session.
- **AMCL convergence — diagnosis confirmed (Phase 2 carry)**: user eyeballed `studio_v2.pgm` (107 s walk + loop closure) in the SPA and confirmed it shows mostly straight wall lines with sparse fine features. This visually corroborates the 2026-04-28-morning AMCL test result (xy_std 5.9 m, 10 000 particles × 200 iter still didn't converge): the studio's T-shape wall geometry plus a feature-poor map gives a flat likelihood surface for global localization. Phase 2 levers stay exactly as documented in NEXT_SESSION.md: ICP-based initial pose seed, retro-reflector landmarks at step corners, slower mapping pass with explicit loop closure, and — critically — restore the LiDAR to pan-pivot center (currently 20 cm offset, temp install). Algorithm work deferred until LiDAR remount; today's work was fully on the operator surface.
- **Live system state (news-pi01, 2026-04-28 close)**: webctl running on `0.0.0.0:8080` for browser smoke, serving `studio_v2.pgm`, `GODO_WEBCTL_*` env-var overrides under `~/.local/state/godo/auth/` so no `sudo` needed for dev. PR-A + Mode-B fold + Track F fold all live. Operator can browse `http://192.168.3.22:8080/` (LAN) or `http://100.127.59.15:8080/` (Tailscale) anonymously, log in as `ncenter`/`ncenter` to enable mutation buttons. godo-tracker NOT running by design (banner is showing — that is the documented expected state).
- **Pipeline used**: full multi-agent pipeline (planner → Mode-A → fold → writer → Mode-B → fold) for PR-A and PR-B. Planner-only for Track E (writer/Mode-A pending into next session). Writer-direct (no planner) for Track F since it was a behavior change of ≤200 LOC across known files. The pipeline-shortcut precedent applied per CLAUDE.md §7.

### 2026-04-27 (Track B — repeatability harness + pose_watch + LastPose UDS surface)

- **Track B landed** on branch `track-b-repeatability` (uncommitted at log time, awaiting closeout commit). Phase 1 measurement instrument PLUS the always-on diagnostic readout channel that sat behind the previously-unexposed AMCL diagnostics. 9 new files + 21 modified, ~2700 net insertions across `production/RPi5/`, `godo-webctl/`, and `godo-mapping/`. Touches C++ (decision below). No edits to `XR_FreeD_to_UDP/`, `doc/RPLIDAR/sources/`, agent defs, or `PROGRESS.md` (Parent owns at closeout).
- **Pose-readback transport — Option 1 (extend UDS schema)**. NEXT_SESSION.md hinted "the latter is cleaner" (separate webctl `/api/last_pose`), but planner showed Option 2 still needs C++ changes upstream (someone has to read AMCL state) and doubles the surfaces. Four-way trade-off table in the plan; Option 1 is smallest blast radius. New UDS command `get_last_pose` is additive; reuses existing `Seqlock<T>` primitive; matches the `set_mode/get_mode/ping` dispatch pattern.
- **"진단 surface는 항상 켜둠, 소비는 on-demand" 원칙 채택** — user raised the question of toggling diagnostics for production. Resolved: `get_last_pose` UDS endpoint is always-on (cost ~30 ns per AMCL iteration for the seqlock store; zero when no client queries). What's "on-demand" is the *consumers* — `repeatability.py` (Phase 1 measurement, operator-launched), `pose_watch.py` (Option C below — cmd window monitor), future Phase 4.5 frontend diagnostic panel. This pattern explicitly rejects compile-flag gating because production diagnosis ("방송 중 카메라가 점프했는데 발산이었나?") is exactly when the surface needs to already exist.
- **Pipeline**: planner v1 → reviewer Mode-A v1 (REWORK, 6 Must-fix + Should/Nit) → planner v2 fold-in → **Mode-A v2 confirmation skipped** per Track A precedent (pipeline-shortcut for clean v2 fold-ins) → writer (4 deviations) → reviewer Mode-B (APPROVE-WITH-NITS) → Parent folded 3 cosmetic nits inline.
- **Option C structure** (user choice over Option B = `--watch` mode in `repeatability.py`): split into separate `pose_watch.py` script, with shared `_uds_bridge.py` helper as SSOT for the Python UDS client. Single Responsibility — measurement vs monitoring are different operational situations with different time pressure and audience. Future diagnostic tools (e.g., `pose_dump_to_grafana.py`) extend this pattern; pinned by new `godo-mapping/CODEBASE.md` invariant (g) "stripts that talk to tracker UDS MUST `from _uds_bridge import UdsBridge`, never copy-paste".
- **`LastPose` 56 B struct + ABI pin** (F1, F7): 5 doubles (x, y, yaw_deg, xy_std_m, yaw_std_deg) + uint64_t `published_mono_ns` + int32_t iterations + 4 uint8_t flags (valid, converged, forced, _pad). `static_assert(sizeof==56)` mirrors the `Offset` precedent at `rt_types.hpp:21`. `is_trivially_copyable` only (Seqlock requirement); NOT `is_standard_layout`.
- **Cold writer F5 ordering pin at OneShot success path only**: `last_pose_seq.store` happens-before `g_amcl_mode = AmclMode::Idle` store, with verbatim Writer comment. The other 4 OneShot Idle-store sites (lidar==null / scan_throw / !got_frame / converge_throw) do NOT publish — they leave the previous LastPose intact. **Live mode also publishes** (Writer deviation 4, Mode-B accepted): plan wording was ambiguous; structurally Live's continuous publish has no race because Live doesn't transition to Idle on each iteration. `forced=1/0` flag distinguishes OneShot vs Live on the wire.
- **Cross-language SSOT three-layer chain** (F2 + F3): canonical at `production/RPi5/src/uds/json_mini.cpp::format_ok_pose` (field names embedded in printf format string); single Python mirror at `godo-webctl/protocol.py::LAST_POSE_FIELDS`; derived `CSV_HEADER` in `repeatability.py`. `test_protocol.py` reads C++ source as text + regex-extracts field names + asserts byte-equal against the Python mirror — drift is mechanical to catch. `repeatability.py` does NOT runtime-import `godo_webctl` (Option C invariant f); test-time SSOT pinning happens via `conftest.py` `sys.path` injection.
- **`format_ok_pose` precision discipline** (F8): `%.6f` for pose fields (1 µm vs 1-2 cm target — well below noise floor), `%.9g` for std fields (preserves dynamic range for sub-mm convergence), `%llu` for monotonic ns. 512-byte reply budget pinned by `test_get_last_pose_reply_under_512_bytes` using INT32_MIN + UINT64_MAX + long-mantissa double — actually exercises the budget rather than rubber-stamping.
- **Hardware-free verification all green**: `production/RPi5/scripts/build.sh` 29/29 hardware-free C++ pass + warnings-as-errors clean; `godo-webctl` 55 passed + 1 skipped (hardware_tracker as expected); `verify-no-hw.sh --quick` 18 tests (10 + 4 + 3 pins + 1 extra positive coverage) PASS from arbitrary cwd. Live `repeatability.py --shots 100` validation deferred to LiDAR reseat (Monday earliest).
- **`verify-no-hw.sh --quick` pytest pre-flight resolver** (Writer deviation 2, accepted): F20 said `python3 -c "import pytest"`; Writer added 2-tier (system pytest first → `uv run --project ../godo-webctl` fallback) since news-pi01's system python3 has no pytest available via apt. Pure superset of F20 spec; no Docker dep introduced (the F20 invariant).
- **Plan files** at `.claude/tmp/plan_track_b_repeatability.md` (v2 final) + `.claude/tmp/review_track_b_repeatability_{v1,v2}.md` (gitignored throwaways). Durable record is the 9 new files + 21 modified files + this PROGRESS.md entry + `doc/history.md` entry.

### 2026-04-27 (Track A — Docker mapping scaffold)

- **Track A landed** on branch `track-a-mapping` (uncommitted at log time, awaiting closeout commit). New top-level dir `/godo-mapping/` ships the LiDAR-independent Docker SLAM toolchain so the moment the RPLIDAR C1 is reconnected (Monday earliest), `bash godo-mapping/scripts/run-mapping.sh control_room_v1` walks the operator through a ~1-minute mapping pass and writes `maps/control_room_v1.{pgm,yaml}`. 11 new files, ~890 lines, zero edits to `production/RPi5/`, `godo-webctl/`, `XR_FreeD_to_UDP/`, or `doc/RPLIDAR/sources/` (F15 scope guard).
- **Pipeline**: planner v1 → reviewer Mode-A v1 (REWORK, 15 findings) → planner v2 (full fold-in, written to `.claude/tmp/plan_track_a_mapping.md`) → reviewer Mode-A v2 (APPROVE-WITH-NITS, 7 new findings; **Parent ran the v2 confirmation directly** after two consecutive subagent API failures — `.claude/tmp/review_track_a_mapping_v2.md`) → writer (11 files, 3 deviations) → reviewer Mode-B (REWORK, 1 Major + 4 Minor) → **Parent applied the narrow one-shot fix to `entrypoint.sh`** (reviewer's recommended path; no third writer round).
- **Major bug caught by Mode-B + fixed**: `entrypoint.sh:12` MAP_SAVER_CMD default was `ros2 run nav2_map_server map_saver_cli` — no `-f ${MAP_OUT_BASE}` flag, leaving the unused MAP_OUT_BASE at L30 as dead code. In production this would have silently written `/godo-mapping/map.{pgm,yaml}` (container-internal cwd default) instead of `/maps/${MAP_NAME}.{pgm,yaml}` (bind-mount). Bind-mounted `maps/` would stay empty after Ctrl+C; container exits 0; failure invisible. Three artifacts agreed on intent (`entrypoint.sh:40-42` comment, `CODEBASE.md:181-184` doc), only the actual default disagreed. Fix: moved MAP_SAVER_CMD assignment to AFTER MAP_OUT_BASE definition (now L32), added `-f ${MAP_OUT_BASE}` to default, rewrote misleading L40-42 comment, added 7-line banner around saver-failure warning so a partial-map situation can't scroll-by unnoticed (Mode-B Finding 3).
- **F1 TF decision — Option A**: `base_frame: laser`, no `base_link → laser` static publisher. Hand-carried mapping has no robot base, so the canonical REP-105 chain is bookkeeping with no operational gain. Single `odom → laser` chain. Resulting map is in laser frame; `cold_writer.cpp` consumes it without frame compensation. Switching to Option B (canonical) is a one-line YAML edit + one new static publisher if production semantics ever require it.
- **F2 unit pin**: `save_map_timeout: 10.0` (double seconds, NOT ms). v1 said `10000`; reviewer caught it would have been 2.7 hours.
- **F9 mockable SIGINT test**: writer added `MAP_SAVER_CMD` env-var indirection at top of `entrypoint.sh` + `TEST_MODE=1` substitutes `sleep infinity` for the `ros2 launch` foreground. Test runs without ROS, without Docker, exits 0, asserts flag file created.
- **SIGINT/SIGTERM gotcha** (Writer deviation, accepted by Mode-B): bash background jobs in non-interactive shells inherit `SIGINT=SIG_IGN` per POSIX, and bash cannot re-trap a signal that was ignored at shell entry. `bash entrypoint.sh &` therefore cannot trap SIGINT in the test path. Test uses `kill -TERM` instead; trap is registered for `INT TERM`; production Docker PID 1 is a foreground exec (not a backgrounded job) so SIGINT works there normally. Trap also signals the foreground child with SIGTERM (not SIGINT) for the same reason — `ros2 launch` Jazzy treats both signals as graceful shutdown. Documented in-file at `entrypoint.sh:46-49` + `tests/test_entrypoint_trap.sh:43-50` + `CODEBASE.md` "Implementation-time discoveries".
- **F11 SSOT discipline**: `production/RPi5/src/localization/occupancy_grid.cpp:148-154` is the single source of truth for accepted YAML keys (`required = {image, resolution, origin, occupied_thresh, free_thresh, negate}` + `warn_accept = {mode, unknown_thresh}`); any unknown key throws `runtime_error` at `load_map`. README's "첫 매핑 후 검증" section asks the operator to `cat maps/<name>.yaml` and compare against the C++ allowlist after the first hardware run. If `nav2_map_server map_saver_cli` Jazzy emits an extra key (e.g., `cost_translation_table`), resolution path is **(a) extend `warn_accept`** in a follow-up RPi5 commit — **never** post-process the YAML in `entrypoint.sh`. The C++ side is authoritative.
- **F13 invariants** (5, mirrors `godo-webctl/CODEBASE.md` pattern): (a) ROS pipeline isolation — verified by `grep -rn 'rclcpp\|ament' production/RPi5/src/` returning zero hits as of `60526cc`, so `--network=host` for ROS DDS is collision-free; (b) Map-format SSOT — see F11 above; (c) Single mapping container at a time — `run-mapping.sh` pre-flight refuses on `docker ps -a --filter name=^godo-mapping$` hit; (d) `/dev/ttyUSB0` not hardcoded — `LIDAR_DEV` env-var override; (e) Hardware-free build/lint, hardware-required run — `verify-no-hw.sh --quick` passes without Docker daemon, `--full` adds `docker build` + image `--help` smoke.
- **Hardware-free verification PASSES**: `bash godo-mapping/scripts/verify-no-hw.sh --quick` exits 0 from any cwd (composite check: `bash -n` on 4 shell scripts, Python AST parse on launch file, mock SIGINT test, `run-mapping.sh --help` parse). `--full` mode (Docker build + 800 MB pull) **deferred to news-pi01** — current dev host has no Docker daemon. Mode-B reviewer flagged this as the only remaining pre-merge gate.
- **Track B (`repeatability.py`) explicitly out of scope** — separate planning round per NEXT_SESSION.md ordering. Will need either UDS schema extension (pose-on-success) or a new `webctl /api/last_pose` endpoint; decision deferred to Track B planner.
- **Plan files** at `.claude/tmp/plan_track_a_mapping.md` (v2 final) + `.claude/tmp/review_track_a_mapping_{v1,v2}.md` (gitignored throwaways). Durable record is the 11 files under `/godo-mapping/` + `CODEBASE.md` "Implementation-time discoveries" + this PROGRESS.md entry. Safe to delete after closeout.

### 2026-04-26 (Phase 4-3 webctl)

- **Phase 4-3 landed** on branch `phase-4-3-webctl` (2 commits: feat + Mode-B housekeeping). New top-level Python project `/godo-webctl/` runs as a separate FastAPI process and drives the C++ tracker exclusively through the UDS server landed in Phase 4-2 D. Operator UX surfaces: 3 HTTP endpoints (`/api/health`, `/api/calibrate`, `/api/map/backup`) + a vanilla-HTML status page with two buttons. 24 new files, 2661 lines insertion, zero edits to `production/RPi5/`.
- **`Amcl::step` σ-overload, OneShot always seed_global, GPIO + UDS surfaces** (Phase 4-2 D) are all consumed end-to-end now: webctl `POST /api/calibrate` → UDS `set_mode {OneShot}` → tracker latches `g_amcl_mode = OneShot` → cold writer's `case AmclMode::OneShot` runs `seed_global` + converge → publishes through Phase 4-2 C deadband (forced=true bypass) → seqlock → 60 fps hot-path UDP send. The whole pipeline can now be exercised by an operator in their browser.
- **Cross-language SSOT** — `protocol.py` mirrors a SUBSET of C++ Tier-1 (UDS wire constants only: `UDS_REQUEST_MAX_BYTES`, mode names, command names, error codes). Tracker-internal Tier-1 (FreeD layout, RT cadence, AMCL sizes) stays C++-only. CODEBASE.md invariant (b) names each pinned constant with file:line citation; `test_protocol.py` pins literal Python values; `test_uds_client.py` pins byte-exact wire (`b'{"cmd":"set_mode","mode":"OneShot"}\n'`). No auto-sync — manual two-side update discipline.
- **Reviewer Mode-A** found a real SSOT bug: planner's D10 said `GODO_WEBCTL_MAP_PATH` is a stem (no `.pgm`) and falsely claimed symmetry with tracker's `cfg.amcl_map_path`. Tracker's actual default is `/etc/godo/maps/studio_v1.pgm` (`.pgm` included); operator using same env value would have webctl looking for `studio_v1.pgm.pgm`. Fixed in plan amendments before Writer entered. Also restructured: paired `_DEFAULTS` + `_PARSERS` + `_ENV_TO_FIELD` tables in `config.py`; three terminal cases on UDS read (newline / EOF / buffer-full → distinct exception classes); HTTPStatus enum (no integer literals); StateDirectory=godo + drop RuntimeDirectory=godo (single-owner /run/godo/); Page Visibility API handbrake; sequence-assertion hardware test.
- **Reviewer Mode-B** found 0 MUST-FIX. Three actionable SHOULD-FIX: S1+S2 wrong C++ file:line citations in CODEBASE.md (commands actually live in `uds_server.cpp:201,206,212`, modes in `json_mini.cpp:119-121, 127-129` — not where the writer cited), S3 `app.py` was string-sniffing `UdsProtocolError` message to distinguish "tracker rejected" (400) from "wire malformed" (502). Folded as a single chore commit: split `UdsServerRejected(UdsError)` subclass carrying `err` attribute; calibrate handler now does `except UdsServerRejected → 400; except UdsProtocolError → 502` with no string scrape. Remaining 5 NITs (logger config, comment polish, button-disable UX, factory unit test) deferred — polish, not correctness.
- **CLAUDE.md §5 directory tree** updated with `/godo-webctl/` entry (P4-3-14, Parent task per Mode-A amendment).
- **SYSTEM_DESIGN.md §7** rewritten — was stale (referenced pre-4-2-D `calibrate_now`/`calibrate_requested` boolean, Pydantic-Settings, TOML on webctl side). Now describes the post-4-2-D `set_mode/get_mode/ping` schema, stdlib dataclass, env-only config, paired SSOT tables, the RuntimeDirectory ownership decision (Mode-A amendment S1, Parent task).
- **`libgpiod-dev` install** lesson from Phase 4-2 D carried forward: when webctl gets a `libsystemd-dev` dep (Phase 4.5+ if it grows native deps), confirm runtime/dev split, name both packages in CODEBASE.md.
- **News-pi01 hardware-required-tracker test** deferred to bring-up: requires a live `godo_tracker_rt` with the UDS server running. Test sequence-asserts post-calibrate `mode == OneShot` then `mode == Idle` within 5 s.
- **Plan file** at `.claude/tmp/plan_phase4_3.md` (gitignored, throwaway) — body + Mode-A amendments fold-back. Safe to delete after this session — `/godo-webctl/CODEBASE.md` + `/godo-webctl/README.md` + this PROGRESS.md entry capture the durable record.

### 2026-04-26 (Phase 4-2 D)

- **Phase 4-2 D landed** on branch `phase-4-2-d-live` (5 commits: Wave A feat + housekeeping, Wave B feat + housekeeping, Mode-B housekeeping). Cold writer state machine is now operator-complete: Live mode body publishes per-scan AMCL fixes through the deadband (`forced=false`) at LiDAR's natural ~10 Hz, OneShot calibrate guarantees convergence regardless of base displacement (always `seed_global`, ~1 s on 5000 particles × 25 iters), and both modes are reachable via two physical buttons (`/dev/gpiochip0` lines BCM 16/20) AND a Unix-domain JSON-lines socket (`/run/godo/ctl.sock`) that Phase 4-3 webctl will consume.
- **`Amcl::step` σ-overload landing** lets Live use a wider motion-model jitter (15 mm xy / 1.5° yaw default) than OneShot's converged-static σ (5 mm / 0.5°). Defended choice (option (a)) — `converge()` semantics preserved, no hidden state, two functions over a parametric helper because OneShot calls `converge()` while Live calls one `step()` per scan. The σ argument's effect is pinned by a bias-block test (two `step()` calls with σ=0.001 vs 0.100 + identical RNG seed produce different `result.xy_std_m`).
- **OneShot seed strategy change** — `if (first_run_inout) seed_global else seed_around` removed; OneShot is unconditionally `seed_global`. User-approved tradeoff: ~1 s slower per calibrate, but always converges (10 cm σ_seed_xy could not handle a 1 m base move, which IS a real production scenario after a tape-out). The `first_run_inout` latch is renamed `live_first_iter_inout` and is re-armed to `true` on every Live exit (including OneShot completion, since OneShot exit IS a Live exit from the latch's perspective). Net: every Live entry seeds globally → cloud is wide enough for σ_live_xy = 15 mm to track ≥ 30 cm/s motion.
- **GPIO + UDS as independent operator-trigger surfaces**: `src/gpio/` uses libgpiodcxx (C++ wrapper of libgpiod v2; system pkg `libgpiod-dev`). Production driver `GpioSourceLibgpiod` blocks in `wait_edge_events` with 100 ms timeout (`SHUTDOWN_POLL_TIMEOUT_MS`) for SIGTERM responsiveness. Last-accepted debounce semantics (rejected events do NOT advance `last_event_ns`) + CLOCK_MONOTONIC time source — burst bouncing > 50 ms cannot let a spurious press through. `src/uds/` uses `poll(2)` for accept (Reviewer Mode-A discovered `SO_RCVTIMEO` does NOT control `accept()` blocking on Linux), hand-rolled JSON for the 4 known message shapes, ModeGetter/ModeSetter callback injection (no global atomic dependency in tests). Both threads self-exit on `g_running.store(false)` + next poll cycle — no `pthread_kill` for either, worst-case shutdown latency 200 ms (2 × 100 ms).
- **Test count** 25 → 28 hardware-free + 1 hardware-required-gpio (libgpiod chip-open + line-config sanity, ran live on news-pi01 once during bring-up). New tests: `test_cold_writer_live_iteration` (Live forced=false + deadband suppression + σ override propagation + live_first_iter latch), `test_gpio_source_fake` (debounce burst pin + S5 press-during-OneShot drop + per-line independence), `test_uds_server` (4 happy commands + parse_error + unknown_cmd + oversized close + shutdown latency ≤ 200 ms via `g_running` not pthread_kill, RAII `TempUdsPath` guard for failure-path cleanup).
- **`libgpiod-dev` install on news-pi01** — Reviewer Mode-A's N5 was wrong; it confused runtime `libgpiod3` (already installed) with development headers `libgpiod-dev` (separate Debian package). Resolved via `sudo apt install libgpiod-dev` mid-session. Headers + pkg-config + `libgpiodcxx` ship with the dev package. User asked the meta-question "왜 dev 버전을 따로 깔아야 하는가?" — answered with the runtime/dev split convention (Debian/Fedora/Alpine all do this; Arch doesn't). Future: when listing third-party deps in CODEBASE.md, name both packages where relevant.
- **Reviewer Mode-A** APPROVE-WITH-NOTES (5 MUST + 8 SHOULD + 8 NIT). Big finding: `SO_RCVTIMEO` doesn't apply to `accept()` on Linux (`man 7 socket` is explicit). Replaced the UDS server's accept loop with `poll(2)` + 100 ms timeout. All 5 MUST + 6 SHOULD + 2 NIT folded into the plan as an "Amendments after Reviewer Mode-A" section before Writer entered.
- **Reviewer Mode-B** APPROVE-WITH-NOTES (0 MUST + 5 SHOULD + 7 NIT). S1/S2/S4/N3/N4 folded as a single housekeeping commit (Tier-1 promotion of UDS_LISTEN_BACKLOG / UDS_CONN_READ_TIMEOUT_SEC / GPIO_EDGE_EVENT_BUFFER_DEPTH; UDS protocol doc accuracy on mid-OneShot set_mode race; gpio_wiring.md `║` glyph swap; CODEBASE.md "Scope" block refresh). S3 (CAS factoring), S5 (UDS recv refactor), N1/N2/N5/N6/N7 deferred — polish not correctness.
- **SYSTEM_DESIGN.md §5** updated by Parent (per Mode-A amendment N1) — "Phase 4-2 B ships only the OneShot branch real; the Live branch is stubbed" line replaced with the Wave-A-and-B-landed reality.
- **Plan file** at `.claude/tmp/plan_phase4_2_d.md` (gitignored, throwaway) — body + Mode-A amendments fold-back. Safe to delete after this session — CODEBASE.md Wave A + Wave B sections + this PROGRESS.md entry capture the durable record.
- **Hybrid mode (adaptive σ from velocity)** added to "장래 검토 / future considerations" below — tentatively Phase 4-2 E or 5+. User raised the idea (LiDAR-derived velocity → adaptive σ_jitter, like IMU-augmented MCL but without the IMU); answered with the velocity-vs-acceleration nuance (1 derivative vs 2 from pose; CPU concern is overstated, the real risks are feedback-loop stability and bootstrap). Deferred until production motion data is available to tune the velocity → σ mapping.

### 2026-04-26 (continued)

- **PR #1 (Phase 4-2 B) self-merged via rebase** to keep `main` linear (origin/main `fb376c6` → `0b64a36`). Local `phase-4-2-b-amcl` branch deleted both sides; `NEXT_SESSION.md` (cold-start brief, throwaway) removed.
- **Phase 4-2 C cold-path deadband filter landed** on new branch `phase-4-2-c-deadband`. Direct writer call (planner skipped) — SYSTEM_DESIGN.md §6.4.1 already specifies the filter exactly, so brief recommended skipping the planner. New header-only module `src/localization/deadband.hpp` exposes three inline helpers: `deadband_shortest_arc_deg` (returns signed shortest arc in (-180, +180]), `within_deadband` (pure predicate, per-axis check on dx / dy / shortest-arc dyaw, strict `<` boundary), and `apply_deadband_publish` (the seam composer that mirrors §6.4.1's `if (forced || !within_deadband(...)) { store; last_written = new; }`). Cold writer's publish line collapses to a single `(void)apply_deadband_publish(...)` call.
- **State threading**: `run_cold_writer` declares a Thread-C-local `Offset last_written{0,0,0}` (matches the smoother's initial `live = prev = target = {0,0,0}` per §6.4.2 — first non-zero AMCL fix is always supra-deadband against zero). Plumbed into `run_one_iteration` as a fourth in-out parameter alongside `last_pose_inout` and `first_run_inout`. The two state slots are independent: a deadband-rejected publish does NOT block `last_pose_inout` from advancing (§6.4.1 — the rejected publish is not a rejected pose estimate, just a sub-noise update the smoother need not see).
- **No new Config keys**: cold-start brief mentioned `cfg.amcl_deadband_xy_mm` / `_yaw_deg`, but those are already in `Config` as `deadband_mm` / `deadband_deg` (under "Smoother & deadband", grouped with `t_ramp_ns` / `divergence_*`). Reused — SSOT. Cold writer divides millimetres by 1000 at the call site (`cfg.deadband_mm / 1000.0`) since `Offset::dx/dy` is metres.
- **Test target**: `tests/test_deadband.cpp` (14 cases, 140 assertions, hardware-free). Pins: per-axis vs. Euclidean (8 mm + 8 mm = 11.31 mm hypot is sub under per-axis but supra under hypot; spec is per-axis so test asserts true), strict `<` boundary at exactly 10 mm / 0.1° (false = supra), yaw wrap forward (359.95° → 0.02° = +0.07° short arc, within deadband) + symmetric backward (= -0.07°), forced=true OneShot bypass with all-sub-deadband Δ, **slow-drift pin** (100 sub-deadband calls in a row do NOT cumulatively shift `last_written` — the filter compares each candidate against last WRITTEN, never against last seen), and an alternating accept/reject sequence to confirm `last_written` tracks the seqlock value.
- **Build/test gates**: `scripts/build.sh` → 25/25 hardware-free PASS (was 24/24; +1 = `test_deadband`), 1/1 python-required PASS, `[m1-no-mutex]` clean (deadband helpers are `noexcept` and stack-only — no mutex/cv references introduced), `[rt-alloc-grep]` baseline unchanged (still the single pre-existing `udp/sender.cpp:103` ctor `std::string` hit; deadband helper introduces zero allocations).
- **Decisions deferred / flagged**: `deadband_shortest_arc_deg` duplicates a similar helper in `amcl_result.cpp`'s anonymous namespace. Not deduplicated this round — promoting it would require a public-API surface change out of scope for §6.4.1, and a third call site has not appeared. Tracked as a follow-up in `production/RPi5/CODEBASE.md` Phase 4-2 C "Deviations" subsection.
- **Housekeeping**: removed three pre-existing unused includes (`<chrono>`, `<thread>`, `<utility>`) from `cold_writer.cpp` while editing the file. Caught by clangd diagnostics; not introduced by this phase but cleaned in-flight.

### 2026-04-26

- **Phase 4-2 B AMCL implementation landed** at `production/RPi5/src/localization/`. New static lib `godo_localization` with `OccupancyGrid` + `load_map` (slam_toolbox PGM/YAML, hand-rolled parser, `EDT_MAX_CELLS = 4'000'000` cell-count cap), `LikelihoodField` (Felzenszwalb 2D EDT separable 1D passes + Gaussian conversion), `Pose2D` + `Particle` + circular-stats helpers (`circular_mean_yaw_deg`, `circular_std_yaw_deg` — atan2-based; the `[359°, 1°)` cluster reads as ~0.6° std, not ~180°), `Rng` (mt19937_64; seed=0 → time-derived, !=0 → deterministic), free functions `downsample` / `evaluate_scan` / `jitter_inplace` / `resample` (low-variance, conditional on N_eff < neff_frac·N), `class Amcl` with **step()/converge() split** (converge implemented in terms of step → SSOT-DRY → mode 4 Live drops in step() per scan), `AmclResult` + `compute_offset` (M3 canonical-360 dyaw matching `apply_offset_inplace`'s wire convention) + `apply_yaw_tripwire` (anchor = `cfg.amcl_origin_yaw_deg`), `cold_writer` state machine (Idle / OneShot real / Live stubbed-and-bounces-to-Idle).
- **`godo_tracker_rt/main.cpp` integration**: `thread_stub_cold_writer` deleted; `run_cold_writer` spawned with an injected `lidar_factory` (testable seam — production passes a closure that `open()`s a real `LidarSourceRplidar`; tests bypass via `run_one_iteration` direct call). M8 SIGTERM watchdog: `pthread_kill(cold_native, SIGTERM)` before `t_cold.join()` so a blocking `scan_frames(1)` cannot delay shutdown indefinitely.
- **`core::AmclMode` enum + `g_amcl_mode` atomic** in `core/rt_flags.{hpp,cpp}` replaces the Phase 4-1 `std::atomic<bool> calibrate_requested`. Three states: `Idle`, `OneShot`, `Live`. Two writers (button, HTTP via godo-webctl) store `OneShot` or `Live`; cold writer consumes with acquire-load and stores `Idle` on completion. `calibrate_requested` removed repo-wide (zero hits in `production/RPi5/src/` and `tests/` other than a single migration breadcrumb comment in `rt_flags.hpp`).
- **20 new AMCL Tier-2 keys** plumbed through `Config` (CLI/env/TOML/defaults), each with positive + negative test cases in `test_config.cpp` (cases 8 → 22). 4 new Tier-1 in `core/constants.hpp`: `PARTICLE_BUFFER_MAX = 10000`, `SCAN_BEAMS_MAX = 720`, `EDT_TABLE_SIZE = 1024`, `EDT_MAX_CELLS = 4'000'000`, plus `EVAL_SCAN_LIKELIHOOD_FLOOR = 1e-6`. Single source of truth for `OCCUPIED_CUTOFF_U8 = 100` in `occupancy_grid.hpp` (consumed by both `likelihood_field.cpp`'s EDT seeding and `amcl.cpp`'s `seed_global` free-cell test — they cannot drift out of sync).
- **24/24 hardware-free tests PASS** (Wave 1 5 new + Wave 2 5 new = 10 added on top of the 14-test Phase 4-1 baseline). Bias-block discipline preserved: `test_likelihood_field.cpp` validates EDT against an independent brute-force O(N²) reference (no Bresenham); `test_amcl_scenarios.cpp` validates `class Amcl` against a Bresenham synthetic ray-caster (no EDT). Two implementations sharing zero code is the SSOT-violation-on-purpose that makes a passing test meaningful. `[m1-no-mutex] clean` build-gate added to `scripts/build.sh` — enforces zero `std::mutex` / `std::shared_mutex` / `std::condition_variable` / `std::lock_guard` / `std::unique_lock` references in `cold_writer.cpp` (M1 wait-free contract). `[rt-alloc-grep]` reports the same single pre-existing UdpSender ctor hit; no new hot-path allocations.
- **CODEBASE.md gains invariant (f)**: *"AMCL has no virtual methods. Particle-filter component swap-out is by `Amcl` template parameter, NOT by ABC. Reuses invariant (a)'s no-ABC philosophy across the localization module."* The top-of-file Module map snapshot is refreshed to current state (was "as of 2026-04-25 late"; now "as of 2026-04-26 Wave 2").
- **Operating-modes clarification (CLAUDE.md §1)**: prior "user-triggered 1-shot, not continuous tracking" wording was incomplete. There are 4 user-triggered actions (all on-demand): mapping, map editing, 1-shot calibrate (Phase 4-2 B, current), Live tracking (Phase 4-2 D). Smoother + 60 Hz hot path was designed primarily around Live mode; 1-shot inherits it as a side-benefit. SYSTEM_DESIGN.md §1 / §5 / §6.1.3 / §6.4 all updated to reflect this: trigger primitive is `std::atomic<AmclMode>`, not `std::atomic<bool>`; smoother docstring documents the Live-driven design intent; AMCL §5 documents the step()/converge() split with a per-mode pseudocode.
- **Reviewer Mode-A** APPROVE-WITH-NOTES (9 MUST-FIX + 7 SHOULD-FIX + 5 NIT folded inline by Planner before Writer entered). **Reviewer Mode-B** APPROVE-WITH-NOTES (no MUST FIX, 10 SHOULD FIX, 5 NIT). All 10 SHOULD + 3 NIT applied as a follow-up housekeeping pass (the 2 skipped NITs were N1 — comment already accurate — and N5 — Eigen3 PUBLIC linkage retained per Wave 1 self-disclosed deviation).
- **Carried into Phase 4-2 C**: cold-path deadband filter. The seam already exists in `cold_writer.cpp`'s publish path (`AmclResult::forced` is forwarded); 4-2 C drops in `if (result.forced || !within_deadband(...)) target_offset.store(...)` with no `cold_writer.cpp` rewrite needed.
- **Carried into Phase 4-2 D**: Live mode body. The `case Live` stub bounces to `Idle` today; 4-2 D fills it with a per-scan `step()` loop, bumps motion-model σ_xy from 5 mm static to ~5–15 mm/scan for ~30 cm/s base motion, adds the toggle source, and uses the same SIGTERM watchdog pattern to interrupt blocking `scan_frames` on Live → Idle.
- **Plan file** at `.claude/tmp/plan_phase4_2_b.md` (gitignored, throwaway). Safe to delete after this session — CODEBASE.md Wave 1 + Wave 2 sections + this PROGRESS.md entry capture the durable record.

### 2026-04-25

- **`godo_freed_passthrough` bring-up tool added** at
  `production/RPi5/src/godo_freed_passthrough/`. Single-thread minimal
  forwarder: opens the FreeD serial port, frames D1 packets via the
  reused `freed::SerialReader` (worker thread writes a local
  `Seqlock<FreedPacket>`), and the main thread polls + forwards each
  new packet verbatim through `udp::UdpSender`. Defaults match the
  user's wiring intent: `--port /dev/ttyAMA0 --baud 38400 --host
  10.10.204.184 --udp-port 50002`. No RT privileges — runs as a normal
  user, no setcap / mlockall / SCHED_FIFO. Per-second stats line on
  stderr. Goal: validate the YL-128 → PL011 → UDP path before bringing
  up the full `godo_tracker_rt` (which adds the offset + 59.94 fps
  cadence).
- **Latent SIGINT-stuck-in-read bug found and worked around in the
  passthrough**: `freed::SerialReader`'s VMIN=1 + VTIME=1 only arms
  the inter-byte timer AFTER the first byte; with no FreeD source
  connected (the bring-up case) `read()` blocks indefinitely, so
  `t_serial.join()` hangs. Fix: after main loop exits,
  `pthread_kill(t_serial.native_handle(), SIGTERM)` to force EINTR;
  worker observes `g_running=false` at top of loop and exits. Measured
  shutdown latency on news-pi01 = 1 ms. The same race exists latently
  in `godo_tracker_rt`'s Thread A (invisible in production because the
  crane streams 60 Hz steady) — flagged in `production/RPi5/CODEBASE.md`
  for future tracker hardening.
- **Verification on news-pi01 (no FreeD hardware yet)**: socat PTY pair
  → `godo_freed_passthrough --port /tmp/pty_a → 127.0.0.1:51234`;
  one synthetic D1 packet (`d1 01 00*26 6e`, valid checksum) written to
  the other PTY end was forwarded byte-identical to the UDP listener.
  SIGINT exit clean (rc=0, ~1 ms). Existing 16/16 hardware-free tests
  still green (`scripts/build.sh` clean other than the pre-existing
  `[rt-alloc-grep]` warning on UdpSender's init-time error message).
- **EBUSY observation when opening `/dev/serial0` on this Pi**:
  `serial-getty@ttyAMA10.service` is enabled by default and owns the
  PL011. `freed::SerialReader`'s open path correctly prints the
  pointer to `production/RPi5/doc/freed_wiring.md §B` (the
  `cmdline.txt` change that disables the kernel serial console). This
  is the expected pre-boot-config error and another argument for
  applying the boot config before the first hardware test rather than
  trying to share the line with getty.
- **Boot config applied + first live run on news-pi01**: edited
  `/boot/firmware/config.txt` (added `enable_uart=1` + `dtparam=uart0=on`)
  and `/boot/firmware/cmdline.txt` (removed `console=serial0,115200`),
  reboot. After reboot `/dev/ttyAMA0` is the RP1 PL011 at
  `0x1F00030000`, getty inactive, dialout group OK. First passthrough
  run hit 60 PPS (matching FreeD 59.94 Hz) with `send_fail=0` and
  `unknown_type=25` (one-shot framing lock-on at startup, stable
  thereafter). UDP target `10.10.204.184:50002` confirmed by the
  existing FreeD receiver on the production network.
- **YL-128 silkscreen label caveat captured in `freed_wiring.md` §A**:
  the YL-128 module in this build labels its TTL pins from the
  *host's* perspective — the TTL output (data going to the host's RX)
  is the pin labelled `RXD`, not `TXD`. Re-discovered today after a
  loose cable retrigger, but this matches the same finding from the
  legacy Arduino bring-up. Diagram and rules now reflect the as-wired
  reality so future hardware swaps don't re-suffer the same trap.
- **Two GPIO-level diagnostics that DO NOT work on Pi 5**, found
  empirically and documented in `freed_wiring.md` §A "Why the obvious
  GPIO probes don't work here": (i) `pinctrl get 15` always reports
  `hi` when GPIO 15 is in alt 4 (UART mode) because RP1 routes the
  alt-function signal directly to the PL011 peripheral, bypassing the
  GPIO input register. (ii) `/proc/tty/driver/ttyAMA` shows `rx:0`
  until someone has the device open — the kernel doesn't enable the
  PL011 receiver path until `open()`. The PPS counter from
  `godo_freed_passthrough` is the actual ground truth for "are bytes
  flowing".
- **Paced-send mode added to `godo_freed_passthrough`** (`--rate-hz`).
  The default as-arrives mode forwarded packets with visible jitter on
  the UE-side cadence (Linux scheduler + 1 ms poll noise leaking
  through). `--rate-hz 59.94` switches to a `clock_nanosleep
  (TIMER_ABSTIME)` send loop that is **independent of serial arrival
  jitter**: each tick reads the latest `Seqlock<FreedPacket>` slot and
  forwards (re-sending the previous packet if no new arrived,
  dropping older packets when source bursts). New stat fields
  `repeat` and `skip` make the source/sink rate mismatch visible.
  Field test on news-pi01 with the live crane: 11,503 packets at
  exactly 60 PPS over ~3 minutes; `skip` and `repeat` both spent
  >95 % of seconds at zero, occasional 1/1 pairs from CFS preemption
  catch-up (zero net cadence loss). UE operator confirmed the receive
  cadence as "딱 59.94이다 — 그대로 멈춰라" — no perceptible jitter.
- **Seqlock-as-single-slot pattern validated**: the writer (Thread A,
  serial reader) overwrites; the reader (Thread D / passthrough main)
  always sees the freshest packet. **Older packets are dropped on
  purpose** — FreeD packets are pose snapshots, so a stale pose has
  zero render value. Sending it would visually drag the camera back
  in time. This is the same invariant `godo_tracker_rt` Thread D
  inherits, and is what makes the steady-cadence guarantee compose
  cleanly with serial-side burstiness.
- **`setup-pi5-rt.sh` applied + dev-host `ncenter` limits added**.
  The script's hardcoded `@godo` group lines went into
  `/etc/security/limits.conf` for production parity (group does not
  exist on news-pi01, so they are no-ops on this host). Added
  `ncenter - rtprio 99` and `ncenter - memlock unlimited` for the
  live dev user via a single `printf | sudo tee -a` (the heredoc
  variant kept hitting indented-EOF traps). `setcap
  cap_sys_nice,cap_ipc_lock+ep` applied to BOTH `godo_tracker_rt`
  AND `godo_jitter` (the script only setcaps the tracker by
  default; the jitter binary needs the same cap to take SCHED_FIFO).
  Verified inside a fresh `sudo -i -u ncenter` PAM session:
  `ulimit -l = unlimited`, `ulimit -r = 99`. `bash -l` does NOT
  pick up the new rlimits — login shell mode is not the same as a
  new PAM session, so `pam_limits.so` is not invoked. SSH
  re-login or `sudo -i -u <user>` is required.
- **`godo_jitter` RT baseline → TS5** at
  `test_sessions/TS5/jitter_summary.md`. Command:
  `sudo -i -u ncenter godo_jitter --duration-sec 60 --cpu 3 --prio 50`.
  Result over 3596 ticks at 59.940 Hz (period 16683350 ns):
  `mean=5.8 µs / p50=3.6 µs / p95=15.4 µs / p99=29.4 µs / max=56.8 µs`.
  No `rt::lock_all_memory: skipped` line in stderr → mlockall
  succeeded (the RLIMIT_MEMLOCK gate in `src/rt/rt_setup.cpp`
  passed). p99 is **1/7 of the SYSTEM_DESIGN.md §6.2 design goal**
  (200 µs); max is well inside one period (16683 µs). vs. the
  2026-04-24 `SCHED_OTHER` baseline (`p99=2028 µs / max=5338 µs`),
  every percentile improved 9×–94×. Caveats: no IRQ pinning yet
  (Phase 4-1 #5), no `isolcpus`, no serial / network co-load — a
  Phase 5 long-run measurement under the production thread mix is
  still required.
- **`godo_tracker_rt` end-to-end verification at 127.0.0.1:6666**.
  Confirmed live UDP flow at 60.0 PPS (599 packets / 9.98 s window
  via `python3 .claude/tmp/udp_listener.py`). Stub cold writer's 6 s
  cyclic offset pattern visible in the X/Y/Pan field deltas. tracker
  startup stderr shows the configured ue/freed/rt parameters and NO
  `rt::lock_all_memory: skipped` line → mlockall succeeded under
  the new `ncenter` PAM session. The expected `errno=111 Connection
  refused` flood appears whenever no UDP listener is bound — that
  is the `connected SOCK_DGRAM` reporting ICMP Port Unreachable;
  flagged for Phase 4-2 to add a throttle similar to the EAGAIN
  miss counter.
- **IRQ inventory captured + recommended pinning landed** at
  `production/RPi5/doc/irq_inventory.md`. Hot-path-relevant IRQs
  (eth0=106, xhci-hcd=131/136, dw_axi_dmac=140, mailbox=158, PL011
  ttyAMA0=125) → CPU 0-2; bursty mmc0/1=161/162, spi=183 → CPU 0-1.
  arch_timer (irq 13) and arm-pmu (irq 34-37) intentionally NOT
  touched (per-CPU). irqbalance not installed on news-pi01 → no
  background re-shuffle to fight. Helper scripts at
  `.claude/tmp/apply_irq_pin.sh` (runtime IRQ pin),
  `.claude/tmp/apply_isolcpus.sh` (cmdline edit Step 2),
  `.claude/tmp/apply_nohz_rcu.sh` (cmdline edit Step 3) — all
  throwaway, will be promoted to a systemd unit in Phase 4-2.
- **PL011 (irq 125) lazy-registration finding** (verified across
  three reboots): the PL011 driver only registers irq 125 after the
  first `open()` of `/dev/ttyAMA0`. Before any process opens the
  device, `/proc/irq/125/smp_affinity_list` does not exist and the
  pin script skips it. The earlier `irq_inventory.md` claim
  ("registers at probe time") is corrected. Production startup
  must therefore re-apply the pin AFTER `godo_tracker_rt` opens
  the FreeD line — Phase 4-2 systemd unit will use
  `ExecStartPost=` for this.
- **Four-step CPU 3 isolation stack measured** → results table in
  `test_sessions/TS5/jitter_summary.md`. Each step gets 1 (Step 0)
  or 3 (Steps 1-3) `godo_jitter --duration-sec 60 --cpu 3 --prio 50`
  runs; the per-step contribution is auditable.

  | Step | Adds | mean | p99 | max(worst) |
  | ---: | --- | ---: | ---: | ---: |
  | 0 | SCHED_FIFO 50 only | 5.8 µs | 29.4 µs | 56.8 µs |
  | 1 | + IRQ pinning | 7.0 µs | 35.2 µs | 111.3 µs |
  | 2 | + `isolcpus=3` | 3.2 µs | **12.0 µs** | **22.2 µs** |
  | 3 | + `rcu_nocbs=3` (nohz_full ignored) | 2.9 µs | 12.7 µs | 28.6 µs |

  Findings: (a) **Step 2 (`isolcpus=3`) is the dominant gain** —
  removed background CPU 3 work (kworker, migration, journald,
  cache pollution); 4.3× max improvement, 2.9× p99. (b) Step 1 IRQ
  pinning had no measurable effect on this idle host — its real
  value will surface under Phase 5 production load. (c) Step 3:
  `nohz_full=3` was IGNORED by the stock RPi Debian Trixie kernel
  (`CONFIG_NO_HZ_FULL=n`, `/sys/devices/system/cpu/nohz_full` does
  not exist); only `rcu_nocbs=3` activated, giving a small mean / p50
  improvement. The cmdline marker is kept anyway for design intent.
  (d) Production target = full stack (Step 3); p99 = 12.7 µs sits
  at 1/16 of the SYSTEM_DESIGN.md §6.2 design goal (200 µs).
- **`.claude/memory/project_cpu3_isolation.md` added** to the in-repo
  memory: codifies "CPU 3 full isolation is the GODO production
  baseline, applied phased so each layer's contribution stays
  auditable". The MEMORY.md index is updated.

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
