# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-30 12:35 KST (eleventh-session close — B-MAPEDIT brush erase shipped + 2 prod hotfixes + silent-degenerate-metric audit memo; main = `9c5166e`).
> **B-MAPEDIT brush erase fully functional end-to-end** on news-pi01 (3 successful Apply ops, 4 backup snapshots, healthy PGM histogram, no yaw tripwire warnings post-restart).
> **2 prod regressions fixed in PR #40** (python-multipart dep + getMaskPng alpha=255 bug) — both instances of the cross-language "tests pass + prod breaks" structural gap.

## TL;DR (operator-set priority order, refreshed 2026-04-30 12:35 KST)

1. **★ Map Edit sub-tab refactor (P0)** — operator's HIL request 2026-04-30 12:30 KST: move `/map-edit` from top-level sidebar to a sub-tab inside `/map`, mirroring System tab's Processes / Extended resources sub-tabs (PR-B pattern at `godo-frontend/src/routes/System.svelte:180-203` + CSS at L397+). Frontend-only, ~80 LOC, single PR. Backend zero LOC (`POST /api/map/edit` route stays). Suggested branch: `feat/map-edit-as-map-subtab`.

2. **★ B-MAPEDIT-2 origin pick (dual-input GUI + numeric)** — ~150 LOC, spec at `.claude/memory/project_map_edit_origin_rotation.md`. **Dual-input is mandatory** per operator decision 2026-04-30 11:35 KST: every continuous correction value MUST support GUI click AND numeric entry side-by-side, not one or the other. Provisional endpoint `POST /api/map/origin` admin-gated, JSON body `{x_m, y_m, mode: "absolute"|"delta"}`. YAML `origin[0..1]` update only — no bitmap rewrite. Auto-backup of YAML; restart-pending sentinel.

