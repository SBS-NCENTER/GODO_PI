# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-30 13:30 KST (eleventh-session full close — 4 PRs landed in one session: #39 #40 #41 #42; main = `787c986`).
> Cache-role pinned per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-set priority order, refreshed 2026-04-30 13:30 KST)

1. **★ B-MAPEDIT-2 origin pick (dual-input GUI + numeric, P0)** — operator-locked spec at `.claude/memory/project_map_edit_origin_rotation.md`. Two input modes side-by-side, NOT one or the other: (Mode A) click any pixel on the rendered PGM → world-coord pre-fill in numeric fields → that becomes the new world (0,0); (Mode B) type `(x_m, y_m)` directly with absolute/delta toggle for fine reproduction from a measured offset. ~150 LOC. Provisional endpoint `POST /api/map/origin` admin-gated, JSON body `{x_m, y_m, mode: "absolute"|"delta"}`. YAML `origin[0..1]` update only — no bitmap rewrite. Auto-backup of YAML; restart-pending sentinel touched. Suggested branch: `feat/p4.5-track-b-mapedit-2-origin-pick`. **Dual-input is mandatory** — single-input proposals will be flagged as regression.

2. **Silent degenerate-metric audit (Task #6 carryover)** — 10 candidates listed in `.claude/memory/project_silent_degenerate_metric_audit.md`. AMCL one-shot guard for low-information map (`entropy_of_likelihood_field < threshold` or similar) is the highest-severity item. Schedule AFTER B-MAPEDIT-2 lands. Deliverable: per-candidate guard / sanity-check / banner-copy decision.

3. **Wire-shape SSOT pin retrospective** — three instances now (PR-A2 keys envelope + PR #40 Fix 1 multipart dep + PR #40 Fix 2 alpha-tracks-paint). Two angles: (a) regex-extract Python ERR_*/FIELDS tuples from C++ `json_mini.cpp::format_ok_*` (PR-B's `test_godo_process_names_match_cmake_executables` pattern); (b) canvas-PNG round-trip CI step that decodes a real `getMaskPng()` output through Pillow with the same alpha-as-paint semantics; (c) integration tests against a fresh `uv sync --no-dev` venv (would have caught PR #40 Fix 1). Prioritize one of (a) (b) (c) per ROI vs effort; either alone would have caught one of the three regressions.

4. **Admin password rotation** — operator's deferred task: `scripts/godo-webctl-passwd` to rotate the default `ncenter`/`ncenter`. Local-only endpoint OR SSH-shell-only (NOT admin-non-loopback). Likely a follow-up "PR-D" — small (~50 LOC).

5. **Deploy hygiene** — surfaced this session: post-merge deploy must rsync BOTH frontend dist AND webctl src. Currently README documents the manual rsync; consider scripting (`scripts/deploy-rpi5.sh` or similar). Would have prevented the 405-on-stale-backend mistake at 12:11 KST.

6. **B-MAPEDIT-3 map rotation (deferred, dual-input)** — ~250 LOC, lower marginal value vs LOC. Same dual-input rule. Operator suggested **VideoCore VII GPU acceleration** for matrix ops. Spec: `.claude/memory/project_videocore_gpu_for_matrix_ops.md`. Don't attempt without first measuring CPU baseline + POC dispatch.

7. **Pipelined-pattern audit** (carryover) — operator-requested systematic audit per `.claude/memory/project_pipelined_compute_pattern.md`.

8. **Track D-5-Live + Track D-5-P** — research-grade follow-ups. Lower priority.

9. **`test_jitter_ring` flaky test** — observed 1× fail. Investigate at low priority.

## Where we are (2026-04-30 13:30 KST — eleventh-session full close)

**main = `787c986`** — four PRs merged this eleventh session in one continuous run:

| PR | What | Notes |
|---|---|---|
| #39 | **B-MAPEDIT brush erase + auto-backup + restart-required** ★ | New `POST /api/map/edit` admin-gated multipart; `MapMaskCanvas` component; Mode-A 14-item fold + Mode-B F1 fold |
| #40 | **B-MAPEDIT prod hotfixes** | python-multipart runtime dep + getMaskPng alpha bug; +1 vitest regression case; silent-degenerate-metric audit memo bundled |
| #41 | **Map Edit as Map page sub-tab** | Operator HIL request; URL-backed (`/map` Overview, `/map-edit` Edit); System.svelte L180-203 pattern mirrored |
| #42 | **Hierarchical SSOT doc reorg** ★ | New root `CODEBASE.md` + `DESIGN.md`; cascade-edit rule operator-locked; NEXT_SESSION cache-role rule pinned; CLAUDE.md §3 Phases refreshed (was three sessions stale) |

**Open PRs**: 0.

## Live system on news-pi01 (post eleventh-session full close)

- **godo-irq-pin.service**: enabled, auto-start.
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. `python-multipart==0.0.27` installed (from PR #40). Prod venv synced from `pyproject.toml`+`uv.lock`.
- **godo-tracker.service**: installed but NOT enabled per operator service-management policy.
- **`/opt/`**: `/opt/godo-tracker/` (binary), `/opt/godo-webctl/` (rsync'd src + .venv with python-multipart), `/opt/godo-frontend/dist/` (SPA bundle `index-CM6owKJy.js` from PR #41 — Map Edit as sub-tab).
- **polkit**: 14 rules.
- **Active map**: `04.29_v3.pgm` (HIL-validated post-fix with 3 successful brush-erase Applies). 4 backup snapshots in `/var/lib/godo/map-backups/`.
- **Branch**: `main @ 787c986`, working tree clean (after this session-close docs commit).

## Quick memory bookmarks (★ open these first on cold-start)

Eleventh session added **four** new in-repo memory entries; thirteen total active. Open in priority order:

1. `.claude/memory/project_map_edit_origin_rotation.md` — Map Edit family spec (B-MAPEDIT brush + B-MAPEDIT-2 origin + B-MAPEDIT-3 rotation). **Dual-input mandate** is the load-bearing rule for B-MAPEDIT-2 plan.
2. `.claude/memory/project_silent_degenerate_metric_audit.md` — 10 audit candidates where "metric trivially passes when input degenerates" pattern could hide bugs. AMCL all-free → σ_xy=0 was the canonical case found during HIL.
3. `.claude/memory/feedback_codebase_md_freshness.md` — extended this session with **cascade-edit rule** for the new hierarchical SSOT doc layout. Read before any cross-stack PR.
4. `.claude/memory/feedback_next_session_cache_role.md` — **NEW** — NEXT_SESSION.md = cache; 3-step absorb routine (read → record in SSOT → prune); session-close rewrites the file as a whole.
5. `.claude/memory/project_godo_service_management_model.md` — operator's policy: SPA is the SOLE start/stop/restart UI.
6. `.claude/memory/project_config_tab_edit_mode_ux.md` — Config tab View/Edit gate spec.
7. `.claude/memory/project_system_tab_service_control.md` — PR-B spec.
8. `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md` — empirical sweep table, convergence cliff.
9. `.claude/memory/project_pipelined_compute_pattern.md` — variable-scope / CPU-pipeline analogy.
10. `.claude/memory/project_videocore_gpu_for_matrix_ops.md` — RPi 5 GPU offload candidates.

Plus carryover: `project_studio_geometry.md`, `project_lens_context.md`, `project_repo_topology.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `frontend_stack_decision.md`, `reference_history_md.md`, `feedback_claudemd_concise.md`, `project_test_sessions.md`, `project_overview.md`, `project_cpu3_isolation.md`, `project_lidar_overlay_tracker_decoupling.md`, `project_rplidar_cw_vs_ros_ccw.md`.

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases (now refreshed) + §6 Golden Rules (now includes cascade rule + NEXT_SESSION cache-role rule) + §7 agent pipeline.
2. **`CODEBASE.md`** (root, NEW) — cross-stack scaffold + module roles + data flow. First stop for "where does X live".
3. **`DESIGN.md`** (root, NEW) — TOC for SYSTEM_DESIGN + FRONT_DESIGN. First stop for "why does X work this way".
4. **`.claude/memory/MEMORY.md`** — full index of all in-repo memory entries (now ~24 lines).
5. **PROGRESS.md** — current through 2026-04-30 eleventh-session full close.
6. **doc/history.md** — Korean narrative.
7. **`production/RPi5/CODEBASE.md`** invariants tail = `(o)`.
8. **`godo-webctl/CODEBASE.md`** invariants tail = `(aa)` (map_edit sole-owner).
9. **`godo-frontend/CODEBASE.md`** invariants tail = `(u)` (MapMaskCanvas sole-mask-state).

## Throwaway scratch (`.claude/tmp/`)

**Keep until B-MAPEDIT-2 ships**:
- `plan_track_b_mapedit.md` — PR #39 reference (shipped, with §8 Mode-A fold). Canonical example of plan + Mode-A fold pattern; useful when scoping B-MAPEDIT-2 plan.

**Keep for one more cycle, then prune**:
- `plan_pr_b_process_monitor.md` — PR #36 reference.
- `plan_pr_c_config_tab_edit_mode.md` — PR #38 reference.
- `plan_service_observability.md` — PR #27 reference.
- `plan_mapping_pipeline_fix.md` — PR #28 reference.
- `plan_track_d_scale_yflip.md` — PR #29 reference.
- `plan_track_d_3_cpp_amcl_cw_ccw.md` — PR #31 reference.
- `plan_track_d_5_sigma_annealing.md` — PR #32 reference.

**Delete when convenient**:
- Anything pre-2026-04-29 not above.

## Tasks alive for next session

- **B-MAPEDIT-2 origin pick (dual-input)** (TL;DR #1) — top priority.
- **Silent degenerate-metric audit** (TL;DR #2, Task #6).
- **Wire-shape SSOT pin retrospective** (TL;DR #3).
- **Admin password rotation** (TL;DR #4).
- **Deploy hygiene script** (TL;DR #5).
- (deferred) B-MAPEDIT-3 rotation + GPU POC + Track D-5 family + pipelined-pattern audit.
- (low priority) `test_jitter_ring` flake fix.

## Session-end cleanup

- NEXT_SESSION.md: rewritten as a whole at session-close per the new cache-role rule (`.claude/memory/feedback_next_session_cache_role.md`). 3-step absorb routine applied — every TL;DR item from the prior NEXT_SESSION that landed this session has been pruned (B-MAPEDIT brush, Map sub-tab refactor, doc hierarchy reorg).
- PROGRESS.md eleventh-session block extended in place to cover the full 10:08 → 13:30 KST window with all 4 PRs.
- doc/history.md eleventh-session block extended with sub-tab refactor narrative + doc-reorg narrative.
- Per-stack CODEBASE.md files unchanged this session (PRs #41 + #42 had no invariant additions; cascade rule honored — root `CODEBASE.md` was added in #42 as the family-shape shift, leaves untouched).
- `.claude/memory/` gained four new entries this session (origin/rotation spec + degenerate-metric audit + cascade-rule extension + NEXT_SESSION cache-role); MEMORY.md index updated.
- Branches cleaned: `feat/p4.5-track-b-mapedit`, `fix/webctl-multipart-dep`, `feat/map-edit-as-map-subtab`, `feat/doc-hierarchy-reorg` all deleted locally after merge.
