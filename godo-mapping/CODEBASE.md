# godo-mapping — codebase map

## Scope

Phase 4 Track A. Docker-based SLAM toolchain (`slam_toolbox` async +
`rplidar_ros` + `nav2_map_server`) that produces 2D occupancy-grid maps
consumed by `production/RPi5/src/localization/occupancy_grid.cpp::load_map`.
Operator-driven, hand-carried mapping; no autonomous component.

Greenfield: no edits to `production/RPi5/`, `godo-webctl/`,
`XR_FreeD_to_UDP/`, or any SSOT doc under `doc/`.

## Directory layout

```text
godo-mapping/
├─ Dockerfile                       # F10 layered: FROM ros:jazzy-ros-base
├─ launch/
│   └─ map.launch.py                # rf2o + rplidar_c1 + async_slam_toolbox_node
├─ config/
│   ├─ rf2o.yaml                    # rf2o_laser_odometry parameters (Tier-2)
│   └─ slam_toolbox_async.yaml      # base_frame=laser, save_map_timeout=10.0
├─ entrypoint.sh                    # PID-1 in container; SIGINT/SIGTERM trap
├─ scripts/
│   ├─ run-mapping.sh               # host-side docker-run wrapper + pre-flights
│   ├─ verify-no-hw.sh              # --quick (default) / --full
│   ├─ _uds_bridge.py               # Track B Option C SSOT (UdsBridge)
│   ├─ repeatability.py             # Track B Phase 1 measurement harness
│   ├─ pose_watch.py                # Track B Option C live-pose watch
│   ├─ conftest.py                  # pytest fixtures + test-time sys.path inject
│   ├─ test_repeatability.py        # 13 cases (10 behavioural + 3 pins)
│   └─ test_pose_watch.py           # 4 cases (happy / reconnect / SIGINT / json)
├─ tests/
│   └─ test_entrypoint_trap.sh      # bare-bash trap mock (no ROS, no Docker)
├─ maps/
│   ├─ .gitkeep                     # keep dir present
│   └─ .gitignore                   # *.pgm + *.yaml (no negations per F4)
├─ README.md
└─ CODEBASE.md                      # ← this file
```

## Module map and responsibilities

| Module | Depends on | Responsibility |
| --- | --- | --- |
| `Dockerfile` | `ros:jazzy-ros-base` | Defines the SLAM container image; layer order tuned for build cache (apt before COPY). Two colcon overlays into `/opt/ros_overlay`: rplidar_ros (Slamtec ros2 branch) + rf2o_laser_odometry (MAPIRlab ros2 branch, SHA-pinned, package.xml format-3 sed patch). |
| `launch/map.launch.py` | `rf2o_laser_odometry`, `rplidar_ros`, `slam_toolbox` | Composes `rf2o_laser_odometry_node` + inline rplidar_node (C1) + `async_slam_toolbox_node`. No `static_transform_publisher` (invariant (h)). |
| `config/rf2o.yaml` | `rf2o_laser_odometry` | Tier-2 rf2o parameters; top-level key `rf2o_laser_odometry:` MUST match launch Node `name=` (see invariant (h)). |
| `config/slam_toolbox_async.yaml` | `slam_toolbox` | Tier-2 SLAM parameters with inline rationale on every numeric literal (F3 carve-out). Explicit `minimum_travel_distance`/`minimum_travel_heading` keys document reliance on the rf2o-published odom source. |
| `rf2o_laser_odometry` (runtime, not file) | `/scan`, `tf2_ros` | Scan-to-scan registration; publishes `odom -> laser` TF + `/odom_rf2o` topic. Replaces the static identity TF (invariant (h)). |
| `entrypoint.sh` | bash, `ros2 launch`, `map_saver_cli` | Container PID-1; traps INT/TERM, invokes `${MAP_SAVER_CMD}`, exits 0. |
| `scripts/run-mapping.sh` | bash, `docker` | Host-side wrapper; pre-flight checks (collision, stale container, LiDAR present, image present) with pinned English error messages. |
| `scripts/verify-no-hw.sh` | bash, `python3`, optionally `docker` | `--quick` (lint + ast + test) and `--full` (build + image smoke). |
| `tests/test_entrypoint_trap.sh` | bash | Mock-driven trap test; no ROS, no Docker. |
| `scripts/_uds_bridge.py` | stdlib | **Track B Option C SSOT** for the Python UDS client (`UdsBridge`). Imported by `repeatability.py` AND `pose_watch.py` — never duplicated inline. Pure stdlib, zero `godo_webctl` runtime import. |
| `scripts/repeatability.py` | `_uds_bridge` | **Track B Phase 1** measurement instrument; drives `godo_tracker_rt` through N OneShot calibrations and emits CSV + summary. CLI surface; 9 exit codes. |
| `scripts/pose_watch.py` | `_uds_bridge` | **Track B Option C** continuous live-pose watch for cmd-window monitoring during shows. Reconnect-loop on tracker death; SIGINT clean exit. |
| `scripts/conftest.py` | pytest, stdlib | Test-only shared fixtures (`fake_uds_server`); injects `godo-webctl/src` into `sys.path` for the cross-package SSOT pin. |
| `scripts/test_repeatability.py` | pytest, conftest | 13 cases (10 behavioural + 3 structural pins). |
| `scripts/test_pose_watch.py` | pytest, conftest | 4 cases (happy / reconnect / SIGINT / json). |

