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
- The measurement is **user-triggered**, never autonomous. The studio operator chooses the mode each time.
- Accuracy target: **1–2 cm** (1-shot mode); Live mode is intentionally looser.

### Operating modes (4 user-triggered actions, all on-demand)

| # | Action | Trigger | Accuracy | Cadence | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | **Initial / re-do mapping** | Operator (Docker session) | n/a | Once per studio change | Builds `.pgm` + `.yaml`. See [SYSTEM_DESIGN.md §4](./SYSTEM_DESIGN.md). |
| 2 | **Map editing** | Operator (webctl, Phase 4.5) | n/a | Rare | Paint over moved fixtures, etc. |
| 3 | **1-shot calibrate** (high accuracy) | GPIO button / HTTP `/api/calibrate` | ≤ 1–2 cm | Once per session, when base moves | AMCL `converge()` runs to convergence; result is forced through deadband. **This is the production path.** |
| 4 | **Live tracking** (low accuracy, toggle) | GPIO button / HTTP `/api/live` | Coarser (depends on motion) | ~10 Hz while toggled on | AMCL `step()` per scan; deadband filters noise. Base may move at up to ~30 cm/s. Implementation deferred to Phase 4-2 D. |

The smoother + 60 Hz hot path was designed around mode (4) — its 60 Hz interpolation between cold-path updates is what makes Live mode renderable to UE. 1-shot mode (3) inherits the smoother as a side-benefit (the operator-triggered jump becomes a smooth ~500 ms ramp instead of a step change).

### Out of scope

