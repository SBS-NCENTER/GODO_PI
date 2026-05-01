# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-01 12:30 KST (thirteenth-session full close — 3 PRs touched main: #54 #55 #56 + #57 docs; main = `0b33621`).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-01 12:30 KST)

1. **★ issue#5 — Live mode pipelined hint (NEW shape, P0)** — Operator-locked redefinition during thirteenth-session HIL. **Live ≡ pipelined one-shot driven by previous-pose-as-hint, never bare `step()`.** Boot anchors via operator hint (or future automated rough-hint). Each Live tick `t` runs `converge_anneal(hint=pose[t-1])` with σ tight (matches inter-tick crane drift, NOT padded). Full design in `.claude/memory/project_calibration_alternatives.md` "Live mode hint pipeline" section. Re-frames issue#5 from "deeper step()" to "Live IS pipelined one-shot." Drives `cold_writer.cpp` Live branch refactor + new cfg keys (`live_carry_pose_as_hint`, `amcl.live_carry_sigma_*`).

2. **★ Far-range automated rough-hint (NEW direction, P0)** — Operator-locked production hint-elimination path. Two-stage: stage 1 = rough (x, y, yaw) from far-range LiDAR features (range > ~3 m, where points are stable studio walls/corners — chroma-wall rounded ㄷ, doors, notches); stage 2 = AMCL precise localization seeded by stage 1. Subsumes earlier approaches A (image match) / B (GPU features) / C (pre-marked landmarks) by adding the far-range pre-filter. Maps to AF analogy: stage 1 = phase detection, stage 2 = contrast detection, operator click = manual focus override. Source: `.claude/memory/project_calibration_alternatives.md` "Automated rough-hint via far-range LiDAR features" section. Schedule after issue#5 lands so the Live carry-over has the right cold-start.

3. **issue#4 — AMCL silent-converge diagnostic** — Now has thirteenth-session HIL data as baseline (50% perfect / 45% near-perfect / 5% miss post-frame-fix). Metric to detect "converged but wrong" cases. Candidates: mean L2 distance from each LiDAR scan dot to the nearest obstacle pixel in PGM; repeatability variance over N runs; multi-basin detector via parallel converges. Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`. Schedule after issue#5 to measure both Live pipeline + far-range automation effectiveness.

4. **restart-pending banner real fix (small frontend PR)** — Self-healing hypothesis from twelfth-session dismissed during thirteenth. PR #45 fixed action-driven path; banner still locks on initial mount + non-action paths (cfg edit triggers, idle polling). Real fix: polling/SSE guard flag on initial mount + after every server-side `restart_pending` mutation. Spec: `.claude/memory/project_restart_pending_banner_stale.md`. Operator workaround during HIL: hard reload page.

