# System Design — LiDAR-based Camera Position Tracker

> **Purpose**: a single place that captures the final system architecture, data flow, module layout, and implementation order for GODO.
>
> **Audience**: the implementer (yourself and any future AI session). When starting new work, read this document together with [CLAUDE.md](./CLAUDE.md) and [PROGRESS.md](./PROGRESS.md).
>
> **Written**: 2026-04-21

---

## 1. Final system topology

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         Studio world frame                           │
│                                                                      │
│   ┌───────────────────┐                                              │
│   │ SHOTOKU Crane     │                                              │
│   │  TK-53LVR/Ti-04VR │                                              │
│   │                   │                                              │
│   │  ┌─FreeD serial─▶ │                                              │
│   │  │                │                                              │
│   │  │  [pan axis]  ◄── RPLIDAR C1 (on pan-axis center)              │
│   │  │                │        │                                     │
│   └──┼────────────────┘        │ USB                                 │
│      │                        ▼                                      │
│      │                ┌──────────────────────────────────────┐       │
│      │                │        Raspberry Pi 5 (8 GB)         │       │
│      │                │  OS: RPi OS Trixie (Debian 13 arm64) │       │
│      │                │                                      │       │
│      │                │  [godo-tracker — single C++ binary]  │       │
│      │                │  ┌────────────────────────────────┐  │       │
│      │                │  │ Thread A: FreeD serial reader  │  │       │
│      │                │  │  └─► parse FreeD 8-channel     │  │       │
│      │                │  │                                │  │       │
│      │                │  │ Thread B: LiDAR scan collector │  │       │
│      │                │  │  └─► rplidar_sdk               │  │       │
│      │                │  │                                │  │       │
│      │                │  │ Thread C: AMCL localizer       │  │       │
│      │                │  │  └─► updates offset (dx,dy)    │  │       │
│      │                │  │                                │  │       │
│      │                │  │ Thread D: UDP sender (RT)      │  │       │
│      │                │  │  └─► 59.94 Hz, FreeD+offset    │  │       │
│      └─serial in──────┼──┘  │    SCHED_FIFO, CPU-pinned   │  │       │
│                       │     └─────────────────────────────┘  │       │
│                       │                                      │       │
│                       │  [shared state: offset, FreeD]       │       │
│                       │  [map files: map.pgm + map.yaml]     │       │
│                       │                                      │       │
│                       │  trigger → recalibrate()             │       │
│                       │  (user: button / UDP command)        │       │
│                       └──────────────────────────────────────┘       │
│                                        │                             │
│                                    UDP │ 59.94 fps                   │
│                                        ▼                             │
│                              ┌───────────────────┐                   │
│                              │  Unreal Engine    │                   │
│                              │   (UDP receiver)  │                   │
│                              └───────────────────┘                   │
└──────────────────────────────────────────────────────────────────────┘
```

### Key design decisions

| Area | Decision |
| --- | --- |
| Yaw handling | AMCL emits `(x, y, yaw)` together. The LiDAR's pose is inferred from how walls/features line up against the map — no separate yaw-correction step |
| Localization | Pre-built 2D map + AMCL |
| Map building | One-time operation inside Docker (Ubuntu 24.04 + ROS 2 Jazzy + `slam_toolbox`) |
| Production runtime | Native C++, no ROS dependency |
| FreeD merge | RPi 5 receives FreeD serial, merges the offset, sends UDP (replaces the legacy Arduino) |
| FreeD Pan | **base-local** (pan-head encoder, relative to the dolly). Because the wheels-parallel rule keeps dolly yaw constant, the reading is effectively world-frame. LiDAR yaw serves only as a safety tripwire for accidental base rotation |
| 59.94 fps RT | `SCHED_FIFO` + CPU pinning + `mlockall` + `clock_nanosleep(TIMER_ABSTIME)`, targeting p99 jitter < 200 µs — comparable to the Arduino |
| RT / cold path split | Hot path (59.94 Hz, Thread D): FreeD recv → apply offset → UDP send, hard deadline ≈ 16.7 ms. Cold path (LiDAR+AMCL): up to 1 s latency acceptable. Crosses via `std::atomic<Offset>` — lock-free, no block on hot path. See §6.1 |
| Offset smoother | Linear ramp (method A): when AMCL writes a new target, hot path drives `live_offset` → `target_offset` linearly over `T_ramp` (default 500 ms, configurable). Prevents step jumps visible in UE. See §6.4 |
| Yaw wrap | Two named sites: (1) inside the smoother — shortest-arc delta; (2) at FreeD pan re-encode — signed-24-bit domain wrap. Legacy `XR_FreeD_to_UDP` got away without explicit wrap because it never added offsets. See §6.5 |
| Trigger UX (Q6) | **Both** — physical GPIO button on the RPi 5 (studio-side) + HTTP POST on the control network (gallery-side). Both enqueue the same `calibrate_now` event in the tracker's command queue |
| Web control plane | Separate FastAPI process `godo-webctl` (RPi 5 localhost + LAN). Never inside the RT binary. IPC via Unix domain socket (JSON-lines). Scope: health, map backup, map edit (remove moving fixtures), map update, calibration trigger |
| Languages | Python (UV) prototyping in Phases 1–2, C++ production from Phase 3 onward, FastAPI (Python) for `godo-webctl` from Phase 4+ |
| Rollback card | Legacy Arduino firmware retained; swap the cable to revert on RPi 5 failure |

---

## 2. Data flow details

### Steady-state operation (59.94 Hz loop)

```text
Crane ──FreeD──► Thread A ──► [latest_freed (atomic)] ──┐
                                                        │