- Correction of Z, Pan, Tilt, Roll, Zoom, Focus (trust the crane's own sensors).
- Camera-head position correction (we only deal with the base).
- Autonomous (non-user-triggered) recalibration. Every cold-path update is operator-initiated.

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
│ Phase 1. Data normalization (Python prototype) ✅ scaffold   │
│   └─ Replaced in production by Phase 4-2 in-process pipeline │
├─────────────────────────────────────────────────────────────┤
│ Phase 2. Localization algorithm                ✅ done       │
│   └─ Pre-built map + AMCL (Track D family closed Phase 4-2) │
├─────────────────────────────────────────────────────────────┤
│ Phase 3. Port to target hardware               ✅ done       │
│   └─ RPi 5 C++ scaffold + godo_smoke 2026-04-23             │
├─────────────────────────────────────────────────────────────┤
│ Phase 4-1. RT hot path closeout                ✅ done       │
│   └─ SCHED_FIFO + CPU 3 isolation, p99=12.7 µs measured     │
├─────────────────────────────────────────────────────────────┤
│ Phase 4-2. LiDAR + AMCL + cold-path           ✅ done       │
│   ├─ AMCL one-shot + Live (Track D-1..D-5)                  │
│   └─ Sigma annealing solved convergence (PR #32)            │
├─────────────────────────────────────────────────────────────┤
│ Phase 4-3. webctl + UDS bridge                 ✅ done       │
│   └─ FastAPI + 14+ endpoints + 4 SSE streams                │
├─────────────────────────────────────────────────────────────┤
│ Phase 4.5. Operator SPA + Map editor          ◄ current     │
│   ├─ P0 SPA scaffold ✅                                      │
│   ├─ P1 Track-B family (config / diag / backup) ✅           │
│   ├─ P2 System tab + process monitor ✅ (PR #36)             │
│   ├─ P2 Map editor brush-erase ✅ (PR #39)                   │
│   ├─ P2 Map editor origin pick ◄ next                       │
│   └─ P2 Map editor rotation (deferred)                       │
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
├─ CLAUDE.md                     ← Operating rules (this file)
├─ CODEBASE.md                   ← Cross-stack scaffold + module roles (root index)
├─ DESIGN.md                     ← Design-doc TOC (links SYSTEM + FRONT)
├─ SYSTEM_DESIGN.md              ← Backend + RT + AMCL + FreeD design SSOT
├─ FRONT_DESIGN.md               ← Frontend / page / component design SSOT
├─ PROGRESS.md                   ← Lean: Current state + Decisions + Open Q + index of weekly archives
├─ /PROGRESS                     ← Weekly session-log archives (YYYY-W##.md, ISO 8601 KST Mon–Sun)
├─ NEXT_SESSION.md               ← Cold-start cache (throwaway, prune-on-absorption)
├─ /.claude
│    ├─ /agents                  ← Agent definitions (planner / writer / reviewer)
│    └─ /memory                  ← Project persistent memory (portable)
│         ├─ MEMORY.md
│         └─ *.md                ← user / feedback / project / reference entries
├─ /doc                          ← Reference documents
│    ├─ history.md                 Cross-session narrative (Korean) — lean: 인트로 + 주차 인덱스
│    ├─ /history                ← Weekly Korean session-narrative archives (YYYY-W##.md)
│    ├─ Embedded_CheckPoint.md     Embedded reliability checklist (reference)
│    ├─ /hardware                ← Hardware decision / measurement reports
│    │    ├─ floor_tilt_survey_TS5.md
│    │    └─ leveling_mount.md
│    └─ /RPLIDAR                 ← RPLIDAR reference docs
│         ├─ RPLIDAR_C1.md       ← C1 deep dive (Phase 0 output)
│         └─ /sources            ← Original datasheets (PDF, read-only)
├─ /prototype                    ← Prototyping / research stacks
│    └─ /Python                  ← Phase 1~2 algorithm prototype (UV)
│         ├─ README.md
│         └─ CODEBASE.md         ← Structural / functional change log
├─ /production                   ← Production deployment stacks
│    └─ /RPi5                    ← C++ tracker (godo_tracker_rt, Phase 3+)
│         ├─ README.md
│         ├─ CODEBASE.md         ← Invariants (a)..(w) + index of weekly archives
│         └─ /CODEBASE           ← Weekly change-log archives (YYYY-W##.md)
├─ /godo-webctl                  ← Operator web control plane (Python FastAPI, Phase 4-3+)
│    ├─ README.md                  drives godo-tracker via UDS at /run/godo/ctl.sock
│    ├─ CODEBASE.md                Invariants (a)..(af) + index of weekly archives
│    ├─ /CODEBASE                  Weekly change-log archives
│    └─ pyproject.toml             UV-managed; FastAPI + bcrypt + pyjwt + pillow + python-multipart
├─ /godo-frontend                ← Operator SPA (Vite + Svelte 5 + TS, Phase 4.5)
│    ├─ README.md                  served by godo-webctl when GODO_WEBCTL_SPA_DIST is set
│    ├─ CODEBASE.md                Invariants (a)..(an) + index of weekly archives
│    ├─ /CODEBASE                  Weekly change-log archives
│    └─ package.json               Pages: Dashboard, Map (with Edit sub-tab), Diag, Config, System (with sub-tabs), Backup, Local, Login
└─ /XR_FreeD_to_UDP              ← Legacy Arduino firmware (rollback card, read-only reference)
     ├─ README.md
     ├─ platformio.ini
     └─ src/main.cpp             ← FreeD D1 parser + UDP send reference
```

**Hierarchy quick-reference:**
- `CODEBASE.md` (root) and `DESIGN.md` (root) are scaffold/index files. They do NOT duplicate per-stack invariant text or design-doc bodies.
- Per-stack `CODEBASE.md` files own their invariants `(a)..(z)..` (the SSOT for "what is built and why each rule exists"). Dated change-log entries live under `<stack>/CODEBASE/YYYY-W##.md` (ISO 8601 KST Mon–Sun weeks). The master keeps invariants + Index only — **no inline most-recent entry** (operator-locked Option (b), 2026-W19).
- `SYSTEM_DESIGN.md` + `FRONT_DESIGN.md` own design narrative; the root `DESIGN.md` is just their TOC.
- `PROGRESS.md` keeps current state + Decisions + Open Q + Index; per-week session blocks under `PROGRESS/YYYY-W##.md`. Same pattern for `doc/history.md` (Korean) → `doc/history/YYYY-W##.md`.

### New-session entry procedure (Mac / Windows alike)

1. Read `CLAUDE.md` (this file) for operating rules.
2. Read `NEXT_SESSION.md` for what's queued (cold-start cache; prune-on-absorption — see §6).
3. Check `.claude/memory/MEMORY.md` and load relevant entries.
4. Open `CODEBASE.md` (root) for "where does X live"; follow into the relevant per-stack `CODEBASE.md` for invariants. For "what just shipped", open the most recent week's archive at `<stack>/CODEBASE/YYYY-W##.md`.
5. Open `DESIGN.md` (root) for "why does X work this way"; follow into `SYSTEM_DESIGN.md` or `FRONT_DESIGN.md`.
6. `PROGRESS.md` / `doc/history.md` for current state + most-recent-week narrative; older sessions under `PROGRESS/YYYY-W##.md` and `doc/history/YYYY-W##.md`.

> Automatic memory loading depends on per-host caches, so **explicitly reading `.claude/memory/MEMORY.md` at the start of each session** is recommended. This folder is all you need to continue work on any machine.

---

## 6. Design principles (Golden Rules)

These rules apply to the Parent orchestrator and all subagents. They are non-negotiable unless the user explicitly overrides.

### Code and docs

- **SSOT / DRY**: one concept, one location. No duplicate implementations.
- **Minimal code**: implement exactly what is requested. No speculative abstractions, no "just in case" code, no drive-by refactoring.
- **No magic numbers**: numeric literals in `src/` require one of (a) a `constexpr` in `core/constants.hpp`, (b) a field of `Config` with a default in `core/config_defaults.hpp`, or (c) a local iteration bound. Anything else is a code-review block. See [SYSTEM_DESIGN.md §11](./SYSTEM_DESIGN.md) for the two-tier scheme.
- **Long-term stability**: follow `doc/Embedded_CheckPoint.md` for any code that will run for years in production.
- **Single-instance discipline**: every independent long-running process (HTTP server, RT daemon, GUI launcher) MUST acquire a per-process pidfile lock at startup BEFORE opening hardware, binding ports, or binding UDS sockets. Lock path: `/run/godo/<service>.pid` (must live on a local FS — tmpfs `/run/godo` is the project default; NFS is unsupported because flock semantics differ). Mechanism: `fcntl(F_SETLK, F_WRLCK)` (C/C++) or `fcntl.flock(LOCK_EX | LOCK_NB)` (Python). On contention: log to stderr, exit code 1. The pidfile path is configurable via Tier-2 config (CLI / env / TOML). Tests use a tmpfs override; production uses the systemd-default. This rule applies to every new long-running module — see godo-webctl invariant (e) and RPi5 production CODEBASE invariant (l) tracker-pidfile-discipline.
- **Preserve existing assets**: minimize changes to the production `XR_FreeD_to_UDP` firmware. If changes are unavoidable, prepare a rollback plan first.
- **Keep CLAUDE.md short**: this file is a guide, not a data store. Push long analyses, specs, and reports into dedicated reference documents and link to them.

### Language policy

- Code, comments, in-repo documents, agent instructions: **English**.
- Engineering terms: **retain the English originals** (never translate to Korean).
- User-facing messages (chat replies, friendly progress updates): Korean with a kind tone.

### Context maintenance

- Code or feature changes → write the dated change-log entry directly into the matching weekly archive `<stack>/CODEBASE/YYYY-W##.md` (compute the ISO 8601 KST week from today's date). The master per-stack `CODEBASE.md` keeps invariants `(a)..(z)..` + Index of archives; do NOT add inline dated entries to the master. The root `CODEBASE.md` is updated only when the *family shape* shifts (new stack added, cross-stack data flow changes). See `.claude/memory/feedback_codebase_md_freshness.md` for the cascade rule and the operator's lock-in, and the weekly archive rotation rule under §6 below.
- Design decisions → update `SYSTEM_DESIGN.md` (backend) or `FRONT_DESIGN.md` (frontend). The root `DESIGN.md` is a TOC; update it only when the design-doc split itself changes.
- Project state / decision changes → update `PROGRESS.md` + `doc/history.md` (Parent's responsibility).
- Global behavioral preferences → update `.claude/memory/` (Parent's responsibility).
- Never write long analysis directly into `CLAUDE.md`; create a dedicated document and link to it.

### NEXT_SESSION.md is a cache, not a SSOT

- `NEXT_SESSION.md` is the cold-start cache: it summarises what's queued so a new session can hit the ground without opening every SSOT file. SSOT documents (PROGRESS.md, doc/history.md, .claude/memory/, per-stack CODEBASE.md) are RAM; NEXT_SESSION.md is cache.
- The 3-step absorption routine: (1) read the queued task in NEXT_SESSION.md, (2) record outcomes in the relevant SSOT(s) at session-close, (3) prune the absorbed item from NEXT_SESSION.md. The file is rewritten as a whole at session-close, not patched in place piece-by-piece across the session.
- See `.claude/memory/feedback_next_session_cache_role.md` for the operator-locked routine and rationale.

### Cascade-edit rule for hierarchical docs

- A change in a leaf (per-stack CODEBASE.md, SYSTEM_DESIGN, FRONT_DESIGN) is its own complete update — the leaf is the SSOT.
- A change that genuinely shifts the *shape* of the family (new stack, renamed module, changed cross-stack arrow, new top-level design doc) updates every affected level in the same commit. No half-cascade.
- Reviewers (Mode-B) should treat a root-level update without a leaf counterpart, OR a leaf update that contradicts the root scaffold, as a Critical finding.
- **Weekly archive rotation** (issue#34, 2026-W19 lock): per-stack `CODEBASE.md`, root `PROGRESS.md`, and `doc/history.md` keep ONLY their scaffold/invariants + Index of weekly archives. Dated entries live in `<stem>/YYYY-W##.md`. When writing a new dated entry during a session, append it directly to the matching weekly archive (compute ISO 8601 KST week from today's date — e.g., 2026-05-05 → `2026-W19.md`). If the week's archive does not yet exist, create it with the standard header (`# <stack>/CODEBASE.md — 2026-W## (YYYY-MM-DD → YYYY-MM-DD KST)` + `Archived weekly. Master: [../<file>.md](../<file>.md).` + `---`) and add the row to the master Index. This is a **leaf-only** routine operation — no root cascade.

### Date + time stamps in date-bearing SSOT entries

The team often runs **multiple sessions per day** (early morning / morning / afternoon / evening / late-night). Date alone is not a unique session identifier — every date-bearing entry MUST carry a KST (GMT+9) **time** in addition to the date so sessions on the same day can be ordered and distinguished.

Format conventions:

- `PROGRESS.md` "Session log" entries: `### 2026-04-29 (afternoon — 14:00–16:34 KST, third close)` or similar bucket+time-range form. The bucket label (early morning / morning / afternoon / evening / late-night) sits next to the explicit KST range.
- `doc/history.md` per-session blocks: `## 2026-04-29 (오후 — 14:00–16:34 KST, 세 번째 close)` matching the human-readable Korean convention already used (`새벽/오전/오후/저녁/심야`) plus the explicit KST window.
- `CODEBASE.md` change-log entries: `### 2026-04-29 16:34 KST — <one-line summary>` — point-in-time stamp, not a range, since these mark the moment the invariant text was written.
- `NEXT_SESSION.md` "third close" / "second close" suffix patterns: include the KST closing time in the header subtitle, e.g., `> Refreshed 2026-04-29 16:34 KST (third close)`.
- Plan files under `.claude/tmp/`: include KST timestamp in the Mode-A / Mode-B fold sections (`### Mode-A review fold (2026-04-29 14:30 KST)`).
- Memory files under `.claude/memory/`: when the body cites a date, append the KST time so future-you can disambiguate.

When converting from the host's clock, use `TZ='Asia/Seoul' date '+%Y-%m-%d %H:%M KST'`. The Pi 5 production host is already on KST so `date` returns the right value directly.

Why this matters: a single day frequently spans 2–3 distinct sessions with different scope (operator HIL, planner runs, writer kickoffs). Without time stamps, a future cold-start cannot tell which `2026-04-29` block describes the state being inherited.

### Issue labelling — `issue#N` / `issue#N.M` decimal scheme

When labelling a new work unit (bug, feature, follow-up) discovered during a session, use the following operator-locked convention:

- **`issue#N`** — distinct sequential integer for an independent work unit (e.g., `issue#3`, `issue#4`, `issue#5`). Pick the next free integer at the time of writing.
- **`issue#N.M`** — decimal sub-issue for tightly-coupled follow-ups stacked on parent `issue#N` (e.g., `issue#2.1`, `issue#2.2`).
- **Greek letters (α, β, γ, ε, ζ) are deprecated** — typing-unfriendly on KR/EN keyboards. Do not introduce new ones; existing references in older docs may stay as historical artefacts.
- **Feature codes** (`B-MAPEDIT`, `B-MAPEDIT-2`, `B-MAPEDIT-3`, etc.) are a separate axis from issue numbers and stay as-is — they describe the *feature surface*, while `issue#N` describes the *work unit*.

Apply the label consistently across: NEXT_SESSION.md TL;DR, plan files under `.claude/tmp/`, PR titles, commit messages, per-stack `CODEBASE.md` change-log entries, and design-doc cross-references.

The currently active list (and the next free integer) is tracked in `NEXT_SESSION.md` — this CLAUDE.md section is the SSOT for *why* the scheme exists, not *what's in flight*.

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

## 8. Deployment + PR workflow (operator-driven)

After Parent (or any contributor) opens a PR, the **operator** drives a standard install → HIL → merge pipeline on `news-pi01`. Parent does not auto-deploy — every install step is operator-initiated, mirroring the broader "every cold-path update is operator-initiated" rule.

### Standard pipeline

```text
PR opened
  ↓
1. Fetch + checkout the PR branch on news-pi01
  ↓
2. Build per stack (see matrix)
  ↓
3. Deploy per stack (see matrix)
  ↓
4. Operator HIL — drive the SPA / trigger the changed scenario in a browser
  ↓
5. Merge → `gh pr merge <N> --squash --delete-branch`
  ↓
6. Local main sync → `git switch main && git pull --ff-only origin main`
```

### Stack-deploy matrix

| Stack touched | Build (in repo tree) | Deploy (to `/opt`) | Service restart |
| --- | --- | --- | --- |
| `godo-frontend` only | `cd godo-frontend && npm install && npm run build` | `sudo rsync -a --delete /home/ncenter/projects/GODO/godo-frontend/dist /opt/godo-frontend/` | none — FastAPI `StaticFiles` reads disk; browser hard-reload (Ctrl+Shift+R) is enough |
| `godo-webctl` only | `cd godo-webctl && uv sync --no-dev` (only if `pyproject.toml` changed) | `sudo rsync -a --delete --exclude='.venv' --exclude='__pycache__' /home/ncenter/projects/GODO/godo-webctl/ /opt/godo-webctl/` then `cd /opt/godo-webctl && sudo -u ncenter uv sync --no-dev` | `sudo systemctl restart godo-webctl` |
| `production/RPi5` (tracker) | `bash production/RPi5/scripts/build.sh` | `sudo bash production/RPi5/systemd/install.sh` (idempotent — rsyncs binary + `share/config_schema.hpp` mirror, polkit, units, env templates) | `sudo systemctl restart godo-tracker` (or via SPA System tab Restart, per the operator service-management policy) |
| Multi-stack PR | each of the above | each of the above | webctl + tracker as touched |

### Critical rsync detail — trailing slash

`rsync -a SOURCE DEST` semantics depend on the SOURCE trailing slash:

- ✅ `rsync -a /…/godo-frontend/dist /opt/godo-frontend/` — **dist itself** lands at `/opt/godo-frontend/dist/`. Correct, because `GODO_WEBCTL_SPA_DIST=/opt/godo-frontend/dist`.
- ❌ `rsync -a /…/godo-frontend/dist/ /opt/godo-frontend/` — **contents** of dist land at `/opt/godo-frontend/{index.html,assets,…}`, AND `--delete` wipes the `dist/` subdirectory if it existed. Breaks the SPA: webctl looks at `/opt/godo-frontend/dist/`, finds nothing.

Recovery from the broken case is the same correct command — `--delete` cleans the stray top-level files and recreates `/opt/godo-frontend/dist/`.

### HIL verification (operator)

Each PR's commit message / PR body documents the golden-path HIL scenario. Generic checklist:

- Hard-reload the SPA (Ctrl+Shift+R) so the new hashed bundle loads.
- DevTools Network tab confirms the new endpoint / cadence is live.
- Drive the scenario described in the PR body. Verify the expected behaviour change happens without a manual reload.
- For tracker-side changes: `journalctl -u godo-tracker -n 50` immediately after restart to confirm clean boot (no segfault, no `clear_pending_flag` panic, no AMCL convergence regression).

### Merge etiquette

- `gh pr merge <N> --squash --delete-branch` — squash keeps `main` history one-PR-per-line; `--delete-branch` removes the origin branch automatically.
- After merge: `git switch main && git pull --ff-only origin main`. Then optionally `git branch -d <merged-branch>` to clean the local ref.
- Merge order matters when one PR's commit message references files from another PR's branch (e.g., a fix PR citing a memory file added by a docs PR). Merge the prerequisite first so the references resolve on `main`.

### Pre-deploy traps

1. **`/var/lib/godo/tracker.toml` ↔ branch `Config` compatibility** — when the deploying branch's `production/RPi5/src/core/config_schema.hpp` lacks a key already present in the live `tracker.toml`, the tracker rejects the file at parse time and systemd auto-restart loops. Strip the unknown key first OR stage the deploy. Reference: `.claude/memory/feedback_toml_branch_compat.md`.
2. **godo-tracker is NOT `enable`d** — operator starts/stops/restarts via the SPA System tab. Do not `systemctl enable godo-tracker` casually. Reference: `.claude/memory/project_godo_service_management_model.md`.
3. **Working tree shared between shells on news-pi01** — Parent's open shell may sit on a different branch than the operator's deploy shell. Both share `/home/ncenter/projects/GODO/`; a `git switch` in either shell reshapes the working tree both see. Coordinate before destructive operations. Reference: `.claude/memory/feedback_check_branch_before_commit.md`.

---

## 9. Open questions

| # | Question | Status | Blocks |
| --- | --- | --- | --- |
| Q4 | How much do chroma-studio fixtures (walls, TV trolleys, chairs, speakers) affect ICP/AMCL accuracy | To be measured empirically in Phase 1 | Phase 2 |
| Q5 | Final UE-side error bound (target ≤ 1–2 cm) | Determined by integration test | Phase 5 |
| Q6 | Trigger UX (physical button vs. network command) | **Resolved (2026-04-24)**: both sources, single `std::atomic<bool>` primitive — details in [SYSTEM_DESIGN.md §6.1.3](./SYSTEM_DESIGN.md) | — |
| Q7 | FreeD merge location | **Resolved (2026-04-21)**: unified inside the RPi 5 C++ binary | — |
| B | Coordinate-setup method | **Resolved (Phase 0)**: pre-built map + AMCL, see [SYSTEM_DESIGN.md §5](./SYSTEM_DESIGN.md) | — |
| C | Compute pipeline | **Resolved (Phase 0)**: RPi 5 native C++ | — |

### Confirmed facts (for reference)

- **The base does not rotate.** Only the LiDAR rotates (with the pan head). The dolly wheels are always parallel, making physical base rotation very hard.
- **Origin = base position at calibration**; must be re-settable.
- People move below LiDAR height; dynamic objects visible to the LiDAR are mainly the crane itself and the studio doors.

---

## 10. Reference documents

### Root navigation hubs

- → **[CODEBASE.md](./CODEBASE.md)** — cross-stack scaffold + module roles + cross-stack data flow + pointers to per-stack CODEBASE.md files.
- → **[DESIGN.md](./DESIGN.md)** — TOC for the design SSOTs (SYSTEM_DESIGN + FRONT_DESIGN) + cross-doc orientation.

### Design SSOTs (leaves)

- → **[SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md)** — final topology, data flow, module layout, mapping workflow (Docker + ROS 2 Jazzy + slam_toolbox), AMCL overview, 59.94 fps RT design, phase plan, failure scenarios, and the Windows handoff guide.
- → **[FRONT_DESIGN.md](./FRONT_DESIGN.md)** — frontend SSOT for the operator SPA (page contracts, route map, auth model, component composition).

### RPLIDAR C1 deep dive (Phase 0 output)

→ **[doc/RPLIDAR/RPLIDAR_C1.md](./doc/RPLIDAR/RPLIDAR_C1.md)** — measurement principle, performance specs, UART protocol, SDK and Python bindings, root-cause analysis for "why raw Python data was noisy", MCU/SBC compatibility matrix, chroma-studio suitability, product-line positioning.

### Others

- [doc/Embedded_CheckPoint.md](./doc/Embedded_CheckPoint.md) — embedded reliability checklist.
- [PROGRESS.md](./PROGRESS.md) — cross-session progress state (English, technical).
- [doc/history.md](./doc/history.md) — cross-session narrative (Korean).
