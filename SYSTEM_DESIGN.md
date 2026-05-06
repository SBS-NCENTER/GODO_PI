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
│                       │  g_amcl_mode ∈ {Idle, OneShot, Live} │       │
│                       │  (user: button / HTTP via godo-webctl)│       │
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
| 59.94 fps RT | `SCHED_FIFO` + CPU pinning + `mlockall` + `clock_nanosleep(TIMER_ABSTIME)`. The p99 jitter target is to be measured on the target host during Phase 4-1 (the "comparable to Arduino" phrasing in prior drafts was aspirational; see §7 Phase 4-1 for the jitter-measurement harness) |
| RT / cold path split | Hot path (59.94 Hz, Thread D): FreeD recv → apply offset → UDP send, hard deadline ≈ 16.7 ms. Cold path (LiDAR+AMCL): up to 1 s latency acceptable. Cross via **seqlock** (single writer per slot, N readers) — `std::atomic<T>` for 24–29 byte payloads is not lock-free on aarch64. See §6.1 |
| Offset smoother | Linear ramp (method A): when AMCL writes a new generation, the hot-path smoother drives `live_offset` → `target_offset` linearly over `T_ramp` (default 500 ms). Uses the seqlock's integer generation counter for edge detection (not float equality), and snaps value-copy at `frac ≥ 1.0` to eliminate float drift. See §6.4 |
| AMCL noise deadband | Thread C filters AMCL outputs in the cold path: if `|Δpos| < DEADBAND_MM` AND `|Δyaw| < DEADBAND_DEG`, the seqlock is **not** written, so the hot-path smoother never sees sub-noise-floor updates. Forced-accept on explicit calibrate bypasses the filter. Defaults `10 mm` / `0.1°`. See §6.4.1 |
| Yaw wrap | Two named sites, both **pure free functions**: (1) `lerp_angle` in the smoother — shortest-arc delta, precondition `|b-a| < 360`; (2) `wrap_signed24` at FreeD pan re-encode — `±2^23` lsb = encoded range (NOT a mechanical crane limit). See §6.5 |
| Trigger UX (Q6) | **Both** — physical GPIO button on the RPi 5 (studio-side) + HTTP POST via `godo-webctl` (control-room-side). Single `std::atomic<godo::rt::AmclMode> g_amcl_mode` primitive in `core/rt_flags.hpp` (replaces the Phase 4-1 boolean `calibrate_requested`). Two writers (button, HTTP) write `OneShot` or `Live`; cold writer transitions back to `Idle` on completion. See §6.1.3 |
| Operating modes | **4 user-triggered actions** (per CLAUDE.md §1): (1) initial / re-do mapping (Docker), (2) map editing (Phase 4.5 webctl), (3) **1-shot calibrate** (high-accuracy, runs `Amcl::converge()` to convergence, deadband-bypassed via `forced=true`), (4) **Live tracking** (toggle-on continuous, runs `Amcl::step()` per scan, deadband applied). Modes (3) and (4) share the same `Amcl` kernel via the `step()`/`converge()` split. Mode (4) body deferred to Phase 4-2 D |
| Web control plane | Separate FastAPI process `godo-webctl`, never inside the RT binary. IPC via Unix domain socket (JSON-lines). **Phase 4-3 scope (minimal)**: `/health`, `/map/backup`, `/calibrate`. Map editor / config editor / full React frontend deferred to Phase 4.5+. See §7 |
| Constants | Two tiers: `core/constants.hpp` for protocol/algorithmic invariants (Tier 1, `constexpr`); `Config` class + `core/config_defaults.hpp` for tunables (Tier 2, TOML-backed, env-override). Magic-number ban enforced by code review. See §11 (Runtime configuration) |
| Languages | Python (UV) prototyping in Phases 1–2, C++ production from Phase 3 onward, FastAPI (Python) for `godo-webctl` from Phase 4+ |
| Rollback card | Legacy Arduino firmware retained; swap the cable to revert on RPi 5 failure |

---

## 2. Data flow details

### Steady-state operation (59.94 Hz loop)

```text
Crane ──FreeD──► Thread A ──► [latest_freed  Seqlock] ──┐
                                                        │
LiDAR ──scan──► Thread B ──► [scan_buffer (mutex)] ◄──  Thread C (AMCL)
                                                        │
                                              deadband │ §6.4.1
                                              filter   ▼
                                          [target_offset Seqlock]
─────────────────────────────────── ▲ ───────────────────────────────
                                    │ seqlock reads; retry if writer in progress
            every 16.68 ms ──► Thread D (RT) ─────────────── hot path
                                    │
                                    ├─ smoother.tick(target, gen, now):
                                    │    if gen_new != target_g: restart ramp
                                    │    if frac ≥ 1: live ← target (snap)
                                    │    else:         linear interp
                                    ├─ read latest_freed
                                    ├─ apply_offset_inplace (dx, dy, dyaw)
                                    │   → FreeD X/Y + Pan (with wrap, §6.5)
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

#### Frame convention (PGM ↔ AMCL ↔ SPA)

The PGM file format stores raster data row-major **top-row-first** —
byte 0 is the top-left pixel, byte (height-1)·width is the bottom-left.
The YAML `origin: [ox, oy, 0]` value is the world coord of the
**bottom-left** pixel (ROS map_server semantics). For the AMCL kernel
to satisfy both — `cells[cy * W + cx]` looking up a cell at world
`(origin_x + cx*res, origin_y + cy*res)` and matching the YAML's
bottom-left anchor — the loader (`occupancy_grid.cpp::load_map`)
**row-flips the PGM payload at load time** so `cells[0..W-1]` holds
the bottom row.

The SPA's `mapViewport.svelte.ts::worldToCanvas` applies a separate
height-1 flip when projecting world coords onto canvas pixels,
because the canvas is drawn with row 0 at top (matching the original
PGM raster, not the AMCL internal frame). The two flips are
deliberately asymmetric — AMCL works in a bottom-row-first frame
internally, the SPA renders in a top-row-first frame visually, and
both convert to/from the same world frame so pose dots and scan
overlays land where YAML origin says they should.

This convention is the bridge for a frame-orientation bug found
2026-05-01 KST during issue#3 HIL — see `production/RPi5/CODEBASE.md`
2026-05-01 entry for the diagnosis.

### When to rebuild the map

- Rebuild when the studio set or layout has changed **significantly** (furniture added/removed, structural change).
- Routine variation is absorbed probabilistically by AMCL, so the map does not need frequent rebuilding.

---

## 5. AMCL overview (C++)

### Inputs

- 2D occupancy grid (`OccupancyGrid`) — slam_toolbox-shaped PGM + YAML.
- LiDAR scan (`godo::lidar::Frame` from the C1 driver).
- Per-mode entry: `Amcl::seed_global(grid, rng)` for first run, `Amcl::seed_around(last_pose, σ_xy, σ_yaw, rng)` thereafter.

### Outputs

- `AmclResult { Pose2D pose; godo::rt::Offset offset; bool forced; bool converged; int iterations; double xy_std_m; double yaw_std_deg; }` (see `src/localization/amcl_result.hpp`).
- The `forced` flag is set by the cold writer for `OneShot` runs so the Phase 4-2 C deadband filter can pass operator-initiated calibrates through unconditionally.

### Algorithm outline

The `Amcl` class exposes a **split API** so the same kernel serves both 1-shot and Live modes (SSOT-DRY):

```text
class Amcl {
    AmclResult step(beams, rng);      // single iteration: motion → sensor → resample
    AmclResult converge(beams, rng);  // loop step() up to amcl_max_iters with early-exit
    void seed_global(grid, rng);      // uniform over free cells; n = amcl_particles_global_n
    void seed_around(pose, σ_xy, σ_yaw, rng);  // Gaussian cloud; n = amcl_particles_local_n
    Pose2D weighted_mean();           // circular mean for yaw (atan2)
    double xy_std_m();                // sqrt(weighted_var_x + weighted_var_y)
    double circular_std_yaw_deg();    // shortest-arc std (NOT linear)
};

OneShot mode (mode 3 in CLAUDE.md §1):
    capture one frame
    seed_around(last_pose, σ_seed) (or seed_global on first run)
    converge():
        for iter in [0, amcl_max_iters):
            step(beams, rng)
            if iter ≥ 3 AND xy_std < th_xy AND circular_std_yaw < th_yaw:
                early-exit
    publish AmclResult (forced=true) → cold writer publish seam → seqlock

Live mode (mode 4, Phase 4-2 D):
    on each LiDAR scan (~10 Hz):
        step(beams, rng)             # one iteration only
        publish AmclResult (forced=false) → deadband → seqlock
    base may move at up to ~30 cm/s; motion-model σ_xy is bumped from
    static (5 mm) to ~5–15 mm/scan for Live.
```

`converge()` is implemented in terms of `step()` so the inner kernel is single-source. Both branches landed: Phase 4-2 B shipped the `OneShot` body (`amcl.converge()` to convergence, `forced=true` bypasses deadband); Phase 4-2 D shipped the `Live` body (per-scan `amcl.step(beams, rng, σ_live_xy, σ_live_yaw)` with the σ-explicit overload, `forced=false` reaches the deadband filter). Operator triggers the modes via two physical GPIO buttons (`src/gpio/`) or a Unix-domain JSON-lines socket at `cfg.uds_socket` (`src/uds/`); both write `g_amcl_mode` directly. Phase 4-2 D also changed OneShot to always `seed_global` (no warm `seed_around` branch) so calibrate after a base move always converges, at a ~1 s wall-clock cost the operator is willing to absorb.

### Internals

- **Sensor model**: pre-built EDT (`LikelihoodField` via Felzenszwalb 2D distance transform) + beam-endpoint Gaussian (`evaluate_scan` returns `exp(Σ log_p_i)`). One bilinear-equivalent lookup per beam, no per-evaluation ray-casting. The likelihood floor (`EVAL_SCAN_LIKELIHOOD_FLOOR`) is Tier-1 in `core/constants.hpp`.
- **Motion model**: per-particle Gaussian jitter (`jitter_inplace`). Static σ in 1-shot mode; bumped for Live.
- **Resampler**: low-variance / systematic, conditional on `N_eff < neff_frac · N`. Pre-allocated ping-pong buffers + cumsum scratch — no heap traffic per iteration.
- **Yaw stats**: `circular_mean_yaw_deg` and `circular_std_yaw_deg` (atan2-based) so the `[359°, 1°)` cluster reads as ~0.6° std, NOT ~180°.

### Convergence criterion (1-shot)

```
converged ⇔ (xy_std_m < amcl_converge_xy_std_m) AND
            (circular_std_yaw_deg < amcl_converge_yaw_std_deg) AND
            iters ≥ 3        # min iterations to avoid converging on the seed
```

### Coarse-to-fine sigma_hit annealing (Track D-5, 2026-04-29)

The single-σ approach above hits a wall on real maps: with `cfg.amcl_sigma_hit_m` tight enough for ROS-spec cm-scale precision (e.g. 0.05 m), 5000 random global particles have near-zero probability of seeding within the Gaussian's useful range — likelihoods come out near-uniform, AMCL never discriminates. Empirical sweep on TS5 chroma studio (5cm-cell 04.29_v3 map) showed σ=0.05 default gave 0/10 convergence; σ=1.0 gave 2/10 single-basin; σ=0.2 gave 9/10 across 3 basins (studio symmetry creates ambiguity at narrow σ alone).

Production OneShot now anneals through a configurable schedule:

```
amcl.sigma_hit_schedule_m       = "1.0,0.5,0.2,0.1,0.05"      # σ_hit per phase
amcl.sigma_seed_xy_schedule_m   = "-,0.10,0.05,0.03,0.02"    # seed_around σ_xy per phase k>0; '-' = phase-0 sentinel
amcl.anneal_iters_per_phase     = 10                          # max iters per phase
```

Per-phase loop in `cold_writer.cpp::converge_anneal`:
1. `lf = build_likelihood_field(grid, σ_k);  amcl.set_field(lf);`
2. Phase 0: `amcl.seed_global` (5000 particles); phase k>0: `amcl.seed_around(carried_pose, σ_xy_k, σ_yaw_k)` (500 particles, σ_yaw shrinks linearly with σ_k/σ_0).
3. Run ≤ K iters with the existing `iters≥3 && converged` early-exit.

**Auto-minima tracking + patience-2 early break**: track best (min) `xy_std_m` across all phases; return THAT pose, not the final-phase pose. If 2 consecutive phases produce worse-than-best xy_std, break early (single-phase noise tolerated, second consecutive bump signals over-tightening into sub-cell discretization). Operator can SAFELY granularize the schedule without over-tightening.

HIL post-Track-D-5: k_post = 10/10, σ_xy median 0.009 m, single-basin lock (1.15, ~0, 173°) on every calibrate. The default 5-phase schedule is wide enough to cover the cliff at σ ≈ 0.1↔0.2 and auto-minima picks the empirical minimum (typically phase 2 = σ=0.2 on this map).

After OneShot completes, `lf` is rebuilt back to `cfg.amcl_sigma_hit_m` so Live mode re-entry sees the operator-controlled σ field, never the annealing-leftover narrow final-phase field.

The pattern generalizes per `.claude/memory/project_pipelined_compute_pattern.md` — pipelined-parallel variants (multiple concurrent AMCL chains at different σ tiers, picking the best result) are scaffolded as Track D-5-P future work.

### Pose-hint phase-0 branch (issue#3, 2026-05-01)

Operator-placed initial pose hints feed AMCL phase 0 of `converge_anneal` directly. Test4/test5 HIL on news-pi01 showed the studio's likelihood landscape has multiple ~equal-score basins separated by ~1 m in (x, y) AND ~90° in yaw — single-σ + uniform global seed converges into the wrong basin once every few calibrates. The fix narrows phase 0 from `seed_global` (5000 uniformly-distributed particles) to `seed_around(hint, σ_xy, σ_yaw)` (500 particles in a Gaussian basin around the operator's clicked pose) so only one basin's particles survive to phase 1.

Wire path (production CODEBASE invariant (p)):

```
SPA <PoseHintLayer/>             ─┐
  ↓ click + drag (or click+click) │
  ↓ viewport.canvasToWorld(...)   │ Mode-A M5 — single math SSOT
  ↓ yawFromDrag(...)              │