LiDAR ──scan──► Thread B ──► [scan_buffer (mutex)] ◄──  Thread C (AMCL)
                                                        │
                            [target_offset (atomic)] ◄──┘    cold path
─────────────────────────────────── ▲ ───────────────────────────────
                                    │ lock-free load, stale OK
            every 16.68 ms ──► Thread D (RT) ─────────────── hot path
                                    │
                                    ├─ smoother.tick(now):
                                    │    live_offset ← interpolate
                                    │    (linear ramp toward target)
                                    ├─ read latest_freed
                                    ├─ add live_offset (dx, dy, dyaw)
                                    │  → FreeD X/Y + Pan (with wrap)
                                    └─► send UDP to Unreal
```

### On trigger (recalibration)

```text
User trigger (physical button or UDP command)
  │
  ▼
Thread C (AMCL) ── enter global localization mode
  │
  ├─ spread N = 10,000 particles over the map
  ├─ converge over 3–5 seconds of scans
  └─► (x, y, yaw) settled → offset = (x − origin_x, y − origin_y)
       └─► atomic update (Thread D picks it up immediately)
```

### On power-up

```text
systemd startup → godo-tracker runs
  │
  ├─ load map (map.pgm + map.yaml)
  ├─ start Thread B → LiDAR scan ingestion
  ├─ Thread C runs AMCL in global-localization mode
  │   └─ converges on (x, y, yaw) within a few seconds
  ├─ offset updates begin
  └─ Threads A and D spin up → UDP at 59.94 fps resumes

Total recovery time: 10–20 seconds (including boot)
```

---

## 3. Module layout (C++ production binary)

### Proposed directory layout

```text
/XR_FreeD_to_UDP                  ← legacy Arduino project (rollback + reference)
/production/RPi5                  ← new C++ application (Phase 3+)
├─ CMakeLists.txt
├─ README.md
├─ CODEBASE.md                    ← module / feature change log
├─ /src
│   ├─ main.cpp
│   ├─ freed_reader.{h,cpp}       ← Thread A: serial + FreeD parser
│   ├─ lidar_reader.{h,cpp}       ← Thread B: rplidar_sdk wrapper
│   ├─ amcl.{h,cpp}               ← Thread C: AMCL implementation
│   ├─ udp_sender.{h,cpp}         ← Thread D: real-time UDP sender
│   ├─ map_loader.{h,cpp}         ← PGM / YAML map loader
│   ├─ config.{h,cpp}             ← TOML / YAML configuration
│   └─ state.{h,cpp}              ← shared state (offset, freed buffer)
├─ /include
├─ /external
│   ├─ rplidar_sdk/               ← git submodule
│   └─ Eigen/                     ← git submodule or apt
├─ /configs
│   └─ godo.toml                  ← baud rate, UDP endpoint, map path, ...
├─ /maps
│   ├─ studio_v1.pgm
│   └─ studio_v1.yaml
├─ /systemd
│   └─ godo-tracker.service
├─ /scripts
│   ├─ build.sh                   ← build script
│   └─ deploy.sh                  ← RPi 5 deployment
└─ /tests
    └─ *.cpp                      ← googletest
