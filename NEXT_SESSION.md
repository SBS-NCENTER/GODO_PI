# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-05 06:30 KST (twenty-third-session close — issue#30 PR #84 is OPEN; HIL surfaced rotation direction bug + mapping pipeline open question + sidecar misclassification, deferred to twenty-fourth session for clean coupled fix).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-05 06:30 KST)

1. **★ issue#30 — rotation direction bug + mapping convention coupled fix** (NEW, top priority twenty-fourth-session). PR #84 OPEN with full backend + frontend implementation merged-ready BUT operator HIL on news-pi01 surfaced 3 findings; operator chose to defer all to next session for coupled investigation rather than partial fix that might "더 꼬일 수도". Spec at `.claude/memory/project_issue30_hil_findings_2026-05-05.md` — **MUST READ before any code touch**.
   - **Finding 1**: `map_transform.py:_affine_matrix_for_pivot_rotation` rotates bitmap CCW for typed +θ; lock requires CW. 1-line fix (negate `theta_rad` at call site). Will require golden-bytes test rewrite for `test_affine_matrix_golden_4x4_theta45`.
   - **Finding 2 (★ blocking Finding 1)**: Mapping pipeline rotation convention. Operator rotated LIDAR initial position 90° CCW between 3 fresh pristine maps (`05.05_v1/v2/v3`); SPA showed map content rotating CCW too (expected CW per slam_toolbox world-frame=initial-pose convention). Plus PGM mapping-preview vs SPA differ by 90°. Likely SAME root cause as Finding 1 (CW↔CCW convention drift in driver/launch). Investigate Finding 2 BEFORE patching Finding 1 to avoid double-flipping.
   - **Finding 3**: `recovery_sweep` mis-classifies pristine maps (no derived-pattern filename) as `kind=synthesized`. All 3 fresh pristines got bogus sidecars on first webctl restart. Fix in PR #84 inline (small).
   - Backup of 3 HIL-test pristines preserved at `/home/ncenter/maps_backup_2026-05-05_pre_issue30_debug/` (3 PGM + 3 YAML + 3 sidecar) so any destructive op can be reverted.

2. **issue#30.1 — backlog from Mode-B round 2** (non-blocking from PR #84 ship; queued for follow-up):
   - Rewrite or delete tautological `test_compose_matches_d4_affine_pivot_rotation` (Path A/B run with identical inputs; D3↔D4 already covered by sister tests).
   - Surface `lineage.kind` glyph inline in `MapList.svelte` per row (currently visible only inside the modal after click).
   - Address `LineageModal.svelte` Svelte a11y compile-time warning (add `role="presentation"` on inner backdrop OR move keydown handler to `<svelte:window>`).
   - HIL revealed the recovery_sweep pristine misclassification (Finding 3 above) — fold inline in PR #84 rather than queue here.

3. **issue#28.1 — B-MAPEDIT-3 follow-ups** (PR #81 Mode-B Major findings + cleanup, half-day batch). Carryover from twenty-second session:
   - **MA1**: 4 missing pytests around asyncio.Lock + SSE protocol.
   - **MA2**: Move `test_apply_reads_pristine_not_latest_derived` from unit (smoke) to integration (real exercise).
   - **MA3-9**: docstring fixes, unused constant removal, HIL tests, kRadToDeg promotion.
   - **Cleanup**: standalone `<OriginAxisOverlay>` + `<GridOverlay>` component file deletion; `cfg.amcl_origin_yaw_deg` hard-removal; `flat` backward-compat key removal.

4. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Round 2 + Writer + HIL is half-day at broadcasting-room wired LAN. Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`.

5. **issue#11 — Live pipelined-parallel multi-thread** (PAUSED awaiting issue#26 first capture). Round 1 plan + Mode-A round 1 fold preserved at `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`.

6. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment.

7. **issue#4 — AMCL silent-converge diagnostic** — comprehensive HIL baseline through nineteenth-session.

8. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow**. Spec at `/doc/shotoku_base_move_and_recal_design.md`. **Depends on issue#30** (same YAML re-anchor math).

9. **issue#17 — GPIO UART direct connection** (perma-deferred).

10. **Bug B — Live mode standstill jitter ~5cm widening** — analysis-first.

11. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic.

**Next free issue integer: `issue#32`** (issue#30 HIL = open in PR #84; issue#30.1 = backlog; issue#31 candidate = vector map evaluation perma-defer per `/doc/issue30_yaml_normalization_design_analysis.md` §"Vector map alternative considered").

## Where we are (2026-05-05 06:30 KST — twenty-third-session close)

**main = `3ac2821`** — PR #83 (KST timestamps) merged, PR #82 (twenty-second-session docs) merged. Working tree on `docs/2026-05-05-issue30-hil-handoff` for this handoff bundle.

