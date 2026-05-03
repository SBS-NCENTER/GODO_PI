# GODO — Codebase scaffold (root)

> **Purpose**: a one-page navigation hub for the three production stacks. Use this file to find which folder owns a concept, which CODEBASE.md to consult for invariants and change-log, and how the stacks talk to each other at runtime.
>
> **What this file is NOT**: it is NOT a place to copy invariant text, change-log entries, or detailed module internals. Each stack's own `CODEBASE.md` is the SSOT for those — duplicating them here would create drift. This file contains only scaffold + module roles + cross-stack data flow + pointers.
>
> **Companion**: see [`DESIGN.md`](./DESIGN.md) for design-doc orientation (SYSTEM_DESIGN + FRONT_DESIGN). This file is "what is built"; DESIGN.md is "how it was decided to be built". Both link out to deep references; both stay short.

---

## 1. Three-stack overview

```text
┌──────────────────────────────────────────────────────────────────────┐
│                          GODO production                             │
│                                                                      │
│  ┌────────────────────────┐  UDS  ┌────────────────────────┐         │
│  │  production/RPi5       │ ◄───► │  godo-webctl           │         │
│  │  (C++17, CMake)        │       │  (Python 3.13, FastAPI)│         │
│  │  godo_tracker_rt       │       │  /run/godo/ctl.sock    │         │
│  │  ─ FreeD parser        │       │  ─ HTTP + SSE          │         │
│  │  ─ RPLIDAR + AMCL      │       │  ─ admin auth (JWT)    │         │
│  │  ─ 59.94 fps UDP→UE    │       │  ─ map / config / svc  │         │
│  │  ─ SCHED_FIFO + CPU 3  │       │  ─ serves the SPA      │         │
│  └────────────────────────┘       └─────────┬──────────────┘         │
│                                             │ HTTP + SSE             │
│                                             ▼                        │
│                              ┌──────────────────────────┐            │
│                              │  godo-frontend           │            │
│                              │  (Svelte 5 + TS, Vite)   │            │
│                              │  /opt/godo-frontend/dist │            │
│                              │  ─ admin SPA, hash-route │            │
│                              │  ─ pose canvas, config,  │            │
│                              │    map editor, system    │            │
│                              └──────────────────────────┘            │
└──────────────────────────────────────────────────────────────────────┘
```

Each stack runs as a separate systemd unit on news-pi01:

| Stack | systemd unit | Owns | CODEBASE | README |
|---|---|---|---|---|
| **C++ tracker** | `godo-tracker.service` | RT pose pipeline + FreeD merge + UDP send | [`production/RPi5/CODEBASE.md`](./production/RPi5/CODEBASE.md) | [`production/RPi5/README.md`](./production/RPi5/README.md) |
| **Web control** | `godo-webctl.service` | Operator HTTP + SSE + UDS bridge to tracker + SPA static serve | [`godo-webctl/CODEBASE.md`](./godo-webctl/CODEBASE.md) | [`godo-webctl/README.md`](./godo-webctl/README.md) |
| **Operator SPA** | (served by webctl) | Operator UI (Dashboard / Map / Diag / Config / System / Backup / Local) | [`godo-frontend/CODEBASE.md`](./godo-frontend/CODEBASE.md) | [`godo-frontend/README.md`](./godo-frontend/README.md) |

Auxiliary stacks (not part of the runtime triangle):

| Stack | Role | CODEBASE | README |
|---|---|---|---|
| `godo-mapping/` | Operator-driven Docker container running `slam_toolbox` + `rplidar_ros` + `rf2o_laser_odometry` + the issue#14 preview-PGM dumper. NOT a long-running daemon — webctl drives it via `systemctl start godo-mapping@active.service` on demand. | [`godo-mapping/CODEBASE.md`](./godo-mapping/CODEBASE.md) | [`godo-mapping/README.md`](./godo-mapping/README.md) |
| `prototype/Python/` | Phase 1–2 algorithm prototyping (UV, Mac/Windows). Not deployed. | [`prototype/Python/CODEBASE.md`](./prototype/Python/CODEBASE.md) | [`prototype/Python/README.md`](./prototype/Python/README.md) |
| `XR_FreeD_to_UDP/` | Legacy Arduino R4 FreeD→UDP firmware. Read-only rollback card. | — | [`XR_FreeD_to_UDP/README.md`](./XR_FreeD_to_UDP/README.md) |