```

### Dependencies

- **Required**: `rplidar_sdk` (official for C1), `Eigen3`, C++17 or later.
- **Optional**: `toml++` (config), `spdlog` (logging), `googletest` (unit tests).
- **System**: `systemd`, `libudev`, kernel `CAP_SYS_NICE` for RT scheduling.

---

## 4. Map-building workflow (Docker, one-time)

### Prerequisites

- RPi OS (Debian 13 Trixie) installed on the microSD, `apt install docker.io` done.
- RPLIDAR C1 connected via USB, visible as `/dev/ttyUSB0`.

### Dockerfile (`Dockerfile.mapping`)

```dockerfile
FROM ros:jazzy-ros-base

RUN apt-get update && apt-get install -y \
    ros-jazzy-slam-toolbox \
    ros-jazzy-rplidar-ros \
    ros-jazzy-nav2-map-server \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
```

### Procedure

```text
┌─────────────────────────────────────────────────────────────────────┐
│  1. Pass the LiDAR USB into the container                           │
│     docker run -it --rm \                                           │
│       --device=/dev/ttyUSB0 \                                       │
│       -v $(pwd)/maps:/work/maps \                                   │
│       godo/mapping:latest                                           │
│                                                                     │
│  2. Launch the rplidar_ros node inside the container                │
│     → publishes the /scan topic                                     │
│                                                                     │
│  3. Launch slam_toolbox (async_slam_toolbox_node)                   │
│     → builds the map in real time                                   │
│                                                                     │
│  4. Roll the LiDAR-mounted crane slowly between door 1              │
│     and door 2, 1–2 passes, 3–5 minutes.                            │
│     Ideally with good lighting and no people                        │
│     (to capture only static features).                              │
│                                                                     │
│  5. Save the map                                                    │
│     ros2 run nav2_map_server map_saver_cli -f /work/maps/studio_v1  │
│     → studio_v1.pgm + studio_v1.yaml                                │
│                                                                     │
│  6. Exit the container. The map files remain under ./maps/.         │
└─────────────────────────────────────────────────────────────────────┘
```

### Map file formats

- `studio_v1.pgm`: 8-bit grayscale occupancy grid (0 = occupied, 255 = free, 205 = unknown).
- `studio_v1.yaml`: metadata (resolution, origin, thresholds). The C++ runtime parses this via `map_loader.cpp`.

### When to rebuild the map

- Rebuild when the studio set or layout has changed **significantly** (furniture added/removed, structural change).
- Routine variation is absorbed probabilistically by AMCL, so the map does not need frequent rebuilding.

---

## 5. AMCL overview (C++)

### Inputs

- 2D occupancy grid (`OccupancyGrid`).
- LiDAR scan (array of distances and angles).
- Previous estimate + uncertainty (covariance).

### Outputs

- Pose estimate `(x, y, yaw)` + covariance matrix.

### Algorithm outline

```text
Init:
    create N particles (N = 100–10,000, adaptive on uncertainty)
    each particle: (x, y, yaw, weight)
    global init: uniformly scatter across the map

Loop (per scan):
    1. Motion update (prediction)
       - in a 1-shot setting, add small jitter (stationary assumption)
    2. Measurement update (correction)
       for each particle:
           expected_scan = ray_cast(map, particle.pose, scan_angles)
           likelihood = beam_model(expected_scan, actual_scan)
           particle.weight *= likelihood
    3. Normalize weights
    4. Resample (low-variance sampler)
    5. Extract the weighted mean pose

Kidnapped-robot detection:
    if total weight before normalization falls below a threshold:
        → global redistribution (scatter particles, converge again)
```

### Performance targets (RPi 5)

| Particle count | Time per iteration | Purpose |
| --- | --- | --- |
| 100 | < 1 ms | Nominal tracking |
| 1,000 | < 10 ms | Transient uncertainty |
| 10,000 | < 100 ms | Global localization (startup / kidnapped) |

Ray-casting dominates. Optimize with Bresenham's algorithm and SIMD (Eigen).

---

## 6. Real-time pipeline (Thread D + smoother)

### 6.1 Hot / Cold path boundary

The 59.94 Hz loop is a **hard deadline** (~16.7 ms). AMCL is **not**. We split
them so AMCL jitter can never block the UDP send.

```text
┌──────────── Hot path (Thread D, 59.94 Hz, deadline 16.7 ms) ──────────┐
│                                                                       │
│  FreeD recv ─► smoother.tick(now) ─► apply_offset ─► UDP send to UE   │
│                      ▲                                                │
└──────────────────────┼────────────────────────────────────────────────┘
                       │  std::atomic<Offset>  (lock-free load)
                       │  stale value is OK — hot path never blocks