TrackerControls "Calibrate from hint" button
  ↓ apiPostCalibrate(body)        │
                                  ▼
godo-webctl POST /api/calibrate
  ↓ Pydantic CalibrateBody (all-or-none seed triple, σ-without-seed
  ↓     rejected, range bounds matching the C++ wire seam)
  ↓ encode_set_mode(seed=...) → JSON NUMBER fields appended to wire
  ↓                                                                 │
                                                                    ▼
godo-tracker UDS handler `set_mode` with hint
  ↓ re-validate hint at the wire seam (defence-in-depth)
  ↓ M3 ordering chain:
  ↓   1. g_calibrate_hint_data.store(bundle)         // Seqlock
  ↓   2. g_calibrate_hint_valid.store(true, release) // sentinel
  ↓   3. g_amcl_mode.store(OneShot, release)         // dispatch
                                                                    ▼
cold_writer::run_one_iteration (acquire-load on g_amcl_mode)
  ↓ if (g_calibrate_hint_valid.load(acquire)) {
  ↓     bundle = g_calibrate_hint_data.load();          // seqlock-fenced
  ↓     converge_anneal phase 0: seed_around(bundle, σ_xy, σ_yaw)
  ↓     instead of seed_global
  ↓     ...
  ↓     g_calibrate_hint_valid.store(false, release);   // consume-once
  ↓ } else { converge_anneal phase 0: seed_global; ... }
```

σ override semantics: when the operator supplies explicit σ values (numeric panel tweak), they apply directly. When omitted, the cold writer falls back to `cfg.amcl_hint_sigma_xy_m_default = 0.50 m` and `cfg.amcl_hint_sigma_yaw_deg_default = 20.0°` (Tier-2, recalibrate class). Both defaults are bumped vs. the existing `amcl_sigma_seed_*` because they cover operator click imprecision (±0.5 m) AND drag-yaw imprecision (±10°), which the existing seeds (tuned for warm-restart) do not.

GPIO-button calibrate keeps its current uniform-seed behaviour — there is no canvas to click for a GPIO trigger.

### Live mode pipelined-hint kernel (issue#5, 2026-05-01)

Phase 4-2 D's per-scan single `Amcl::step` Live body locks onto the
wrong basin and drifts ~4 m / ~90° even after a clean OneShot at the
same physical pose (`.claude/memory/project_amcl_multi_basin_observation.md`):
the `seed_global` first-iteration entry is the principal cause, and a
single `step()` per scan lacks the convergence depth to escape once a
wrong basin locks in. Operator-locked solution
(`project_calibration_alternatives.md` "Live mode hint pipeline"):
re-shape Live to a sequential pipelined one-shot driven by the
previous-tick pose as hint.

**Two Live kernels, one selector**:

```
cfg.live_carry_pose_as_hint:
  false (default this PR, rollback path)
    → run_live_iteration: per-scan Amcl::step with the wider Live σ
      pair (cfg.amcl_sigma_xy_jitter_live_m / _yaw_jitter_live_deg);
      seed_global on first iter, seed_around(last_pose, …) thereafter.
      Behaviour pre-issue#5; kept as the rollback path until HIL
      approves the carry-hint default.
  true (HIL operator opt-in)
    → run_live_iteration_pipelined: per-scan converge_anneal_with_hint
      driven by `last_pose` (carried from the most recent OneShot or
      from the previous Live tick) with TIGHT σ
      (cfg.amcl_live_carry_sigma_xy_m = 0.05 m,
       cfg.amcl_live_carry_sigma_yaw_deg = 5°) and a SHORT schedule
      (cfg.amcl_live_carry_schedule_m = "0.2,0.1,0.05" by default).
```

**Hint source contract**:

```
Tick t=0 (Live just toggled ON):
   hint = last_pose, which carries:
       - the most recent OneShot pose (run_one_iteration end), OR
       - the last Live pose from a previous Live session (preserved
         across Idle re-entry).
   Cold-start guard: if `last_pose_set` flag is false (no OneShot has
   run AND no prior pipelined Live tick has produced a converged pose),
   reject Live entry with an actionable stderr message and bounce to
   Idle. Operator must Calibrate first.

Tick t≥1:
   hint = pose[t-1], i.e. the previous tick's converged pose.
```

**σ + schedule semantics** (`project_hint_strong_command_semantics.md`):

- σ_xy = 0.05 m: matches inter-tick crane-base drift (100 ms tick × 30 cm/s peak ≈ 30 mm; default leaves margin). NOT padded for AMCL search comfort. Operators widen via tracker.toml without rebuild.
- σ_yaw = 5°: conservative for non-rotating SHOTOKU dolly base (CLAUDE.md §1).
- Short schedule: with a tight carry-σ, basin lock is automatic; the wide-σ phases of OneShot's anneal (1.0, 0.5) waste depth. 3 phases × ~10 ms ≈ 30 ms per-tick wall-clock keeps headroom under the 100 ms LiDAR period.

**Hint-flag discipline (extends invariant (p))**: the pipelined path NEVER touches `g_calibrate_hint_*`. Consume-once clearing is OneShot-only (`run_one_iteration` end). The pure kernel `converge_anneal_with_hint` accepts the hint pose + σ pair as parameters, so it is reachable from both the OneShot wrapper (`converge_anneal`, which DOES consult the flag and forwards via the pure kernel) and the Live carry path (which sources hint from `last_pose`) without a flag-clear race.

**Mid-Live re-anchor is out of scope**: clicking the SPA pose-hint while Live is ticking does NOT re-anchor the carry path — the pipelined Live kernel never reads `g_calibrate_hint_*`. Operator must (a) toggle Live OFF, (b) place hint, (c) Calibrate (OneShot consumes the hint), (d) toggle Live ON again. Live then carries forward from the freshly-converged OneShot pose. This is intentional; a future PR can revisit if HIL surfaces a UX gap.

**Sequential ships first, pipelined-parallel deferred**: per `project_pipelined_compute_pattern.md`, the K-step pipeline runs sequentially in this PR (single thread, one σ schedule pass per tick). Multi-thread parallel pipelining (multiple concurrent AMCL chains at different σ tiers, picking the best) is scaffolded for a future PR.

**Default-flip rollout**: this PR ships with `cfg.live_carry_pose_as_hint = false` for HIL safety. Operator A/B's the kernel via tracker.toml override + restart, compares to the legacy ~4 m drift on the same physical scenario, decides. A follow-up PR (~3 LOC: flip the compile-time default, bump CONFIG_SCHEMA `default_repr` "0" → "1") flips the default after HIL approval.

**Pinned by**:
- `production/RPi5/CODEBASE.md` invariant (q) — kernel ownership + Bool-as-Int convention.
- `tests/test_cold_writer_live_pipelined.cpp` — 8 cases covering the contract surface.
- `tests/test_amcl_scenarios.cpp` Scenario E — `converge_anneal_with_hint` stays in hint basin under tight σ.
- `tests/test_cold_writer_live_iteration.cpp` — explicit rollback-path baseline pin.

### Yaw safety tripwire (post-Track-D-5)

The tripwire fires ONCE on the final result of `converge_anneal` (intermediate-phase poses are not tripwire candidates — the schedule's wider phases produce intentionally noisy poses that would spam stderr if checked).

### Yaw safety tripwire

Lives in the cold-writer wrapper, NOT in `Amcl` itself. Anchor is `grid.origin_yaw_deg` (the YAML `origin[2]` parsed at map load — see §13.8 for the SSOT migration), not the previous AMCL output:

```
if shortest_arc(pose.yaw_deg, grid.origin_yaw_deg) > amcl_yaw_tripwire_deg:
    log("yaw_drift", ...)   # Phase 4-3 wires a UDP warning bit
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
                       │  seqlock read (no blocking, retry on writer)
                       │  stale value is OK — hot path never blocks
┌──────────────────────┴──────── Cold path (AMCL, ≤ 1 s) ───────────────┐
│                                                                       │
│  LiDAR scan ─► AMCL ─► deadband filter ─► seqlock write               │
│                                   ▲                                    │
│                                   └─ see §6.4.1                       │
└───────────────────────────────────────────────────────────────────────┘
```

#### 6.1.1 Shared data types — pinned

```cpp
namespace godo::rt {

// Exchanged across the hot/cold boundary.
struct Offset {
    double dx;    // metres, world-frame
    double dy;    // metres, world-frame
    double dyaw;  // degrees, [0, 360) canonical (see §6.5 lerp_angle)
};
static_assert(sizeof(Offset) == 24, "Offset layout is ABI-visible");

// Hot-path input from Thread A (FreeD serial reader).
struct FreedPacket {
    std::array<std::byte, 29> bytes;  // FreeD D1 packet len, per legacy §20
};

}  // namespace godo::rt
```

Both are **strictly larger than any lock-free `std::atomic<T>` on aarch64
without `-march=armv8.4-a+lse2`**. We do not rely on wide atomics. The
crossing is done with a **seqlock** for both `target_offset` and
`latest_freed`:

```cpp
// One writer, N readers. Writer bumps `seq` before and after the payload
// write; readers retry if the sequence changed during the read.
template <typename T>
class Seqlock {
    alignas(64) std::atomic<std::uint64_t> seq_{0};
    T payload_{};

public:
    void store(const T& v) noexcept {                // single writer
        const auto s = seq_.load(std::memory_order_relaxed);
        seq_.store(s + 1, std::memory_order_release);
        payload_ = v;
        seq_.store(s + 2, std::memory_order_release);
    }
    T load() const noexcept {                        // any reader
        for (;;) {
            const auto s1 = seq_.load(std::memory_order_acquire);
            if (s1 & 1) continue;                    // writer in progress
            const T copy = payload_;
            const auto s2 = seq_.load(std::memory_order_acquire);
            if (s1 == s2) return copy;
        }
    }
    std::uint64_t generation() const noexcept {
        return seq_.load(std::memory_order_acquire) & ~uint64_t{1};
    }
};
```

- `target_offset` is a `Seqlock<Offset>`: writer = Thread C (AMCL), readers
  = Thread D (hot path) **and** the IPC server (godo-webctl reads it for
  `/health`). Multi-reader is **allowed** by seqlock.
- `latest_freed` is a `Seqlock<FreedPacket>`: writer = Thread A (serial
  reader), reader = Thread D.
- The seqlock `generation()` (always even on a consistent payload) doubles
  as the **update counter** used by the smoother (see §6.4).

#### 6.1.2 Time source — pinned

**All** time measurements in the RT pipeline use `CLOCK_MONOTONIC`:

```cpp
inline std::int64_t monotonic_ns() noexcept {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1'000'000'000LL + ts.tv_nsec;
}
```

`clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, ...)` in Thread D uses
the same clock, so the smoother's elapsed-time arithmetic never crosses
clock domains. `std::chrono::steady_clock` is **not** used — its epoch is
implementation-defined and the mixing has historically caused bugs.

#### 6.1.3 Trigger primitive — pinned

The trigger primitive is a single **atomic enum** in `core/rt_flags.hpp`:

```cpp
enum class AmclMode : std::uint8_t {
    Idle    = 0,    // cold writer parked; smoother holds the last published Offset
    OneShot = 1,    // run converge() once, publish, return to Idle
    Live    = 2,    // run step() per scan until toggled off (Phase 4-2 D body)
};