---

## 2. Module roles per stack

### `production/RPi5/` — C++ real-time tracker

- `src/core/` — `Config`, `OperatorMode`, constants, defaults, pidfile.
- `src/freed/` — FreeD packet parser + state machine.
- `src/lidar/` — RPLIDAR C1 driver (rplidar_sdk wrapper).
- `src/amcl/` — Adaptive Monte Carlo Localization (in-house, ~1k LOC). Sigma annealing, particle filter, likelihood field, scan ops.
- `src/rt/` — Hot-path scheduler (`SCHED_FIFO`, CPU 3 pinned, `mlockall`, `clock_nanosleep(TIMER_ABSTIME)`), pose double-buffer, smoother.
- `src/io/` — UDP sink (FreeD→UE), UDS server (`/run/godo/ctl.sock`), JSON encoder/decoder (`json_mini`).
- `src/udp/output_transform.{hpp,cpp}` — issue#27 sole-owner stage that applies operator-tunable per-channel offset + sign to the FreeD packet AFTER `apply_offset_inplace` (AMCL merge) and BEFORE `udp.send`. Six channels (X/Y/Z/Pan/Tilt/Roll) with `final = sign * (raw + offset)`; Zoom/Focus pass-through. Decodes back into a `LastOutputFrame` SeqLock for the SPA's "Final output (UDP)" readout. See `production/RPi5/CODEBASE.md` invariant (v).
- `src/cold/` — Cold-path threads (one-shot calibrate, live tracking, cold writer with deadband + tripwire).
- `src/ipc/` — Restart-pending sentinel reader/clearer (boot-time clear), service control surface.
- Tests live next to sources under `tests/`. `pytest` is NOT used (this is C++).
- Builds with CMake. `production/RPi5/scripts/install.sh` provisions systemd unit + polkit rule (rule (a) manage-units + rule (b) login1 reboot/poweroff).

### `godo-webctl/` — Python operator control plane

- `src/godo_webctl/app.py` — FastAPI app (single uvicorn worker, single instance via pidfile lock at `/run/godo/webctl.pid`).
- `src/godo_webctl/uds_client.py` — Bridge to the C++ tracker over `/run/godo/ctl.sock`. JSON line protocol.
- `src/godo_webctl/protocol.py` — Wire-shape SSOT. Mirrors `production/RPi5/src/io/json_mini.cpp::format_*` envelopes.
- `src/godo_webctl/auth.py` — JWT issue/verify, password file (`/etc/godo/users.json`), atomic write.
- `src/godo_webctl/maps.py` — Active-map symlink, list, image, dimensions, activate, delete.
- `src/godo_webctl/backup.py` — Map auto-backup directory (`/var/lib/godo/map-backups/<ts>`).
- `src/godo_webctl/map_edit.py` — Brush-erase mask→PGM transform (B-MAPEDIT, sole owner of pixel writes).
- `src/godo_webctl/services.py` — systemd unit start/stop/restart via `systemctl` + polkit; reboot/poweroff via login1.
- `src/godo_webctl/processes.py` — `/proc` parser for the System tab process list.
- `src/godo_webctl/resources_extended.py` — `/proc` + `/sys` parsers for per-core CPU + mem + disk panels.
- `src/godo_webctl/diag.py` — Diagnostics SSE source.
- `src/godo_webctl/restart_pending.py` — Sentinel writer (webctl owns set; tracker owns clear at boot).
- `src/godo_webctl/activity.py` — Operator activity log.
- Tests under `tests/`. `pytest -m "not hardware_tracker"` for hardware-free CI.
- Managed by `uv` (lockfile pinned). Prod install via `uv sync --no-dev` into `/opt/godo-webctl/.venv`.

### `godo-frontend/` — Svelte 5 SPA