## Dependency graph

```text
Host                                Container (godo-mapping:dev)
─────────                            ───────────────────────────
run-mapping.sh ─── docker run ───►   entrypoint.sh
verify-no-hw.sh ── docker build ──► (Dockerfile) ──► launch/ + config/
test_entrypoint_trap.sh ──── (no Docker, bash-only) ──►  entrypoint.sh
                                                          │
                                                          ├─ ros2 launch map.launch.py
                                                          │       ├─ rplidar_ros/rplidar_node (C1, /scan)
                                                          │       ├─ rf2o_laser_odometry_node
                                                          │       │   (params from config/rf2o.yaml)
                                                          │       │   /scan ──► odom→laser TF + /odom_rf2o
                                                          │       └─ slam_toolbox/async_slam_toolbox_node
                                                          │           (params from config/slam_toolbox_async.yaml)
                                                          │           /scan + odom→laser TF ──► /map + map→odom TF
                                                          │
                                                          └─ on signal: ${MAP_SAVER_CMD}
                                                                          │
                                                                          ▼
                                                                /maps/<MAP_NAME>.{pgm,yaml}
                                                                          │
                                                                          ▼
                                                                host bind mount: ./maps/
                                                                          │
                                                          (operator copy) ▼
                                                                /etc/godo/maps/<name>.{pgm,yaml}
                                                                          │
                                                                          ▼
                                              production/RPi5: occupancy_grid.cpp::load_map
```

No back-edges. Container → tracker is asynchronous via the saved file pair;
no live IPC.

## Invariants

Invariants (a)–(e) are pinned per Track A's plan v2 finding F13 and
reproduced verbatim here. (f) and (g) are added by Track B per its
plan v2 (Option C).

### (a) ROS pipeline isolation

All ROS dependencies live inside the Docker image. The host RPi 5 has zero
ROS install; `production/RPi5/` and `godo-webctl/` have zero ROS imports.
Verified by `grep -rn 'rclcpp\|ament' production/RPi5/src/` returning zero
hits as of commit 77d7863. The tracker is a non-ROS C++ binary; ROS 2 DDS
multicast on the host network plane has no peer in the tracker process.
`--network=host` for ROS DDS is therefore collision-free.

### (b) Map-format SSOT

`maps/*.{pgm,yaml}` MUST be loadable by
`production/RPi5/src/localization/occupancy_grid.cpp::load_map`. The
required + warn_accept key sets at lines 148-154 are the single source of
truth. If `nav2_map_server map_saver_cli` emits a key outside that union,
the resolution path is a follow-up RPi5 commit extending `warn_accept`
(path (a) per F11) — never YAML post-processing in this stack.

### (c) Single mapping container at a time

The container name is `godo-mapping` (fixed). `run-mapping.sh` refuses to
start if `docker ps -a --filter name=^godo-mapping$ --format '{{.Names}}'`
returns a hit, with the F6 pinned message:

```text
godo-mapping: container 'godo-mapping' is already running. Stop it first: docker stop godo-mapping
```

### (d) `/dev/ttyUSB0` is not hardcoded

`run-mapping.sh` reads `LIDAR_DEV="${LIDAR_DEV:-/dev/ttyUSB0}"` and passes
`--device="${LIDAR_DEV}"` to `docker run`. Operators on hosts where the
LiDAR enumerates as `/dev/ttyUSB1` etc. override via env-var without
editing source.

### (e) Hardware-free build/lint, hardware-required run

`scripts/verify-no-hw.sh` (`--quick` default, `--full` opt-in) passes
without LiDAR and without Docker daemon (`--quick`) or with Docker daemon
but no LiDAR (`--full`). Only `scripts/run-mapping.sh` requires the
physical LiDAR + USB CP2102 dongle.

### (f) Track B harness has zero `godo_webctl` runtime dependency

The `LAST_POSE_FIELDS` SSOT is enforced at **test time** via
`scripts/conftest.py` `sys.path` injection (`godo-webctl/src` is
prepended only inside the test process). The runtime modules
(`scripts/_uds_bridge.py`, `scripts/repeatability.py`,
`scripts/pose_watch.py`) MUST NOT import `godo_webctl` — pinned by
`test_repeatability.py::test_no_godo_webctl_runtime_import` which
spawns a fresh subprocess and asserts no `godo_webctl*` module ends
up in `sys.modules` after the three runtime imports.

