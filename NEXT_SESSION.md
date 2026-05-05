# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-05 afternoon KST (twenty-fifth-session close — 3 PRs merged: #87 issue#30.1 backlog + #88 issue#32 KST regex/formatter + #89 issue#33 lineage init / backup 맵 이름 column. issue#28.1 deferred to this next session per operator scope decision).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-05 afternoon KST)

1. **★ issue#28.1 — B-MAPEDIT-3 follow-ups** (now top priority — carryover from twenty-second-session, deferred through the 24th + 25th to make room for issue#30 / issue#30.1 / issue#32 / issue#33). Half-day batch from PR #81 Mode-B Major findings + cleanup:
   - **MA1**: 4 missing pytests around asyncio.Lock + SSE protocol.
   - **MA2**: Move `test_apply_reads_pristine_not_latest_derived` from unit (smoke) to integration (real exercise).
   - **MA3-9**: docstring fixes, unused constant removal, HIL tests, kRadToDeg promotion.
   - **Cleanup**: standalone `<OriginAxisOverlay>` + `<GridOverlay>` component file deletion; `cfg.amcl_origin_yaw_deg` hard-removal; `flat` backward-compat key removal.

2. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Round 2 + Writer + HIL is half-day at broadcasting-room wired LAN. Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`.

3. **issue#11 — Live pipelined-parallel multi-thread** (PAUSED awaiting issue#26 first capture). Round 1 plan + Mode-A round 1 fold preserved at `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`.

4. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment.

5. **issue#4 — AMCL silent-converge diagnostic** — comprehensive HIL baseline through nineteenth-session.

6. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow**. Spec at `/doc/shotoku_base_move_and_recal_design.md`. issue#30 dependency resolved (twenty-fourth) → can resume planning.

7. **issue#17 — GPIO UART direct connection** (perma-deferred).

8. **Bug B — Live mode standstill jitter ~5cm widening** — analysis-first.

9. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic.

**Next free issue integer: `issue#34`** (issue#30 / 30.1 / 32 / 33 = MERGED; issue#31 candidate = vector map evaluation perma-defer per `/doc/issue30_yaml_normalization_design_analysis.md` §"Vector map alternative considered").

## Where we are (2026-05-05 afternoon KST — twenty-fifth-session close)

**main = `af5b1bc`** — PR #89 merged. Three back-to-back ships this session (each squash-merged):
- `837d3f2` — PR #87 issue#30.1 (PR #84 Mode-B round 2 backlog: 5 commits → 1)
- `6ad4112` — PR #88 issue#32 (KST backup TS regex + formatter: 2 commits → 1)
- `af5b1bc` — PR #89 issue#33 (Apply-on-pristine lineage init + backup 맵 이름 column: 1 commit)

**Open PRs**: docs/2026-05-05-twenty-fifth-session-close (this PR, after merge → main rolls forward).

**Live system on news-pi01**: webctl + frontend on `af5b1bc`. All three operator HIL scenarios verified pre-merge:
- PR #87: inline lineage glyph appears on derived rows; LineageModal a11y compile-clean.
- PR #88: post-PR-#83 (no-Z) backups are restorable; 로컬 시각 column matches wall clock.
- PR #89: pristine→Apply produces `Generation: 1` + `Parents: [pristine]` (was `0` / `(none)`); Backup table renders `맵 이름` column extracted from `entry.files`.

