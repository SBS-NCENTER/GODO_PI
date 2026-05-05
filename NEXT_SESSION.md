# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-05 morning KST (twenty-fourth-session close — issue#30 PR #84 MERGED with all 3 HIL findings folded; mapping driver fix migrated from sed-patch to `flip_x_axis: True` runtime parameter after operator caught cumulative-mapping ghosting on the morning sed version).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-05 KST)

1. **issue#30.1 — backlog from PR #84 Mode-B round 2** (non-blocking, queued for half-day batch):
   - Rewrite or delete tautological `test_compose_matches_d4_affine_pivot_rotation` (Path A/B run with identical inputs; D3↔D4 already covered by sister tests).
   - Surface `lineage.kind` glyph inline in `MapList.svelte` per row (currently visible only inside the modal after click).
   - Address `LineageModal.svelte` Svelte a11y compile-time warning (add `role="presentation"` on inner backdrop OR move keydown handler to `<svelte:window>`).

2. **issue#28.1 — B-MAPEDIT-3 follow-ups** (PR #81 Mode-B Major findings + cleanup, half-day batch). Carryover from twenty-second session:
   - **MA1**: 4 missing pytests around asyncio.Lock + SSE protocol.
   - **MA2**: Move `test_apply_reads_pristine_not_latest_derived` from unit (smoke) to integration (real exercise).
   - **MA3-9**: docstring fixes, unused constant removal, HIL tests, kRadToDeg promotion.
   - **Cleanup**: standalone `<OriginAxisOverlay>` + `<GridOverlay>` component file deletion; `cfg.amcl_origin_yaw_deg` hard-removal; `flat` backward-compat key removal.

3. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Round 2 + Writer + HIL is half-day at broadcasting-room wired LAN. Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`.

4. **issue#11 — Live pipelined-parallel multi-thread** (PAUSED awaiting issue#26 first capture). Round 1 plan + Mode-A round 1 fold preserved at `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`.

5. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment.

6. **issue#4 — AMCL silent-converge diagnostic** — comprehensive HIL baseline through nineteenth-session.

7. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow**. Spec at `/doc/shotoku_base_move_and_recal_design.md`. issue#30 dependency now resolved → can resume planning.

8. **issue#17 — GPIO UART direct connection** (perma-deferred).

9. **Bug B — Live mode standstill jitter ~5cm widening** — analysis-first.

10. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic.

**Next free issue integer: `issue#32`** (issue#30 = MERGED in PR #84; issue#30.1 = backlog above; issue#31 candidate = vector map evaluation perma-defer per `/doc/issue30_yaml_normalization_design_analysis.md` §"Vector map alternative considered").

## Where we are (2026-05-05 KST — twenty-fourth-session close)