3. **Doc hierarchy reorg + cascade rule (Task #4 from this session)** — operator-requested 2026-04-30 11:50 KST. Create root `CODEBASE.md` + root `DESIGN.md` as scaffold/TOC linking per-stack files (`production/RPi5/CODEBASE.md`, `godo-webctl/CODEBASE.md`, `godo-frontend/CODEBASE.md`; `SYSTEM_DESIGN.md`, `FRONT_DESIGN.md`). Guardrail: **invariants stay in per-stack files, root contains scaffold + module roles + cross-stack data flow ONLY** (no duplicate invariant text, SSOT/DRY). Add cascade-edit rule + NEXT_SESSION.md cache-role rule to memory + CLAUDE.md. Audit CLAUDE.md for stale content while we're there. Estimated ~200 LOC docs.

4. **Silent degenerate-metric audit (Task #6 — new)** — 10 candidates listed in `.claude/memory/project_silent_degenerate_metric_audit.md`. Schedule AFTER B-MAPEDIT-2 lands. Deliverable: per-candidate guard / sanity-check / banner-copy decision. AMCL one-shot guard for low-information map (`entropy_of_likelihood_field < threshold` or similar) is the highest-severity item.

5. **Wire-shape SSOT pin retrospective (carryover from tenth-session)** — second instance of cross-language wire drift this week (PR-A2 keys envelope + PR #40 Fix 2 alpha-tracks-paint). Two angles to apply: (a) regex-extract the Python ERR_* / FIELDS tuples from `json_mini.cpp::format_ok_*` in C++ source (PR-B's `test_godo_process_names_match_cmake_executables` pattern); (b) canvas-PNG round-trip CI step that decodes a real `getMaskPng()` output through Pillow with the same alpha-as-paint semantics. Either alone would have caught one of the two regressions.

6. **Admin password rotation** — operator's deferred task: `scripts/godo-webctl-passwd` to rotate the default `ncenter`/`ncenter` admin password. Operator decision (PR-C era): rotate via Local-only endpoint OR SSH shell only (NOT via admin-non-loopback). Likely a follow-up "PR-D" — small (~50 LOC). Not blocking.

7. **B-MAPEDIT-3 map rotation (deferred, dual-input)** — ~250 LOC, lower marginal value vs LOC. Same dual-input rule. Operator suggested **VideoCore VII GPU acceleration** for matrix ops. Spec: `.claude/memory/project_videocore_gpu_for_matrix_ops.md`. Don't attempt without first measuring CPU baseline + POC dispatch on a single op.

8. **Pipelined-pattern audit** (Task #9 carryover from tenth-session) — operator-requested systematic audit per `.claude/memory/project_pipelined_compute_pattern.md`.

9. **Track D-5-Live (sigma annealing for Live mode)** + **Track D-5-P (parallel pipelined annealing)** — research-grade follow-ups to D-5. Lower priority.

10. **`test_jitter_ring` flaky test** — observed 1× fail during D-5 build. Investigate at low priority.

11. **Deploy hygiene** — surfaced this session: post-merge deploy must rsync BOTH frontend dist AND webctl src, not just one. Currently README documents the manual rsync; consider scripting (`scripts/deploy-rpi5.sh` or similar) so future sessions don't repeat the 405-on-stale-backend mistake.

## Where we are (2026-04-30 12:35 KST — eleventh-session close)

**main = `9c5166e`** — two PRs merged this eleventh session:

| PR | What | Notes |
|---|---|---|
| #39 | **B-MAPEDIT brush erase + auto-backup + restart-required** ★ | New `POST /api/map/edit` admin-gated multipart; new `/map-edit` SPA route; `MapMaskCanvas` component; Mode-A 14-item fold + Mode-B F1 fold |
| #40 | **B-MAPEDIT prod hotfixes (multipart dep + alpha-tracks-paint)** | python-multipart runtime dep + getMaskPng alpha bug; +1 vitest regression case; silent-degenerate-metric audit memo bundled |

**Open PRs**: 0.

## Live system on news-pi01 (post eleventh-session close)

- **godo-irq-pin.service**: enabled, auto-start.
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. `python-multipart==0.0.27` now installed. Prod venv synced from `pyproject.toml`+`uv.lock` at 12:11 KST.
- **godo-tracker.service**: installed but NOT enabled per operator service-management policy (manual-start via SPA System tab Start button).
- **`/opt/`**: `/opt/godo-tracker/` (binary + helper + config_schema), `/opt/godo-webctl/` (rsync'd source + `.venv` with python-multipart), `/opt/godo-frontend/dist/` (SPA bundle `index-CPi2ceQe.js`, refreshed 12:13 KST with PR #40 alpha fix).
- **polkit**: 14 rules loaded.
- **Active map**: `04.29_v3.pgm` (restored from auto-backup `20260430T031846Z` after the alpha-bug full-FREE nuke; HIL-validated post-fix with 3 successful brush-erase Applies). 4 backup snapshots in `/var/lib/godo/map-backups/`.
- **Branch**: `main @ 9c5166e`, working tree clean (after this session-close docs commit).
- **LAN-IP path**: blocked at SBS_XR_NEWS AP (client-isolation); Tailscale `100.127.59.15` works.
- **Default admin password rotation pending**.

## Throwaway scratch (`.claude/tmp/`)

**Keep until B-MAPEDIT-2 ships**:
- `plan_track_b_mapedit.md` — PR #39 reference (shipped, with §8 Mode-A fold). Keep as the canonical example of plan + Mode-A fold pattern.

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

## Quick memory bookmarks (★ open these first on cold-start)

Eleventh session added **two** new in-repo memory entries; eleven total active. Open in priority order:

1. `.claude/memory/project_map_edit_origin_rotation.md` — **NEW (eleventh session)** — Map Edit family spec (B-MAPEDIT brush + B-MAPEDIT-2 origin + B-MAPEDIT-3 rotation). **Dual-input mandate is the load-bearing rule** for any future B-MAPEDIT-2/-3 plan.
2. `.claude/memory/project_silent_degenerate_metric_audit.md` — **NEW (eleventh session)** — 10 audit candidates where "metric trivially passes when input degenerates" pattern could hide bugs. AMCL all-free → σ_xy=0 was the canonical case found during HIL.
3. `.claude/memory/project_godo_service_management_model.md` — operator's policy: SPA is the SOLE start/stop/restart UI.
4. `.claude/memory/project_config_tab_edit_mode_ux.md` — Config tab View/Edit gate spec.
5. `.claude/memory/feedback_codebase_md_freshness.md` — every implementation task updates relevant CODEBASE.md before commit/merge/push.
6. `.claude/memory/project_system_tab_service_control.md` — PR-B spec.
7. `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md` — empirical sweep table, convergence cliff.
8. `.claude/memory/project_pipelined_compute_pattern.md` — variable-scope / CPU-pipeline analogy.
9. `.claude/memory/project_videocore_gpu_for_matrix_ops.md` — RPi 5 GPU offload candidates.
10. `.claude/memory/project_rplidar_cw_vs_ros_ccw.md` — D-2/D-3 hypothesis history.

Plus carryover: `project_studio_geometry.md`, `project_lens_context.md`, `project_repo_topology.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `frontend_stack_decision.md`, `reference_history_md.md`, `feedback_claudemd_concise.md`, `project_test_sessions.md`, `project_overview.md`, `project_cpu3_isolation.md`, `project_lidar_overlay_tracker_decoupling.md`.

## Quick orientation files for next session

1. **CLAUDE.md** §6 Golden Rules + §7 agent pipeline.
2. **`.claude/memory/MEMORY.md`** — full index of all in-repo memory entries (now 22 lines).
3. **PROGRESS.md** — current through 2026-04-30 eleventh-session block.
4. **doc/history.md** — ditto, Korean narrative.
5. **`production/RPi5/CODEBASE.md`** invariants tail = `(o)` (godo-systemctl-polkit + login1).
6. **`godo-webctl/CODEBASE.md`** invariants tail = `(aa)` (map_edit sole-owner; new this session).
7. **`godo-frontend/CODEBASE.md`** invariants tail = `(u)` (MapMaskCanvas sole-mask-state; new this session).

## Tasks alive for next session

- **Map Edit sub-tab refactor** (TL;DR #1) — top priority.
- **B-MAPEDIT-2 origin pick** (TL;DR #2).
- **Doc hierarchy reorg** (TL;DR #3, Task #4 from this session).
- **Silent degenerate-metric audit** (TL;DR #4, Task #6 from this session).
- **Wire-shape SSOT pin retrospective** (TL;DR #5).
- **Admin password rotation** (TL;DR #6).
- (deferred) B-MAPEDIT-3 rotation + GPU POC + Live annealing + parallel annealing + pipelined-pattern audit.
- (low priority) `test_jitter_ring` flake fix.
- (operational) Deploy script for post-merge rsync of BOTH frontend dist + webctl src.

## Session-end cleanup

- NEXT_SESSION.md itself: refreshed in place 2026-04-30 12:35 KST.
- PROGRESS.md + doc/history.md updated 2026-04-30 12:35 KST with the eleventh-session block (2 PRs).
- All three stack CODEBASE.md files already carry the PR #39 invariant blocks (webctl `(aa)` + frontend `(u)`); production/RPi5/CODEBASE.md unchanged this session.
- `.claude/memory/` gained two new entries: `project_map_edit_origin_rotation.md` + `project_silent_degenerate_metric_audit.md`. MEMORY.md index updated with both bullets.