┌──────────────────────┴──────── Cold path (AMCL, ≤ 1 s) ───────────────┐
│                                                                       │
│  LiDAR scan ─► AMCL ─► new target offset ─► atomic_store              │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

Consequences:

- AMCL may run at 1 Hz, 10 Hz, or stall for 500 ms — the hot path keeps
  emitting UDP with the last-known `target_offset`, which the smoother is
  still driving `live_offset` toward.
- `sizeof(Offset)` must fit a lock-free atomic on both x86_64 and aarch64
  (8 bytes = double, or 16-byte with `std::atomic<Offset>` + compiler
  guarantee). If 16 bytes is not lock-free on our target toolchain, fall
  back to seqlock (one writer, one reader — single reader is guaranteed
  by the architecture).
- Trigger events (physical button, HTTP POST) push into a separate
  `std::atomic<bool> calibrate_requested` that Thread C polls.

### 6.2 Thread D skeleton

```cpp
// Pseudo-code
void udp_sender_thread() {
    // Real-time scheduling
    struct sched_param sp;
    sp.sched_priority = 50;  // SCHED_FIFO, high priority
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);

    // Pin to CPU 3 (CPUs 0–2 handle everything else)
    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(3, &mask);
    pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);

    // Lock all memory
    mlockall(MCL_CURRENT | MCL_FUTURE);

    // Absolute-time periodic timer
    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);

    const long period_ns = 16683350;  // 1/59.94 * 1e9

    while (running) {
        const auto now = clock_now();

        // Lock-free read of shared state
        FreedPacket p = latest_freed.load();
        Offset target = target_offset.load();  // cold path writes this

        // Smooth toward the latest target (see §6.4)
        smoother.tick(target, now);
        const Offset off = smoother.live();

        // Merge offset into X, Y, and Pan (see §6.5 for yaw wrap)
        p.x   += off.dx;
        p.y   += off.dy;
        p.pan  = wrap_signed24(p.pan + to_q15(off.dyaw));

        // Send
        send_udp(p);

        // Wait for the next period (absolute deadline, no drift)
        next.tv_nsec += period_ns;
        while (next.tv_nsec >= 1000000000) {
            next.tv_nsec -= 1000000000;
            next.tv_sec  += 1;
        }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
    }
}
```

### 6.3 Operational checklist

- [ ] `/etc/security/limits.conf`: `@godo - rtprio 99`.
- [ ] systemd unit: `CPUAffinity=0-3`, `CPUSchedulingPolicy=fifo`, `CPUSchedulingPriority=50`.
- [ ] IRQ isolation: `echo 0-2 > /proc/irq/<num>/smp_affinity_list` (keep CPU 3 free for Thread D).
- [ ] `sudo systemctl disable ondemand`; `cpupower frequency-set -g performance`.
- [ ] Hardware watchdog: `/etc/systemd/system.conf` → `RuntimeWatchdogSec=10s`.

### 6.4 Offset smoother — linear ramp (method A)

Cold-path updates are **irregular**. AMCL may emit two updates 5 ms apart
(refined estimates in a converging burst) and then none for 1 s. If Thread D
just read `atomic_offset` directly, UE would see step changes on every
update — visibly snappy.

The smoother sits inside Thread D, state is private (no atomic), tick cost
is a handful of FLOPs.

```text
State:
    live      : Offset   current applied value
    prev      : Offset   where the ramp started from
    target    : Offset   latest AMCL-computed value
    t_start   : time     when the current ramp began
    T_ramp    : const    default 500 ms (configurable)

On each Thread D tick(now, target_new):
    if target_new ≠ target:
        prev    ← live          # restart ramp from wherever we are now
        target  ← target_new
        t_start ← now

    frac ← clamp((now − t_start) / T_ramp, 0.0, 1.0)
    live.dx   ← prev.dx   + (target.dx   − prev.dx)   × frac
    live.dy   ← prev.dy   + (target.dy   − prev.dy)   × frac
    live.dyaw ← lerp_angle(prev.dyaw, target.dyaw, frac)   # see §6.5
```

