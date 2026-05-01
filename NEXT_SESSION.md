# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-01 14:30 KST (fourteenth-session full close — 3 PRs touched main: #58 #59 #60 + #61 docs; main = `315c631`).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-01 14:30 KST)

1. **★ issue#5 — Live mode pipelined hint (P0, full pipeline)** — Carryover from thirteenth-session lock-in. **Live ≡ pipelined one-shot driven by previous-pose-as-hint, never bare `step()`.** Boot anchors via operator hint (or future automated rough-hint). Each Live tick `t` runs `converge_anneal(hint=pose[t-1])` with σ tight (matches inter-tick crane drift, NOT padded). Full design in `.claude/memory/project_calibration_alternatives.md` "Live mode hint pipeline" section. Architectural impact comparable to issue#3 (PR #54). Drives `cold_writer.cpp` Live branch refactor + new cfg keys (`live_carry_pose_as_hint`, `amcl.live_carry_sigma_*`). **Start with full Planner → Reviewer Mode-A → Writer → Reviewer Mode-B pipeline.**

2. **★ Far-range automated rough-hint (P0, after issue#5)** — Operator-locked production hint-elimination path. Two-stage: stage 1 = rough (x, y, yaw) from far-range LiDAR features (range > ~3 m, where points are stable studio walls/corners); stage 2 = AMCL precise localization seeded by stage 1. Source: `.claude/memory/project_calibration_alternatives.md` "Automated rough-hint via far-range LiDAR features" section. Schedule after issue#5 lands so Live carry-over has the right cold-start.

3. **issue#4 — AMCL silent-converge diagnostic** — Now has thirteenth-session HIL data as baseline (50% perfect / 45% near-perfect / 5% miss post-frame-fix). Metric to detect "converged but wrong" cases. Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

4. **restart-pending banner non-action paths fix (small frontend PR)** — PR #59 (issue#8) fixed action-driven + idle polling via 1 Hz backstop. Remaining: confirm initial-mount path on a fresh tab loads with sentinel cleared correctly. May already be resolved by PR #59 — needs operator HIL re-check before scoping. If still buggy, polling/SSE guard flag spec in `.claude/memory/project_restart_pending_banner_stale.md`.

5. **B-MAPEDIT-2 origin reset (cosmetic)** — `04.29_v3.yaml` origin `[14.995, 26.164, 0]` should reset to SLAM-original `[-10.855, -7.336, 0]` or operator-meaningful value. Frame fix (PR #56) works regardless of sign; this is hygiene only. Operator decides target value.

6. **issue#6 — B-MAPEDIT-3 yaw rotation** — Frame redefinition (Problem 2 per `feedback_two_problem_taxonomy.md`). Operator-locked direction: revisit hint UI's two-point pattern as candidate UX. Spec: `.claude/memory/project_map_edit_origin_rotation.md` §B-MAPEDIT-3.

7. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern.

**Next free issue integer: `issue#10`** (issue#8 + issue#9 shipped this session).

## Where we are (2026-05-01 14:30 KST — fourteenth-session full close)

**main = `315c631`** — 3 PRs merged this session (+ PR #61 docs):

| PR | issue | What | Merge style |
|---|---|---|---|
| #58 | governance | thirteenth-session memory bundle + cold-start refresh + CLAUDE.md §8 Deployment + issue#N labelling | squash |
| #59 | issue#8 | restart-pending banner polling backstop | squash |
| #60 | issue#9 | action-driven mode refresh hook | web UI merge commit |
| #61 | — | fourteenth-session close docs | (PR open at session-close — operator merges) |

**Open PRs**: #61 (docs only — chronicler output for this session).

## Live system on news-pi01 (post fourteenth-session close)

- **godo-irq-pin.service**: enabled, auto-start (unchanged).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. **Updated this session** — `/opt/godo-webctl/` unchanged, but `/opt/godo-frontend/dist/` rebuilt + rsync'd twice (PR #59 deploy → rsync trailing-slash trap → recovery; PR #60 deploy clean).
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. Binary at `/opt/godo-tracker/godo_tracker_rt` unchanged this session (no RPi5/tracker code change).
- **`/opt/godo-frontend/dist/`**: rebuilt from PR #60 source (latest hashed bundle name `index-DTXq8WZy.js`). Anyone re-checking out main and running `npm run build` will see a slightly different bundle hash because of the PR-#60 source content.
- **polkit**: 14 rules (unchanged).
- **`/var/lib/godo/tracker.toml`**: unchanged this session — still empty (carryover from thirteenth-session deploy reset).
- **`/etc/godo/tracker.env`**: contains a now-redundant `GODO_CONFIG_PATH=/var/lib/godo/tracker.toml` line from the PR #56 deploy workaround (cosmetic only — operator can remove anytime; same as install.sh default).
- **Active map**: `04.29_v3.pgm` with origin `[14.995, 26.164, 0]` (queued for cosmetic reset per TL;DR #5).
- **Branch**: `main @ 315c631`, working tree clean (after the chronicler commit).

## Quick memory bookmarks (★ open these first on cold-start)

Fourteenth session added **one** new in-repo memory entry:

1. ★ `.claude/memory/project_tracker_down_banner_action_hook.md` — issue#9 investigation + fix. Convention: service-action handlers (Start/Stop/Restart for the 3 systemd services) call BOTH `refreshMode()` AND `refreshRestartPending()` after a successful POST. Documents that operator-perceived "consistent fast" tracker-down banner clearance was emergent polling-phase alignment, made explicit by PR #60.

Carryover from thirteenth session (now on main via PR #58 merge):
- `project_hint_strong_command_semantics.md`, `feedback_toml_branch_compat.md`, `project_restart_pending_banner_stale.md`
- `project_calibration_alternatives.md` extended with TWO operator-locked direction sections (Live pipeline + far-range rough-hint)

Carryover (still active):
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`
- `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`
- `project_cpu3_isolation.md`, `frontend_stack_decision.md`, `reference_history_md.md`
- `project_lidar_overlay_tracker_decoupling.md`, `project_rplidar_cw_vs_ros_ccw.md`
- `project_amcl_sigma_sweep_2026-04-29.md`, `project_pipelined_compute_pattern.md`, `project_amcl_multi_basin_observation.md`
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`, `project_map_edit_origin_rotation.md`
- `project_repo_canonical.md`

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + **§8 Deployment + PR workflow (NEW this session)** + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold + module roles.
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN.
4. **`.claude/memory/MEMORY.md`** — full index (~33 lines after fourteenth-session addition).
5. **PROGRESS.md** — current through 2026-05-01 fourteenth-session close.
6. **doc/history.md** — Korean narrative.
7. **`production/RPi5/CODEBASE.md`** invariants tail = `(p)` (unchanged this session).
8. **`godo-webctl/CODEBASE.md`** invariants tail = `(ac)` (unchanged this session).
9. **`godo-frontend/CODEBASE.md`** invariants tail = `(ac)` (unchanged this session — issue#8 + issue#9 added change-log entries but no new invariants).

## Issue labelling reminder (now CLAUDE.md SSOT)

Operator-locked **issue#N.M** scheme is now in **CLAUDE.md §6** (was previously in this file). Sequential integer for distinct units; decimal for sub-issues stacked on a parent; Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis. Next free integer: **issue#10**.

## Throwaway scratch (`.claude/tmp/`)

**Keep until issue#5 ships**:
- `plan_issue_3_pose_hint_ui.md` — PR #54 reference. Most thorough plan in repo with both Mode-A AND Mode-B folds + Parent decision folds. Useful when scoping issue#5 (which has comparable architectural impact).

**Keep for one more cycle, then prune**:
- `plan_track_b_map_viewport_shared_zoom.md` — PR #46 reference.
- `plan_track_b_mapedit_2_origin_pick.md` — PR #43 reference.

**Delete when convenient**:
- Older plans (`plan_track_b_mapedit.md`, `plan_pr_b_process_monitor.md`, `plan_pr_c_config_tab_edit_mode.md`, `plan_service_observability.md`).
- Anything pre-2026-04-30 not above.

## Tasks alive for next session

- **issue#5 — Live mode pipelined hint** (TL;DR #1 — P0 full pipeline)
- **Far-range automated rough-hint** (TL;DR #2 — P0 after issue#5)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #3)
- **restart-pending banner non-action paths fix** (TL;DR #4 — verify if PR #59 already covers it)
- **B-MAPEDIT-2 origin reset** (TL;DR #5 — cosmetic)
- **issue#6 — B-MAPEDIT-3 yaw rotation** (TL;DR #6 — revisit two-point UX)
- **issue#7 — boom-arm masking** (TL;DR #7 — optional)

## Session-end cleanup

- NEXT_SESSION.md: rewritten as a whole per the cache-role rule. 3-step absorb routine applied — issue#8 + issue#9 + governance items pruned (now on main and recorded in PROGRESS.md / doc/history.md / per-stack CODEBASE.md / memory). issue#5 + #4 + #6 + #7 + far-range + banner-non-action + origin-reset carry over.
- PROGRESS.md fourteenth-session block added at the top of the session log (PR #61).
- doc/history.md fourteenth-session block added (PR #61).
- Per-stack CODEBASE.md files: `godo-frontend/CODEBASE.md` got two new change-log entries added inline by PRs #59 and #60. webctl + RPi5 CODEBASE.md unchanged this session.
- `.claude/memory/` gained 1 new entry this session (`project_tracker_down_banner_action_hook.md`); MEMORY.md index updated in PR #60 commit.
- Branches cleaned: `fix/issue-8-restart-pending-banner-poll-backstop`, `fix/issue-9-mode-refresh-action-hook`, `docs/2026-05-01-thirteenth-session-cold-start` — all merged + remote-deleted. Local: `git branch -d fix/issue-9-...` ran; `git branch` shows clean state.
- CLAUDE.md sections renumbered: §8 Deployment + PR workflow inserted; old §8 Open questions → §9; old §9 Reference documents → §10.
