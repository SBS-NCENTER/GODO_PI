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
│   └─ map.launch.py                # rplidar_c1 + async_slam_toolbox_node
├─ config/
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
| `Dockerfile` | `ros:jazzy-ros-base` | Defines the SLAM container image; layer order tuned for build cache (apt before COPY). |
| `launch/map.launch.py` | `rplidar_ros`, `slam_toolbox` | Composes upstream `rplidar_c1_launch.py` with `async_slam_toolbox_node`. No `static_transform_publisher`. |
| `config/slam_toolbox_async.yaml` | `slam_toolbox` | Tier-2 SLAM parameters with inline rationale on every numeric literal (F3 carve-out). |
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
                                                          │       ├─ rplidar_c1_launch.py
                                                          │       └─ slam_toolbox/async_slam_toolbox_node
                                                          │           (params from config/slam_toolbox_async.yaml)
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
  `map_frame: map`, `resolution: 0.05`, `save_map_timeout: 10.0`,
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