Why **linear ramp** over EMA / rate-limit:

| | Linear ramp (A, **chosen**) | First-order LPF (B) | Rate-limit slew (C) |
| --- | --- | --- | --- |
| Transition time | Fixed `T_ramp` — predictable | Exponential, never truly "done" | Varies with jump magnitude |
| Tunable | 1 knob (`T_ramp`) | 1 knob (`τ`) | 1 knob (`v_max`) |
| Behavior on rapid updates | Naturally re-targets from current live | Same | Same |
| UE operator mental model | "changes take 0.5 s, deterministic" | Hard to reason about | Big jumps visibly slow |

Rapid re-target is handled by the `prev ← live` assignment above: every new
AMCL target starts a **fresh** ramp from the current interpolated position,
so repeated small corrections blend cleanly into one continuous motion.

Acceptance tests (Phase 4):

- [ ] Single step update: `live` reaches `target` within `T_ramp ± 1 frame`.
- [ ] No update during 10 s: `live == target`, exact, no drift.
- [ ] Rapid updates (5 within 50 ms): `live` path monotonic toward final
      target, no oscillation, no overshoot.
- [ ] Yaw wrap at 359° → 1°: `live` traverses the short arc (2° CW), not
      the long arc (358° CCW).

### 6.5 Yaw wrap — two named sites

Legacy `XR_FreeD_to_UDP` is pure passthrough: raw 24-bit signed pan bytes
go in one side and out the other. It never needed an explicit wrap because
it never performed arithmetic on the angle. GODO **does** add an offset to
pan, so we need explicit wrap in two places:

```text
Site 1 — inside the smoother (float degrees):
    Operates on Offset::dyaw, which is an angle difference in ℝ degrees.

    double lerp_angle(double a, double b, double frac) {
        // shortest-arc delta in (−180, +180]
        double d = std::fmod(b - a + 540.0, 360.0) - 180.0;
        double y = a + d * frac;
        // normalize to [0, 360)
        y = std::fmod(y, 360.0);
        if (y < 0.0) y += 360.0;
        return y;
    }

Site 2 — at FreeD pan re-encode (signed 24-bit 1/32768 deg):
    int32_t wrap_signed24(int64_t v) {
        // FreeD pan range: ±2^23 = ±256.0 deg (physical crane limit)
        constexpr int64_t R = 1LL << 24;   // 16_777_216
        constexpr int64_t H = 1LL << 23;   //  8_388_608
        v = ((v % R) + R) % R;             // [0, R)
        if (v >= H) v -= R;                // (−H, +H]
        return static_cast<int32_t>(v);
    }
```

Both are **pure functions**; both must have unit tests pinning:

- [ ] `lerp_angle(359.0, 1.0, 0.5) == 0.0` (short arc, not 180.0).
- [ ] `lerp_angle(10.0, 350.0, 0.5) == 0.0` (short arc on the other side).
- [ ] `lerp_angle(0.0, 360.0, 0.5) == 0.0` (aliased).
- [ ] `wrap_signed24(max_int + 1) == min_int` (rollover).
- [ ] `wrap_signed24(x) == x` for `x ∈ [−H, H)` (identity in range).

Neither site mutates the underlying `Offset`; they produce the bytes that
go out on the wire. Keeping them as free functions (not methods) makes the
unit tests trivial and prevents accidental re-wrapping.

---

## 7. Phase-by-phase plan (Phase 1 → 5)

### Phase 1 — measurement and Python prototype (current)

- [x] FreeD Pan semantics validated → **base-local, effectively world-frame under wheels-parallel rule**.
- [ ] Scaffold `/prototype/Python` with UV.
- [ ] Clone `rplidar_sdk`, build `ultra_simple` on Mac/Windows.
- [ ] Raw scan dump (design the text / binary format).
- [ ] Python visualization (polar plot, quality histogram).
- [ ] Noise measurement: variance over 100 static frames, √N-rule verification.
- [ ] Retro-reflector distinguishability test (quality threshold).
- [ ] Chroma-wall NIR reflectivity test.

### Phase 2 — algorithm validation (Python)

- [ ] ICP prototype (open3d or in-house).
- [ ] Particle filter prototype (numpy).
- [ ] Synthetic-data AMCL sanity check.
- [ ] Reproducibility on real dumps (target ≤ 1 cm).

### Phase 3 — map building + C++ port

