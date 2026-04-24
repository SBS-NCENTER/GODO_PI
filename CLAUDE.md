# Project: LiDAR-based Camera Position Tracker

## Language & Tone

- Technical / engineering terms: **keep English originals** (stack frame, calling convention, cache line — never translate).
- Code, comments, commit messages, in-repo documents: **English**.
- User-facing conversation: Korean, tender/friendly tone.
- Diagrams and tables: **Unicode box drawing only** (┌─┐│└─┘├┤┬┴┼▼▲►◄); never ASCII (+--+|).

---

## 1. Project overview (What & Why)

### Current problem

- The studio uses a **SHOTOKU crane** (TK-53LVR / Ti-04VR family).
- The crane outputs FreeD packets (X, Y, Z, Pan, Tilt, Roll, Zoom, Focus).
- The existing converter [`/XR_FreeD_to_UDP`](./XR_FreeD_to_UDP/) (Arduino R4 WiFi, PlatformIO) turns FreeD into UDP that Unreal Engine consumes.
- The crane base is movable, but the **recalibration procedure is complex**, so in practice the base is kept fixed.

### Goal

- Use the RPLIDAR C1 to measure the crane base's **world (x, y) position** so we can re-register after a base move by simply adding a computed **(dx, dy) offset** to the FreeD X/Y.
- The measurement is **user-triggered 1-shot**, not continuous tracking. This avoids sustained LiDAR noise.
- Accuracy target: **1–2 cm**. Tighter is better.

### Out of scope