The cross-language SSOT chain is:

```text
production/RPi5/src/uds/json_mini.cpp::format_ok_pose  (canonical)
   ↑                                                    ↑
   │ regex                                              │ regex
   │                                                    │
godo-webctl/src/godo_webctl/protocol.py                godo-mapping/scripts/
::LAST_POSE_FIELDS                                     _uds_bridge.py::
   ↑                                                   _LAST_POSE_FIELDS_LOCAL
   │                                                    ↑
   └─ test_protocol.py drift pin              test_repeatability.py
                                              ::test_local_fields_match_protocol_mirror
                                              (test-time import via conftest)
```

### (g) `_uds_bridge.py` is the single Python UDS client (Option C)

Any Python script under `scripts/` that talks to the tracker UDS MUST
`from _uds_bridge import UdsBridge` — never copy-paste the class
inline. Future diagnostic tools (e.g., a hypothetical
`pose_dump_to_grafana.py`) extend this pattern.

### (h) `odom→laser` TF is rf2o-published, never static

The TF chain `map→odom→laser` requires both edges to be **dynamic and motion-derived** for slam_toolbox's Karto scan-match gate (`minimum_travel_distance: 0.5`, `minimum_travel_heading: 0.5`) to fire on real scan-pose deltas. A static `tf2_ros static_transform_publisher odom→laser` (the 2026-04-28 hotfix that landed in `map.launch.py:44-50`) reports zero motion forever and causes slam_toolbox to integrate exactly one scan and ignore every subsequent one — observed empirically as the 107-occupied-pixel artifact at `maps/0429_2.pgm`.

The mapping launch graph MUST publish `odom→laser` from a scan-derived odometry node:

- Plan A (current): `rf2o_laser_odometry_node` driven by `config/rf2o.yaml`.
- Plan B (sketch): `ros2_laser_scan_matcher` from AlexKaravaev's port.
- Plan C (config-only fallback): no external odom node; instead set `minimum_travel_distance: 0.0` and `minimum_travel_heading: 0.0` in `config/slam_toolbox_async.yaml` and accept Karto-only scan-match risk for symmetric / sparse rooms.

A reviewer or maintainer who removes the rf2o (or B/C equivalent) from the launch file MUST replace it with one of the other two paths in the same change. Re-introducing a static identity TF is a hard invariant violation.

**Verification**: `grep -n "static_transform_publisher" godo-mapping/launch/map.launch.py` must return zero hits as of the post-fix commit.

### (i) Preview node single-writer + atomic PGM rename (issue#14)

`preview_node/preview_dumper.py` is the SOLE writer to
`/maps/.preview/<MAP_NAME>.pgm`. The node:

- Subscribes `/map` (`nav_msgs/msg/OccupancyGrid`) at QoS depth 1.
- Throttles to `PREVIEW_DUMP_HZ = 1.0` (1 Hz; min interval 1e9 ns).
- Encodes via the pure-stdlib `pgm_encoder.encode_pgm_p5` +
  `occupancy_to_pixels` — Y-flipped to top-down PGM, pixel mapping
  `unknown=205, free=254, occupied (≥50%)=0`.
- Atomic write: open `.pgm.tmp` → `fsync` → `os.replace(tmp, target)`.
  webctl's `/api/mapping/preview` therefore never observes a half-
  written file.

The pure encoder lives in `pgm_encoder.py` (no rclpy import) so
`tests/test_preview_dumper_pgm_encoder.py` runs hardware-free under
`verify-no-hw.sh --quick`.

**Single-instance enforcement** is inherited from four parent layers
(`docker run` → `entrypoint.sh` → `ros2 launch` → the rclpy node) so
this node does NOT add a fifth pidfile per CLAUDE.md §6 single-
instance discipline interpretation: pidfiles are mandatory only for
top-level long-running processes, not for transient children whose
lifetime is bounded by their parent.

### (j) LIDAR_DEV env-var SSOT chain (issue#14)

The chain from operator to running rplidar driver is:

```text
operator's tracker.toml [serial] lidar_port  (SSOT — tracker schema row,
   ↓                                          config_schema.hpp:120)
webctl mapping._resolve_lidar_port()         (read via
   ↓                                          webctl_toml.read_tracker_serial_section)
/run/godo/mapping/active.env (LIDAR_DEV=…)   (atomic write)
   ↓
systemd EnvironmentFile= directive
   ↓
docker run --device=${LIDAR_DEV}
   ↓
container env LIDAR_DEV
   ↓
launch/map.launch.py rplidar Node serial_port=os.environ.get('LIDAR_DEV', '/dev/ttyUSB0')
```