**Open PRs**:
- **PR #84 (issue#30)** — pick-anchored YAML normalization + sidecar SSOT + LineageModal. Branch `feat/issue-30-yaml-normalization`. Pipeline complete (Planner R1-R3 + Mode-A R1-R3 APPROVE + Writer R1-R2 + Mode-B R2 APPROVE WITH MINOR), 195+41+464+48=748 tests green, but **HIL surfaced 3 findings** that warrant coupled fix in twenty-fourth session before merge.
- **PR for this handoff** — `docs/2026-05-05-issue30-hil-handoff` branch, 1 memory entry + MEMORY.md index + NEXT_SESSION.md rewrite. Awaiting commit + push.

**Twenty-third-session merged**: PR #83 (`3ac2821`, 16 files +182/-53) — KST timestamp convention. Branched, HIL'd, merged on news-pi01.

## Live system on news-pi01 (post twenty-third-session, pre-issue#30 deploy revert)

UNCHANGED from twenty-second-session except KST timestamp convention now active.

**KST convention active**: derived map names + backup dirs + ISO timestamps in JSON metadata + godo_smoke session log all use KST via `godo_webctl.timestamps.now_kst()` / `kst_iso_seconds()`.

**PR #84 deploy state**: operator deployed PR #84 to news-pi01 for HIL. Live `/opt/godo-webctl/` + `/opt/godo-frontend/` may carry the issue#30 changes; fresh `05.05_v1/v2/v3` pristine maps in `/var/lib/godo/maps/` exercised the new pipeline. **The 3 sidecar JSON files in maps/ are bogus (Finding 3)**; operator may want to manually `rm` them before next mapping session.