- [ ] RPi 5 setup (OS, Docker, apt deps).
- [ ] `Dockerfile.mapping` + one-time map build.
- [ ] Scaffold `/production/RPi5` (CMake, submodules).
- [ ] Port `lidar_reader` + `map_loader` + baseline AMCL.
- [ ] Cross-check AMCL output against the Python reference.

### Phase 4 — FreeD integration + RT pipeline

**Phase 4-1 — RT hot path only** (no LiDAR dependency yet)

- [ ] `freed_reader` (serial + parser).
- [ ] `offset_smoother` (linear ramp, §6.4) + unit tests.
- [ ] `yaw_wrap` utilities (`lerp_angle`, `wrap_signed24`, §6.5) + unit tests.
- [ ] `udp_sender` (RT 59.94 fps, §6.2).
- [ ] End-to-end replay test: canned FreeD + synthetic offset steps → UDP
      capture on loopback → byte-identity vs. expected trajectory.
- [ ] p99 jitter measurement (< 200 µs target).

**Phase 4-2 — Cold path + integration**

- [ ] `lidar_source_rplidar` (reuse from `godo_smoke`).
- [ ] `amcl_localizer` (port from Phase 2 Python reference).
- [ ] Atomic `target_offset` wiring; hot path reads it.
- [ ] Trigger wiring: GPIO button + `calibrate_now` HTTP endpoint (served
      by the `godo-webctl` process below).
- [ ] systemd unit + watchdog wiring.
- [ ] Document the Arduino rollback procedure.

**Phase 4-3 — Control plane (`godo-webctl`, separate process)**

- [ ] FastAPI app: `/health`, `/map/backup`, `/map/edit` (remove moving
      fixtures), `/map/update`, `/calibrate`.
- [ ] Unix domain socket IPC to `godo-tracker` (JSON-lines commands).
- [ ] Static pages: status dashboard, map editor UI (OpenCV + numpy on
      the Python side — the tracker binary is never involved in editing).
- [ ] systemd unit, reverse-proxied behind nginx for LAN access.

### Phase 5 — field integration

- [ ] In-studio integration with the real crane + RPi 5 + Unreal.
- [ ] Long-run stability (8 h+).
- [ ] Jitter measurement vs. Arduino.
- [x] Q6 trigger UX: both — physical GPIO button + network HTTP POST (resolved 2026-04-24).
- [ ] Field operator's manual.

---

## 8. Failure scenarios and responses

| Scenario | Symptom | Automatic response | Manual response |
| --- | --- | --- | --- |
| RPi 5 hang | UDP stops | Hardware watchdog reboot (~10 s) | — |
| AMCL fails to converge | Offset unchanged | Retry in global-localization mode | Rebuild map |
| LiDAR disconnect | No scans | Reconnection loop; alert at 30 s | Check USB |
| FreeD serial disconnect | UDP X/Y stuck | Reconnection loop; warn at 5 s | Check cable |
| Suspected base rotation | LiDAR yaw jumps | Set UDP warning flag + log | Realign wheels |
| RPi 5 hard failure | System down | — | Cable-swap to Arduino rollback |
| Map corruption | AMCL fails to start | Restore map from git | Rebuild map |
| AMCL produces huge offset jump | Hot path smoother drives UE through a wide arc over `T_ramp` | Clamp `|target − live|` at a sanity limit (e.g., 2 m, 10°); refuse updates beyond that, log `amcl_divergence` | Re-trigger calibration |
| `godo-webctl` crash | API unreachable; tracker unaffected | systemd restart | Check logs |
| FreeD pan wrap at ±256° | `wrap_signed24` must handle overflow cleanly | Covered by pinned unit tests (§6.5) | — |

---

## 9. Windows handoff — resume the next day

> Step-by-step entry guide for the operator (the user).

### Step 0 — load context (10 minutes)

1. Copy or `git pull` the GODO folder onto Windows.
2. Open these files in order to recover context:
   - [CLAUDE.md](./CLAUDE.md) — project guide.
   - [PROGRESS.md](./PROGRESS.md) — current state.
   - This file ([SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md)) — end-to-end design.
   - [doc/RPLIDAR/RPLIDAR_C1.md](./doc/RPLIDAR/RPLIDAR_C1.md) — C1 reference.
   - [.claude/memory/MEMORY.md](./.claude/memory/MEMORY.md) — memory index.