A change at the SSOT (operator edits `tracker.toml`) propagates through
the chain on the next mapping start without any container rebuild.
The fallback default `/dev/ttyUSB0` matches the tracker schema row
default, so a missing-file or missing-section path resolves to the
same value the tracker would use.

**Operator-locked SSOT discipline**: webctl reads tracker-owned keys
but does NOT add them to `WebctlSection` (PR #63 lock-in). When two
stacks own different facets of the same concept, the SSOT lives where
the value originates.

### (k) SLAMTEC angle convention via `flip_x_axis: True` parameter (PR #84)

The upstream `Slamtec/rplidar_ros` driver's `src/rplidar_node.cpp:247-251`
publishes `/scan` with `angle_min/max = M_PI - angle_in/out`. Per
SLAMTEC's own datasheet (`doc/RPLIDAR/sources/SLAMTEC_rplidar_datasheet_C1_v1.2_en.pdf`
page 11, Figure 2-4) the correct REP-103 conversion is `ψ = -θ` (single
negation handles both left-handed → right-handed handedness flip and
CW → CCW direction). The upstream `M_PI - θ` adds an extra 180°
rotation, mapping every beam endpoint to the origin-symmetric
position. HIL on 2026-05-05 KST (`test_180check_left_obstacle`)
verified the fingerprint: a 1 m wall physically in front of the LIDAR
appeared at PGM `-x_world` (origin point reflection).

**Operational fix (chosen 2026-05-05 KST after the sed-only fix broke
rf2o)**:

The `Dockerfile` `RUN` block uses the upstream driver as-is (no
source patch), pinned to commit `24cc9b6` for reproducibility. The
180° correction is applied via the existing `flip_x_axis: True`
runtime parameter in `launch/map.launch.py`. This parameter shifts
`apply_index` by `scan_midpoint` (= n/2) in the publish_scan data
fill loop:

```cpp
if (flip_X_axis) {
    if (apply_index >= scan_midpoint)
        apply_index = apply_index - scan_midpoint;
    else
        apply_index = apply_index + scan_midpoint;
}
```

Composed with `M_PI - θ`, this gives physically-correct beam
endpoints AND keeps the published angle range in the conventional
`[-π, π]` band that rf2o + slam_toolbox internal logic expects.

**Why the sed-only path was reverted**: an earlier sed patch replaced
`M_PI - angle_min/max` with `-angle_min/max` directly. This produced
physically-correct beam endpoints but shifted the published angle
range to `[-2π, 0]`. The shifted range broke rf2o's scan-to-scan
registration logic — operator HIL observed "지도가 잔상처럼 남아있어
… 움직이면 계속 새로 그리는 듯해" (ghosting / failure to recognise
the same wall across consecutive scans). Reverting to upstream +
flip_x_axis preserves the conventional range AND the orientation.

**Invariants the operator + reviewer must keep**:

1. `git checkout 24cc9b6dea97e045bda1408eaa867ce730fd3fc3` — keep
   the commit pin for reproducibility.
2. The rplidar Node parameter block in `launch/map.launch.py` MUST
   include `'flip_x_axis': True`. Removing it re-introduces the
   180° physical-orientation bug.
3. Do NOT re-introduce the `M_PI - angle → -angle` sed patch on top
   of `flip_x_axis: True`; the two compose into a different
   transformation (visual mirror) and double-flip the orientation.

A reviewer adding a `tf_static` workaround instead must explain why
the parameter-based composition is no longer preferred.

Live tracker path is unaffected: `production/RPi5/src/lidar/lidar_source_rplidar.cpp`
uses the vendored `rplidar_sdk` directly and `production/RPi5/src/localization/scan_ops.cpp:53`
applies the correct `-angle` negation. See `.claude/memory/project_rplidar_cw_vs_ros_ccw.md`
for the full 5-path angle-convention SSOT.

## Phase 4.5 follow-up candidates

- Pin `Dockerfile` `FROM ros:jazzy-ros-base` by image digest after the first
  successful production build to harden reproducibility against upstream
  tag drift.
- Track the `nav2_map_server map_saver_cli` Jazzy YAML emission against
  `occupancy_grid.cpp:148-154`; if any key drifts in a future ROS update,
  extend `warn_accept` (path (a)) rather than post-process.
- Add map editor round-trip checklist for the Phase 4.5 webctl map editor
  (paint over moved fixtures → save → reload by tracker → verify pose).
- I²C / direct-UART LiDAR variants (e.g., RPLIDAR S series) — generalize
  `LIDAR_DEV` to also accept a generic `LIDAR_LAUNCH` parameter so the
  upstream launch file can be swapped.
- Add a `docker compose` profile so the operator does not need to memorize
  `--network=host --device=... -v ...:/maps`. Optional convenience.
- Loop-closure parameters in `config/slam_toolbox_async.yaml` are upstream
  defaults; tune empirically against control-room-sized maps once we have a
  reproducibility baseline (Track B Phase 1 deliverable).

