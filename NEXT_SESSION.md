# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-30 22:00 KST (twelfth-session full close — 9 PRs touched main this session: #43 #44 #45 #46 #47 #48 #49 #50 + #51 open; main = `fd87cd1`).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-04-30 22:00 KST)

1. **★ issue#3 — initial pose hint UI (P0)** — Multi-basin yaw fix. test4/test5 HIL screenshots showed AMCL `converged` flag lying: same physical pose, one-shot ≈ 5–10° yaw error, live ≈ 90° yaw error. σ_xy = 0.01 m yet 2m+ overlay error at distance. T-shape studio + low feature density → multi-basin localization. Operator clicks rough position on map → particle initial spread narrowed to chosen basin → 90° false-converge eliminated. Source: `.claude/memory/project_amcl_multi_basin_observation.md`. Builds on PR #46's clickable viewport + `pixelToWorld` math from `originMath.ts`. Backend: extend `/api/calibrate` to accept optional `{seed_x_m, seed_y_m, seed_yaw_deg}`. Frontend: pose-hint click handler on Map page; visual marker; "Calibrate from hint" button.

2. **issue#4 — AMCL silent-converge diagnostic** — Operator observation forced this up. Metric to detect "converged but wrong" cases. Candidates:
   - mean L2 distance from each LiDAR scan dot to the nearest obstacle pixel in PGM (when this is high but σ_xy is low → "겉converged")
   - repeatability: run calibrate N times, σ of pose results
   - multi-basin detector: parallel converges from N seeds, count distinct cluster centers
   Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md` (NEXT_SESSION TL;DR carryover). Schedule AFTER issue#3 lands (issue#4 measures whether issue#3 actually escapes the basin).

3. **issue#5 — Pipelined K-step Live AMCL** — Operator-proposed pattern from `.claude/memory/project_pipelined_compute_pattern.md` applied to live mode. Each scan goes through K iterations distributed across K ticks → per-scan accuracy approaches one-shot quality at near-Live throughput. Does NOT solve multi-basin (separate problem). Schedule after issue#3 + issue#4 confirm AMCL is reliable.

4. **issue#6 — B-MAPEDIT-3 yaw rotation** — Frame redefinition (Problem 2). PGM bilinear resample + YAML `origin[2]`. Dual-input GUI + numeric. ADD sign convention CCW-positive (operator-locked). Spec: `.claude/memory/project_map_edit_origin_rotation.md` §B-MAPEDIT-3. **DO NOT schedule until AMCL is stable** (issue#3 + #4) — applying rotation while AMCL still wobbles is wasted effort (next calibrate flips back to wrong basin and undoes alignment).

5. **issue#7 — boom-arm angle masking (optional)** — issue#4 diagnostic might reveal that the test5 center cluster (small group of cyan dots near pose dot, present in BOTH modes per operator HIL) is a hardware artifact (boom arm intercepting LiDAR rays at certain pan angles). If pan-correlation is confirmed, add cfg option `amcl.exclude_pan_angles_deg` to mask those angles from likelihood matching. Skip otherwise.

6. **PR #51 — issue#2.4 Map page common header** — open + awaiting HIL. Recovers PR #47 components from dead branch + new layout (TrackerControls/LastPoseCard above sub-tabs, ScanToggle right end of sub-tabs row, Overview canvas above MapListPanel). 278 vitest pass, +0.7 kB gzip vs main.

## Where we are (2026-04-30 22:00 KST — twelfth-session full close)

**main = `fd87cd1`** — 8 PRs merged this session:

| PR | issue# | What | Status |
|---|---|---|---|
| #43 | — | B-MAPEDIT-2 origin pick (dual GUI + numeric, ADD sign) | merged |
| #44 | — | B-MAPEDIT-2 minor cleanup (Mode-B M1 + M2) | merged |
| #45 | issue#1 | restart-pending banner refresh after service action | merged |
| #46 | issue#2 | shared map viewport + zoom UX + Map Edit LiDAR overlay | merged |
| #47 | issue#2.1 | Last pose card + Tracker controls — **stacked-PR base bug, never reached main** | dead-merge; recovered by #51 |
| #48 | issue#2.2 | panClamp single-case + pinch zoom + dd348ba sensitivity hotfix | merged + main direct hotfix |
| #49 | — | branch-check-before-commit feedback memory | merged |
| #50 | issue#2.3 | Map Edit overlay/pan/pinch (PR #46 HIL hotfix — duplicate mapCanvas removed) | merged |

**Open PR**: #51 (issue#2.4 Map page common header) — recovers #47 components + new common-header layout. Awaiting operator HIL + merge.

## Live system on news-pi01 (post twelfth-session close)

- **godo-irq-pin.service**: enabled, auto-start.
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. No webctl src changes this session — same `/opt/godo-webctl/` as eleventh-session close.
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. No tracker C++ changes this session.
- **`/opt/`**: `/opt/godo-tracker/` (binary unchanged), `/opt/godo-webctl/` (unchanged), `/opt/godo-frontend/dist/` (rebuilt from PR #43 → #50 sequence; latest hash `index-DfDv6223.js` from PR #50 deploy).
- **polkit**: 14 rules (unchanged).
- **Active map**: `04.29_v3.pgm` (B-MAPEDIT brush-edited, B-MAPEDIT-2 origin-edited at session start; HIL ran on this).
- **Branch**: `main @ fd87cd1`, working tree clean (after this session-close docs commit).

## Quick memory bookmarks (★ open these first on cold-start)

Twelfth session added **three** new in-repo memory entries:

1. ★ `.claude/memory/feedback_two_problem_taxonomy.md` — **AMCL accuracy ⊥ frame redefinition**. Read this before any conversation about "scan ↔ map mismatch" or "(x, y) sent to UE doesn't match my coords". Distinguishes Problem 1 vs Problem 2; B-MAPEDIT-2/3 only address Problem 2.
2. ★ `.claude/memory/project_amcl_multi_basin_observation.md` — test4/test5 HIL: ~90° yaw multi-basin between modes for the SAME physical pose. Drives issue#3 (pose hint) priority. Hardware mount ruled out (operator: ~1cm rotation axis offset, scan dot bands thin); motor spin-up ruled out (code inspection — motor always-on).
3. `.claude/memory/feedback_check_branch_before_commit.md` — Shared-Pi gotcha: operator's `git checkout main` silently switches MY working tree too. Run `git branch --show-current` before staging; read `[main <hash>]` in commit output before pushing. Caught after dd348ba landed on origin/main bypassing PR review.

Plus extended this session:
- `.claude/memory/project_map_viewport_zoom_rules.md` — Rule 1 updated to allow trackpad pinch (synthetic ctrlKey) while keeping scroll-wheel zoom forbidden.
- `.claude/memory/project_map_edit_origin_rotation.md` — B-MAPEDIT-3 (issue#6) sign convention locked to ADD (matches B-MAPEDIT-2).

Carryover (still active):
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `project_repo_topology.md`
- `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`
- `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`
- `project_cpu3_isolation.md`, `frontend_stack_decision.md`, `reference_history_md.md`
- `project_lidar_overlay_tracker_decoupling.md`, `project_rplidar_cw_vs_ros_ccw.md`
- `project_amcl_sigma_sweep_2026-04-29.md`, `project_pipelined_compute_pattern.md`
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`
- `project_silent_degenerate_metric_audit.md`

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases (refreshed) + §6 Golden Rules + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold + module roles.
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN.
4. **`.claude/memory/MEMORY.md`** — full index of all in-repo memory entries (~28 lines).
5. **PROGRESS.md** — current through 2026-04-30 twelfth-session close.
6. **doc/history.md** — Korean narrative.
7. **`production/RPi5/CODEBASE.md`** invariants tail = `(o)` (unchanged this session).
8. **`godo-webctl/CODEBASE.md`** invariants tail = `(ab)` (unchanged this session).
9. **`godo-frontend/CODEBASE.md`** invariants tail = `(ab)` (PR β added; PR #50 issue#2.3 extended `(ab)` clauses but didn't add new letters).

## Naming convention reminder

Operator-locked **issue#N.M** scheme as of this session:
- Sequential integers (issue#1, issue#2, issue#3, ...) for distinct work units.
- Decimal (issue#2.1, issue#2.2, ...) for tightly-coupled follow-ups stacked on a parent issue.
- Greek letters (α, β, γ, ε, ζ) are deprecated for typing-friendliness — operator: "내가 키보드로 로마자 입력해서 답변하기가 어려워서 말이야".
- Feature codes (B-MAPEDIT, B-MAPEDIT-2, B-MAPEDIT-3) are distinct from PR identifiers and stay.

## Throwaway scratch (`.claude/tmp/`)

**Keep until issue#3 ships**:
- `plan_track_b_map_viewport_shared_zoom.md` — PR #46 reference (shipped). Canonical example of plan + Mode-A fold + Parent decision fold pattern; useful when scoping issue#3 plan.

**Keep for one more cycle, then prune**:
- `plan_track_b_mapedit_2_origin_pick.md` — PR #43 reference.
- `plan_track_b_mapedit.md` — PR #39 (eleventh-session) reference.
- `plan_pr_b_process_monitor.md`, `plan_pr_c_config_tab_edit_mode.md`, `plan_service_observability.md` — older references.

**Delete when convenient**:
- Anything pre-2026-04-29 not above.

## Tasks alive for next session

- **issue#3 — initial pose hint UI** (TL;DR #1 — multi-basin direct fix)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #2)
- **issue#5 — Pipelined K-step Live AMCL** (TL;DR #3)
- **issue#6 — B-MAPEDIT-3 yaw rotation** (TL;DR #4 — wait for AMCL stable)
- **issue#7 — boom-arm masking** (TL;DR #5 — optional)
- **PR #51 (issue#2.4)** open — operator HIL + merge

## Session-end cleanup

- NEXT_SESSION.md: rewritten as a whole at session-close per the cache-role rule. 3-step absorb routine applied — every TL;DR item from the prior NEXT_SESSION that landed this session has been pruned.
- PROGRESS.md twelfth-session block added at the top of the session log.
- doc/history.md twelfth-session block added.
- Per-stack CODEBASE.md files: `godo-frontend/CODEBASE.md` updated three times this session (PR #46 invariant `(ab)`, PR #48 wheel-zoom carve-out clause, PR #50 layered-canvas alpha cleanup). Webctl + RPi5 unchanged.
- `.claude/memory/` gained three new entries this session (`feedback_two_problem_taxonomy.md`, `project_amcl_multi_basin_observation.md`, `feedback_check_branch_before_commit.md`); MEMORY.md index updated. Two existing memories extended (zoom rules + B-MAPEDIT-3 sign).
- Branches cleaned: `feat/p4.5-track-b-mapedit-2-origin-pick`, `fix/p4.5-restart-banner-refresh-after-action`, `feat/p4.5-track-b-map-viewport-shared-zoom`, `feat/p4.5-mapedit-controls-parity` (dead), `chore/p4.5-track-b-mapedit-2-minor-cleanup`, `fix/p4.5-pan-clamp-and-pinch-zoom`, `docs/branch-check-feedback-memory`, `fix/p4.5-mapedit-overlay-and-pan-pinch` — all merged + ready for local delete after operator confirms. Open: `feat/p4.5-issue-2.4-map-common-header` (PR #51).