extern std::atomic<AmclMode> g_amcl_mode;  // initial value: Idle
```

- Physical GPIO button and `godo-webctl` both call
  `g_amcl_mode.store(AmclMode::OneShot, release)` for a 1-shot calibrate
  or `g_amcl_mode.store(AmclMode::Live, release)` to enter Live tracking.
  Two writers, idempotent stores — multiple presses collapse harmlessly.
- Cold writer (`src/localization/cold_writer.cpp`) consumes with
  `g_amcl_mode.load(acquire)` per loop tick. After a `OneShot` run completes
  it stores `AmclMode::Idle` to return the state machine to its parked state.
  `Live` mode runs continuously until the operator stores `Idle` (toggle off).
- **Not a queue.** Idempotent stores + the three-state machine cover every
  user action defined in CLAUDE.md §1. If future work adds non-idempotent
  commands (e.g., `map_reload`, `emergency_stop`), an MPSC lock-free ring
  would slot in beside the mode atomic; mentioned here so the upgrade
  path is explicit.
- **Migration note (2026-04-26)**: replaced the Phase 4-1 boolean
  `std::atomic<bool> calibrate_requested`. The atomic-enum form is needed
  because `OneShot` and `Live` are distinguishable states, not two writes
  to the same flag. See `production/RPi5/CODEBASE.md` Wave 2 section.

#### 6.1.4 Consequences

- AMCL may run at 1 Hz, 10 Hz, or stall for 500 ms — the hot path keeps
  emitting UDP with the last-known `target_offset`, driven toward by the
  smoother's ramp.
- Deadband at the cold path (§6.4.1) guarantees `target_offset` does not
  oscillate from AMCL's sub-cm noise, so the smoother's ramp actually
  completes.
- No kernel object sits between Thread A/C and Thread D on the happy
  path — seqlock reads are spin-free when the writer is idle.

### 6.2 Thread D skeleton

Lifecycle invariants (set in `main()` **before** any thread spawns):

```cpp
int main(int argc, char** argv) {
    // Process-wide. Must precede any std::thread / pthread_create so every
    // future stack is eligible for locking. Calling from inside a thread
    // only affects that thread's existing pages (bug in the v2 spec).
    if (mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        perror("mlockall"); return 1;
    }

    // Mask SIGCHLD / SIGPIPE at the process level; individual threads
    // unmask only what they must handle. Thread D handles no signals.
    sigset_t mask; sigfillset(&mask);
    pthread_sigmask(SIG_BLOCK, &mask, nullptr);

    setlocale(LC_ALL, "C");       // children inherit, see codebase invariant (d)
    Config cfg = Config::load(argv, env);
    ...
    spawn_threads(cfg);
    ...
}
```

Thread D (59.94 Hz UDP sender):

```cpp
std::atomic<bool> g_running{true};  // flag set to false on SIGTERM