### Track B follow-up candidates (Phase 4.5+)

- Add `--out-format json` to `repeatability.py` for log-shipping pipelines
  (current CSV is the durable archive; JSON would be cheaper to ingest).
- Add a `mode_after` column to the CSV — captures `get_mode` at the
  end of each shot to detect mid-experiment Live toggles.
- Promote `pose_watch.py`'s 2 Hz polling to a streaming UDS subscription
  if Phase 4.5 introduces a server-push variant (current one-shot
  request/response is fine for 2 Hz but doesn't scale to 60 Hz).
- Statistical correlation between `xy_std_m` and the per-shot deviation
  from the session mean — would tell us if the AMCL-internal spread is
  a useful proxy for the harness-measured repeatability bound.
- Plotting (matplotlib / vega-lite / etc.) — currently the operator
  consumes the CSV in Excel or pandas. A small `plot_repeatability.py`
  companion could land in Phase 5 once the field-test demands it.

### Implementation-time discoveries

- `bash` background jobs of a non-interactive shell inherit `SIGINT=SIG_IGN`
  per POSIX; `trap` cannot re-enable a signal that was ignored at shell
  entry. The hardware-free trap test therefore sends `SIGTERM` instead of
  `SIGINT`. The production path (Docker forwarding SIGINT to PID 1) is
  unaffected because PID 1 in a container does not inherit `SIG_IGN`. The
  trap registers for both `INT TERM` so the production Ctrl+C path stays
  byte-exact.
- The trap sends `SIGTERM` (not `SIGINT`) to the foreground child for the
  same reason — `sleep infinity` started as a backgrounded child of a
  non-interactive shell ignores `SIGINT`. `ros2 launch` treats `SIGTERM`
  as a graceful shutdown of its launch graph.
- The trap tolerates a non-zero exit from `${MAP_SAVER_CMD}` (logs a
  warning, still `exit 0`) so a partial-map situation does not mask the
  operator's intentional Ctrl+C.

## Change log

### 2026-05-05 KST (afternoon) — PR #84 issue#30 Finding 2 v2: flip_x_axis composition

#### Changed

- `Dockerfile` — removed the `sed` patch, restored upstream driver
  source. Kept `git checkout 24cc9b6` commit pin for reproducibility.
- `launch/map.launch.py` — added `'flip_x_axis': True` to the rplidar
  Node parameters. This composes with the upstream `M_PI - angle`
  formula to produce physically-correct orientation while keeping
  the published angle range in conventional `[-π, π]` (which the
  earlier sed-only fix had shifted to `[-2π, 0]`, breaking rf2o
  scan-to-scan registration).

#### Updated

- Invariant `(k)` rewritten to describe the parameter-composition
  approach and the deletion-resistance rules (commit pin,
  `flip_x_axis: True`, no double-fix).

#### Why

Operator HIL on the morning's sed-only fix showed correct
single-frame orientation but BROKEN cumulative mapping: "지도가
잔상처럼 남아있어 … 움직이면 계속 새로 그리는 듯해". Diagnosed as
the unconventional `[-2π, 0]` published angle range breaking rf2o's
scan-to-scan registration. The upstream driver already exposes
`flip_x_axis` (a `n/2` shift in `apply_index`) which composes
exactly with `M_PI - angle` to give correct orientation in
conventional range. Container rebuild required after deploy.

### 2026-05-05 KST (morning) — PR #84 issue#30 Finding 2 v1: rplidar_ros sed patch (REVERTED)

#### Changed (later reverted, see "afternoon" entry above)

- `Dockerfile` (lines 46–90) — replaced `git clone --depth 1 --branch ros2`
  with `git clone` + `git checkout 24cc9b6dea97e045bda1408eaa867ce730fd3fc3`
  + `sed -i 's|M_PI - angle_max|-angle_max|g; s|M_PI - angle_min|-angle_min|g' src/rplidar_node.cpp`
  to fix the upstream `Slamtec/rplidar_ros` sign bug (extra 180° rotation
  on the published `/scan` topic).

#### Why reverted

The sed-only fix produced correct single-frame orientation but
shifted the published angle range to `[-2π, 0]` (out of conventional
`[-π, π]` bound). rf2o_laser_odometry's scan-to-scan registration
silently degraded — visible in cumulative mapping as wall-ghosting
during operator motion. See "afternoon" entry above for the
parameter-composition replacement that keeps both correct
orientation AND conventional range.

### 2026-05-01 23:21 KST — issue#14: preview node + LIDAR_DEV env chain

#### Added

- `preview_node/__init__.py` — empty package marker.
- `preview_node/pgm_encoder.py` — pure stdlib + numpy encoder.
  `occupancy_to_pixels(width, height, data)` Y-flips and threshold-maps
  the OccupancyGrid `data` array; `encode_pgm_p5(width, height, pixels)`
  prepends the netpbm `P5\n<W> <H>\n255\n` header. Hardware-free; no
  rclpy import.
- `preview_node/preview_dumper.py` — thin rclpy node that subscribes
  `/map`, throttles to 1 Hz via `PREVIEW_DUMP_MIN_INTERVAL_NS`, and
  atomic-writes `/maps/.preview/${MAP_NAME}.pgm` (tmp + fsync +
  os.replace).
- `tests/test_preview_dumper_pgm_encoder.py` — 8 hardware-free cases:
  P5 header byte-exact, pixel mapping (-1→205, 0→254, ≥50→0), Y-flip
  pin, shape-mismatch rejection, end-to-end byte-exact, constant pins.

#### Changed

- `Dockerfile` — added `python3-numpy` to the apt layer (issue#14
  preview-node dep). `COPY preview_node/ /godo-mapping/preview_node/`
  + chmod for the rclpy entrypoint script.
- `launch/map.launch.py` — added `preview_dumper` Node to the launch
  graph (invoked as `python3 -m preview_node.preview_dumper` with
  `cwd=/godo-mapping`). Modified the rplidar Node's `serial_port` to
  honour `os.environ.get('LIDAR_DEV', '/dev/ttyUSB0')` so webctl's
  resolved tracker `[serial] lidar_port` value flows to the driver.
- `entrypoint.sh` — added `mkdir -p /maps/.preview` (idempotent;
  tolerant of failure under TEST_MODE without /maps mounted) and made
  `MAP_OUT_DIR` overrideable via env-var.
- `scripts/verify-no-hw.sh` — `--quick` now also collects the new
  `tests/` directory (1 hardware-free pytest module, 8 cases).

#### Tests

- 8 new hardware-free pytest cases under `tests/test_preview_dumper_pgm_encoder.py`.
- `verify-no-hw.sh --quick` execution (entire chain) green.

### 2026-05-01 18:36 KST — issue#13-candidate (partial): SLAM default resolution 0.05 → 0.025 m/cell

#### Changed

- `config/slam_toolbox_async.yaml` — `resolution: 0.05 → 0.025`. The σ_xy
  tighten experiment on PR-#62 (logged in
  `.claude/memory/project_hint_strong_command_semantics.md`) demonstrated that
  the standstill ±2-3 cm AMCL jitter floor is map-cell quantization-bounded:
  observed y range 36 mm = 0.73 cells at the previous 0.05 m/cell. Halving
  the cell width halves the quantization floor; AMCL likelihood-field memory
  grows ~4× (2× along each axis), still well under Pi 5 8 GB.
