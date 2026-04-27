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