void udp_sender_thread(Config cfg) {
    // Real-time scheduling — this thread only.
    sched_param sp{.sched_priority = 50};
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);

    cpu_set_t mask; CPU_ZERO(&mask); CPU_SET(cfg.rt_cpu, &mask);
    pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);

    // Periodic deadline in CLOCK_MONOTONIC (§6.1.2).
    timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);
    const int64_t period_ns = godo::constants::FRAME_PERIOD_NS;  // 16_683_350

    OffsetSmoother smoother{cfg.t_ramp_ns};   // §6.4

    while (g_running.load(std::memory_order_acquire)) {
        const int64_t now_ns = monotonic_ns();              // §6.1.2

        // Seqlock reads — never block the hot path (§6.1.1).
        const FreedPacket p      = latest_freed.load();
        const uint64_t    gen    = target_offset.generation();
        const Offset      target = target_offset.load();

        // Smooth toward the latest target; gen-based edge detection (§6.4).
        smoother.tick(target, gen, now_ns);
        const Offset off = smoother.live();

        FreedPacket out = p;
        apply_offset_inplace(out, off);                     // §6.5

        send_udp(out, cfg.ue_addr);

        // Absolute-time deadline; advance and sleep.
        next.tv_nsec += period_ns;
        while (next.tv_nsec >= 1'000'000'000) {
            next.tv_nsec -= 1'000'000'000;
            next.tv_sec  += 1;
        }
        int rc;
        do {
            rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, nullptr);
        } while (rc == EINTR);
        if (rc != 0) { /* log + emergency exit, watchdog will reboot */ }
    }
}
```

Notes pinned by the skeleton:

- `g_running` is a `std::atomic<bool>` — the compiler may not hoist the
  load out of the loop (v2 spec was silent).
- `clock_nanosleep` return value is checked; `EINTR` is looped. Signals
  are blocked process-wide per the `main()` stanza above, but this guard
  is cheap and guards against future signal-handling changes.
- `apply_offset_inplace` contains the dx/dy/dyaw merge and pan re-encode
  with wrap; see §6.5 for the exact arithmetic.
- CPU affinity, rtprio, and RAM period all come from `Config`; no
  magic numbers in the function body. See §11.

#### 6.2.2 Final-output transform stage (issue#27, 2026-05-04 KST)

Inserted between `apply_offset_inplace` (AMCL merge) and `send_udp`:

```text
FreedPacket out = latest_freed.load();
apply_offset_inplace(out, smoother.live());     // AMCL → world delta merge
apply_output_transform_inplace(out, output_xform); // operator per-channel sign + offset
LastOutputFrame snap = decode_last_output_from_packet(out);
snap.published_mono_ns = monotonic_ns();
snap.valid = 1;
last_output_seq.store(snap);                    // SeqLock for SPA readout
udp.send(out);                                  // 60 Hz to UE
```

The transform applies `final = sign * (raw + offset)` per channel, in
scaled-double space, across X/Y/Z (1/64 mm/lsb) and Pan/Tilt/Roll
(1/32768°/lsb). Zoom + Focus pass-through (raw u24 bytes preserved).
Reload class is **Restart** — values are captured by const ref in
`thread_d_rt` from boot-time `Config` (no SeqLock-published transform
fields; mid-run hot-flip would race the post-transform `LastOutputFrame`
publish).

Roll byte position: the FreeD D1 spec lists bytes 9-11 as "Reserved
Data" but SHOTOKU emits a non-zero constant there and PIXOTOPE-side
decoders treat it as Roll; per-LSB scale assumed equal to Pan/Tilt's
1/32768° (operator can correct via `output_transform.roll_*` schema
rows if PIXOTOPE-side decode differs). See
`production/RPi5/src/udp/output_transform.hpp` for the rationale.

The post-transform `LastOutputFrame` flows over UDS (`get_last_output`)
to the SPA's `<LastPoseCard/>` "Final output (UDP)" 8-channel grid,
giving operators visibility into the actual values being sent to UE
without re-implementing the wire decode in the SPA.

### 6.2.1 UDS bootstrap path (issue#18, 2026-05-03)

`main()`'s pre-thread-spawn boot sequence — between `Config::load` and
`spawn_threads` — runs three UDS-bootstrap actions in this exact order:

```
pidfile_lock(cfg.pidfile_path)                    // invariant (l)
godo::uds::audit_runtime_dir(cfg.uds_socket)      // MF3 — log-only
godo::uds::sweep_stale_siblings(cfg.uds_socket)   // SF3 — clean stale .tmp
banner emit
spawn_threads(cfg)                                // thread_uds → UdsServer::open()
```

**Why this exact order**:

- `pidfile_lock` first — every later step depends on the single-instance
  invariant. If the lock fails, no UDS state is touched.
- `audit_runtime_dir` second — emits ONE stderr line cataloguing the
  inherited UDS state at boot:
  `uds bootstrap audit: ctl.sock=<TYPE_size_or_ENOENT> siblings=<n> [<list-cap-3>]`.
  Captures the inherited state BEFORE any cleanup so journalctl can
  forensic-trace what was found at boot.
- `sweep_stale_siblings` third — `glob(3)` over `<socket_path>.*.tmp`
  with strict `globfree()` RAII. Regular files unconditionally swept;
  socket-typed siblings are unlinked only if `mtime` is older than
  `UDS_STALE_SIBLING_MIN_AGE_SEC = 2s` (defence-in-depth — pidfile
  invariant already excludes concurrent trackers, but the mtime gate
  prevents a hypothetical self-delete race).
- Banner + `spawn_threads` last — `thread_uds` constructs the
  `UdsServer` on its stack; `UdsServer::open()` runs the atomic-rename
  bind sequence + the existing PR #73 `lstat`-non-socket guard as
  second line of defence inside the open path. `<pid>.tmp` does not
  exist until `UdsServer::open()` runs, so `sweep_stale_siblings` (which
  ran earlier) cannot self-delete the tracker's own temp socket.

**Graceful shutdown** — SIGTERM → `g_running.store(false)` →
`server.run()` returns → stack unwinding fires `~UdsServer()` →
`close()` → `unlink(socket_path_)`. The destructor-unlink path is the
canonical cleanup; `audit_runtime_dir` + `sweep_stale_siblings` cover
the unclean-shutdown case where the destructor never ran.

**Forensic logging** — `UdsServer::open()`'s rename failure path now
calls `log_lstat_for_throw(path, label)` BEFORE the existing throw,
emitting per-endpoint stderr lines with the `S_IFSOCK / S_IFREG /
S_IFDIR / ENOENT / lstat_errno=<n>` discriminator. The throw text is
unchanged so any caller / journalctl grep keying on `rename(`
continues to work. The helper is namespace-internal (exposed in
`uds_server.hpp`) so the unit test can drive it directly with the
four discriminator inputs without forcing `rename(2)` failure or
introducing mocks.

Cross-references: production CODEBASE invariant `(u)
uds-bootstrap-stale-state-discipline`; `production/RPi5/doc/uds_protocol.md`
§H Bootstrap and operator forensics (with H.2 documenting the
`ss -lxp` historical-bind-path display quirk and H.3 the operator
journalctl + HIL recipes).

### 6.3 Operational checklist

- [ ] `/etc/security/limits.conf`: `@godo - rtprio 99`.
- [ ] systemd unit: `CPUAffinity=0-3`, `CPUSchedulingPolicy=fifo`, `CPUSchedulingPriority=50`.
- [ ] **IRQ inventory + isolation** — produce in Phase 4-1, not assumed here.
      On news-pi01, enumerate the USB xHCI IRQ (LiDAR + FreeD adapter) and
      the Ethernet IRQ; steer them to CPUs 0–2 via
      `/proc/irq/<n>/smp_affinity_list`. The `<n>` values must be measured
      with `grep -E "xhci|eth" /proc/interrupts` on the target host — there
      is no portable table. Record the findings in
      `production/RPi5/doc/irq_inventory.md`.
- [ ] `sudo systemctl disable ondemand`; `cpupower frequency-set -g performance`.
- [ ] Hardware watchdog: `/etc/systemd/system.conf` → `RuntimeWatchdogSec=10s`.
- [ ] **FreeD serial wiring — PL011 UART0 on 40-pin header**. FreeD
      arrives as RS-232 ±12 V from the SHOTOKU crane; a YL-128 (MAX3232)
      converts it to 3.3 V TTL. The YL-128 **must** be powered from the
      Pi's 3V3 rail (pin 1 or 17) — NOT 5 V — so both sides of the link
      are 3.3 V CMOS with clean noise margins. Resistor dividers on the
      RX line are NOT used; they erode the VIH/VIL margins and have
      caused intermittent framing errors on prior Arduino R4 builds.
      Wiring: YL-128 TXD → Pi GPIO 15 (pin 10, UART0 RX); GND common;
      VCC from pin 1. FreeD is unidirectional, so Pi TX is unwired.
- [ ] `/boot/firmware/config.txt`: `enable_uart=1` +
      `dtparam=uart0=on`; in `/boot/firmware/cmdline.txt`, remove
      `console=serial0,115200` (the kernel serial console would otherwise
      own `/dev/ttyAMA0`). Verify with
      `stty -F /dev/ttyAMA0 38400 parenb parodd cs8 -cstopb` after reboot.
      Full procedure in `production/RPi5/doc/freed_wiring.md`.

### 6.4 Offset smoother — linear ramp (method A)

The smoother sits inside Thread D. State is private (no atomics). Tick cost
is a handful of FLOPs.

**Design intent (clarified 2026-04-26)**: the smoother + 60 Hz hot path
was designed primarily around **Live mode** (CLAUDE.md §1 mode 4). Live
mode publishes new `Offset`s at ~10 Hz from the cold writer; the smoother
interpolates between those updates so UE renders at a steady 59.94 fps
without visible "tick-tick" jumps. **1-shot calibrate (mode 3) inherits
the smoother as a side-benefit** — the operator-triggered re-localization
becomes a smooth ramp instead of a step change. If only mode 3 existed,
the smoother would be optional. The full architecture exists because
mode 4 needs it, so mode 3 gets it for free.

**Default ramp duration (issue#12, 2026-05-01 18:07 KST)**: `T_RAMP_NS`
defaults to **100 ms** (lowered from the original 500 ms after operator
HIL approval). At 10 Hz LiDAR cadence the inter-tick period is ~100 ms,
so a 1-tick ramp suffices to hide per-tick step changes without
visible lag. The earlier 500 ms value was tuned for the OneShot UX
which inherits the smoother as a side-benefit; OneShot is
operator-triggered and rare, so its comfort no longer dominates the
trade-off. Operators may restore 500 ms via `smoother.t_ramp_ms = 500`
in tracker.toml (Restart class).

#### 6.4.1 Deadband filter — at the cold path, before seqlock write

AMCL produces sub-cm jitter even when the true pose is static (SLAMTEC C1
range noise + particle resampling variance). If every AMCL call wrote
`target_offset`, the smoother would restart its ramp on every scan and
`live` would hover a fraction of the way to a target that moved before the
ramp could finish.

The filter lives **in Thread C (AMCL writer)**, not the smoother, because
AMCL knows its own noise floor and the filter should not burn hot-path
FLOPs on data that is trivially rejectable.

```text
Cold path, after AMCL produces pose estimate `new`:

    if |new.dx  − last_written.dx|   < DEADBAND_MM  AND
       |new.dy  − last_written.dy|   < DEADBAND_MM  AND
       shortest_arc(new.dyaw, last_written.dyaw)
                                     < DEADBAND_DEG:
        return                                    # noise — do nothing

    target_offset.store(new)                      # seqlock write (§6.1.1)
    last_written ← new                            # Thread-C-local, no atomic
```

Constants (see §11):

| Constant | Default | Rationale |
| --- | --- | --- |
| `DEADBAND_MM` | 10.0 mm (1 cm) | Matches CLAUDE.md §1 accuracy target floor; below the 1–2 cm UE-visible envelope. |
| `DEADBAND_DEG` | 0.1° | ≈ 2× the tilt-survey threshold 0.057° at `R_max = 10 m`; wide enough that tilt micro-oscillation does not fight the smoother, narrow enough that a real base-rotation is still caught. |

Forced-accept path: when `calibrate_requested` was consumed this scan
(§6.1.3), the filter is **bypassed** — the operator explicitly asked for
a new fix, so whatever AMCL produces is authoritative even if within the
deadband. Implementation: pass `force=true` into the cold-path writer
after `calibrate_requested.exchange(false) == true`.

#### 6.4.2 Hot-path smoother tick — generation-based edge

`target` equality on floats cannot be used to detect a new update
(floating-point drift would fire every tick). The smoother uses the
seqlock **generation counter** (§6.1.1), which is an integer, exact.

```text
State (Thread-D-local, no atomics):
    live     : Offset   current applied value
    prev     : Offset   where the current ramp started from
    target   : Offset   copy of the target from the latest-seen generation
    target_g : uint64   generation that 'target' was loaded at
    t_start  : int64_t  CLOCK_MONOTONIC ns at which the current ramp began

Initialization (before the first tick):
    live = prev = target = {0, 0, 0}
    target_g = 0            # any non-zero first-seen gen triggers ramp start
    t_start  = -∞           # ensures first post-init gen bump starts a ramp

On each Thread D tick(target_new, gen_new, now_ns):
    if gen_new != target_g:                       # genuinely new write
        prev      ← live                          # start from where we are
        target    ← target_new
        target_g  ← gen_new
        t_start   ← now_ns

    if (now_ns - t_start) >= T_ramp_ns:           # SNAP at frac >= 1.0
        live ← target                             # value-copy, exact
    else:
        frac       ← (now_ns - t_start) / T_ramp_ns   # float ∈ [0, 1)
        live.dx    ← prev.dx + (target.dx - prev.dx) × frac
        live.dy    ← prev.dy + (target.dy - prev.dy) × frac
        live.dyaw  ← lerp_angle(prev.dyaw, target.dyaw, frac)   # §6.5
```

Two things the v2 spec got wrong that this fixes:

1. **Ramp completion**: `(now - t_start) >= T_ramp_ns` triggers an explicit
   `live ← target` value-copy. No float round-off in the "done" path; the
   acceptance test "no update for 10 s → `live == target` exact" now holds.
2. **Edge detection**: Integer `gen_new != target_g` is exact. AMCL sub-cm
   noise that was filtered by the deadband never reaches the hot path
   anyway, but even if it did, the gen counter only increments on a
   successful seqlock write — one per *accepted* target, not one per
   AMCL call.

#### 6.4.3 Why linear ramp over EMA / rate-limit

| | Linear ramp (A, **chosen**) | First-order LPF (B) | Rate-limit slew (C) |
| --- | --- | --- | --- |
| Transition time | Fixed `T_ramp` — predictable | Exponential, never truly "done" | Varies with jump magnitude |
| Tunable | 1 knob (`T_ramp`) | 1 knob (`τ`) | 1 knob (`v_max`) |
| Rapid-update behaviour | Naturally re-targets from current live | Same | Same |
| UE operator mental model | "changes take 0.5 s, deterministic" | Hard to reason about | Big jumps visibly slow |

Rapid re-target — two updates within `T_ramp` — is handled by the
`prev ← live` assignment: each new generation starts a **fresh** ramp
from the current interpolated position. Repeated small corrections blend
cleanly.

**What the smoother does NOT guarantee**: monotonicity under adversarial
update sequences. If AMCL's deadband-filtered outputs genuinely
non-monotone (true pose estimate overshoots then corrects), `live` will
follow that non-monotone path. This is correct behaviour — the hot path
should not second-guess what the localizer says is the best current
estimate. The acceptance test previously listed as "monotonic toward
final target" is dropped; see below.

#### 6.4.4 Acceptance tests (Phase 4-1)

- [ ] **Single step update**: one new generation with target = (1, 0, 0).
      `live` reaches `target` within `T_ramp ± 1 frame`; final value
      byte-identical via the snap path.
- [ ] **No update during 10 s**: `live == target`, exact (value-copy),
      no float drift.
- [ ] **Sub-deadband AMCL noise (10 scans, |Δ| < 5 mm, < 0.05°)**: cold
      path filters all; generation does not bump; `live` does not move.
- [ ] **Rapid updates within T_ramp (3 distinct gens in 50 ms)**: `live`
      smoothly interpolates; at the final gen, ramp starts fresh from
      current `live`; reaches final `target` in `T_ramp` from that moment.
      No overshoot, no oscillation beyond what AMCL itself emits.
- [ ] **Yaw wrap 359° → 1°**: `live.dyaw` traverses 2° CW (short arc),
      not 358° CCW.
- [ ] **Forced accept under deadband**: `calibrate_requested = true` +
      AMCL emits delta within deadband → filter bypassed, generation
      bumps, smoother re-targets. Tests the recovery scenario in §8.

### 6.5 Yaw wrap — two named sites

Legacy `XR_FreeD_to_UDP` is pure passthrough (see `XR_FreeD_to_UDP/src/main.cpp:20`
for the packet field comment; `readU24BE`/`writeU24BE` at L203–215 touch
only zoom/focus, pan is byte-copied). That design never performs arithmetic
on the pan value, so no wrap function was needed. GODO **does** add an
offset to pan, so we need explicit wrap in two places:

```cpp
// Site 1 — inside the smoother (float degrees).
// Operates on Offset::dyaw, an angle in ℝ degrees, canonical range [0, 360).
// Precondition: |b - a| < 360 on the raw float difference. AMCL never
// produces multi-turn deltas (it has no multi-turn concept), so this is
// satisfied by construction. Violations are caught by the pinned test
// `lerp_angle(0, 720, 0.5) == 0` which confirms the shortest-arc collapse.
double lerp_angle(double a, double b, double frac) noexcept {
    const double d = std::fmod(b - a + 540.0, 360.0) - 180.0;  // ∈ (−180, +180]
    double y = a + d * frac;
    y = std::fmod(y, 360.0);
    if (y < 0.0) y += 360.0;
    return y;  // [0, 360)
}

// Site 2 — at FreeD pan re-encode.
// FreeD D1 pan field: signed 24-bit, 1/32768 deg per lsb (per FreeD D1
// spec; legacy XR_FreeD_to_UDP comment at L20 confirms the wire format,
// but the signedness claim is verified against the spec, NOT against the
// legacy code which is pan-agnostic). The encoding range is ±2^23 = ±256°;
// this is the *encoded* range, NOT a physical crane limit (SHOTOKU
// Ti-04VR mechanical pan is typically ±170°).
int32_t wrap_signed24(int64_t v) noexcept {
    constexpr int64_t R = 1LL << 24;   // 16_777_216 (one full turn in lsb)
    constexpr int64_t H = 1LL << 23;   //  8_388_608 (half turn)
    v = ((v % R) + R) % R;             // reduce to [0, R)
    if (v >= H) v -= R;                // fold to [−H, +H)
    return static_cast<int32_t>(v);
}
```

Both are **pure free functions** (not methods); this makes the unit tests
trivial and prevents accidental re-wrapping if someone adds a
transformation between the two sites.

Pinned unit tests:

`lerp_angle` (all must pass byte-identical, no `approx`):

- [ ] `lerp_angle(a, a, frac) == a` for `a ∈ {0, 90, 180, 270}`, any `frac` — fixed-point identity.
- [ ] `lerp_angle(359.0, 1.0, 0.0) == 359.0` — endpoint at `frac=0`.
- [ ] `lerp_angle(359.0, 1.0, 1.0) == 1.0` — endpoint at `frac=1`.
- [ ] `lerp_angle(359.0, 1.0, 0.5) == 0.0` — short arc, not 180.
- [ ] `lerp_angle(10.0, 350.0, 0.5) == 0.0` — short arc on the other side.
- [ ] `lerp_angle(0.0, 360.0, 0.5) == 0.0` — aliased endpoints.
- [ ] `lerp_angle(0.0, 720.0, 0.5) == 0.0` — documents the `|b - a| < 360`
      precondition: a 720° delta collapses to 0° shortest-arc.

`wrap_signed24`:

- [ ] Identity in range: `wrap_signed24(x) == x` for `x ∈ {−H, −1, 0, 1, H−1}`.
- [ ] Upper edge: `wrap_signed24(H) == −H` (H is outside the canonical range).
- [ ] Rollover: `wrap_signed24(H + 1) == −H + 1`.
- [ ] Negative rollover: `wrap_signed24(−H − 1) == H − 1`.
- [ ] Idempotence: `wrap_signed24(wrap_signed24(v)) == wrap_signed24(v)` for
      any `v ∈ [−2^30, 2^30)`.

### 6.6 Parallel particle evaluation (issue#11)

The cold writer's per-tick compute is dominated by the per-particle
`evaluate_scan` loop. Phase-0 5-min main capture (PR #96 / `53453f5` /
`.claude/tmp/phase0_results_5min_20260506_095949.md`) measured the
sequential breakdown at K ≈ 17 iters / scan, N=500 particles:

| Stage          | p50 (ms) | share of TOTAL p50 |
|----------------|---------:|:------------------:|
| LF rebuild     |    39.58 |             29.1 % |
| jitter         |     0.77 |              0.6 % |
| evaluate_scan  |    94.85 |             69.7 % |
| normalize      |     0.14 |              0.1 % |
| resample       |     0.07 |              0.1 % |
| **TOTAL**      | **136.15** |       **7.34 Hz** |

The 10 Hz LiDAR rate produces ~30 % scan drop against a 7.34 Hz cold
path. issue#11 partitions the per-particle eval across a
`ParallelEvalPool` with workers pinned to `{CPU 0, 1, 2}` and joins per
AMCL step:

```text
┌────────────────────────────────────────────────────────────┐
│ Cold writer thread (CFS, cpus 0/1/2)                       │
│                                                            │
│   for k in σ_schedule:                                     │
│     LF.rebuild(σ_k)                       ──── 13.2 ms     │
│     for iter in K_phase:                                   │
│       jitter_inplace(front_)              ──── ~0.05 ms    │
│       ┌──────── pool.parallel_for ──────┐                 │
│       │ Worker 0 (CPU 0)                │                 │
│       │   evaluate_scan(front_[i_0..N/3])│ ─ ~1.85 ms     │
│       │ Worker 1 (CPU 1)                │   parallel      │
│       │   evaluate_scan(front_[N/3..2N/3])│  fork-join    │
│       │ Worker 2 (CPU 2)                │                 │
│       │   evaluate_scan(front_[2N/3..N])│                 │
│       └─────── join (≤ 50 ms timeout) ──┘                 │
│       normalize_weights()                ──── 0.14 ms     │
│       resample (conditional)             ──── 0.07 ms     │
│                                                            │
│   apply_deadband_publish(target_offset, …)                 │
│                                                            │
│ Thread D (SCHED_FIFO 50 on CPU 3) — UNAFFECTED.            │
└────────────────────────────────────────────────────────────┘
```

**Cache topology** is the load-bearing reason this fork-join design
holds at Pi 5 scale: the 16 MB likelihood field is read-only during
each step, so all three workers pull the same cache lines; reads
replicate across L1d without any MESI coherence traffic. By contrast
Option B (multi-tier σ pipeline) would require 3 × LF replicas (48 MB)
which exceed the Pi 5 8 GB DRAM bandwidth budget under sustained load
(plan §2.B'). The single-LF design also keeps the cold path's working
set inside the natural locality the sequential path already enjoyed.

**Bit-equality with sequential** (plan §3.6 proof; pinned by
`tests/test_amcl_parallel_eval.cpp::case 1`): workers write to a
partition-disjoint subrange of `front_[i].weight`; `normalize_weights`
+ `weighted_mean()` then sum in identical i-order, so the IEEE 754
reductions are bit-equal regardless of worker thread interleaving. The
invariant explicitly forbids parallelizing `weighted_mean` without
re-deriving the proof — see CODEBASE.md `(s)`.

**Diag surface**: `Seqlock<ParallelEvalSnapshot>` published at 1 Hz by
`run_diag_publisher` (mirroring the JitterSnapshot seam). UDS
`get_parallel_eval` reads it (`uds_protocol.md` §C.11). Operator
acceptance bar: `dispatch_count` grows in step with cold-writer
iters, `fallback_count == 0` in steady state, `degraded == 0`,
`p99_us` ≤ 4000 µs. `degraded == 1` means the pool transitioned to
permanent inline-sequential mode (ctor 1 s timeout OR a single 50 ms
join overrun); the cold writer continues at the pre-issue#11
sequential speed without accuracy regression.

**Rollback**: TOML `amcl.parallel_eval_workers = 1` boots the pool
with no worker threads — `parallel_for` runs fn on the caller thread
and produces output bit-equal to the pre-issue#11 sequential path.
Restart-class so the operator gets a clean re-start path; no mid-run
hot-flip.

**Cross-applicability**: the same pool is the primitive for issue#19
(EDT 2D Felzenszwalb row/column passes). issue#19 ships the extension
(`parallel_for_with_scratch<S>` for per-worker `(v, z)` scratch pairs)
— see §6.6.1 below. Together issue#11 + issue#19 absorb 99 % of the
per-tick cold compute, projecting ~21 Hz at p50 (48 ms / scan) on the
same Phase-0 fixture. issue#11 ships the simpler
`parallel_for(begin, end, fn)` surface only.

### 6.6.1 EDT 2D parallelisation (issue#19)

The Felzenszwalb 2D EDT (`localization/likelihood_field.cpp::build_likelihood_field`)
runs two 1-D passes — column (W independent vertical sweeps) then row
(H independent horizontal sweeps). Phase-0 measured LF rebuild p50 at
~40 ms (29 % of TOTAL p50 in pre-issue#11 sequential, 46 % of TOTAL
p50 post-issue#11). issue#19 partitions both passes across the same
`ParallelEvalPool` (cores 0/1/2, CPU 3 still vetoed by Thread D RT
contract):

```text
┌─────────────────────────────────────────────────────────────────┐
│ build_likelihood_field (cold writer thread, cpus 0/1/2)          │
│                                                                  │
│   ┌─── pool.parallel_for_with_scratch<EdtScratch> (col pass) ─┐  │
│   │ Worker 0: cols [0   .. W/3) — 16-float aligned residue    │  │
│   │ Worker 1: cols [W/3 .. 2W/3) — 16-float aligned residue   │  │
│   │ Worker 2: cols [2W/3 .. W)   — last-worker takes residue  │  │
│   └─── join (range-proportional deadline, anchor=W·H/3) ─────┘   │
│                                                                  │
│   ┌─── pool.parallel_for_with_scratch<EdtScratch> (row pass) ─┐  │
│   │ Worker 0: rows [0   .. H/3)                              │   │
│   │ Worker 1: rows [H/3 .. 2H/3)                             │   │
│   │ Worker 2: rows [2H/3 .. H)                               │   │
│   └─── join (same deadline shape) ────────────────────────────┘  │
│                                                                  │
│   sq_dist → values   (Gaussian conversion, sequential)            │
└─────────────────────────────────────────────────────────────────┘
```

**EDT scratch ownership** is the API surface delta. Felzenszwalb's
`edt_1d` needs two per-sweep scratch buffers (`v` parabola-locator
indices + `z` parabola intersections). Caller builds
`std::vector<EdtScratch> per_worker(workers)` once per pass and passes
it via `parallel_for_with_scratch<EdtScratch>`. Each worker receives
`(thread_idx, &per_worker[thread_idx])` so EDT writes into its own
scratch slot — no contention, no per-iter heap allocation. Pool stays
Scratch-agnostic via a type-erased `void*` shim (D1 / m3 fold);
runtime size guard `if (per_worker.size() != workers)
{ fprintf + std::abort(); }` trips in BOTH debug AND release
(`[edt-scratch-asserted]` build-grep at `parallel_eval_pool.cpp`
function definition; `assert(...)` macro is banned per D1 because it
compiles out under release).

**Cache-line aligned column partition** (D4) — `floor(W/3)` rounded
down to the nearest multiple of 16 floats (= 64 B Cortex-A76 line
width); the last worker absorbs the residue. Row pass uses the
naive `floor(H/3)` partition because consecutive rows are
`W·sizeof(float)` bytes apart so worker boundaries are naturally
cache-aligned. Bit-equality with sequential preserved at production
1000×1000 scale (`tests/bench_lf_rebuild.cpp` case 2 memcmp).

**Range-proportional deadline** (reuses the issue#11 pattern at
`.claude/memory/project_range_proportional_deadline_pattern.md`)
with EDT-specific Tier-1 anchors:
- `EDT_PARALLEL_DEADLINE_BASE_NS = 50 ms` (single-pass anchor at the
  1000-dim reference scale).
- `EDT_PARALLEL_ANCHOR_DIM = 1000` (`max(W, H)` is the dispatch range,
  NOT cell count). Formula: `scale = max(1, max(W,H) / 1000)`.
- Production 1000×1000 → scale=1 → deadline = 50 ms per pass.
  2000×2000 (EDT_MAX_CELLS edge) → scale=2 → deadline = 100 ms per
  pass. Both passes back-to-back at the edge ≈ 200 ms total — well
  under the 5 s SIGTERM watchdog.
- m2 fallback rule (operator-locked 2026-05-06 21:00 KST): if HIL or
  `bench_lf_rebuild` measures 2000×2000 worker p99 > 80 ms, anchor
  drops to 750 via a separate small PR (preserves production-scale
  headroom while tightening the EDT_MAX_CELLS edge to 1.9× headroom).

**Bit-equality with sequential**: workers write to disjoint output
subranges (column subranges in the col pass, row subranges in the
row pass); `sq_dist → values` Gaussian conversion stays sequential
so the IEEE 754 exp() ordering is identical. Pinned by
`tests/test_likelihood_field_parallel.cpp` cases 2/3/4 (FNV-1a-
equivalent memcmp at 16×16 + 256×256 + 1000×1000) and
`tests/bench_lf_rebuild.cpp` case 2 (memcmp at production
1000×1000 scale).

**Graceful fallback** (R7 / R8): if the pool transitions to
permanent inline-sequential (`pool->degraded()` returns true) at
any point during a build, the affected pass is re-run sequentially
using `per_worker[0]`'s scratch. Subsequent calls short-circuit
straight to sequential because `degraded` is sticky for the rest
of the process. Workers=0 rollback (TOML
`amcl.parallel_eval_workers = 1`) bit-equal to pre-issue#19
sequential — `per_worker` sized to `max(1, worker_count())` so the
empty-cpus path has exactly 1 scratch slot; the runtime size-guard
sees the expected size; output bit-equal to nullptr path.

**M1 spirit preservation**: `cold_writer.cpp` source text never
gains `<mutex>` or `std::mutex`. The 3 `build_likelihood_field`
call sites in `cold_writer.cpp` thread the existing `pool*` (the
issue#11 plumbing) into the new `pool` overload of
`build_likelihood_field`; `[m1-no-mutex]` build-grep stays clean.

**Combined projection (issue#11 + issue#19)**: TOTAL p50 87 →
~47 ms ≈ 21.4 Hz at p50, matching §6.6 closing paragraph's
prediction. Operator HIL on news-pi01 verifies post-deploy via
fresh Phase-0 5-min capture (`GODO_PHASE0_TRIM_ON=1`); acceptance
bar LF rebuild p50 ≤ 17 ms, TOTAL p50 ≤ 50 ms, cold-path Hz ≥ 18,
`[pool-degraded]` count == 0.

**Rollback**: TOML `amcl.parallel_eval_workers = 1` (the issue#11
single-lever) — same lever covers both eval-pool and EDT
parallelism. No new TOML key (D5 / A5).

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

- [ ] `core/constants.hpp` + `core/config.{hpp,cpp}` (§11).
- [ ] `core/rt.hpp` — `Offset`, `FreedPacket`, `Seqlock<T>` (§6.1.1).
- [ ] `core/time.hpp` — `monotonic_ns()` (§6.1.2).
- [ ] `freed/` — serial reader + D1 parser + tests (canned-packet fixture
      committed under `tests/fixtures/freed_packets/`; byte sequences are
      captured from the legacy Arduino once and frozen).
- [ ] `smoother/` — linear ramp with gen-based edge + snap (§6.4) + tests
      (all six acceptance tests from §6.4.4).
- [ ] `yaw/` — `lerp_angle`, `wrap_signed24` (§6.5) + pinned tests.
- [ ] `udp/` — RT sender (§6.2), `SCHED_FIFO`, CPU-pinned, `mlockall` in
      `main()`.
- [ ] End-to-end replay test: scripted fixture generator produces a
      canned FreeD packet stream and a scripted offset-step sequence; a
      loopback receiver captures UDP; expected trajectory is compared
      byte-for-byte. Fixture definition lives in
      `tests/fixtures/phase4_replay.toml`.
- [ ] Jitter measurement harness — measures **actual** p99 on the target
      host. The 200 µs target in CLAUDE.md is a design goal, not a
      verified baseline; the harness's first job is to establish what
      this RPi 5 + `godo-tracker` actually delivers so later regression
      tests have a number to defend.

**Phase 4-2 — Cold path + integration**

- [ ] `lidar/` — reuse from `godo_smoke`, promoted out of the smoke
      binary's source tree.
- [ ] `localization/` — port AMCL from Phase 2 Python reference.
- [ ] Cold-path deadband filter (§6.4.1) in the AMCL post-processor.
- [ ] `seqlock` wiring: Thread C writes `target_offset`, Thread D reads.
- [ ] Trigger wiring: GPIO button + UDS command `calibrate_now` from
      `godo-webctl`, both `store(true)` into `calibrate_requested` (§6.1.3).
- [ ] systemd unit + watchdog wiring.
- [ ] Document the Arduino rollback procedure.

**Phase 4-3 — Control plane `godo-webctl` (LANDED 2026-04-26)**

Scope cut deliberately: three endpoints needed for day-to-day operation.
Everything else (map editing, config editing, richer UI) is Phase 4.5 or
Phase 5. Top-level project at `/godo-webctl/` (UV-managed Python).

- [x] `src/godo_webctl/app.py` — FastAPI app factory, three handlers:
      `GET /api/health` (UDS `get_mode` round-trip), `POST /api/calibrate`
      (UDS `set_mode {OneShot}`), `POST /api/map/backup` (atomic two-phase
      copy of `<map>.pgm + <map>.yaml` into
      `/var/lib/godo/map-backups/<UTC ts>/`).
- [x] `src/godo_webctl/uds_client.py` — pure-stdlib `socket(AF_UNIX,
      SOCK_STREAM)` JSON-lines client; sync surface wrapped via
      `asyncio.to_thread`. Three terminal cases on read: newline /
      EOF-before-newline / buffer-full → distinct exception classes
      (`UdsTimeout`, `UdsUnreachable`, `UdsProtocolError`,
      `UdsServerRejected`).
- [x] `src/godo_webctl/protocol.py` — Tier-1 wire constants mirrored from
      `production/RPi5/src/uds/{uds_server.cpp, json_mini.cpp}` and
      `production/RPi5/src/core/constants.hpp`. Canonical request encoders
      (`encode_ping`, `encode_get_mode`, `encode_set_mode`) — clients
      MUST emit the canonical byte form `b'{"cmd":"set_mode","mode":"OneShot"}\n'`
      so the cross-language SSOT pin (drift-detected by `test_protocol.py`)
      stays meaningful. Wire schema is the post-Phase-4-2-D
      `set_mode/get_mode/ping` over `g_amcl_mode = {Idle, OneShot, Live}`,
      NOT the pre-4-2-D `calibrate_now/calibrate_requested` boolean.
- [x] `src/godo_webctl/config.py` — stdlib `dataclass` + `_DEFAULTS` /
      `_PARSERS` / `_ENV_TO_FIELD` paired tables. Env-only config (no
      TOML) — surface is 7 keys, paired tables are SSOT. NOT
      Pydantic-Settings. NOT `/etc/godo/tracker.toml`-parsing on the
      webctl side; webctl never reads the tracker's TOML.
- [x] `src/godo_webctl/backup.py` — mirrors
      `production/RPi5/src/localization/occupancy_grid.cpp::yaml_path_for`
      (strip `.pgm`, append `.yaml`). Two-phase atomic rename with
      bounded `MAX_RENAME_ATTEMPTS = 9` retry on `EEXIST`/`ENOTEMPTY`.
- [x] systemd unit `godo-webctl.service`; `After=godo-tracker.service`,
      `Wants=godo-tracker.service`. **`StateDirectory=godo`** for
      `/var/lib/godo/`; `RuntimeDirectory=godo` deliberately OMITTED
      (godo-tracker.service is the canonical owner of `/run/godo/`).
      `User=ncenter` — same uid as godo_tracker_rt (UDS perm caveat).
- [x] `src/godo_webctl/static/index.html` — vanilla HTML + JS; 1 Hz
      poll of `/api/health`, two operator buttons. Page Visibility API
      handbrake pauses polling when the tab is hidden.
- [x] 52/52 hardware-free pytest cases + 1 hardware-required-tracker
      sequence test (`test_app_hardware_tracker.py`) deferred to news-pi01
      bring-up. ruff + format clean.

**Track A — Docker mapping toolchain (LANDED 2026-04-27)**

- [x] New top-level dir `/godo-mapping/` packages the §4 mapping workflow as a
      single self-contained Docker stack: `Dockerfile` (`ros:jazzy-ros-base` +
      `slam_toolbox` + `rplidar_ros` + `nav2_map_server`), `entrypoint.sh`
      with SIGINT-trap → `map_saver_cli -f /maps/${MAP_NAME}` discipline,
      host-side `scripts/run-mapping.sh` with pre-flight (filename collision
      / stale container / `LIDAR_DEV` override). `verify-no-hw.sh --quick`
      and `--full` modes for hardware-free CI; live `docker run`-required
      mapping run runs Monday earliest after LiDAR reseat.
- [x] CODEBASE.md invariants (a)-(e): ROS pipeline isolation (no rclcpp/ament
      in `production/RPi5/`, so `--network=host` is collision-free);
      Map-format SSOT cite `production/RPi5/src/localization/occupancy_grid.cpp:148-154`;
      single mapping container at a time; `/dev/ttyUSB0` not hardcoded;
      hardware-free build/lint, hardware-required run.

**Track B — AMCL diagnostic readout + repeatability + pose_watch (LANDED 2026-04-27)**

Phase 1 measurement instrument plus the always-on diagnostic readout
channel that makes future diagnostic consumers (frontend panel, CLI dump
tools) thin clients on a stable surface. **Diagnostic surface principle**:
always-on at the source (~30 ns/iter Seqlock store; cost 0 when no client
queries), on-demand at the consumer side (operator launches the script,
opens the panel). Explicitly NOT gated behind a compile flag — production
needs the surface to exist the moment something goes wrong (e.g. "방송 중
카메라가 점프했는데 발산이었나?" diagnosis); a flag-gated tool would require
rebuild/redeploy/reproduce, too slow for control-room reality.

- [x] C++ extension: new 56-byte `LastPose` rt-type (5 doubles + uint64_t
      `published_mono_ns` + int32_t `iterations` + 4 uint8_t flags incl.
      `valid` and `forced`); `Seqlock<LastPose>` populated unconditionally
      by both OneShot and Live kernels (Live publishes with `forced=0` so
      `pose_watch.py` works during shows); F5 ordering pin places
      `last_pose_seq.store` BEFORE `g_amcl_mode = Idle` on the OneShot
      success path so readers polling `get_mode==Idle` then
      `get_last_pose` cannot see stale-pose-with-new-mode.
- [x] New UDS command `get_last_pose` — additive to the post-4-2-D
      `set_mode/get_mode/ping` schema; reply schema documented in
      `production/RPi5/doc/uds_protocol.md` §C.4; `format_ok_pose` precision
      split (`%.6f` for pose, `%.9g` for std fields, `%llu` for mono_ns);
      512 B reply budget pinned by test.
- [x] Cross-language SSOT three-layer chain: canonical at
      `production/RPi5/src/uds/json_mini.cpp::format_ok_pose`; sole Python
      mirror at `godo-webctl/src/godo_webctl/protocol.py::LAST_POSE_FIELDS`;
      derived `CSV_HEADER` in `godo-mapping/scripts/repeatability.py`. Drift
      caught by `test_protocol.py` reading C++ source as text + regex pin.
- [x] `godo-mapping/scripts/_uds_bridge.py` — shared `UdsBridge` class
      (Option C invariant g — both consumers `from _uds_bridge import
      UdsBridge`, never copy-paste).
- [x] `godo-mapping/scripts/repeatability.py` — Phase 1 measurement
      harness: drives N OneShots, logs to CSV with incremental fsync,
      NaN-safe summary stats (mean/stdev/min/max/p95-of-|deviation|),
      exit codes 0..7 + 130 (incl. tracker-death-streak detection at 3
      consecutive UDS failures).
- [x] `godo-mapping/scripts/pose_watch.py` — cmd-window monitor with
      reconnect loop: backoff 1s/2s/4s on EPIPE/ECONNRESET/ECONNREFUSED/ENOENT,
      prints `DISCONNECTED` sentinel + retries; SIGINT clean exit ≤ 200 ms.
      Text + JSON output formats. Designed for tmux/screen during shows.
- [x] 18 hardware-free pytest cases (10 + 4 + 3 pins + 1 positive coverage)
      + 5 new C++ tests + 13 webctl protocol pins. Hardware-required live
      `--shots 100` run deferred to LiDAR reseat.

**Phase 4.5 — Control plane extensions (defer until Phase 5 reveals need)**

- [ ] `/api/config` GET/PATCH with reload-class classification (§11).
- [ ] `/api/map/edit` — remove moving fixtures from the PGM (numpy/OpenCV
      on the Python side). Requires a client-side editor; architecture to
      be designed when the React frontend lands.
- [ ] `/api/map/update` — rebuild the map after a studio change; likely
      triggers a docker-based re-mapping workflow rather than inline
      editing.
- [ ] Frontend framework choice (React vs plain HTML + htmx); decided
      when 4.5 starts.

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
| AMCL produces huge offset jump (non-triggered) | Hot path would ramp UE through a wide arc over `T_ramp` | Clamp **new AMCL delta vs. `last_written` target** (NOT vs. `live`) at a sanity limit (default 2 m / 10°, configurable). Refuse, log `amcl_divergence`, emit an SSE event to `godo-webctl`. Comparing against `last_written` means a smoothing lag does not trigger false rejections | Press Calibrate — this sets `calibrate_requested = true`, which **bypasses** the clamp (§6.4.1 forced-accept path) so kidnapped-recovery always works |
| `godo-webctl` crash | API unreachable; tracker unaffected | systemd restart; UDS socket lives under `RuntimeDirectory=godo` so the stale socket file is cleaned automatically on service stop | Check logs |
| `godo-tracker` crash before `godo-webctl` | HTTP endpoints return 503 (tracker_client UDS connect fails) | `godo-webctl` systemd unit has `After=godo-tracker.service` + `Wants=godo-tracker.service`; webctl retries connect on each request; health check shows `tracker_offline` | Investigate tracker logs |
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

## 11. Runtime configuration

Constants live in two tiers; mixing them is the root cause of "magic
number" bugs and cross-host drift.

### 11.1 Tier 1 — compile-time invariants (`core/constants.hpp`)

Values that can never change without a protocol or algorithmic
reinterpretation. `constexpr` in a header, included anywhere.

```cpp
namespace godo::constants {

// FreeD D1 protocol — pinned by the wire format, not tunable.
inline constexpr int      FREED_PACKET_LEN = 29;
inline constexpr double   FREED_PAN_Q      = 1.0 / 32768.0;   // deg per lsb

// SLAMTEC C1 sample decoding — pinned by the SDK.
inline constexpr double   RPLIDAR_Q14_DEG  = 90.0 / 16384.0;
inline constexpr double   RPLIDAR_Q2_MM    = 1.0 / 4.0;

// Hot-path cadence — pinned by UE's 59.94 fps project standard.
inline constexpr double   FRAME_RATE_HZ    = 60000.0 / 1001.0;
inline constexpr int64_t  FRAME_PERIOD_NS  = 16'683'350;

}  // namespace godo::constants
```

Rule: any change requires a major version bump and coordinated downstream
update (UE project file, legacy Arduino rollback etc.).

### 11.2 Tier 2 — runtime-tunable (`Config`, TOML-backed)

Values that operators change per-host or per-operating-condition. Defaults
live in `core/config_defaults.hpp` as `constexpr`; effective values are
loaded from `/var/lib/godo/tracker.toml` at tracker startup, with an env-var
override layer underneath. (The TOML lives under `/var/lib/godo` rather
than `/etc/godo` because the systemd unit declares
`ReadOnlyPaths=/etc/godo` + `ProtectSystem=strict`; the SPA Config tab's
atomic-rename writer needs a parent directory the tracker process can
mkstemp + rename in. `/var/lib/godo` is in `ReadWritePaths`.)

```cpp
namespace godo::config::defaults {

// Network.
inline constexpr std::string_view UE_HOST          = "192.168.0.0";  // TBD
inline constexpr int              UE_PORT          = 6666;

// Serial devices.
inline constexpr std::string_view LIDAR_PORT       = "/dev/ttyUSB0";
inline constexpr int              LIDAR_BAUD       = 460'800;
inline constexpr std::string_view FREED_PORT       = "/dev/ttyAMA0";   // PL011 UART0 via YL-128 on the 40-pin header, see §6.3
inline constexpr int              FREED_BAUD       = 38'400;

// Smoother & deadband (§6.4).
inline constexpr int64_t          T_RAMP_NS        = 500'000'000;   // 500 ms
inline constexpr double           DEADBAND_MM      = 10.0;          // 1 cm
inline constexpr double           DEADBAND_DEG     = 0.1;
inline constexpr double           DIVERGENCE_MM    = 2000.0;        // §8
inline constexpr double           DIVERGENCE_DEG   = 10.0;

// RT scheduling.
inline constexpr int              RT_CPU           = 3;
inline constexpr int              RT_PRIORITY      = 50;

// IPC.
inline constexpr std::string_view UDS_SOCKET       = "/run/godo/ctl.sock";

}  // namespace godo::config::defaults
```

Example `/var/lib/godo/tracker.toml`:

```toml
[network]
ue_host = "10.1.2.3"
ue_port = 6666

[serial]
lidar_port = "/dev/ttyUSB0"
freed_port = "/dev/ttyAMA0"   # PL011 UART0 + YL-128 per §6.3

[smoother]
t_ramp_ms   = 500
deadband_mm = 10.0
deadband_deg = 0.1

[rt]
cpu      = 3
priority = 50

[ipc]
uds_socket = "/run/godo/ctl.sock"
```

### 11.3 Reload classes — frontend editability

Every Tier-2 key is classified by **what it takes to apply a change**.
The classification is surfaced through `GET /api/config` (Phase 4.5) so a
future React settings page can show the right UX ("applied immediately"
vs "restart required" vs "recalibration required").

| Reload class | Meaning | Keys |
| --- | --- | --- |
| `hot` | Tracker applies on the next hot-path tick (≤ 16.7 ms). No restart. | `ue_host`, `ue_port`, `t_ramp_ms`, `deadband_mm`, `deadband_deg`, `divergence_mm`, `divergence_deg` |
| `restart` | Requires `systemctl restart godo-tracker`. | `lidar_port`, `lidar_baud`, `freed_port`, `freed_baud`, `rt_cpu`, `rt_priority`, `uds_socket` |
| `recalibrate` | Hot-reload + forced calibrate (sets `calibrate_requested`). | `map_path`, `origin_x`, `origin_y` |

Implementation flow (deferred to Phase 4.5):

1. Webctl `PATCH /api/config` writes the merged TOML to disk.
2. Webctl sends `reload_config` over UDS.
3. Tracker re-loads the TOML, bucketises the diff by class, applies what
   it can, reports what it can't back over UDS.
4. Response body lists `applied`, `needs_restart`, `needs_recalibrate`.
5. Frontend surfaces this as coloured badges next to each field.

### 11.4 Magic-number ban — code review rule

Numeric literals in `src/` require one of:

- (a) a `constexpr` in `core/constants.hpp` (Tier 1), or
- (b) a field of `core::Config` (Tier 2) with a default in `core/config_defaults.hpp`, or
- (c) a local iteration / indexing bound (`for (int i = 0; i < v.size(); ++i)`).

Anything else is a code-review block. This is added to CLAUDE.md §6
Golden Rules at the same commit that introduces `core/constants.hpp`.

### 11.5 Webctl-owned schema rows (issue#12, 2026-05-01 18:07 KST)

Some Tier-2 keys describe behaviour of **godo-webctl**, not the
tracker. They live in the same `CONFIG_SCHEMA[]` table because the
SPA's Config tab is schema-driven (one render path for every operator-
tunable knob), but no tracker logic path consumes their value. The
tracker stores them through the existing `apply_one` /
`read_effective` / `render_toml` round-trip purely to keep the schema
contract uniform; webctl is the sole consumer and reads the rendered
`/var/lib/godo/tracker.toml` directly.

Currently two such keys:

| Key | Type | Range | Default | Reload class | Consumer |
| --- | --- | --- | --- | --- | --- |
| `webctl.pose_stream_hz` | Int | [1, 60] | 30 Hz | Restart | `last_pose_stream` SSE producer |
| `webctl.scan_stream_hz` | Int | [1, 60] | 30 Hz | Restart | `last_scan_stream` SSE producer |

**Why not a parallel `WEBCTL_CONFIG_SCHEMA[]`?** Mode-A C1/C2/C3
established that the "schema-row-only, NOT Config-mapped" route is
architecturally infeasible — `apply_one` rejects unmapped keys with
`internal_error`, `read_effective` returns default-zero sentinels, and
`apply_set` never reaches the `restart_pending` flag. Adding 80 LOC for
a parallel mirror was not earned by the cleanliness benefit; the
12-LOC plumbing path (Route 2) keeps every existing test pattern alive
plus a new invariant `(r)` in `production/RPi5/CODEBASE.md`
documenting the "tracker never reads" contract.

**Reload-class semantics**: webctl-owned rows are Restart class. After
the operator edits via SPA, the tracker writes `restart_pending` (the
generic banner fires); the operator runs `systemctl restart
godo-webctl` (NOT godo-tracker — the tracker has no live-reload work
to do). webctl re-reads the value at startup via
`godo_webctl/webctl_toml.read_webctl_section`. Per-key restart-target
hints in the SPA banner are out of scope.

**Cadence-tier discipline**: only the **map-related** SSE streams
(`last_pose_stream`, `last_scan_stream`) are config-driven via these
keys. Other SSE producers stay on their compile-time defaults
(`SSE_TICK_S = 0.2 s` for `diag_stream`,
`SSE_SERVICES_TICK_S = 1 s` for `services_stream`,
`SSE_PROCESSES_TICK_S = 1 s` for `processes_stream`,
`SSE_RESOURCES_EXTENDED_TICK_S = 1 s` for `resources_extended_stream`).
The split is operator-locked "지도 부분에만 적용" — the rationale is
that the Map tab's pose marker + scan overlay benefit the most from
high-cadence updates, while the diag / system tabs are debug-loop
cadence by design.

Cross-link for code: `production/RPi5/CODEBASE.md` invariant `(r)`
covers the storage half (Config-mapped, tracker-unconsumed); the
consumer half lives in `godo-webctl/CODEBASE.md` invariant `(ac)`
(`webctl_toml.py` reader + `sse.py` per-stream cadence resolution).

---

## 12. SPA-driven mapping pipeline (issue#14)

Operator triggers SLAM mapping from the SPA Map > Mapping sub-tab.
The Phase 4-3 + Phase 4.5 plumbing is reused; godo-mapping joins as a
fourth stack and webctl gains a mode coordinator.

### 12.1. Mode coordinator (D1)

The "is mapping in progress?" question is owned **entirely** by webctl.
Tracker UDS is NOT extended. State derives from
`(/run/godo/mapping/state.json, docker inspect output)`. The C++ code
does not need to know about mapping mode — when mapping is active the
tracker is stopped (L2), so `/run/godo/ctl.sock` is unavailable, which
is the existing tracker-down behaviour for webctl.

State machine (5 states):

```text
Idle ─► Starting ─► Running ─► Stopping ─► Idle
         ╲           ╲           ╲
          ╲           ╲           ╲ stop_timeout (defensive docker kill)
           ╲           ╲           ╲
            ╲           ▼           ▼
             ╲       Failed (container_crashed)
              ▼
         Failed (image_missing / tracker_stop_failed /
                 container_start_timeout)

Failed ─► Idle  (operator acknowledge via POST /api/mapping/stop)
```

### 12.2. Tracker-stop race (D3)

`POST /api/mapping/start` runs synchronously through:

1. Validate name (regex + reserved + maps-dir uniqueness).
2. Pre-flight `docker image inspect ${IMAGE_TAG}` (no auto-build).
3. Persist `state.json` as Starting (single source of truth).
4. `systemctl stop godo-tracker.service` (sync; ServicesError → Failed).
5. Resolve `[serial] lidar_port` from tracker.toml.
6. Atomic-write `/run/godo/mapping/active.env`.
7. `systemctl start godo-mapping@active.service`.
8. Poll `docker inspect State.Status == "running"` for up to
   `MAPPING_CONTAINER_START_TIMEOUT_S = 8.0 s`.

Step 8's polling cadence is `MAPPING_DOCKER_INSPECT_POLL_S = 0.25 s`.
Failure at any step transitions to Failed; the tracker stays stopped
(operator restarts via System tab per L2).

### 12.3. Preview node design (D8)

The container's launch graph spawns a Python rclpy node
(`preview_node/preview_dumper.py`) that subscribes `/map`, throttles to
1 Hz, and atomic-writes `/maps/.preview/<MAP_NAME>.pgm` (tmp + fsync +
os.replace). `/maps/.preview/` is hidden from `maps.list_pairs` via the
leading-dot subdirectory + `MAPS_NAME_REGEX` first-char rule.

Pure encoder lives in `pgm_encoder.py` (numpy + stdlib) so unit tests
run hardware-free under `verify-no-hw.sh --quick`.

### 12.4. Singleton-ticker SSE broadcast (M4)

`/api/mapping/monitor/stream` is a singleton-ticker broadcast: ONE
asyncio task runs the per-second snapshot at any time, regardless of
subscriber count; per-subscriber `asyncio.Queue` fans out the same
`bytes` frame. Subprocess invocations (`docker stats` / `df` / `du`)
happen once per tick, not once per subscriber × tick. Self-terminates
when `container_state ∈ {no_active, exited}`.

Docker-only frame shape (S1 amendment): RPi5 host stats stay in the
existing `/api/system/resources/extended/stream`. The SPA's monitor
strip subscribes to BOTH streams in parallel.

### 12.5. Failure recovery (L11)

Four mitigated cases:

- **Image missing**: `POST /api/mapping/start` returns 412 with build
  instructions. Webctl never auto-builds.
- **Container crash mid-mapping**: webctl's status reconcile sees
  `inspect == None or "exited"` while state was Running → transitions
  to Failed with `error_detail="container_crashed"` and
  `journal_tail_available=true`. Partial PGM (if entrypoint trap
  ran) is preserved; the operator decides whether to keep it.
- **LiDAR USB unplug mid-mapping**: rplidar driver fails inside the
  container → container exits non-zero. Same code path as crash.
- **Tracker stop fails before mapping start**: 503 with explicit
  Korean error guiding the operator to the System tab.

### 12.6. systemd template + polkit

Unit: `godo-mapping@.service`, instance fixed to `active` (D4).
EnvironmentFile=`/run/godo/mapping/%i.env` (resolves to `active.env`)
written by webctl immediately before `systemctl start`. Restart=no
(failures surface as Failed, never silently retried).

Polkit rule (rule (c) in `49-godo-systemctl.rules`) grants ncenter
group `start`/`stop`/`restart` ONLY on `godo-mapping@active.service`
— scope explicitly excludes any other instance name (defence against
operator typos / curiosity that would spawn a second container).

Stop-timeout ordering invariant (M5):
`docker stop --time=10 < TimeoutStopSec=20s < webctl_timeout=25s` so
the entrypoint's `map_saver_cli` save (~2-5 s) completes before any
layer escalates to SIGKILL.

### 12.7. L14 lock-out

When `mapping.status().state ∈ {Starting, Running, Stopping}`, four
existing endpoints return 409 `mapping_active`:

- `POST /api/calibrate`
- `POST /api/live`
- `POST /api/map/edit`
- `POST /api/map/origin`

`POST /api/maps/<name>/activate` and `DELETE /api/maps/<name>` are
NOT blocked — operator may still browse / activate / delete *other*
maps while mapping is in progress. The new map being created is
special (filesystem write race) but doesn't exist at canonical path
until container exit, so no race with activate.

---

## 13. Map edit pipeline (issue#28)

The Map Edit pipeline (Coord-mode + Erase-mode Apply) is a webctl-side
mutation that produces a NEW map pair on disk and leaves the active
map untouched until the operator manually activates the new pair AND
restarts godo-tracker. Tracker C++ code is read-only on this path.

### 13.1. Pristine vs derived file model

Every map slot has a single immutable **pristine pair** plus zero or
more **derived pairs**:

```text
maps/
  ├─ studio_v1.pgm              ← pristine bitmap (immutable post-mapping)
  ├─ studio_v1.yaml             ← pristine metadata (immutable)
  ├─ studio_v1.20260504-103412-wallcal01.pgm    ← derived pair #1
  ├─ studio_v1.20260504-103412-wallcal01.yaml
  ├─ studio_v1.20260504-141055-tvshift.pgm      ← derived pair #2
  └─ studio_v1.20260504-141055-tvshift.yaml
```

Filename grammar (regex `DERIVED_NAME_REGEX` in
`godo-webctl/constants.py`):

```text
<base>.YYYYMMDD-HHMMSS-<memo>.{pgm,yaml}
       └─ second-resolution timestamp (Mode-A M5 lock — collision near-impossible
          with the asyncio.Lock serialising every Apply)
                       └─ memo: ^[A-Za-z0-9_-]+$, max 32 chars (Mode-A C7 + N3)
```

Why this shape — see
`.claude/memory/project_pristine_baseline_pattern.md`. Quality loss
is always exactly **1× resample** regardless of how many derivations
the operator has chained, because every Apply ALWAYS reads the
pristine baseline.

### 13.2. Coord-mode Apply — pick-anchored + delta-on-top (issue#30)

> **Supersedes the SUBTRACT semantic from PR #79 (issue#27) and PR #81
> (issue#28).** The operator's mental model — "맵을 새로 정렬했으니
> origin은 (0, 0, 0°)이 되어야 한다" — surfaced in twenty-third-session
> opening discussion and is now the operator-locked behavior. SSOT:
> `/doc/issue30_yaml_normalization_design_analysis.md` +
> `.claude/memory/project_pick_anchored_yaml_normalization_locked.md`.

Per Apply, the operator picks a point on the canvas (the
**picked-world** coord) AND optionally types a numeric delta on top.
The picked point — possibly nudged by the typed delta — becomes world
**(0, 0)** in the new (derived) frame, and the derived YAML's yaw is
**0**:

```text
# Inputs
picked_world  = (canvas-clicked world coord at time of click)
typed_delta   = (x_m, y_m, theta_deg)  # 0 / empty = no further nudge
parent_cum    = previous derived's `cumulative_from_pristine` (identity for PICK#1)

# Compose this Apply's cumulative against pristine
cum.translate = picked_world − R(-θ_active)·typed_delta_xy
cum.rotate    = wrap(parent_cum.rotate + typed_theta)         # in (-180, 180]

# Bitmap pivot (pristine-frame pixel coord) — yaw-aware
i_p, j_p_top  = pristine_world_to_pixel(cum.translate, ox_p, oy_p, oθ_p, W_p, H_p, res)

# Off-center bbox of pristine corners after rotating by -θ around (i_p, j_p_top)
W_d, H_d, x_min, y_min = off_center_bbox(W_p, H_p, i_p, j_p_top, -θ)
i_p_new = i_p     - x_min
j_p_new = j_p_top - y_min

# Derived YAML origin: world (0, 0) lands at (i_p_new, j_p_new) in derived bitmap
new_origin_x_m   = -i_p_new · res
new_origin_y_m   = -((H_d - 1) - j_p_new) · res
new_origin_yaw_deg = 0.0
```

Cumulative tracking lives in a per-derived sidecar JSON file (see
§13.5 below). Every Apply ALWAYS reads pristine and applies the
composed cumulative — **image quality stays at 1× resample regardless
of cascade depth**, preserving
`.claude/memory/project_pristine_baseline_pattern.md`.

**Q1 lock (informational pristine yaw)**: pristine YAML yaw `oθ_p`
MAY be non-zero (e.g. test_v4 has 1.604 rad). It enters
`pristine_world_to_pixel` for the world↔pixel transform, but
`cumulative.rotate_deg` accumulates ONLY the operator's typed θ —
NOT pristine yaw — so the operator's mental cumulative matches the
JSON exactly.

**Q2 lock (delta-on-top UX)**: SPA input boxes for x_m / y_m / θ
default placeholder `0` / empty meaning "no further nudge". The XY
click on the canvas captures `picked_world_*` into INTERNAL state and
does NOT pre-fill the input boxes. The operator's typed values are
the delta on top.

**C-2.1 lock (algebra)**: `cumulative.translate = picked_world −
R(-θ_active)·typed_delta`. With `θ_active = 0` and `typed_delta = 0`,
`cumulative.translate = picked_world` so the picked point lands at
derived world (0, 0). With `typed_delta ≠ 0`, the picked-world is
shifted by `typed_delta` (in the active-at-pick frame) before
becoming the new origin.

The YAML yaw normalization aligns naturally with AMCL's
yaw-blind likelihood-field cell mapping
(`.claude/memory/project_amcl_yaw_metadata_only.md`): `dyaw =
current.yaw_deg − 0 = current.yaw_deg`, so the operator's FreeD-output
dyaw reads cleanly in the new frame with no hidden divergence.

Wire shape (POST `/api/map/edit/coord` body — issue#30):

```json
{
  "x_m":              0.0,        // typed delta (0 = no nudge)
  "y_m":              0.0,
  "theta_deg":        0.0,        // optional
  "picked_world_x_m": 5.0,        // canvas-clicked world coord (optional;
  "picked_world_y_m": 0.0,        // omission triggers legacy fallback +
                                  // X-GODO-Deprecation: picked_world_missing)
  "memo":             "wallcal01"
}
```

### 13.3. Resample (Lanczos-3 → BICUBIC)

Spec calls for **Lanczos-3** but Pillow's `Image.rotate()` does NOT
accept `LANCZOS` as a resampling kernel — it rejects with
`ValueError`. The implementation uses **BICUBIC** as the second-best
quality kernel, with a 3-class re-threshold pass to keep occupancy
semantics intact:

```text
free      = >= 254 (white)
occupied  = == 0   (black)
unknown   = otherwise → 205 (mid-grey)
```

Constants in `godo-webctl/constants.py`:
`MAP_ROTATE_THRESH_FREE = 254`,
`MAP_ROTATE_THRESH_OCC  = 0`,
`MAP_ROTATE_THRESH_UNK  = 205`. The 3-class re-threshold is applied
**after** BICUBIC resampling so anti-aliased edge pixels do not
introduce phantom intermediate occupancy values.

Auto-canvas-expand keeps the entire rotated bitmap inside the new
canvas. Hard cap `MAP_ROTATE_MAX_CANVAS_PX = 4096` rejects runaway
rotations with a 422 + SSE `rejected{reason: canvas_too_large}` frame.

### 13.4. Atomic triple-write protocol (issue#30 — C3-triple)

Three-file atomicity is critical: a partial write that lands a new
PGM without a matching YAML (or sidecar JSON) leaves the maps
directory in a state where activation chooses an inconsistent triple.
Sequence (implemented in `godo-webctl/src/godo_webctl/map_transform.py
::_atomic_write_triple`):

```text
1. Write PGM to <derived>.pgm.tmp + fsync
2. Write YAML to <derived>.yaml.tmp + fsync
3. Write sidecar JSON to <derived>.sidecar.json.tmp + fsync
4. fsync(parent_dir)
5. rename <derived>.pgm.tmp → <derived>.pgm
6. rename <derived>.yaml.tmp → <derived>.yaml
7. rename <derived>.sidecar.json.tmp → <derived>.sidecar.json
8. fsync(parent_dir)

Cascade rollback on rename failure:
- YAML failure (between 5 and 6): unlink <derived>.pgm
- JSON failure (between 6 and 7): unlink <derived>.pgm AND <derived>.yaml
```

Sidecar is written **last** so its absence is recoverable: a missing
sidecar with both PGM + YAML present surfaces as `kind="synthesized"`
or `kind="auto_migrated_pre_issue30"` via the recovery sweep (see
§13.5). The sidecar carries integrity SHAs over the on-disk PGM +
YAML bytes so an out-of-band hand-edit between Applies can be detected
and surfaced as `HTTP 422 sidecar_sha_mismatch`.

Stale `.tmp` files from a power loss or kill mid-Apply are swept on
every `list_pairs_grouped()` invocation AND at lifespan startup.
Tested by `tests/test_map_transform.py::test_yaml_failure_unlinks_pgm`,
`test_orphan_tmp_swept_idempotent`, and the integration tests
`tests/test_app_integration.py::test_apply_pipeline_writes_c3_triple_atomically`
+ `test_apply_pipeline_yaml_failure_unlinks_pgm_atomically`.

### 13.5. Sidecar SSOT (issue#30 — `godo.map.sidecar.v1`)

Every derived map carries a peer JSON file
`<derived_base>.YYYYMMDD-HHMMSS-<memo>.sidecar.json` reified by
`godo_webctl.sidecar.Sidecar`. Schema literal:
`"godo.map.sidecar.v1"`. Sole owner of the schema is
`godo-webctl/src/godo_webctl/sidecar.py` — no other module reads or
writes `*.sidecar.json` directly.

Body shape (top-level keys):

```text
schema:                       godo.map.sidecar.v1
kind:                         "derived" | "synthesized"
source.pristine_pgm:          <pristine PGM filename>
source.pristine_yaml:         <pristine YAML filename>
lineage.generation:           int (-1 = unknown)
lineage.parents:              [<base>, <derived_1>, …]   # pristine-first
lineage.kind:                 "operator_apply" | "synthesized" | "auto_migrated_pre_issue30"
cumulative_from_pristine.translate_x_m:  float (pristine-frame world coord
                                                that lands at derived world (0,0))
cumulative_from_pristine.translate_y_m:  float
cumulative_from_pristine.rotate_deg:     float (typed θ accumulation only;
                                                 NOT including pristine yaw — Q1 lock)
this_step:                    {delta_*, picked_world_*} — null for synthesized
result_yaml_origin:           {x_m, y_m, yaw_deg}
result_canvas:                {width_px, height_px}
integrity.pgm_sha256:         hex over derived PGM bytes
integrity.yaml_sha256:        hex over derived YAML bytes
created.iso_kst:              "YYYY-MM-DDTHH:MM:SS+09:00"
created.memo:                 operator-supplied memo
created.reason:               "operator_apply" | etc.
```

Recovery sweep (`sidecar.recovery_sweep`) runs at **lifespan startup**
AND **opportunistically on every `/api/maps`** call:

| Pre-state | Action |
|---|---|
| PGM + YAML + sidecar | no-op |
| PGM + YAML + no sidecar, derived filename pattern | synthesize `("derived", "auto_migrated_pre_issue30", 1)` |
| PGM + YAML + no sidecar, non-derived filename | synthesize `("synthesized", "synthesized", -1)` |
| PGM only | unlink |
| YAML only | unlink |

Pinned by `tests/test_sidecar.py::test_recovery_sweep_*` and the
integration test
`tests/test_app_integration.py::test_pr81_legacy_derived_auto_migration`.

Wire access — `GET /api/maps/{name}/sidecar` returns:

```json
{ "name": "<name>", "sidecar": SidecarV1 | null }
```

`null` when the pair exists but no sidecar is on disk yet (legacy /
pristine map). Frontend mirror lives in
`godo-frontend/src/lib/protocol.ts::SidecarV1`/`SidecarResponse` and
is consumed by `LineageModal.svelte`.

### 13.5. SSE progress channel

A single in-process broadcaster (`godo-webctl/src/godo_webctl/sse.py`)
emits per-frame JSON objects on `/api/map/edit/progress`:

```json
{"phase": "starting" | "yaml_rewrite" | "rotate" | "restart_pending" | "done" | "rejected",
 "progress": 0.0..1.0,
 "request_id": "<hex16>",
 "reason": "<error short-tag>"      // only on phase=rejected
}
```

Every frame carries `request_id` (hex16, server-issued per Apply
session). The SPA captures `request_id` from the synchronous Apply
response body and DROPS frames whose `request_id` does not match —
prevents stale-tab leakage (Mode-B CR3 fix in
`godo-frontend/src/components/ApplyMemoModal.svelte`,
pinned by `tests/unit/ApplyMemoModal.test.ts`).

Heartbeat every `SSE_PROGRESS_HEARTBEAT_S = 5` keeps proxies from
killing the keep-alive.

### 13.6. Concurrency guard (asyncio.Lock)

`/api/map/edit/coord` and `/api/map/edit/erase` share a single
module-scoped `asyncio.Lock` (`map_edit_pipeline_lock` in
`godo-webctl/src/godo_webctl/app.py`). Two concurrent POSTs (e.g.,
two SPA tabs) serialise; the second waits for the first to commit
or fail. Combined with the second-resolution timestamp this makes
filename collisions practically impossible.

### 13.7. Restart-pending sentinel

Pipeline does NOT restart godo-tracker. Final phase touches
`/run/godo/restart_pending` (path from `cfg.restart_pending_path`).
The SPA System tab surfaces a banner; the operator clicks Restart
when convenient. This preserves the project rule "every cold-path
update is operator-initiated."

### 13.8. Yaw frame SSOT — YAML `origin[2]` is the SOLE source of truth

issue#28 made the active map's YAML `origin[2]` (parsed into
`OccupancyGrid::origin_yaw_deg` in `occupancy_grid.cpp`) the SOLE
source of truth for the AMCL frame yaw. The Tier-2 config field
`amcl.origin_yaw_deg` was deprecated for one release and **hard-removed
in issue#28.1 (2026-W19)**: field, schema row, TOML/env/CLI readers,
defaults entry, and apply_get/apply_set rows all deleted. Existing
`/var/lib/godo/tracker.toml` files that still carry the key must
have it stripped before installing the issue#28.1+ binary
(`sudo sed -i '/^amcl\.origin_yaw_deg/d' /var/lib/godo/tracker.toml`)
because the schema validator rejects unknown keys.

Pinned by `production/RPi5/tests/test_cold_writer_offset_invariant.cpp::
OffsetComputedAgainstGridYaw_NotConfigField` — asymmetric values
(grid=10°, hypothetical fallback=0°) catch any regression that
re-anchors the offset to a 0-degree path that ignores the grid.

---

## 14. Change log

- **2026-05-04 (issue#28, B-MAPEDIT-3 twenty-second-session close — HIL fix retrospective)**: §13 Map edit pipeline retains its body (still accurate post-HIL), but two important runtime details surfaced during operator HIL that future readers should know:
  - **`grid.origin_yaw_deg` is NOT consumed by `evaluate_scan`**. AMCL particle filter operates as if origin_yaw = 0; the YAML yaw is a static OUTPUT-stage offset (`compute_offset` subtracts it from `pose.yaw` to produce FreeD output dyaw) plus an informational tripwire input. This is why Option B (bake-into-bitmap) is the only correct path for yaw correction — Option A (metadata-only) would change output dyaw without moving the likelihood field, leaving walls at the wrong world angles.
  - **Bitmap rotation sign**: `map_rotate.py` calls `Image.rotate(-typed_yaw_deg)` so the operator's typed +θ rotates the world frame (not the bitmap content) by +θ CCW. Equivalently the bitmap content moves -θ in PIL terms (visually CW), aligning the picked direction with the new horizontal +x. Pinned by `test_rotation_direction_negates_typed_yaw`.
  - **YAML SUBTRACT and bitmap rotation are mutually exclusive**: pipeline now passes `theta_deg=None` to `apply_origin_edit_in_memory` when bitmap rotation is the source-of-truth (Option B). Pinned by `test_post_map_edit_coord_with_theta_does_not_double_count`.
- **2026-05-04 (issue#28, B-MAPEDIT-3 cascade close)**: new §13 Map edit pipeline added (pristine vs derived file model, translate-then-rotate composition, Lanczos-3 intent + BICUBIC implementation + 3-class re-threshold, atomic pair-write protocol with PGM-rollback on YAML failure, SSE progress channel with `request_id`-tagged frames, `asyncio.Lock` concurrency guard, restart-pending sentinel handoff to operator, `cfg.amcl_origin_yaw_deg` deprecation in favour of YAML `origin[2]` SSOT). §13 Change log renumbered to §14. Cross-references new memory files `project_pristine_baseline_pattern.md` and `feedback_overlay_toggle_unification.md`.
- **2026-04-24 (v3.1, FreeD transport pinned)**: FreeD transport is **hardware UART** on the RPi 5, not USB-CDC. Crane RS-232 → YL-128 (MAX3232) → PL011 UART0 (GPIO 14/15, 40-pin header). §6.3 gains two ops-checklist items: (a) YL-128 VCC MUST come from the Pi's 3V3 rail so both sides of the TTL link are 3.3 V — an Arduino R4 build previously suffered intermittent framing errors when resistor dividers were added "for safety"; the verified fix is identical 3.3 V rails with no divider; (b) `/boot/firmware/config.txt` needs `enable_uart=1` + `dtparam=uart0=on`, and `cmdline.txt` must drop `console=serial0,115200` so the kernel serial console does not own `/dev/ttyAMA0`. §11.2 default `FREED_PORT` updated from `/dev/ttyACM0` to `/dev/ttyAMA0`. A new Phase 4-1 doc deliverable `production/RPi5/doc/freed_wiring.md` captures the pin-by-pin wiring, config-file diff, and verification procedure.
- **2026-04-24 (v3, post Mode-A review)**: five blocker-level findings addressed: (1) `std::atomic<T>` replaced with an explicit `Seqlock<T>` template (§6.1.1) — `Offset = {dx, dy, dyaw}` and `FreedPacket[29]` are both too wide for lock-free atomics on Cortex-A76 without LSE2. Multi-reader permitted (Thread D + webctl). (2) Smoother edge detection switched from float equality to seqlock **generation counter** (integer, exact), and ramp completion snaps `live ← target` by value-copy at `frac ≥ 1.0` (§6.4.2). (3) Phase 4-3 scope cut to three endpoints (`/health`, `/map/backup`, `/calibrate`); map editor + full React frontend moved to Phase 4.5 (§7). (4) Trigger IPC primitive unified across CLAUDE.md / §1 / §6.1.3 / §7 as `std::atomic<bool> calibrate_requested` (idempotent, queue upgrade path documented). (5) AMCL divergence clamp now compares `target_new` against `last_written` (not `live`), and explicit `calibrate_requested` bypasses the clamp — eliminates the kidnapped-recovery deadlock (§8). Additional: §6.1.2 time source pinned to `CLOCK_MONOTONIC`; §6.2 moves `mlockall` to `main()` before thread spawn, `g_running` is `std::atomic<bool>`, `clock_nanosleep` loops on `EINTR`, signals blocked process-wide; §6.3 IRQ list marked TBD-measure in Phase 4-1; §6.4.1 new cold-path deadband filter (10 mm / 0.1° default) suppresses sub-noise AMCL jitter; §6.5 removes the bogus "physical crane limit" comment, adds precondition docs + endpoint-identity / fixed-point unit tests; §11 new Runtime configuration section with two-tier constants (constexpr invariants + TOML-backed tunables) and reload classes (hot / restart / recalibrate) for future frontend editing; §12 renumbered from §11. Magic-number ban added as a code-review rule.
- **2026-04-24**: §1 key-decisions table gains 5 rows (hot/cold split, smoother, yaw wrap, trigger UX, web plane). §6 restructured: §6.1 hot/cold boundary, §6.2 thread D skeleton (now reads target via smoother), §6.3 ops checklist, §6.4 linear-ramp smoother with A/B/C comparison and acceptance tests, §6.5 yaw wrap at two named sites with pinned unit tests. §7 Phase 4 split into 4-1/4-2/4-3. §8 gains 3 new failure rows (AMCL divergence, webctl crash, pan wrap). Q6 (trigger UX) resolved. RPi 5 hardware bring-up proven: 500-frame capture × 3 iterations, 10.02 Hz steady, byte-identical Python parity. Smoother method A chosen over EMA / rate-limit on predictability grounds. `godo-webctl` scoped as a separate FastAPI process, never inside the RT binary.
- **2026-04-21 (later)**: added §10 — Phase 1 Python prototype tools, two-backend (SDK-wrapper vs Non-SDK) framework, library plan, dump format, and test sequence. SDK-wrapper uses `pyrplidar` with explicit caveat; official-SDK `ultra_simple` three-way comparison deferred as a Phase 1 follow-up. scikit-learn removed (threshold check suffices). CSV write path pinned to stdlib `csv.writer`. Session-txt log gains `csv_sha256` / `csv_byte_count`.
- **2026-04-21**: initial version. Decisions locked: yaw Approach B, O3 → O4 hybrid, Docker-based map building, RPi 5 FreeD integration, C++ production.