- Inline comment block on the `resolution:` key rewritten to record the
  rationale, the operator HIL data point, and the existing-map non-migration
  rule.
- "Directory layout" pointer to the YAML key updated from `resolution: 0.05`
  to `resolution: 0.025` so doc and YAML stay in sync.

#### Out of scope

- Existing PGM/YAML maps under `/var/lib/godo/maps/` stay at 0.05 m/cell.
  Only new SLAM runs pick up the new default.
- Distance-weighted likelihood (separate issue#13 follow-up).
- AMCL likelihood-field code untouched (memory budget covered by Pi 5 8 GB).

#### Tests

- (none — mapping pipeline runs in Docker per CLAUDE.md §3, not unit-tested
  in repo; YAML diff is a single literal change.)

### 2026-04-27 — Phase 4 Track A initial scaffold

#### Added

- `Dockerfile` — F10 layered: `FROM ros:jazzy-ros-base`; apt installs
  `slam-toolbox`, `rplidar-ros`, `nav2-map-server`; `COPY launch/`,
  `COPY config/`, `COPY entrypoint.sh` in slow→fast order; LABEL
  `godo-mapping=dev` for `docker image prune --filter`.
- `launch/map.launch.py` — composes `rplidar_c1_launch.py` (upstream Jazzy
  defaults) with `slam_toolbox/async_slam_toolbox_node`. Plan F1 Option A:
  no `static_transform_publisher`.
- `config/slam_toolbox_async.yaml` — `base_frame: laser`, `odom_frame: odom`,
  `map_frame: map`, `resolution: 0.025` (halved 2026-05-01; see change log),
  `save_map_timeout: 10.0`,
  `min_laser_range: 0.05`, `max_laser_range: 12.0`, plus update-rate
  defaults. Each numeric literal carries an inline origin/rationale
  comment per F3.
- `entrypoint.sh` — container PID-1; traps INT/TERM, invokes
  `${MAP_SAVER_CMD:-ros2 run nav2_map_server map_saver_cli -f
  /maps/${MAP_NAME}}` after stopping the launch graph. `--help` shim per
  N1; `TEST_MODE=1` substitutes `sleep infinity` for the launch
  invocation per F9.
- `scripts/run-mapping.sh` — host-side `docker run` wrapper; pre-flight
  checks for filename collision, stale container, LiDAR device, image
  presence with byte-exact F6 messages; `LIDAR_DEV` env-var override;
  N7 SCRIPT_DIR/ROOT_DIR cwd anchor.
- `scripts/verify-no-hw.sh` — `--quick` (default; `bash -n` + Python AST
  parse + trap test + `--help` smoke; ~1 s) and `--full` (`docker build`
  + container `--help` smoke; ~5 min, ~800 MB pull); N7 cwd anchor.
- `tests/test_entrypoint_trap.sh` — F9 8-step contract; bare bash, no ROS,
  no Docker. Mocks `MAP_SAVER_CMD="touch <flag>"`, sends `SIGTERM` (see
  Implementation-time discoveries above for SIGINT vs SIGTERM rationale),
  asserts exit 0 + flag presence.
- `maps/.gitkeep` — keep dir present in git.
- `maps/.gitignore` — `*.pgm` + `*.yaml` (F4: no negations).
- `README.md` — Korean operator procedure (5-step walkthrough), env-var
  table, F11 first-time-verification checklist citing
  `occupancy_grid.cpp:148-154`, troubleshooting (LiDAR device, stale
  container, filename collision, N4 image cleanup, MAP_NAME, premature
  Ctrl+C, hardware-free verification).

#### Changed

- (none — greenfield)

#### Removed

- (none)

#### Tests

- `tests/test_entrypoint_trap.sh` — 1 hardware-free test (8 assertions);
  invoked by `verify-no-hw.sh --quick`.
- `verify-no-hw.sh --quick` — composite check (`bash -n` on 4 shell
  scripts + `ast.parse` on launch file + trap test + run-mapping.sh
  `--help` parse).
- `verify-no-hw.sh --full` — `--quick` set + `docker build` + `docker run
  --rm godo-mapping:dev --help` smoke.

### 2026-04-27 — Phase 4 Track B: repeatability harness + pose watch (Option C)

#### Added

- `scripts/_uds_bridge.py` — shared stdlib UDS client (`class UdsBridge`).
  SSOT for the Python tracker UDS surface (Option C invariant g);
  imported by both `repeatability.py` and `pose_watch.py`. Pure stdlib,
  zero `godo_webctl` runtime import.
- `scripts/repeatability.py` — Phase 1 measurement instrument; CLI
  driving `godo_tracker_rt` through N OneShot calibrations, incremental
  CSV write + per-row fsync, terminal summary statistics. 9 exit codes
  including F10 tracker-death streak (exit 7) and F14 shots
  validation (exit 1).
- `scripts/pose_watch.py` — Track B Option C continuous live-pose watch
  for cmd-window monitoring. Reconnect-loop (1s/2s/4s backoff) on
  tracker death; SIGINT clean exit within ~200 ms; --once smoke-test
  flag; --format text|json.
- `scripts/conftest.py` — pytest fixtures (`fake_uds_server`,
  `tmp_socket_path`) + test-time `sys.path` injection of
  `godo-webctl/src` so the cross-package SSOT pin can import
  `godo_webctl.protocol` without the runtime modules taking a runtime
  dependency.
- `scripts/test_repeatability.py` — 13 cases: happy_path_3_shots,
  diverged_shot, connection_refused, dry_run, single_converged_shot
  (F4 N<2 NaN-safe), tracker_death_streak (F10), default_out_path
  (F11), out_path_creates_parent (F13), shots_zero_rejected (F14),
  shots_negative_rejected, busy_tracker_returns_3, plus 3 structural
  pins (csv_header_byte_exact, no_godo_webctl_runtime_import,
  local_fields_match_protocol_mirror).
- `scripts/test_pose_watch.py` — 4 cases (happy_path_3_ticks_text_format,
  reconnect_after_tracker_death, sigint_clean_exit, format_json_one_line_per_tick).

#### Changed

- `scripts/verify-no-hw.sh` — `--quick` now invokes `pytest scripts/`
  to collect both new test files (F20). Pre-flight checks system
  python3 + pytest; falls back to `uv run --project ../godo-webctl`
  if pytest is not on system Python; pinned English error if neither
  route works. No Docker dep introduced.

#### Removed

- (none)

#### Tests

- 18 new hardware-free Python tests collected by
  `verify-no-hw.sh --quick`.
- The Phase 4.5 reviewer should also re-run
  `production/RPi5/scripts/build.sh` (29 → 30 hardware-free C++
  tests, +1 ordering pin, +4 cases inside `test_uds_server`) — see
  `production/RPi5/CODEBASE.md` Track B change-log.

### 2026-04-29 — Plan-F1 follow-up: rf2o laser odometry replaces identity TF

#### Bug discovery

Operator-collected studio maps (`maps/0429_*.pgm` family, 4 PGM files)
all showed single-position scan-fan artifacts of 63–114 occupied pixels,
versus the thousands of pixels expected for a 60-second studio walk with
loop closure. PGM histogram check on `maps/0429_2.pgm` confirmed
**107 occupied pixels** total, with all hits in a single fan-shape from
one position.

#### Root cause

The 2026-04-28 hotfix added a static identity `tf2_ros
static_transform_publisher` on the `odom -> laser` edge to "close the TF
chain" without an external odom source. This made slam_toolbox see zero
motion forever; the Karto `minimum_travel_distance: 0.5` /
`minimum_travel_heading: 0.5` pre-filter (slam_toolbox upstream Jazzy
defaults, NOT overridden in the previous YAML) gated out every scan
after the first, so only one scan ever got integrated.

#### Chosen path: Plan A (rf2o_laser_odometry)

Replace the static identity TF with **rf2o_laser_odometry** consuming
`/scan` and publishing a true scan-derived `odom -> laser` TF + the
informational `/odom_rf2o` topic. slam_toolbox now sees motion deltas,
the gate fires correctly, and per-scan integration resumes. See
invariant **(h)** above for the full rationale + Plan B / C fallbacks.

Plans B (laser_scan_matcher) and C (drop the gate, accept Karto-only
scan-match) are documented in `.claude/tmp/plan_mapping_pipeline_fix.md`
as fallbacks should rf2o turn out to be unsalvageable in HIL — they did
not need to be exercised because the empirical Plan A build succeeded
on first attempt.

#### Empirical build outcome

- Dockerfile rf2o overlay: `git clone
  https://github.com/MAPIRlab/rf2o_laser_odometry.git`
- SHA pinned: `b38c68e46387b98845ecbfeb6660292f967a00d3` (ros2 HEAD as of
  2026-04-29)
- package.xml format-1 → format-3 sed patch applied (PR #41 mitigation)
- `colcon build --packages-select rf2o_laser_odometry --merge-install
  --cmake-args -DCMAKE_BUILD_TYPE=Release`
- Colcon summary: `Summary: 1 package finished [47.3s]` — clean build,
  no compile warnings or errors emitted to stderr
- Image: `godo-mapping:dev` (sha256:17e89c84e996…)
- Smoke check: `ros2 pkg executables rf2o_laser_odometry` prints
  `rf2o_laser_odometry rf2o_laser_odometry_node` ✓

#### Added

- `config/rf2o.yaml` — Tier-2 rf2o parameters; top-level key
  `rf2o_laser_odometry:` byte-equal to launch Node `name=` (M1 fold).
- `Dockerfile` rf2o overlay block — second colcon-overlay layer.
- `launch/map.launch.py` — new `rf2o` Node block with explicit
  `name='rf2o_laser_odometry'` (M1) and
  `parameters=[..., {'use_sim_time': False}]` (M2) defense-in-depth pin.
- CODEBASE.md invariant (h).

#### Changed

- `launch/map.launch.py` — deleted the `static_odom_to_laser` block;
  reordered `LaunchDescription` to `[rf2o, rplidar, slam,
  slam_configure, slam_activate]` so the TF is online before
  slam_toolbox latches.
- `config/slam_toolbox_async.yaml` — added explicit
  `minimum_travel_distance: 0.5` + `minimum_travel_heading: 0.5` keys
  with rationale comment citing slam_toolbox upstream SSOT path
  (M5 fold). Values match upstream defaults — no behavior change.
- `scripts/verify-no-hw.sh` — `--full` now also smoke-tests
  `ros2 pkg executables rf2o_laser_odometry` inside the built image
  (S4 fold).
- `README.md` — 참고 + troubleshooting + directory tree updates.

#### Removed

- `launch/map.launch.py` `static_odom_to_laser` Node (lines 44-50 of
  pre-fix commit).

#### Tests

- `scripts/verify-no-hw.sh --full` gains one smoke step (rf2o binary
  reachability via `/opt/ros_overlay/install/setup.bash`).
- `tests/test_entrypoint_trap.sh` — unchanged; runs in `TEST_MODE=1`
  which bypasses `ros2 launch` entirely. Still passes.
- HIL test pending: operator runs the standard 5-step procedure at the
  studio; pass criterion is **`occupied >= 5000`** in the saved PGM
  (vs. 107 pre-fix).

#### Rollback

If HIL reveals rf2o divergence on the studio's geometry, the operator
can ship Plan C (config-only fallback) as a single-file revert:
- Restore the static identity TF in `launch/map.launch.py`.
- Set `minimum_travel_distance: 0.0` and `minimum_travel_heading: 0.0`
  in `config/slam_toolbox_async.yaml`.
- Document the rollback in invariant (h)'s Plan-C variant text.