3. Ask Claude Code to read those five files and continue from there.

### Step 1 — Phase 1 day plan

```text
┌─────────────────────────────────────────────────────────────────┐
│ Morning (before the LiDAR arrives)                              │
│  □ Scaffold /prototype/Python with UV (30 min)                  │
│  □ Clone rplidar_sdk, attempt a Windows build (30 min)          │
│  □ Define the dump format (CSV: angle, distance, quality, flag) │
│                                                                 │
│ After the LiDAR is on the bench                                 │
│  □ Dump 100 static-position frames via ultra_simple (10 min)    │
│  □ Implement Python loader + polar plot (30 min)                │
│  □ Compute noise variance, verify √N rule (30 min)              │
│  □ Reflector test (bike reflectors) at 1 m / 5 m (30 min)       │
│                                                                 │
│ Afternoon                                                       │
│  □ Investigate anomalies, re-measure                            │
│  □ Record the day's results in PROGRESS.md                      │
│  □ Leave a clear next-session starting point                    │
└─────────────────────────────────────────────────────────────────┘
```

### Step 2 — expected artifacts

- `/prototype/Python/pyproject.toml`.
- `/prototype/Python/src/godo_lidar/` (package).
- `/prototype/Python/scripts/dump_scan.py` (wraps the SDK).
- `/prototype/Python/scripts/analyze.py` (visualization / analysis).
- `/prototype/Python/data/YYYYMMDD_scan_*.csv`.
- Updated `/PROGRESS.md`.

### Step 3 — if you get stuck