- Correction of Z, Pan, Tilt, Roll, Zoom, Focus (trust the crane's own sensors).
- Camera-head position correction (we only deal with the base).

---

## 2. System architecture (high level)

```text
┌────────────────────────────────────────────────────────────────────┐
│                    Studio world frame                              │
│                                                                    │
│   ┌──────────────┐                                                 │
│   │ SHOTOKU Crane│──► FreeD(X,Y,Z,P,T,R,Z,F) ──┐                   │
│   │   Base       │                             │                   │
│   │   + Boom     │                             ▼                   │
│   │   + Camera   │                    ┌─────────────────┐          │
│   └──────┬───────┘                    │  godo-tracker   │          │
│          │ pan-axis center            │   (RPi 5, C++)  │          │
│          ▼                            │  ※ integrates   │          │
│   ┌──────────────┐                    │    FreeD→UDP    │          │
│   │  RPLIDAR C1  │─► scan data ──────►│    + LiDAR loc  │          │
│   │  (on pan-    │                    └────────┬────────┘          │
│   │   axis center)│                            │                   │
│   └──────────────┘                             ▼                   │
│                                        ┌─────────────────┐         │
│                                        │ Unreal Engine   │         │
│                                        │  (UDP receiver) │         │
│                                        └─────────────────┘         │
└────────────────────────────────────────────────────────────────────┘
```

### Key physical assumption

- The RPLIDAR is mounted at the **geometric center of the crane's pan axis**.
  - → LiDAR world (x, y) is **invariant** to pan rotation.
  - → LiDAR yaw follows pan rotation.
  - → Unknowns to solve: `(x, y)` + `yaw` (a standard 2D SLAM/localization problem).
- The origin is the **base location at calibration time**; it must be re-settable (as a simple 2D translation subtraction).

---

## 3. Phases

```text
┌─────────────────────────────────────────────────────────────┐
│ Phase 0. Deep analysis of RPLIDAR C1           ✅ done       │
│   └─ Deliverable: doc/RPLIDAR/RPLIDAR_C1.md                  │
├─────────────────────────────────────────────────────────────┤
│ Phase 1. Data normalization (Python prototype) ◄ current    │
│   ├─ Raw data dump via the official SDK                     │
│   ├─ Noise characterization, filter design                  │
│   └─ Static (x, y, yaw) extraction pipeline                 │
├─────────────────────────────────────────────────────────────┤
│ Phase 2. Localization algorithm                             │
│   ├─ Reference-scan + ICP (provisional per Phase 0)         │
│   ├─ World-frame pose from the origin                       │
│   └─ Reproducibility test (repeat scans at same position)   │
├─────────────────────────────────────────────────────────────┤
│ Phase 3. Port to target hardware                            │
│   ├─ RPi 5 as primary host (provisional per Phase 0)        │
│   ├─ Trigger UX (physical button vs. network — Q6)          │
│   └─ Offset delivery path                                   │
├─────────────────────────────────────────────────────────────┤
│ Phase 4. FreeD integration                                  │
│   ├─ FreeD receive + offset merge + UDP send (unified C++)  │
│   └─ Origin-reset interface                                 │
├─────────────────────────────────────────────────────────────┤
│ Phase 5. Field integration test (Unreal Engine)             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Hardware inventory and roles

| Device | Current role | Status |
| --- | --- | --- |
| SLAMTEC RPLIDAR C1 | 2D 360° scanner | confirmed |
| Raspberry Pi 5 (8 GB RAM, 32 GB microSD) | LiDAR capture + localization + FreeD→UDP merge | **confirmed as sole production host** |
| Raspberry Pi Pico × 2 | Trigger button candidate | per Q6 |
| Arduino R4 WiFi | Backup FreeD→UDP (rollback card) | standby |
| Existing XR_FreeD_to_UDP firmware | Reference + rollback | retained, never modified |

### Current hardware connection

- The RPLIDAR C1 connects over USB through a **CP2102N-based 4-pin-to-USB-C module** (3.3 V TTL UART @ 460,800 bps internally).
- MCU-direct connection details: see [doc/RPLIDAR/RPLIDAR_C1.md §6](./doc/RPLIDAR/RPLIDAR_C1.md#6-mcu--sbc-direct-connection).

---

## 5. Languages and tooling

| Area | Language | Tool |
| --- | --- | --- |
| LiDAR data testing / prototyping | Python | UV (macOS / Windows) |
| Production on RPi 5 | C++17+ | CMake |
| Existing crane FreeD converter | Arduino C/C++ | PlatformIO (VSCode extension) |
| Unreal Engine integration | FreeD over UDP | — |

### Directory structure

```text
/                                ← GODO workspace root
├─ CLAUDE.md                     ← This document (SSOT)
├─ SYSTEM_DESIGN.md              ← End-to-end system design & implementation guide
├─ PROGRESS.md                   ← Cross-session progress log (Mac / Windows)
├─ /.claude
│    ├─ /agents                  ← Agent definitions (planner / writer / reviewer)
│    └─ /memory                  ← Project persistent memory (portable)
│         ├─ MEMORY.md
│         └─ *.md                ← user / feedback / project / reference entries
├─ /doc                          ← Reference documents
│    ├─ Embedded_CheckPoint.md   ← Embedded reliability checklist (reference)
│    ├─ /hardware                ← Hardware decision / measurement reports
│    │    ├─ floor_tilt_survey_TS5.md
│    │    └─ leveling_mount.md
│    └─ /RPLIDAR                 ← RPLIDAR reference docs
│         ├─ RPLIDAR_C1.md       ← C1 deep dive (Phase 0 output)
│         └─ /sources            ← Original datasheets (PDF)
├─ /prototype                    ← Prototyping / research stacks
│    └─ /Python                  ← Python prototype project (Phase 1~2, UV)
│         ├─ README.md
│         └─ CODEBASE.md         ← Structural / functional change log
├─ /production                   ← Production deployment stacks
│    └─ /RPi5                    ← C++ application on Raspberry Pi 5 (Phase 3~)
│         ├─ README.md
│         └─ CODEBASE.md
└─ /XR_FreeD_to_UDP              ← Legacy Arduino firmware (rollback card, reference)
     ├─ README.md
     ├─ platformio.ini
     └─ src/main.cpp             ← FreeD D1 parser + UDP send reference
```

### New-session entry procedure (Mac / Windows alike)

1. Read `CLAUDE.md` and `PROGRESS.md` first for full context.
2. Check `.claude/memory/MEMORY.md` and load relevant entries.
3. As needed, open `SYSTEM_DESIGN.md`, `doc/RPLIDAR/RPLIDAR_C1.md`, and other references.

> Automatic memory loading depends on per-host caches, so **explicitly reading `.claude/memory/MEMORY.md` at the start of each session** is recommended. This folder is all you need to continue work on any machine.

---

## 6. Design principles (Golden Rules)

These rules apply to the Parent orchestrator and all subagents. They are non-negotiable unless the user explicitly overrides.

### Code and docs

- **SSOT / DRY**: one concept, one location. No duplicate implementations.
- **Minimal code**: implement exactly what is requested. No speculative abstractions, no "just in case" code, no drive-by refactoring.
- **Long-term stability**: follow `doc/Embedded_CheckPoint.md` for any code that will run for years in production.
- **Preserve existing assets**: minimize changes to the production `XR_FreeD_to_UDP` firmware. If changes are unavoidable, prepare a rollback plan first.
- **Keep CLAUDE.md short**: this file is a guide, not a data store. Push long analyses, specs, and reports into dedicated reference documents and link to them.

### Language policy

- Code, comments, in-repo documents, agent instructions: **English**.
- Engineering terms: **retain the English originals** (never translate to Korean).
- User-facing messages (chat replies, friendly progress updates): Korean with a kind tone.

### Context maintenance

- Code or feature changes → update the relevant `CODEBASE.md` in the same change.
- Project state / decision changes → update `PROGRESS.md` (Parent's responsibility).
- Global behavioral preferences → update `.claude/memory/` (Parent's responsibility).
- Never write long analysis directly into `CLAUDE.md`; create a dedicated document and link to it.

### Memory storage — in-repo, not host cache

GODO is collaborated on via GitHub, so every auto-memory operation
(create, update, delete) MUST target the in-repo folder, not the
host-specific default path:

- ✅ `<repo-root>/.claude/memory/` — committed to git, shared with
  every collaborator and every host (Mac / Windows).
- ❌ `~/.claude/projects/<project-hash>/memory/` — host-local, not
  shared, causes divergence between machines and collaborators.

When the harness's system prompt names a host-specific memory path,
treat that as a default to be **overridden by this rule**. All new
memory entries and `MEMORY.md` updates are written under
`<repo-root>/.claude/memory/`, committed with the change they
describe, and pushed so collaborators see them on their next pull.

### Cross-platform hygiene (Mac / Windows / Linux RPi 5)

The repo is worked on from three platforms. Git configuration files enforce the basics automatically on every clone; the rules below are for humans and agents to follow explicitly.

- **Line endings**: `.gitattributes` normalizes all text to LF inside the repo. Never override with `git config core.autocrlf=true` locally. If a tool produces CRLF, fix the tool — do not commit CRLF to work around it.
- **LiDAR raw data**: `prototype/Python/out/*/data/` is gitignored. Never bypass with `git add -f`. Raw CSVs are regenerable from a fresh scan; archival policy (LFS vs. out-of-repo) will be decided after Phase 1.
- **Per-machine runtime config** (LiDAR port, UE host/port, map file path): lives in `/scripts/run-<platform>-<role>.sh` (or `.ps1` on Windows) or as CLI arguments. Never hardcode machine-specific values into source files.
- **Machine switch protocol**: before ending a session on machine A, commit + push. Before starting on machine B, `git pull --rebase`. Concurrent edits across machines are disallowed; session state belongs in `PROGRESS.md` so the next machine can resume.

### Read-only folders

- `/XR_FreeD_to_UDP/*` and `/doc/RPLIDAR/sources/*` are **read-only** for every agent. Reference them freely; never modify or delete.

### Agent self-preservation

- No agent (planner / writer / reviewer) modifies its own or another agent's definition file. Agent definitions change only after the user approves.

---

## 7. Agent pipeline

Three specialized agents, orchestrated by the Parent (this assistant, in the main chat).

### Roles (one line each)

- **code-planner** — turns a user request into a concrete plan (task list, file changes, module boundaries, risks, test strategy). No code.
- **code-writer** — implements code and tests per an approved plan. Updates `CODEBASE.md`. No self-review.
- **code-reviewer** — reviews either a plan (Mode-A) or an implementation (Mode-B). No fixes; only findings and recommendations.

Full definitions: `.claude/agents/code-planner.md`, `.claude/agents/code-writer.md`, `.claude/agents/code-reviewer.md`.

### Standard pipeline

```text
User request
    ↓
Planner ──► Reviewer (Mode-A) ──► (approve) Writer ──► Reviewer (Mode-B) ──► User
              │                                            │
              └─ rework → Parent recalls Planner           └─ rework → Parent recalls Writer
```

### Orchestration rules

- **Flexibility (A2)**: Parent decides per-task whether to use the full pipeline or a subset. Trivial edits (typo, one-line fix) can call the Writer directly. Feature-scale work goes through the whole pipeline.
- **Report-only reviews (B2)**: when the Reviewer flags issues, Parent (and the user, for major ones) decides whether to rework or accept. No automatic loops.
- **Writer owns tests (C1)**: the Writer produces tests alongside implementation. The Reviewer gates test quality via a strict bias-blocking checklist (see `code-reviewer.md`).
- **Agent definition changes**: whenever the pipeline itself needs to change (new agent, changed boundary), Parent asks the user before editing anything under `.claude/agents/`.

---

## 8. Open questions

| # | Question | Status | Blocks |
| --- | --- | --- | --- |
| Q4 | How much do chroma-studio fixtures (walls, TV trolleys, chairs, speakers) affect ICP/AMCL accuracy | To be measured empirically in Phase 1 | Phase 2 |
| Q5 | Final UE-side error bound (target ≤ 1–2 cm) | Determined by integration test | Phase 5 |
| Q6 | Trigger UX (physical button vs. network command) | **Resolved (2026-04-24)**: both — GPIO button on RPi 5 + HTTP POST via `godo-webctl`, same command queue | — |
| Q7 | FreeD merge location | **Resolved (2026-04-21)**: unified inside the RPi 5 C++ binary | — |
| B | Coordinate-setup method | **Resolved (Phase 0)**: pre-built map + AMCL, see [SYSTEM_DESIGN.md §5](./SYSTEM_DESIGN.md) | — |
| C | Compute pipeline | **Resolved (Phase 0)**: RPi 5 native C++ | — |

### Confirmed facts (for reference)

- **The base does not rotate.** Only the LiDAR rotates (with the pan head). The dolly wheels are always parallel, making physical base rotation very hard.
- **Origin = base position at calibration**; must be re-settable.
- People move below LiDAR height; dynamic objects visible to the LiDAR are mainly the crane itself and the studio doors.

---

## 9. Reference documents

### End-to-end design

→ **[SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md)** — final topology, data flow, module layout, mapping workflow (Docker + ROS 2 Jazzy + slam_toolbox), AMCL overview, 59.94 fps RT design, phase plan, failure scenarios, and the Windows handoff guide.

### RPLIDAR C1 deep dive (Phase 0 output)

→ **[doc/RPLIDAR/RPLIDAR_C1.md](./doc/RPLIDAR/RPLIDAR_C1.md)** — measurement principle, performance specs, UART protocol, SDK and Python bindings, root-cause analysis for "why raw Python data was noisy", MCU/SBC compatibility matrix, chroma-studio suitability, product-line positioning.

### Others

- [doc/Embedded_CheckPoint.md](./doc/Embedded_CheckPoint.md) — embedded reliability checklist.
- [PROGRESS.md](./PROGRESS.md) — cross-session progress state.