- `src/routes/` — Top-level pages: Dashboard, Map (with Edit sub-tab), Diagnostics, Config, System (with Processes / Extended sub-tabs), Backup, Local, Login.
- `src/components/` — Reusable: `PoseCanvas`, `MapMaskCanvas`, `ConfigEditor`, `RestartPendingBanner`, `Sidebar`, sparklines, modal helpers.
- `src/stores/` — Svelte stores: `auth`, `mapMetadata`, `lastPose`, `lastScan`, `scanOverlay`, `restartPending`, `systemServices`, `config`, etc.
- `src/lib/` — Pure TS: `api` (fetch wrapper + ApiError), `protocol` (wire-shape mirror of webctl `protocol.py`), `router` (30-line hash-router), `format`, `constants`.
- `src/styles/` — CSS variables (light + dark theme); no per-component hex tokens.
- `tests/unit/` — Vitest, jsdom shimmed.
- `tests/e2e/` — Playwright; runs on dev hosts only (RPi 5 doesn't have the browser deps).
- Built with Vite. Prod install: `npm run build` → `dist/` rsynced to `/opt/godo-frontend/dist/` (served by webctl).

### `prototype/Python/` — algorithm prototyping (Mac/Windows)

- Phase 1–2 only. Not deployed. UV-managed. Out-of-band raw lidar data lives under `out/<TS>/data/` (gitignored).

---

## 3. Cross-stack data flow at runtime

```text
┌────────────────────────────────────────────────────────────────────┐
│  HOT PATH (60 Hz, RT-prio, CPU 3 pinned)                           │
│                                                                    │
│  FreeD UART ─► freed parser ─► smoother ─► UDP socket ─► UE        │
│                                  ▲                                 │
│                                  │ pose + offset                   │
│  RPLIDAR USB ─► lidar driver ──► pose double-buffer ◄──────────┐  │
│                       │                                         │  │
│                       └─► AMCL (cold path, separate thread) ────┘  │
└────────────────────────────────────────────────────────────────────┘
       ▲ control verbs                       ▲ pose / scan SSE
       │ over /run/godo/ctl.sock             │ over UDS-readback
       │                                     │
┌──────┴─────────────────────────────────────┴──────────────────────┐
│  godo-webctl (FastAPI, single uvicorn worker)                     │
│                                                                   │
│   ┌─ HTTP /api/* ────────────────────► SPA (browser)              │
│   │                                                               │
│   ├─ SSE /api/diag/stream                                         │
│   ├─ SSE /api/scan/stream                                         │
│   ├─ SSE /api/system/processes/stream                             │
│   ├─ SSE /api/system/resources/extended/stream                    │
│   └─ SSE /api/mapping/monitor/stream  (issue#14, only when active)│
│                                                                   │
│   Static: /opt/godo-frontend/dist/  (when GODO_WEBCTL_SPA_DIST=)  │
└───────────────────────────────────────────────────────────────────┘
       │ systemctl start godo-mapping@active.service
       │ + atomic-write /run/godo/mapping/active.env
       ▼
┌───────────────────────────────────────────────────────────────────┐
│  systemd template unit godo-mapping@active.service                │
│  → docker run --rm --device=${LIDAR_DEV} -v /var/lib/godo/maps:…  │
│        ${IMAGE_TAG}  (godo-mapping:dev)                           │
│      └─► slam_toolbox + rplidar_ros + rf2o_laser_odometry         │
│          + preview_dumper rclpy node                              │
│              writes /maps/.preview/<name>.pgm @ 1 Hz              │
│                                                                   │
│  Mutually exclusive with godo-tracker (L2 — webctl stops tracker  │
│  before starting mapping). Operator restarts tracker post-stop    │
│  via SPA System tab. NOT enabled — webctl is the SOLE caller.     │
└───────────────────────────────────────────────────────────────────┘
```

Key invariants this picture enforces:

- **Tracker is the single hardware owner during normal operation.** No other process opens the LiDAR, the FreeD UART, or the UE UDP socket. **Exception (issue#14)**: during mapping the tracker is stopped (L2) and the godo-mapping container takes the LiDAR; webctl orchestrates the handoff. After mapping the operator manually restarts the tracker via System tab.
- **webctl is the single tracker client.** The SPA never speaks UDS directly; it only speaks HTTP/SSE to webctl. This makes the auth + audit boundary clean.
- **Map files are tracker-owned at boot, webctl-owned for edits.** The tracker reads `/var/lib/godo/maps/active.{pgm,yaml}` once at startup; webctl writes to those files via atomic mkstemp + os.replace through `map_edit.py` (B-MAPEDIT). The `/var/lib/godo/restart_pending` sentinel is webctl-set + tracker-cleared (asymmetric ownership; both run as `ncenter`).
- **issue#14 mapping pipeline mode is webctl-owned.** Tracker has zero awareness of mapping mode (no UDS extension). State.json at `/run/godo/mapping/state.json` is webctl's authoritative view, reconciled against `docker inspect`. Coordinator boundary is documented in `godo-webctl/CODEBASE.md` invariants `(ad)..(af)`.
- **No SPA-to-tracker shortcut.** Even local-host SPA traffic transits webctl. This is by design — see `godo-frontend/CODEBASE.md` invariant (b) (loopback gate is two-layer).

---

## 4. Where invariants live (do not duplicate here)

Each stack's CODEBASE.md owns a lettered invariant list `(a)..(z)..(aa)..` plus a chronological change log. **Do not copy invariant text into this file.** When a behavior is established, the canonical text lives in the per-stack CODEBASE.md and this root file at most points to it by section name.

Current invariant tail per stack (as of 2026-05-01):

| Stack | Invariants tail |
|---|---|
| `production/RPi5/CODEBASE.md` | `(o) godo-systemctl-polkit-discipline` |
| `godo-webctl/CODEBASE.md` | `(af) issue#14 mapping preview path SSOT + PNG re-encode` |
| `godo-frontend/CODEBASE.md` | `(ad) issue#14 mode-aware UI gating via mappingStatus` |
| `godo-mapping/CODEBASE.md` | `(j) issue#14 LIDAR_DEV env-var SSOT chain` |

The tail letter is just a quick orientation hint — letters do not increment monotonically (some have been retired or skipped). Always read the per-stack file for the canonical list.

Cascade rule: when a structural change spans two or more stacks (e.g., a new wire shape in webctl that the SPA must consume), update the relevant invariants in **every** affected CODEBASE.md AND, if the high-level role/data-flow changes, update §1–§3 of this root file. Invariants stay in their per-stack home; the root file is updated only when the scaffold or data flow itself shifts.

---

## 5. Doc hierarchy

```text
CLAUDE.md                                ← Operating rules (golden rules + agent pipeline)
├── PROGRESS.md                          ← Cross-session log, English (Parent maintains)
├── doc/history.md                       ← Cross-session log, Korean narrative
├── NEXT_SESSION.md                      ← Cache (cold-start aid; throwaway, prune-on-absorption)
├── CODEBASE.md                          ← THIS FILE (cross-stack scaffold + module roles)
│   ├── production/RPi5/CODEBASE.md      ← C++ tracker invariants + change log
│   ├── godo-webctl/CODEBASE.md          ← Python webctl invariants + change log
│   ├── godo-frontend/CODEBASE.md        ← Svelte SPA invariants + change log
│   ├── godo-mapping/CODEBASE.md         ← SLAM container invariants + change log (issue#14)
│   └── prototype/Python/CODEBASE.md     ← Prototype change log
└── DESIGN.md                            ← Design-doc TOC (links SYSTEM + FRONT)
    ├── SYSTEM_DESIGN.md                 ← Backend / RT / AMCL / FreeD design
    └── FRONT_DESIGN.md                  ← Frontend / page / component design
```

Hierarchy ownership rule: **a file at level N never duplicates content from a file at level N+1.** The root CODEBASE.md and DESIGN.md describe the SHAPE of the family; the leaves contain the load-bearing text. When a leaf changes, update only the leaf — the root scaffold rarely needs touching, and that's intentional (the root file's purpose is exactly to be the stable index).

---

## 6. New-session cold-start

On a fresh session, the recommended read order is:

1. `CLAUDE.md` — operating rules, agent pipeline, golden rules.
2. `NEXT_SESSION.md` — what was just shipped + what's queued. Prune-on-absorb so it stays current.
3. `.claude/memory/MEMORY.md` — index of in-repo memory entries.
4. **This file** — for "where does X live" questions.
5. `DESIGN.md` — for "why does X work this way" questions; follow into SYSTEM_DESIGN or FRONT_DESIGN as needed.
6. The relevant per-stack `CODEBASE.md` — for invariants + recent change log on the area you're touching.
7. `PROGRESS.md` / `doc/history.md` — for "what happened in the last few sessions" narrative.