**Decision needed at twenty-fourth-session opening**: should we revert news-pi01 to main (pre-issue#30) so existing pristines aren't muddied with synthesized sidecars? Or leave deployed since fix is incoming? Operator preference TBD.

## Quick memory bookmarks (★ open these first on cold-start)

This session added **1 NEW memory entry** + updated MEMORY.md index:

1. ★ `.claude/memory/project_issue30_hil_findings_2026-05-05.md` — **MUST READ before any issue#30 code touch**. All 3 HIL findings with concrete file:line analysis + 1-line fix proposal + investigation plan for the mapping convention question.

Carryover (still active from prior sessions):
- `feedback_subtract_semantic_locked.md` ★ DELETED in PR #84 commit (superseded by `project_pick_anchored_yaml_normalization_locked.md`).
- `project_pick_anchored_yaml_normalization_locked.md` ★ NEW in PR #84 commit (issue#30 SSOT for pick-anchored semantic).
- `feedback_timestamp_kst_convention.md` (PR #83 lock — KST convention).
- `project_yaml_normalization_design.md` (round-1 spec, superseded by `/doc/issue30_yaml_normalization_design_analysis.md`).
- `project_amcl_yaw_metadata_only.md` (AMCL yaw-blind in cell mapping; sets the architectural shape for issue#30 + Finding 2).
- `project_rplidar_cw_vs_ros_ccw.md` (related to Finding 2; documents prior C++ AMCL bug + frontend fix).
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
4. **`.claude/memory/MEMORY.md`** — full index (~53 entries; 1 added this session).
5. **PROGRESS.md** — current through 2026-05-04 twenty-second-session close.
6. **doc/history.md** — Korean narrative through 스물 두 번째 세션.
7. **★ `.claude/memory/project_issue30_hil_findings_2026-05-05.md`** — twenty-fourth-session entry MUST start here.
8. **`/doc/issue30_yaml_normalization_design_analysis.md`** — issue#30 design SSOT (NEW in PR #84 commit; if PR #84 is reverted, this file is also reverted).
9. **PR #84** — `https://github.com/SBS-NCENTER/GODO_PI/pull/84` (OPEN, contains complete impl awaiting HIL fix-in).

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
- `issue#30` — YAML normalization to (0, 0, 0°) per Apply — **OPEN in PR #84 (HIL fix-in pending)**.
- `issue#31` (candidate) — Vector map representation feasibility study (perma-deferred research per `/doc/issue30_yaml_normalization_design_analysis.md` §"Vector map alternative considered").

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions**:
- `plan_issue_30_yaml_normalization.md` — ★ 1101 lines including all 5 review folds (Planner R1, Mode-A R1, Mode-A R2, Mode-A R3, Mode-B R1, Mode-B R2). Host-local on news-pi01 (`.claude/tmp/` is gitignored). Twenty-fourth-session reads this to get full context of the rounds, decisions, locks, and Mode-B R2 verdict.
- `plan_issue_11_live_pipelined_parallel.md` — Round 1 plan + Mode-A round 1 fold.
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold.

**Delete when convenient** (older plans no longer referenced):
- `plan_issue_28_b_mapedit3_yaw_rotation.md` (PR #81 reference, kept one cycle as issue#30 Planner reference; can drop now since issue#30 plan exists).
- `plan_issue_27_map_polish_and_output_transform.md` (PR #79 reference, three cycles old).
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference, four cycles old).
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference, four cycles old).
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference, four cycles old).

## Tasks alive for next session

- **issue#30 — HIL fix-in (rotation direction + mapping convention + sidecar misclassification)** (TL;DR #1 — top priority, coupled investigation)
- **issue#30.1 — Mode-B round 2 backlog** (TL;DR #2)
- **issue#28.1 — B-MAPEDIT-3 follow-ups** (TL;DR #3 — half-day batch)
- **issue#26 — measurement tool round 2 + Writer + HIL** (TL;DR #4)
- **issue#11 — Live pipelined-parallel** (TL;DR #5 — PAUSED)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #6)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #7)
- **issue#29 — SHOTOKU base-move** (TL;DR #8 — depends on issue#30)
- **issue#17 — GPIO UART migration** (TL;DR #9 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #10)
- **issue#7 — boom-arm angle masking** (TL;DR #11)

## Twenty-fourth-session warm-up note

Twenty-third session was a major multi-stage ship: KST timestamp convention (PR #83 merged) + complete issue#30 implementation (PR #84 OPEN at HIL gate). Issue#30's pipeline was the longest+deepest stack to date — Planner R1 → Mode-A R1 (REWORK MAJOR) → Planner R2 → Mode-A R2 (REWORK MINOR) → Planner R3 → Mode-A R3 (APPROVE) → Writer R1 → Mode-B R1 (REWORK MAJOR — wire-shape showstopper) → Writer R2 → Mode-B R2 (APPROVE WITH MINOR). Operator's HIL caught a sign-flipped AFFINE rotation direction PLUS surfaced a pre-existing mapping pipeline rotation convention question that's likely the same root cause.

The session-close decision per operator: "이 회전 문제들이 거의 동일한 원인인 것 같은데. 어느 한쪽만 수정하면 나중에 더 꼬일 수도 있어. 일단 PR 닫지 말고 바로 다음 세션에 이어서 하는게 좋을 것 같아". Both issues investigated together in twenty-fourth.

**Cold-start sequence for twenty-fourth session**:

1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. **★ Open `.claude/memory/project_issue30_hil_findings_2026-05-05.md`** — the SSOT for what's pending and why. Concrete file:line analysis of all 3 findings.
4. Open `.claude/memory/project_rplidar_cw_vs_ros_ccw.md` — prior CW/CCW convention bug context (related to Finding 2).
5. Open `.claude/tmp/plan_issue_30_yaml_normalization.md` — full plan + 5 review folds for context on the locked semantics.
6. Operator opens session: confirm investigation order (Finding 2 BEFORE Finding 1 to avoid double-flipping). Possibly revert news-pi01 to main first to clean the bogus sidecars before continuing investigation.
7. Investigation steps for Finding 2:
   - Capture single scan with LIDAR in known orientation, log raw beam angles + ROS-published angles to confirm rplidar_ros2 driver CW→CCW conversion sign.
   - Inspect `production/RPi5/docker/` (or wherever `godo-mapping:dev` is built) for slam_toolbox launch + tf_static configuration.
   - Compare PGM mapping-preview (rviz) vs SPA rendering convention.
8. After Finding 2 root-cause clear, decide: bundle into PR #84 OR split as issue#32.
9. Apply Finding 1 fix (1-line `_affine_matrix_for_pivot_rotation` negation) + golden-bytes test rewrite. HIL re-test.
10. Apply Finding 3 fix (recovery_sweep filter to derived-pattern only) + cleanup of bogus sidecars.
11. Mode-B re-review (round 3). Operator HIL re-test. Squash-merge.

**If twenty-fourth-session operator changes priority**: TL;DR #2 (issue#30.1 backlog), #3 (issue#28.1), or #4 (issue#26) could come first. issue#30 fix is operator-locked top priority but operator may pivot.

## Session-end cleanup (twenty-third)

- NEXT_SESSION.md: rewritten as a whole per cache-role rule. Stale TL;DR #1 (issue#30 Planner kickoff) absorbed into PR #84's complete pipeline + HIL findings memory; promoted issue#30 HIL fix-in to TL;DR #1.
- `.claude/memory/`: 1 new entry (`project_issue30_hil_findings_2026-05-05.md`); MEMORY.md index updated.
- `.claude/tmp/plan_issue_30_yaml_normalization.md`: 1101 lines kept host-local for twenty-fourth-session reference.
- `/home/ncenter/maps_backup_2026-05-05_pre_issue30_debug/`: 9 files (3 PGM + 3 YAML + 3 sidecar) preserved as pre-fix snapshot.
- PROGRESS.md / doc/history.md: NOT updated this session (chronicler defers until PR #84 lands; partial-PR docs would be churn).
- Per-stack CODEBASE.md / SYSTEM_DESIGN.md / FRONT_DESIGN.md: NOT updated this session (also gated on PR #84 merge).
- Branches: `feat/issue-30-yaml-normalization` pushed to origin (PR #84 OPEN); `docs/2026-05-05-issue30-hil-handoff` (this file commit) pending push.