**Manual maps_dir snapshots taken this session** (per `feedback_manual_maps_backup_pre_hil.md`):
- `/home/ncenter/maps_backup_2026-05-05_tue_pre_issue30.1_hil/` (71 files; pre PR #87 HIL).
- `/home/ncenter/maps_backup_2026-05-05_pre_issue33_hil/` (38 files; pre PR #89 HIL).
- Operator may delete after the next mapping session that intentionally overwrites the layout.

## Twenty-fifth-session merged-PR summary

### PR #87 (`837d3f2`, MERGED): issue#30.1 — PR #84 Mode-B round 2 backlog
- 5 commits squashed: tautological test removal + lineage_kind wire-shape addition + inline glyph + LineageModal a11y split + Mode-B fold (4th `LINEAGE_GLYPHS` entry for `backup` value caught by Mode-B reviewer).
- Diff: +535 / -123, 13 files.
- Tests: webctl 1049/1049 + frontend 468/468 (4 new vitest cases). `npm run build` LineageModal a11y warning gone.
- Pipeline: full (Planner → Mode-A APPROVE WITH FOLDS → Writer → Mode-B APPROVE WITH MINOR → inline Mode-B fold → ship).
- Operator HIL pass.

### PR #88 (`6ad4112`, MERGED): issue#32 — KST backup TS regex / formatter
- 2 commits squashed: docs (manual-backup memory carryover from issue#30.1 morning) + fix.
- Diff: +246 / -22, 9 files.
- Backend: `_BACKUP_TS_PATTERN` regex `Z$` → `Z?$` (1 character — aligns FastAPI Path validator with `map_backup._TS_REGEX`'s pre-existing dual-form acceptance).
- Frontend: extracted `tsToUnix` to `lib/format.ts::backupTsToUnix` (pure helper detecting optional `Z`, choosing UTC vs KST `+09:00`); column header `시점 (UTC)` → `시점 (raw)`.
- Tests: 1 new pytest (no-Z restore round-trip) + 4 new vitest cases (Z-UTC, no-Z-KST, equivalence, malformed→NaN).
- Pipeline: pipeline short-circuit (per `feedback_pipeline_short_circuit.md`) — direct-writer + Parent self-verify, no Planner / no Mode-A / no Mode-B.
- Operator HIL pass.

### PR #89 (`af5b1bc`, MERGED): issue#33 — lineage init + backup map-name column
- 1 commit. Diff: +258 / -3, 8 files.
- Backend: `app.py:801` `parent_lineage = []` → `[pristine_base]`. First Apply now produces `generation: 1` + `parents: [pristine_base]`.
- Frontend: new `lib/format.ts::backupMapNames(files)` pure helper extracting unique map stems from `entry.files`; `<th>맵 이름</th>` column rendered between 로컬 시각 and 파일 수 with monospace + word-break.
- Tests: 1 new pytest pinning the lineage-chain invariant (`generation: 1` + `parents: [pristine_base]`); 5 new vitest cases for `backupMapNames` (full triple, legacy 2-file, .sidecar.json suffix-order guard, multi-map sorted, empty/unknown→[]); 1 component test pinning the rendered column text.
- Pipeline: direct-writer (small surface, 5-LOC core fix + ~50-LOC frontend addition; no explicit short-circuit framing because of coupled UX change).
- Operator HIL pass: pristine→Apply→Generation 1 / Parents [pristine] verified; Backup 맵 이름 column verified.

## Quick memory bookmarks (★ open these first on cold-start)

This session updated 1 new memory entry (in addition to the 3 carryover updates from PR #84 still relevant):

1. ★ **NEW** `.claude/memory/feedback_manual_maps_backup_pre_hil.md` — operator-locked safety net distinct from SPA per-pair backup. Trigger condition: PR touches `maps_dir`-mutating code. Naming: `/home/ncenter/maps_backup_<YYYY-MM-DD>_<context>/`. Verify diff after copy.

Carryover (still active from prior sessions):
- `project_rplidar_cw_vs_ros_ccw.md` ★ 5-path SSOT (load-bearing for any LIDAR-angle code).
- `project_pick_anchored_yaml_normalization_locked.md` ★ issue#30 SSOT for pick-anchored semantic + yaw direction lock.
- `project_issue30_hil_findings_2026-05-05.md` — full Finding 1/2/3 history with all 3 fix rounds.
- `feedback_timestamp_kst_convention.md` (PR #83 lock — KST convention).
- `project_yaml_normalization_design.md` (round-1 spec, superseded by `/doc/issue30_yaml_normalization_design_analysis.md`).
- `project_amcl_yaw_metadata_only.md` (AMCL yaw-blind in cell mapping).
- `project_pristine_baseline_pattern.md`, `feedback_overlay_toggle_unification.md`, `project_pipelined_compute_pattern.md`, `project_cpu3_isolation.md`, `project_amcl_multi_basin_observation.md`, `project_calibration_alternatives.md`, `project_hint_strong_command_semantics.md`, `project_gpio_uart_migration.md`.
- `project_issue11_analysis_paused.md`, `project_issue26_measurement_tool.md`.
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`, `feedback_ssot_following_discipline.md`, `feedback_deploy_branch_check.md`, `feedback_relaxed_validator_strict_installer.md`, `feedback_post_mode_b_inline_polish.md`, `feedback_verify_before_plan.md` (★ MOST-VIOLATED), `feedback_helper_injection_for_testability.md`, `feedback_build_grep_allowlist_narrowing.md`, `feedback_ship_vs_wire_check.md`, `feedback_docstring_implementation_drift.md`.
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`.
- `frontend_stack_decision.md`, `reference_history_md.md`.
- `project_lidar_overlay_tracker_decoupling.md`.
- `project_amcl_sigma_sweep_2026-04-29.md`.
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`.
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`.
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`.
- `project_repo_canonical.md`, `project_tracker_down_banner_action_hook.md`, `project_restart_pending_banner_stale.md`.

**Memory candidate (flagged for Parent next session, NOT yet written)**: regex two-layer drift lesson — when relaxing/transitioning a regex/format consumer, audit ALL parser sites (defence-in-depth layers can drift independently). Distinct from `feedback_relaxed_validator_strict_installer.md`. Surfaced as the issue#32 root cause this session.

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §8 Deployment + PR workflow + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UNCHANGED this session.
3. **`DESIGN.md`** (root) — TOC. UNCHANGED.
4. **`.claude/memory/MEMORY.md`** — full index (~53 entries; +1 added this session).
5. **PROGRESS.md** — twenty-fifth-session block at top (this session's narrative + lessons).
6. **doc/history.md** — 스물 다섯 번째 세션 block at top (Korean narrative).
7. **`/doc/issue30_yaml_normalization_design_analysis.md`** — issue#30 design SSOT (still the load-bearing reference for any sidecar / lineage / pick-anchored work).

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 34); decimal for sub-issues (e.g. `issue#28.1`, `issue#30.1`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

**Reservations from /doc/issue11_design_analysis.md §8** (DO NOT use these integers for new issues):
- `issue#19` — EDT 2D Felzenszwalb parallelization.
- `issue#20` — Track D-5-P (deeper σ schedule for OneShot, staggered-tier).
- `issue#21` — NEON/SIMD vectorization of `evaluate_scan` per-beam loop.
- `issue#22` — Adaptive N (KLD-sampling).
- `issue#23` — LF prefetch / gather-batch.
- `issue#24` — Phase reduction 3→1 in Live carry (TOML-only).
- `issue#25` — `amcl_anneal_iters_per_phase` 10→5 (TOML-only).
- `issue#26` — Cross-device GPS-synced measurement tool.
- `issue#27` — output_transform + SUBTRACT origin + LastOutput SSE — DONE in PR #79.
- `issue#28` — B-MAPEDIT-3 yaw rotation — DONE in PR #81.
- `issue#29` — SHOTOKU base-move + two-point cal-reset workflow.
- `issue#30` — YAML normalization to (0, 0, 0°) per Apply — **DONE in PR #84 (3 HIL fold rounds)**.
- `issue#30.1` — PR #84 Mode-B round 2 backlog — **DONE in PR #87**.
- `issue#31` (candidate) — Vector map representation feasibility study (perma-deferred research).
- `issue#32` — Backup TS regex + frontend formatter KST transition — **DONE in PR #88**.
- `issue#33` — Apply-on-pristine lineage init + backup map-name column — **DONE in PR #89**.

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions**:
- `plan_issue_30.1_mode_b_backlog.md` — issue#30.1 plan + Mode-A fold + Mode-B fold (full 3-pipeline-stage record). Useful reference if a similar Mode-B-backlog cleanup pattern repeats.
- `plan_issue_30_yaml_normalization.md` — 1101 lines including all 5 review folds (issue#30 family). Still load-bearing for issue#29 (SHOTOKU base-move) which inherits a lot of Q1/Q2 lock material.
- `plan_issue_11_live_pipelined_parallel.md` — Round 1 plan + Mode-A round 1 fold.
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold.

**Delete when convenient** (older plans no longer referenced):
- `plan_issue_28_b_mapedit3_yaw_rotation.md` (PR #81 reference — superseded by issue#30 lock)
- `plan_issue_27_map_polish_and_output_transform.md` (PR #79 reference)
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference)
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference)
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference)

## Tasks alive for next session

- **★ issue#28.1 — B-MAPEDIT-3 follow-ups** (TL;DR #1 — half-day batch, top priority)
- **issue#26 — measurement tool round 2 + Writer + HIL** (TL;DR #2)
- **issue#11 — Live pipelined-parallel** (TL;DR #3 — PAUSED)
- **issue#13 — distance-weighted likelihood** (TL;DR #4)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #5)
- **issue#29 — SHOTOKU base-move** (TL;DR #6)
- **issue#17 — GPIO UART migration** (TL;DR #7 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #8)
- **issue#7 — boom-arm angle masking** (TL;DR #9)

## Twenty-sixth-session warm-up note

Twenty-fifth was a single-arc morning session (~2.5 h, 10:30–13:00 KST) that shipped 3 PRs. issue#30.1 went through the full pipeline (Planner → Mode-A → Writer → Mode-B → inline fold). issue#32 was the first time pipeline short-circuit was applied to a HIL-discovery-driven hot-fix (1-character regex + 16-LOC pure helper) — confirmed third application of the rule. issue#33 had a coupled lineage-fix + UX-feature shape so direct-writer without explicit short-circuit framing was the right grain.

Two pre-existing bugs (issue#32 + issue#33) surfaced during PR #87 operator HIL — both adjacent to the issue#30 cascade (KST timestamp transition + lineage chain integrity). Operator's HIL discipline (read modal contents, click restore button, observe behaviour) is the last-line bug detector for production-only paths. Lesson reinforced: structural changes that introduce or transition format conventions need coordinated audit of ALL parser sites.

**Cold-start sequence for twenty-sixth session**:

1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. **★ Open `.claude/memory/feedback_manual_maps_backup_pre_hil.md`** if next PR will touch `maps_dir`-mutating code (issue#28.1's MA1+MA2 may NOT touch maps_dir — verify before proposing snapshot).
4. **★ For issue#28.1**: open `.claude/tmp/plan_issue_28_b_mapedit3_yaw_rotation.md` (the PR #81 plan + Mode-B Major findings list) — that's the source of MA1-9 backlog items.
5. PR #87/#88/#89 history is in this NEXT_SESSION.md plus per-stack CODEBASE.md change-log entries dated 2026-05-05 10:50/11:48/12:04 KST.

**Most likely first task**: TL;DR #1 (issue#28.1 — B-MAPEDIT-3 follow-ups, half-day batch). Operator may pivot to issue#26 / issue#29 if SHOTOKU base-move work becomes urgent.

## Session-end cleanup (twenty-fifth)

- NEXT_SESSION.md: rewritten as a whole per cache-role rule. Stale TL;DR #1/#2 (issue#30.1 + issue#28.1 dual half-day batch) absorbed: issue#30.1 → MERGED in PR #87 (cross-referenced to per-stack CODEBASE entries); issue#28.1 promoted to TL;DR #1 for next session. New issue#32 + issue#33 entries added (both MERGED, in the issue-label reservation table).
- `.claude/memory/`: 1 new entry (`feedback_manual_maps_backup_pre_hil.md`, committed in PR #88). 0 entries updated this session.
- `.claude/tmp/plan_issue_30.1_mode_b_backlog.md`: ~530 lines kept host-local (Planner output + Mode-A fold + Mode-B fold). Useful template for future Mode-B-backlog cleanups.
- `/home/ncenter/maps_backup_2026-05-05_tue_pre_issue30.1_hil/` (71 files) + `/home/ncenter/maps_backup_2026-05-05_pre_issue33_hil/` (38 files): preserved pre-HIL snapshots — operator may delete after next mapping session that intentionally overwrites maps_dir.
- PROGRESS.md / doc/history.md: updated by chronicler this session-close.
- Per-stack CODEBASE.md: each PR added its own change-log entry inline (3 entries on godo-webctl/CODEBASE.md + 3 on godo-frontend/CODEBASE.md, dated 2026-05-05 10:50/11:48/12:04 KST). UNCHANGED by chronicler.
- SYSTEM_DESIGN.md / FRONT_DESIGN.md: no design decisions introduced this session — UNCHANGED.
- Root CODEBASE.md / DESIGN.md: no family-shape shift — UNCHANGED.
- Branches: 3 feature branches squash-merged with `--delete-branch` on origin (chore/issue-30.1-mode-b-backlog, fix/issue-32-backup-kst-timestamp-end-to-end, fix/issue-33-pristine-lineage-and-backup-display); local copies cleaned via `git branch -d`.