**main = `af3b6cf`** — PR #84 (issue#30 + 3 HIL fold) MERGED. Includes 4 commits squashed:
- pick-anchored YAML normalization + sidecar SSOT (the original PR #84 body)
- HIL fold v1: driver sed patch + AFFINE sign + recovery_sweep guard + cleanup
- HIL fold v2: yaw direction operator-relock (`+typed θ = visual CCW θ`) + frontend 2-point negate + cropping fix
- HIL fold v3: driver fix migrated from sed to `flip_x_axis: True` runtime parameter (sed broke rf2o cumulative mapping)

**Open PRs**: none on issue#30 path. issue#30 branch deleted on origin.

**Live system on news-pi01**: webctl + frontend + mapping container all on `af3b6cf`. Cumulative mapping verified working with `test_180check_dockercheck_v1` (operator HIL afternoon — both 30° and ~70° (≈90°) yaw rotations produce correct visual + correct cumulative behaviour).

## Twenty-fourth-session merged-PR summary

PR #84 (`af3b6cf`, MERGED): pick-anchored YAML normalization + 3 HIL fold rounds.
- **4 commits in PR** (squash-merged into 1 main commit):
  1. `640b420` — original feat (pick-anchored YAML + sidecar SSOT)
  2. `e865aed` — HIL fold v1 (driver sed + AFFINE -theta + recovery guard)
  3. `b668f26` — operator-relock yaw direction (+typed = visual CCW; frontend 2-point negate)
  4. `f9694e4` — driver fix v2 (sed → flip_x_axis runtime parameter; sed had broken rf2o)
- **Diff**: +5366 / -1409 (+3957 effective after rename collapse)
- **Tests**: webctl 1047/1047 (2 pre-existing flakes deselected); frontend 464/464 + originMath 37/37; RPi5 ctest 48/48
- **Operator HIL verifications**:
  - `test_180check_left_obstacle` (morning): driver 180° point-reflection bug confirmed via wall-position fingerprint
  - `test_180check_after_fix` (afternoon): sed driver fix gave correct single-frame orientation
  - `05.05_v3.20260505-085323-after_fix` (afternoon): cropping bug + yaw direction wrong → relock
  - `05.05_v4`, `05.05_v6` (afternoon late): cumulative mapping ghosting with sed fix → migrate to flip_x_axis
  - `test_180check_dockercheck_v1` (final): everything correct (single-frame + cumulative + 30° yaw + ~70° yaw)

## Quick memory bookmarks (★ open these first on cold-start)

This session updated 3 memory entries (no new entries):

1. ★ `.claude/memory/project_rplidar_cw_vs_ros_ccw.md` — 5-path SSOT for LIDAR angle convention. Mapping driver entry now describes the chosen `flip_x_axis: True` runtime fix + why the sed source-patch was reverted. Read this before touching anything in `godo-mapping/`.
2. ★ `.claude/memory/project_pick_anchored_yaml_normalization_locked.md` — issue#30 lock + new "Yaw rotation sign convention" section locking `+typed θ = visual CCW θ`.
3. ★ `.claude/memory/project_issue30_hil_findings_2026-05-05.md` — full Finding 1/2/3 history with all 3 fix rounds (initial fix → re-lock → flip_x_axis migration).

Carryover (still active from prior sessions):
- `feedback_subtract_semantic_locked.md` — DELETED (superseded by `project_pick_anchored_yaml_normalization_locked.md`).
- `project_pick_anchored_yaml_normalization_locked.md` ★ NEW in PR #84 commit (issue#30 SSOT for pick-anchored semantic + yaw direction lock).
- `feedback_timestamp_kst_convention.md` (PR #83 lock — KST convention).
- `project_yaml_normalization_design.md` (round-1 spec, superseded by `/doc/issue30_yaml_normalization_design_analysis.md`).
- `project_amcl_yaw_metadata_only.md` (AMCL yaw-blind in cell mapping; sets the architectural shape for issue#30 + Finding 2).
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

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §8 Deployment + PR workflow + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UNCHANGED this session.
3. **`DESIGN.md`** (root) — TOC. UNCHANGED.
4. **`.claude/memory/MEMORY.md`** — full index (~52 entries; 0 added, 3 updated this session).
5. **PROGRESS.md** — current through 2026-05-04 twenty-second-session close (chronicler will update for twenty-fourth at session-end).
6. **doc/history.md** — Korean narrative through 스물 두 번째 세션 (chronicler will append twenty-fourth).
7. **`/doc/issue30_yaml_normalization_design_analysis.md`** — issue#30 design SSOT.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 32; issue#31 candidate = vector map evaluation perma-defer); decimal for sub-issues (e.g. `issue#28.1`, `issue#30.1`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

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
- `issue#30` — YAML normalization to (0, 0, 0°) per Apply — **DONE in PR #84 (`af3b6cf`, with 3 HIL fold rounds)**.
- `issue#31` (candidate) — Vector map representation feasibility study (perma-deferred research per `/doc/issue30_yaml_normalization_design_analysis.md` §"Vector map alternative considered").

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions**:
- `plan_issue_30_yaml_normalization.md` — ★ 1101 lines including all 5 review folds (Planner R1, Mode-A R1, Mode-A R2, Mode-A R3, Mode-B R1, Mode-B R2). Host-local on news-pi01 (`.claude/tmp/` is gitignored). Useful reference for issue#29 (SHOTOKU base-move) which inherits a lot of the Q1/Q2 lock material.
- `plan_issue_11_live_pipelined_parallel.md` — Round 1 plan + Mode-A round 1 fold.
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold.

**Delete when convenient** (older plans no longer referenced):
- `plan_issue_28_b_mapedit3_yaw_rotation.md` (PR #81 reference — superseded by issue#30 lock)
- `plan_issue_27_map_polish_and_output_transform.md` (PR #79 reference)
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference)
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference)
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference)

## Tasks alive for next session

- **issue#30.1 — Mode-B round 2 backlog** (TL;DR #1 — half-day)
- **issue#28.1 — B-MAPEDIT-3 follow-ups** (TL;DR #2 — half-day batch)
- **issue#26 — measurement tool round 2 + Writer + HIL** (TL;DR #3)
- **issue#11 — Live pipelined-parallel** (TL;DR #4 — PAUSED)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #5)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #6)
- **issue#29 — SHOTOKU base-move** (TL;DR #7 — issue#30 dependency now resolved)
- **issue#17 — GPIO UART migration** (TL;DR #8 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #9)
- **issue#7 — boom-arm angle masking** (TL;DR #10)

## Twenty-fifth-session warm-up note

Twenty-fourth session was a single-day issue#30 ship + 3 HIL fold rounds. The longest fold round was Finding 2 (driver) which went through 2 attempts: the initial sed-patch produced correct single-frame orientation but broke cumulative mapping via the resulting `[-2π, 0]` non-standard angle range (rf2o's scan-to-scan registration silently degraded → wall-ghosting during operator motion). Root-caused by tracing how `M_PI - angle` keeps angle range conventional and recognising that the upstream driver's `flip_x_axis` runtime parameter does the operationally-equivalent `n/2` index shift. Composing `M_PI - angle` (180° in published angle values) with `flip_x_axis: True` (180° in array indices) gives identity in published-vs-physical correspondence AND preserves the conventional `[-π, π]` range. Final operator HIL (`test_180check_dockercheck_v1`) confirmed all three corrections (single-frame + cumulative + 30° yaw + ~70° yaw).

**Cold-start sequence for twenty-fifth session**:

1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. **★ Open `.claude/memory/project_rplidar_cw_vs_ros_ccw.md`** if touching anything related to LIDAR angles or godo-mapping — this is the load-bearing 5-path SSOT after this session's churn.
4. **★ Open `.claude/memory/project_pick_anchored_yaml_normalization_locked.md`** if touching map_transform / sidecar / OriginPicker — yaw direction lock + bbox/affine inverse-pair invariant.
5. PR #84 history is in `.claude/memory/project_issue30_hil_findings_2026-05-05.md` (3 rounds + final fix details).

**Most likely first task**: TL;DR #1 (issue#30.1 backlog half-day) or TL;DR #2 (issue#28.1 backlog half-day). Operator may pivot to issue#26 / issue#29 if SHOTOKU base-move work becomes urgent.

## Session-end cleanup (twenty-fourth)

- NEXT_SESSION.md: rewritten as a whole per cache-role rule. Stale TL;DR #1 (issue#30 HIL fix-in coupled investigation) absorbed into `project_issue30_hil_findings_2026-05-05.md` with all 3 rounds documented. PR #84 promoted to MERGED.
- `.claude/memory/`: 3 entries updated (`project_rplidar_cw_vs_ros_ccw.md`, `project_pick_anchored_yaml_normalization_locked.md`, `project_issue30_hil_findings_2026-05-05.md`). 0 new entries.
- `.claude/tmp/plan_issue_30_yaml_normalization.md`: 1101 lines kept host-local for next-session reference.
- `/home/ncenter/maps_backup_2026-05-05_pre_issue30_debug/`: 9 files (3 PGM + 3 YAML + 3 sidecar) preserved as pre-fix snapshot — operator may delete after the next mapping session that overwrites them.
- PROGRESS.md / doc/history.md: chronicler will update at session-end.
- Per-stack CODEBASE.md: `godo-mapping/CODEBASE.md` invariant `(k)` rewritten + change log added (morning-sed REVERTED + afternoon-flip_x_axis chosen). `godo-webctl/CODEBASE.md` change log added (Finding 1 + Finding 3 inline notes). UPDATED.
- SYSTEM_DESIGN.md / FRONT_DESIGN.md: chronicler will check.
- Branches: `feat/issue-30-yaml-normalization` deleted on origin (squash-merge with `--delete-branch`); local copy can be cleaned with `git branch -d feat/issue-30-yaml-normalization` after switching to main.