5. **B-MAPEDIT-2 origin reset (cosmetic)** — `04.29_v3.yaml` origin shifted from SLAM-original `[-10.855, -7.336, 0]` to `[14.995, 26.164, 0]` over twelfth-session origin-pick attempts (4 cumulative ADD picks). Frame fix (PR #56) works regardless of origin sign, but cosmetic reset to SLAM-original or operator-meaningful value is queued. Operator decision: which value to reset to.

6. **issue#6 — B-MAPEDIT-3 yaw rotation** — Frame redefinition (Problem 2 per `feedback_two_problem_taxonomy.md`). Deferred from twelfth-session "until AMCL stable"; AMCL is now stable (PR #56 + #54). Operator-locked direction during thirteenth: revisit hint UI's two-point pattern as candidate UX ("issue#6도 회전 중심 대신 지금처럼 두 점으로 해도 될 것 같은데... 이건 그때 가서 생각해보자"). Spec: `.claude/memory/project_map_edit_origin_rotation.md` §B-MAPEDIT-3.

7. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern. Skip otherwise.

## Where we are (2026-05-01 12:30 KST — thirteenth-session full close)

**main = `0b33621`** — 3 PRs merged this session (+ PR #57 docs):

| PR | issue# | What | Status |
|---|---|---|---|
| #54 | issue#3 | initial pose hint UI for AMCL multi-basin fix (full pipeline; 3-stack) | merged |
| #55 | — | install fix — tracker.toml RW path under systemd sandbox | merged |
| #56 | — | AMCL row-flip PGM at load (frame y-flip bug, latent since project start) | merged |
| #57 | — | thirteenth-session close docs (PROGRESS.md + doc/history.md) | merged |

**No open PRs**.

## Live system on news-pi01 (post thirteenth-session close)

- **godo-irq-pin.service**: enabled, auto-start (unchanged).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. **Updated this session** — `/opt/godo-webctl/` rsync'd from PR #54 source for issue#3 hint key recognition.
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. **Updated this session** — `/opt/godo-tracker/godo_tracker_rt` binary has frame fix (PR #56) + hint kernel (PR #54). `/opt/godo-tracker/share/config_schema.hpp` refreshed via re-run install.sh.
- **`/opt/`**: `/opt/godo-frontend/dist/` rebuilt with PR #54 PoseHintLayer + PoseHintNumericFields + TrackerControls "Calibrate from hint" button (latest hash `index-DH4XLG5Y.js`).
- **polkit**: 14 rules (unchanged).
- **`/var/lib/godo/tracker.toml`**: NEW location per PR #55 install fix; auto-created empty by install.sh; previously held hint σ keys (PATCHed during PR #54 σ probing) but stripped during PR #56 deploy because main-based binary did not yet recognize them. Currently hint σ keys ABSENT — operator can re-set via SPA Config tab when issue#5 work begins.
- **`/etc/godo/tracker.env`**: contains a now-redundant `GODO_CONFIG_PATH=/var/lib/godo/tracker.toml` line from the PR #56 deploy workaround. Same as install.sh's default — operator can remove the line cosmetically; no functional impact.
- **Active map**: `04.29_v3.pgm` with origin `[14.995, 26.164, 0]` (4-cumulative-ADD shifted from SLAM-original; queued for cosmetic reset per TL;DR #5).
- **Branch**: `main @ 0b33621`, working tree clean (after this session-close memory bundle commit).

## Quick memory bookmarks (★ open these first on cold-start)

Thirteenth session added **three** new in-repo memory entries + extended one:

1. ★ `.claude/memory/project_hint_strong_command_semantics.md` — **Hint = operator's strong command, not weak prior**. σ default 0.5 m / 20° operator-locked. AMCL converges INSIDE hint cloud; precision must not degrade when hint is correct. Read this before any AMCL-accuracy proposal that would broaden the search basin (distance-weighted likelihood, etc.) — those need to be opt-in or gated, not change default.
2. ★ `.claude/memory/feedback_toml_branch_compat.md` — **Pre-deploy hygiene**: when deploying any branch whose Config struct lacks a key already present in the runtime TOML, strip the key or stage the deploy. Surfaced during PR #56 deploy when `/var/lib/godo/tracker.toml` carried PR #54 hint keys but PR #56's main-based binary did not yet recognize them → systemd auto-restart loop.
3. `.claude/memory/project_restart_pending_banner_stale.md` — Self-healing hypothesis dismissed; real fix needs polling/SSE guard flag. Drives TL;DR #4 small frontend PR.

Plus extended this session:
- `.claude/memory/project_calibration_alternatives.md` — TWO new sections (Live mode hint pipeline + Automated rough-hint via far-range features). These are operator-locked directions for issue#5 + production automation. Drives TL;DR #1 + #2.

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

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold + module roles.
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN.
4. **`.claude/memory/MEMORY.md`** — full index of all in-repo memory entries (~32 lines after thirteenth-session additions).
5. **PROGRESS.md** — current through 2026-05-01 thirteenth-session close.
6. **doc/history.md** — Korean narrative.
7. **`production/RPi5/CODEBASE.md`** invariants tail = `(p)` (PR #54 issue#3 added invariant `(p)` calibrate-hint atomic publish ordering).
8. **`godo-webctl/CODEBASE.md`** invariants tail = `(ac)` (PR #54 issue#3 added `(ac)` calibrate-hint forward-compat-discipline).
9. **`godo-frontend/CODEBASE.md`** invariants tail = `(ac)` (PR #54 issue#3 added `(ac)` pose-hint-layer-sibling-canvas-discipline).

## Naming convention reminder (carryover from twelfth-session)

Operator-locked **issue#N.M** scheme:
- Sequential integers (issue#1, issue#2, issue#3, ...) for distinct work units.
- Decimal (issue#2.1, issue#2.2, ...) for tightly-coupled follow-ups stacked on a parent issue.
- Greek letters (α, β, γ, ε, ζ) deprecated for typing-friendliness.
- Feature codes (B-MAPEDIT, B-MAPEDIT-2, B-MAPEDIT-3) are distinct from PR identifiers and stay.

## Throwaway scratch (`.claude/tmp/`)

**Keep until issue#5 ships**:
- `plan_issue_3_pose_hint_ui.md` — PR #54 reference. Canonical example of full-pipeline plan with both Mode-A AND Mode-B folds applied + Parent decision folds. Most thorough plan in repo; useful when scoping issue#5 (which has even more architectural impact).

**Keep for one more cycle, then prune**:
- `plan_track_b_map_viewport_shared_zoom.md` — PR #46 reference.
- `plan_track_b_mapedit_2_origin_pick.md` — PR #43 reference.

**Delete when convenient**:
- `plan_track_b_mapedit.md`, `plan_pr_b_process_monitor.md`, `plan_pr_c_config_tab_edit_mode.md`, `plan_service_observability.md` — older references.
- Anything pre-2026-04-30 not above.

## Tasks alive for next session

- **issue#5 — Live mode pipelined hint** (TL;DR #1 — operator-locked NEW shape)
- **Far-range automated rough-hint** (TL;DR #2 — operator-locked NEW direction)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #3 — measures #1+#2 effectiveness)
- **restart-pending banner real fix** (TL;DR #4 — small frontend PR)
- **B-MAPEDIT-2 origin reset** (TL;DR #5 — cosmetic)
- **issue#6 — B-MAPEDIT-3 yaw rotation** (TL;DR #6 — revisit two-point UX pattern)
- **issue#7 — boom-arm masking** (TL;DR #7 — optional)

## Session-end cleanup

- NEXT_SESSION.md: rewritten as a whole at session-close per the cache-role rule. 3-step absorb routine applied — every TL;DR item from the prior NEXT_SESSION (twelfth-session) that landed this session (issue#3) has been pruned. issue#4 + #5 + #6 + #7 carry over with thirteenth-session refinements.
- PROGRESS.md thirteenth-session block added at the top of the session log (PR #57).
- doc/history.md thirteenth-session block added (PR #57).
- Per-stack CODEBASE.md files: all three stacks updated in-line by the underlying PRs. `production/RPi5/CODEBASE.md` invariant tail moved to `(p)`; webctl + frontend invariant tail moved to `(ac)`.
- `.claude/memory/` gained 3 new entries this session (`project_hint_strong_command_semantics.md`, `feedback_toml_branch_compat.md`, `project_restart_pending_banner_stale.md`); `project_calibration_alternatives.md` extended with TWO new operator-locked direction sections (Live pipeline + far-range rough-hint). MEMORY.md index updated in this commit.
- Branches cleaned: `feat/issue-3-pose-hint-ui`, `fix/install-tracker-toml-rw-path`, `fix/amcl-y-flip-frame-convention`, `docs/2026-05-01-thirteenth-session-close` — all merged + ready for local delete. No stuck branches this session.