- SDK build fails on Windows → consult `rplidar_sdk/README.md`. Fallback: **use SLAMTEC RoboStudio pre-built to dump data first**.
- COM port not recognized → reinstall SLAMTEC's official CP2102 driver.
- Data looks wrong → run through the checklist in [doc/RPLIDAR/RPLIDAR_C1.md §5](./doc/RPLIDAR/RPLIDAR_C1.md#5-raw-vs-sdk-noise--root-causes).

---

## 10. Phase 1 Python prototype — tools and library plan

> **Scope**: this section pins the tooling for the Phase 1 measurement work that lives under `/prototype/Python`. The production C++ binary (Phase 3+) is governed by §3 and §6 above.

### 10.1 Two-backend acquisition framework (SDK-wrapper vs Non-SDK)

Phase 1 runs **two parallel acquisition backends** against the same physical setup so we can quantify what the SDK-level parser silently does for us.

| Axis | SDK-wrapper backend (`pyrplidar`) | Non-SDK backend (raw `pyserial` + in-house parser) |
| --- | --- | --- |
| Protocol decoding | Python port of the SLAMTEC protocol (standard / express / ultra) | Only the modes we implement (standard mode first) |
| Quality field handling | Per-spec bits pre-applied | Raw bits visible; threshold applied explicitly |
| Frame-sync reliability | Checksum failures discarded internally | Failures observable; drop / repair policy is ours |
| Buffer / timing | Library-managed | Byte-level timing visible |
| Customization | What the wrapper exposes | Every byte is ours |
| Effort | A few lines of init code | Protocol implementation per the SLAMTEC v2.8 PDF |
| Role | Fast empirical baseline on Windows | Research / byte-level debugging |

> **Honesty note**: [doc/RPLIDAR/RPLIDAR_C1.md §4](./doc/RPLIDAR/RPLIDAR_C1.md#4-sdk-and-python-bindings) marks `pyrplidar` as **unofficial** for C1 and recommends "official C++ SDK + pybind11/ctypes" for production. We use `pyrplidar` in Phase 1 because it lets us start measuring on Windows today without a C++ toolchain. The authoritative three-way comparison — adding the official SDK's `ultra_simple` CLI as a third backend — is scheduled as a **Phase 1 follow-up task** once the C++ build environment is ready. Until then, the SDK-wrapper path should be treated as a baseline, not as a certified reference.

The backends emit the **same `Frame` dataclass** (`angle_deg`, `distance_mm`, `quality`, `flag`, `timestamp_ns`), so every downstream analysis stage is backend-agnostic.

See [doc/RPLIDAR/RPLIDAR_C1.md §5](./doc/RPLIDAR/RPLIDAR_C1.md#5-raw-vs-sdk-noise--root-causes) for the seven known causes of "SDK looks clean, raw is noisy".

### 10.2 Library plan (Phase 1)

| Library | Role | Justification |
| --- | --- | --- |
| `pyrplidar` | SDK-wrapper backend | Python port of the SLAMTEC protocol; lets us measure on Windows today without a C++ build. Caveat: unofficial for C1 (see §10.1). |
| `pyserial` | Non-SDK backend | Direct access to the CP2102 USB-serial bytes |
| `numpy` | Numeric kernel | Per-direction variance, √N verification |
| `pandas` | Post-hoc analysis only | Per-frame / per-angle aggregation in `analyze.py`. **Never on the capture write path** — CSV is written via stdlib `csv.writer`. |
| `matplotlib` | Visualization | Polar plot, quality histogram, time-series |

Excluded for Phase 1 (defer until actually needed):

- `scikit-learn` — DBSCAN would be speculative for §10.4 Step 3 (threshold check is sufficient).
- `open3d` — point cloud + ICP, Phase 2.
- `scipy.optimize` — add only if RANSAC + numpy proves insufficient.

### 10.3 Persisted artifacts (all runs)

Every measurement run produces two files so that later sessions — including AI re-analysis without the hardware — can reproduce and verify it.

1. **CSV dump** (`/prototype/Python/data/<timestamp>_<backend>_<tag>.csv`), one row per LiDAR sample:
   ```text
   frame_idx,sample_idx,timestamp_ns,angle_deg,distance_mm,quality,flag
   ```
2. **Session txt log** (`/prototype/Python/logs/<timestamp>_<backend>_<tag>.txt`):
   - Header: timestamp, host, OS, python version, backend, baud, motor PWM, scan mode, port
   - Capture params: frame count, target distance, angular window, operator notes
   - Run stats: frames captured, samples/sec, dropped frames, mean / median quality, wall-clock duration
   - Artifact hash: `csv_sha256`, `csv_byte_count` (so a later session can detect drift between the two files)

Both directories are gitignored; only `.gitkeep` is committed.

### 10.4 Test sequence (Phase 1)

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Step 1 — Backend parity test (SDK vs Non-SDK)                          │
│    capture_sdk.py + capture_raw.py at the same static position         │
│    analyze_compare.py reports per-angle distance / quality delta       │
│                                                                        │
│ Step 2 — Noise characterization                                        │
│    100+ static frames per backend                                      │
│    analyze_noise.py reports per-direction variance, √N check           │
│                                                                        │
│ Step 3 — Retro-reflector distinguishability                            │
│    test_reflector.py at 0.5 / 2 / 5 / 10 m, 0 / 30 / 45 / 60 / 75°     │
│    Threshold target: marker quality ≥ 200, background ≤ 100            │
│                                                                        │
│ Step 4 — Chroma-wall NIR effective range                               │
│    test_chroma_nir.py against green / blue / black surfaces            │
│    Logs effective range, return rate, per-surface quality              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Change log

- **2026-04-24**: §1 key-decisions table gains 5 rows (hot/cold split, smoother, yaw wrap, trigger UX, web plane). §6 restructured: §6.1 hot/cold boundary, §6.2 thread D skeleton (now reads target via smoother), §6.3 ops checklist, §6.4 linear-ramp smoother with A/B/C comparison and acceptance tests, §6.5 yaw wrap at two named sites with pinned unit tests. §7 Phase 4 split into 4-1/4-2/4-3. §8 gains 3 new failure rows (AMCL divergence, webctl crash, pan wrap). Q6 (trigger UX) resolved. RPi 5 hardware bring-up proven: 500-frame capture × 3 iterations, 10.02 Hz steady, byte-identical Python parity. Smoother method A chosen over EMA / rate-limit on predictability grounds. `godo-webctl` scoped as a separate FastAPI process, never inside the RT binary.
- **2026-04-21 (later)**: added §10 — Phase 1 Python prototype tools, two-backend (SDK-wrapper vs Non-SDK) framework, library plan, dump format, and test sequence. SDK-wrapper uses `pyrplidar` with explicit caveat; official-SDK `ultra_simple` three-way comparison deferred as a Phase 1 follow-up. scikit-learn removed (threshold check suffices). CSV write path pinned to stdlib `csv.writer`. Session-txt log gains `csv_sha256` / `csv_byte_count`.
- **2026-04-21**: initial version. Decisions locked: yaw Approach B, O3 → O4 hybrid, Docker-based map building, RPi 5 FreeD integration, C++ production.
