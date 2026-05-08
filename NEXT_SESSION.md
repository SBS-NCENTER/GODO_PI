# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-08 ~12:00 KST (thirtieth-session close — issue#37 K=3 gate + issue#36 yaw tripwire elimination shipped via PR #107 (`1779c02`); Round A `amcl.range_min_m` sweep completed on news-pi01 with **4.5 m chosen as production tracker.toml setting** — Bug B "5cm widening" eliminated entirely (~14/min → 0); pose_x σ 7.7→2.44 mm (3.2× improvement); pose_y σ 2.2→2.38 mm (essentially unchanged); yaw_std cliff at 7 m identified as -y wall oblique-beam loss. PR #109 (re-targeted as PR #110 after stacked-PR-base-stale pitfall) ships PHASE0 line `pose_x_m`/`pose_y_m`/`xy_std_m`/`yaw_std_deg` extension + `amcl.range_min_m` cap 2→5→10 m + SHOTOKU Q12 yaw override TBD note).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-08 KST)

1. **★ issue#22 — KLD-sampling adaptive N** (Round B kickoff). Round A characterized Bug B as multi-basin particle-filter degeneracy; 4.5 m hard cutoff (issue#38) eliminates it for current studio geometry. Adaptive N adds the algorithmic robustness layer — KLD divergence detection grows N when posterior widens (disturbance) AND shrinks N during steady state (cache pressure ↓ → RT jitter ↓ further). Empirical motivation from sweep:
   - At 5 m: RT jitter max 37 µs (vs 26-29 µs at 4-4.5 m) due to elevated iters median 18-19. Adaptive N would let cold-path drop iters/N during steady state, reclaiming the cache budget for Thread D.
   - OneShot first-tick still N=5000 fixed (heaviest cold-path burst). Adaptive at OneShot lets convergence end early when KLD bound met.
   - Bug B mitigation BACKUP: if 4.5 m hard cutoff insufficient at a future studio, KLD-grown N during disturbance preserves particle diversity → escapes degenerate state without filter restart.
   - Reuses Round A measurement infra (PR #110's PHASE0 ext) — sigma_xy stddev + pose_x/y stddev are direct issue#22 acceptance metrics.
   - Implementation note: at every Live step, compute KLD bound on (x, y, yaw) bin discretization; clamp N ∈ [N_min, N_max]; pass new N to existing `parallel_for(0, N, fn)` (issue#11 partition logic auto-adjusts). Tier-2 config `amcl.kld_n_min`, `amcl.kld_n_max`, `amcl.kld_eps`, `amcl.kld_z_alpha`, bin sizes (3 keys for x/y/yaw cell discretization). ~500-1000 LOC.
   - **Memory anchor**: `.claude/memory/project_round_a_range_min_m_sweep_2026-05-08.md` (Round A findings + issue#22 motivation update).

2. **issue#19.5 — EDT cache locality / SIMD optimisation** (deferred from 29th-session TL;DR #1; Round A's range_min_m=4.5 reduces beam count which slightly relieves the EDT memory-bandwidth ceiling, but issue#19's measured 1.43× ceiling vs 3× projection is still real and unaddressed). Felzenszwalb 1D EDT NEON / prefetch / transpose-tile / row-major rewrite candidates — bench-driven exploration. Sequence after issue#22 since issue#22 may further reduce EDT relevance via N-shrinking → eval load drop.

3. **issue#13 — distance-weighted AMCL likelihood** (priority DOWN post-Round-A). Operator's `range_min_m=4.5 m` hard cutoff supersedes most of issue#13's down-weight motivation in current studio. Still has value if future studios need distance-dependent weighting (heterogeneous near-features where some are useful and some noise). Standalone single-knob experiment when revisited.

4. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. Phase 5 prep work — measures RPi5↔UE wire-time. Resume when issue#22 Round B winds down.

5. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow + forward kinematics override**. Spec at `/doc/shotoku_base_move_and_recal_design.md`. **Updated this session** with §3.2 forward-kinematics-override path + Q1-Q11 (operator round-2) + Q12 (yaw override TBD pending spec sheet). issue#29 scope SHIFTED from "re-anchor workflow" to "forward kinematics layer" — operator-locked design discussion 30th-session. Spec-sheet collection (TK-53LVR / Ti-04VR boom length, mount geometry, encoder sign convention) is operator-side prerequisite before Plan kickoff.

6. **issue#21 — NEON/SIMD vectorization of `evaluate_scan` per-beam loop**. Pi 5 Cortex-A76 has NEON; bilinear coordinate transform is 4-double-vectorizable. Projected ~2-3× per-particle speedup, orthogonal to issue#11 fork-join + issue#19 EDT (still benefits even with pool active). Lower priority post-issue#22 since adaptive N may reduce eval load enough that NEON's ROI shrinks.

7. **issue#23 — LF prefetch / gather-batch**. `__builtin_prefetch` 4-8 beams ahead OR 4-particle lockstep gather. ~1.5-2× single-core speedup, very orthogonal. Same priority logic as issue#21 — adaptive N first reduces N → reduces this issue's leverage.

8. **issue#7 — boom-arm angle masking** (optional, contingent on issue#4 diagnostic).

9. **issue#17 — GPIO UART direct connection** (perma-deferred).

10. **PR #96 / Phase-0 cleanup decision point**. PHASE0 instrumentation now PROMOTED to first-class diag via PR #110's `pose_x_m`/`pose_y_m`/`xy_std_m`/`yaw_std_deg` field extension — the original "TEMPORARY env-var-gated" framing has been superseded. Cleanup decision: keep `GODO_PHASE0=1` env-var gate (current behavior) OR promote PHASE0 lines to default-on (operator opt-out). Defer to issue#22 HIL when adaptive N stats need same instrumentation.

11. **issue#19.2 / 19.3 / 19.4 (deferred follow-ups, unchanged from 29th)**:
    - issue#19.2 — production-runtime fold-rate telemetry (m2 HIL ask)
    - issue#19.3 — aligned-vs-naive partition 1-shot wallclock A/B (D-bench-2)
    - issue#19.4 — `RUN_SERIAL TRUE` bench harness + strict floor restoration

12. **Future: SPA Config tab search input** (low-priority UX). Verify if `project_config_tab_grouping.md` (issue#15 candidate) covers this or separate.

**Next free issue integer: `issue#39`** (issue#37 K=3 gate DONE in PR #107; issue#36 yaw tripwire DONE in PR #107 squash via #108; issue#38 `range_min_m` cap bumps DONE in PR #110; issue#19.1–.5 reserved decimal sub-issues per CLAUDE.md §6 scheme; issue#35 candidate still tracking — 0 reproductions in 28th-30th sessions).

## Where we are (2026-05-08 ~12:00 KST — thirtieth-session close)

**main HEAD = `1779c02`** — PR #107 (issue#37 K=3 gate + issue#36 yaw tripwire elim squash) merged 2026-05-07 KST. Recent shipping order (most recent first):

- `1779c02` — PR #107 issue#37 K=3 gate + issue#36 yaw tripwire elim (2026-05-07 17:25 KST)
- `0928441` — PR #106 chore(memory) Parent territory (2026-05-07 ~08:30 KST)
- `1af71ee` — PR #105 chronicler 29th-session close (2026-05-07 ~08:20 KST)
- `7a91806` — PR #104 issue#19 main (2026-05-07 ~08:00 KST)

**Open PRs at session-close**: PR #110 (Round A measurement-infra + issue#38 cap bumps + SHOTOKU Q12 doc) — re-targeted from PR #109 after stacked-PR-base-stale pitfall (PR #109 merged into orphan stacked branch `feat/issue-37-pool-k-gate` instead of main). Operator merges PR #110 + this session-close PR (#111) at thirtieth close. Once both merge, main has all 30th-session work.

**Live system on news-pi01**: webctl + frontend + tracker all on PR #110's content (`feat/round-a-prep` HEAD = `e28b258`). Tracker last restarted **2026-05-08 10:48:04 KST** for 4.5 m HIL run + subsequent operator interaction. Mode = Live (operator stopped Live mid-session for analysis but tracker still running). `/var/lib/godo/tracker.toml`:
- `range_min_m = 4.5` (operator decision, validated 53 min Bug B = 0)
- `range_max_m = 12` (default)
- PHASE0 emit = ON (`GODO_PHASE0=1` override.conf still active from 29th-session)

**Production HIL acceptance (Round A 4.5 m × 53 min, n=31,668)**:

- pose_x stddev: **2.44 mm** (vs baseline 7.7 mm, 3.2× improvement)
- pose_y stddev: **2.38 mm** (vs baseline 2.2 mm, essentially unchanged)
- xy_std_m mean: 9.34 mm (within converge cap 15 mm, AMCL stable)
- yaw_std mean: 0.113° (cliff-free; 7 m setting has 0.136° cliff)
- iters median: 17-18 (within phase budget)
- Bug B 30-50 mm: 0.0063% (2 events / 31,668 deltas) ★ — 14/min → 0
- Bug B 50+ mm: **0** (53 min, robust acceptance)
- pool-degraded: 0 ★
- pool-miss-streak: 0 (gate not even tested by spike)
- yaw tripwire: 0 ★ (issue#36 elim verified)
- RT jitter max (UDS get_jitter): 28.8 µs (vs 5 m's 37 µs — 22% lower)
- scan rate: 9.87 Hz (within LiDAR nominal)

## Thirtieth-session merged-PR summary

### PR #107 (`1779c02`, MERGED): feat(issue#37): ParallelEvalPool K=3 consecutive-misses gate (1-Strike → 3-Strike)

- Replace 1-Strike-Out trip with K=3 consecutive-misses gate; reset on success-completion.
- 50 ms range-proportional join deadline UNCHANGED (no `kJoinTimeoutBaseNs` value flip).
- New Tier-1 constant `kConsecutiveMissesGate = 3` + `Impl::consecutive_misses_` atomic counter, single-writer via existing `in_dispatch_` CAS.
- `[pool-miss-streak]` (K-1 absorbed) vs `[pool-degraded]` (K-th trip) log-line shapes — distinct prefix grep.
- `fallback_count_++` relocated INSIDE the K-th trip branch (m1' fold) — K-1 absorbed paths contribute 0.
- Public API surface UNCHANGED — `ParallelEvalSnapshot` 40 B layout pinned.
- **Squash-merged WITH issue#36** (yaw tripwire elim, originally PR #108) — both fixes ship as `1779c02`.
- Pipeline: full (Planner R1 (c1+d) → Mode-A R1 APPROVE → operator pivot → Planner R2 (c2 K=3) → Mode-A R2 APPROVE w/ minor → Writer 3 commits → Mode-B APPROVE clean).
- HIL acceptance ≥6 h Live mode, 0 pool-degraded events ★ (validated 7.96 h × 197K samples).

### PR #108 (`672d203`, MERGED-TO-STACKED-BRANCH): feat(issue#36): eliminate cold_writer yaw tripwire feature (full removal)

- Stacked on `feat/issue-37-pool-k-gate`; operator merged via `gh pr merge 108 --squash --delete-branch` BEFORE PR #107 → squash propagated into PR #107's diff. PR #108's mergeCommit `672d203` lives on the stacked branch lineage; its content reached main via PR #107.
- 3 commits + 1 chore (cstddef cleanup post-Mode-B): function `apply_yaw_tripwire` removed end-to-end, `Config::amcl_yaw_tripwire_deg` field + schema row + plumbing dropped, `HotConfig` sizeof 40→32 B, ~280 LOC delta across 23 files.
- HIL: 26,290 yaw tripwire / 1 h pre-fix → 0 / 5 h post-fix ★.

### PR #110 (`feat/round-a-prep`, OPEN at session-close): feat: Round A measurement-infra + issue#38 range_min cap bump + SHOTOKU Q12 doc note

- Re-target of PR #109 (which merged into orphan stacked branch `feat/issue-37-pool-k-gate`). Same head branch, base = main.
- 4 commits:
  - `e39f266` — PHASE0 line `pose_x_m`/`pose_y_m`/`xy_std_m`/`yaw_std_deg` extension. ~12 LOC. Round A measurement infrastructure.
  - `482689e` — issue#38: `amcl.range_min_m` validation cap 2.0 → 5.0 m. Test added.
  - `3efbfb3` — docs(issue#29): SHOTOKU forward kinematics §3.2 + Q12 yaw override TBD note. operator-side spec-sheet check pending.
  - `e28b258` — issue#38: cap 5.0 → 10.0 m (HIL-driven follow-up after operator's 5 m / 7 m sweep showed need for >5 m headroom).
- Round A sweep evidence baked into commit messages (commit `e28b258` carries the full sweep table).

### PR #111 (this session-close PR — to be opened): docs: 2026-05-08 thirtieth-session close

- Memory: `project_round_a_range_min_m_sweep_2026-05-08.md` (Round A findings + Bug B mechanism + 4.5 m decision rationale + future-studio caveat).
- MEMORY.md index updated.
- NEXT_SESSION.md rewritten as whole (this file).
- chronicler skill output: PROGRESS.md + doc/history.md + per-stack CODEBASE.md + SYSTEM_DESIGN.md + FRONT_DESIGN.md updates documenting 30th-session shipping.

## Quick memory bookmarks (★ open these first on cold-start)

This session ADDED 1 memory entry:

1. ★ **NEW** `.claude/memory/project_round_a_range_min_m_sweep_2026-05-08.md` — Round A `amcl.range_min_m` sweep findings (0.15 / 4 / 4.5 / 5 / 7 m). 4.5 m production decision evidence. Bug B characterized as multi-basin particle filter degeneracy. RT jitter side-finding (5 m has highest jitter due to elevated iters → cache pressure on Thread D). Future studios need their own sweep — 4.5 m is news-pi01-specific.

This session UPDATED 1 existing memory entry:

1. `.claude/memory/project_yaw_tripwire_design_flaw.md` — `(RESOLVED 2026-05-07 — issue#36)` annotation added (in PR #107).

Carryover (still active from prior sessions):

- `project_range_proportional_deadline_pattern.md` ★ — issue#11 + issue#19 instances; K=3 gate added as 30th-session reuse via issue#37 (different mechanism — not deadline scaling but consecutive-miss gate, but same architectural surface).
- `project_pipelined_compute_pattern.md` ★ — issue#11 reference design pattern (still active for Live tracker / FreeD smoother / map activate / Phase 5 UE).
- `project_yaw_tripwire_design_flaw.md` ★ + `project_oneshot_vs_mapedit_origin_yaw.md` ★ — operator-locked physical invariants. Tripwire RESOLVED via issue#36; OneShot-vs-MAPEDIT clarification still load-bearing for operator workflow.
- `feedback_cross_section_consistency_after_round_2_adds.md` ★ — issue#11 §3.7/§4 sibling lesson. Reinforced this session via PR #110 stacked-PR-base-stale pitfall (analogous review-discipline lesson — re-verify base branch state when stacked PR's parent merges).
- `project_amcl_multi_basin_observation.md` ★ — Bug B mechanism characterized this session as PARTICULAR INSTANCE of this pattern. Cross-link added in `project_round_a_range_min_m_sweep_2026-05-08.md`.
- `project_cpu3_isolation.md` — RT hot path isolation. Validated this session: jitter unchanged from baseline (28.8 µs at 4.5 m); cpu3 < 5% busy.
- `project_phase0_instrumentation_pattern.md` ★ — Phase-0 trim pattern. PROMOTED this session (PR #110's PHASE0 ext takes the pattern from "TEMPORARY env-gated" to "first-class default-on diag" via the new pose+sigma fields).
- `project_rplidar_cw_vs_ros_ccw.md` ★ 5-path SSOT (load-bearing for any LiDAR-angle code).
- `project_pick_anchored_yaml_normalization_locked.md` ★ issue#30 SSOT.
- `project_issue30_hil_findings_2026-05-05.md` — full Finding 1/2/3 history.
- `project_pristine_baseline_pattern.md`, `feedback_overlay_toggle_unification.md`.
- `feedback_timestamp_kst_convention.md`, `project_amcl_yaw_metadata_only.md`.
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`, `feedback_ssot_following_discipline.md`, `feedback_deploy_branch_check.md`, `feedback_relaxed_validator_strict_installer.md`, `feedback_post_mode_b_inline_polish.md`, `feedback_verify_before_plan.md`, `feedback_helper_injection_for_testability.md`, `feedback_build_grep_allowlist_narrowing.md`, `feedback_ship_vs_wire_check.md`, `feedback_docstring_implementation_drift.md`, `feedback_manual_maps_backup_pre_hil.md`, `feedback_systemctl_edit_empty_content_no_save.md`.
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`.
- `frontend_stack_decision.md`, `reference_history_md.md`.
- `project_lidar_overlay_tracker_decoupling.md`.
- `project_amcl_sigma_sweep_2026-04-29.md`.
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`.
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`, `project_config_tab_grouping.md`.
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`.
- `project_repo_canonical.md`, `project_tracker_down_banner_action_hook.md`, `project_restart_pending_banner_stale.md`.
- `project_calibration_alternatives.md`, `project_hint_strong_command_semantics.md`, `project_gpio_uart_migration.md`, `project_mapping_precheck_and_cp210x_recovery.md`, `project_uds_bootstrap_audit.md`.
- `project_live_mode_cpu_thrashing_2026-05-05.md`, `project_issue26_measurement_tool.md`.

## Quick orientation files for next session (Round B kickoff)

1. **CLAUDE.md** §6 Golden Rules + §7 Agent pipeline + §8 Deployment.
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UNCHANGED this session.
3. **`DESIGN.md`** (root) — TOC. UNCHANGED this session.
4. **`.claude/memory/MEMORY.md`** — full index (~64 entries; 1 added this session).
5. **PROGRESS/2026-W19.md** — 30th-session block (chronicler output).
6. **doc/history/2026-W19.md** — corresponding Korean narrative.
7. **`production/RPi5/CODEBASE.md`** invariant `(s)` — ParallelEvalPool K=3 gate added this session.
8. **`production/RPi5/CODEBASE/2026-W19.md`** 2026-05-08 entry — Round A sweep + issue#37/#36/#38 shipping.
9. ★ **`.claude/memory/project_round_a_range_min_m_sweep_2026-05-08.md`** — Round A findings; primary anchor for issue#22 Round B kickoff.
10. **`/doc/shotoku_base_move_and_recal_design.md`** §3.2 + Q1-Q12 — Round C prep when issue#29 picked up.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = **39**); decimal for sub-issues; Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

**Reservations from prior sessions + this session** (DO NOT use these integers for new issues):

- `issue#19` — DONE in PR #104 (29th-session).
- `issue#19.1` — `EdtScratch` lifetime hoist into `Amcl` (R5 mitigation; dormant).
- `issue#19.2` — production-runtime fold-rate telemetry.
- `issue#19.3` — aligned-vs-naive partition 1-shot wallclock A/B.
- `issue#19.4` — `RUN_SERIAL TRUE` bench harness.
- `issue#19.5` — EDT cache locality / SIMD optimisation. (deferred from 29th-session TL;DR #1)
- `issue#20` — Track D-5-P (deeper σ schedule for OneShot, staggered-tier).
- `issue#21` — NEON/SIMD vectorization of `evaluate_scan` per-beam loop.
- `issue#22` — Adaptive N (KLD-sampling). **★ Round B kickoff candidate (this-session promotion).**
- `issue#23` — LF prefetch / gather-batch.
- `issue#24` — Phase reduction 3→1 in Live carry (TOML-only).
- `issue#25` — `amcl_anneal_iters_per_phase` 10→5 (TOML-only).
- `issue#26` — Cross-device GPS-synced measurement tool.
- `issue#27` — DONE in PR #79.
- `issue#28` — DONE in PR #81.
- `issue#28.1` — DONE in PR #93.
- `issue#28.2` — DONE in PR #95.
- `issue#29` — SHOTOKU base-move + forward kinematics override. **Spec updated this session with §3.2 + Q12.**
- `issue#30` — DONE in PR #84.
- `issue#30.1` — DONE in PR #87.
- `issue#31` (candidate) — Vector map representation feasibility study.
- `issue#32` — DONE in PR #88.
- `issue#33` — DONE in PR #89.
- `issue#34` — DONE in PR #91.
- `issue#34.1` — DONE in PR #92.
- `issue#11` — DONE in PR #99 (28th-session).
- `issue#36` — DONE in PR #107 squash (via #108) (this session, 30th).
- `issue#37` — DONE in PR #107 (this session, 30th).
- `issue#37.1-.7` — reserved follow-ups (pool sep, trip-recover, c1 deadline raise, EDT-side gate, windowed K-gate, snapshot extension, stress harness).
- `issue#38` — DONE in PR #110 (this session, 30th — `amcl.range_min_m` cap bumps + Round A measurement infra).
- `issue#35` (candidate) — UDS hang after RPLIDAR I/O fallback. Sample size 2 from 27th-session, 0 reproductions in 28th-30th sessions.

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions**:

- `plan_issue_19_edt_parallelization.md` — issue#19 journey reference.
- `plan_issue_11_live_pipelined_parallel.md` — issue#11 journey reference.
- `plan_issue_11_phase0_instrumentation.md` — trim instrumentation reference.
- `plan_issue_28.1_and_doc_hierarchy.md`.
- `plan_issue_26_latency_measurement_tool.md`.
- `plan_issue_30_yaml_normalization.md`.
- `plan_issue_30.1_mode_b_backlog.md`.
- `plan_issue_37_pool_fate_coupling.md` — issue#37 journey including operator pivot R1→R2 + 4-option matrix + Mode-B fold. Reusable template for "operator-pivot mid-pipeline" pattern.
- `plan_issue_36_yaw_tripwire_elimination.md` — issue#36 journey. Reusable for "feature elimination cascade" pattern.
- `phase0_results_long_run_2026-05-07_160813.md` — issue#37 motivation HIL anchor.
- `phase0_overnight_baseline_2026-05-08.log` (gitignored — `/tmp/`) — 8 h × 0.15 m baseline, 197 K samples.
- `phase0_4.5m_53min_2026-05-08.log` (gitignored — `/tmp/`) — Round A production decision evidence.

**Delete when convenient**:

- `plan_issue_28_b_mapedit3_yaw_rotation.md` (PR #81 reference)
- `plan_issue_27_map_polish_and_output_transform.md` (PR #79 reference)
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference)
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference)
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference)

## Tasks alive for next session (thirty-first)

- **★ issue#22 KLD-sampling adaptive N** (TL;DR #1 — Round B kickoff)
- issue#19.5 EDT cache locality / SIMD (TL;DR #2)
- issue#13 distance-weighted likelihood (TL;DR #3 — priority DOWN post-Round-A)
- issue#26 cross-device latency tool round 2 (TL;DR #4 — paused)
- issue#29 SHOTOKU forward kinematics override (TL;DR #5 — spec sheet collection prerequisite)
- issue#21 NEON `evaluate_scan` (TL;DR #6)
- issue#23 LF prefetch (TL;DR #7)
- issue#7 boom-arm masking (TL;DR #8)
- issue#17 GPIO UART (TL;DR #9 — perma-deferred)
- PR #96 Phase-0 cleanup (TL;DR #10 — superseded by PR #110 promotion)
- issue#19.2 / 19.3 / 19.4 (TL;DR #11)
- SPA Config tab search (TL;DR #12)

## Thirty-first-session warm-up note

Thirtieth was an **issue-shipping + HIL-sweep + design-discussion** session (~16 hours wall-clock 2026-05-07 17:00 KST → 2026-05-08 12:00 KST, sleep included):

- Operator brief on session-open: "이제 다음 세션 이어서 진행하자~~ 아까 했던 작업에서 더 테스트를 해보는게 좋을 것 같아서 GODO_PHASE0=1 제거는 아직 안했어".
- Long-run HIL re-capture (~9 h) → pool fate-coupling longevity finding → issue#37 K=3 gate. Full pipeline (Planner R1 c1+d → Mode-A R1 → operator pivot to c2 → Planner R2 → Mode-A R2 → Writer → Mode-B → operator HIL ≥6 h).
- Stacked PR #108 (issue#36) merged into squash via #107, simultaneously: shipping yaw tripwire elimination + K=3 gate as one ship.
- Round A — `amcl.range_min_m` sweep with operator-driven hypothesis refinement: flat-wall hypothesis → 5 m gut → 7 m yaw cliff discovery → 4 m geometric reasoning → 4.5 m sweet spot empirically validated. 53-minute final HIL with Bug B = 0 ★.
- SHOTOKU forward kinematics override design discussion (operator-led during sleep prep) — `/doc/shotoku_base_move_and_recal_design.md` §3.2 + Q12 added.
- Stacked-PR-base-stale pitfall caught at session-close → PR #110 re-target.
- chronicler PR #111 to wrap.

**Cold-start sequence for thirty-first session**:

1. Read `CLAUDE.md` (operating rules).
2. Read this `NEXT_SESSION.md`.
3. ★ Read `.claude/memory/project_round_a_range_min_m_sweep_2026-05-08.md` (primary Round A anchor + issue#22 motivation update).
4. ★ For issue#22 plan kickoff: read `production/RPi5/src/localization/amcl.cpp` (`step()` body, particle resampling, weighted-mean) + `parallel_eval_pool.hpp` (existing partition API for adaptive N integration).
5. PR #107 / #110 / #111 history in `PROGRESS/2026-W19.md` + `doc/history/2026-W19.md` + `production/RPi5/CODEBASE/2026-W19.md`.

**Most likely first task**: TL;DR #1 (issue#22 KLD-sampling adaptive N planning kickoff). PHASE0 measurement infrastructure + Round A baseline (sigma_xy 7 mm / pose σ 2.4 mm) ready as acceptance bar.

## Session-end cleanup (thirtieth — Parent territory follow-up commit)

- This file (`NEXT_SESSION.md`): rewritten as a whole per cache-role rule. Stale TL;DR items absorbed (issue#37 → DONE in PR #107; issue#36 → DONE via squash in #107; issue#38 → DONE in PR #110; Bug B "5cm widening" → RESOLVED via issue#38). New TL;DR #1 elevation (issue#22) reflects post-Round-A priorities.
- `.claude/memory/`: 1 new entry (`project_round_a_range_min_m_sweep_2026-05-08.md`) added in PR #111. `MEMORY.md` Index updated.
- `.claude/tmp/`: NO new plan files this session (all work done via direct Writer briefs after issue#37/#36 plans). `phase0_*.log` backups in `/tmp/` (gitignored, host-local).
- PROGRESS / doc/history: chronicler will write the 30th-session block in PR #111.
- Per-stack CODEBASE.md weekly archives: `production/RPi5/CODEBASE/2026-W19.md` will receive the issue#37 + issue#36 + issue#38 entries via chronicler.
- SYSTEM_DESIGN.md / FRONT_DESIGN.md: chronicler decides if cascade needed (issue#37/#36/#38 invariant `(s)` updates were folded inline in PR #107; this session's main delta is Round A measurement infra + Tier-2 cap bump, both leaf-only).
- Root CODEBASE.md / DESIGN.md: UNCHANGED (no family-shape shift).
- Branches: 3 feature/docs branches handled at close — `feat/round-a-prep` (PR #110 OPEN), `docs/2026-05-08-thirtieth-session-close` (PR #111 OPEN). Stacked-PR-stale ghosts: `feat/issue-37-pool-k-gate` and `feat/issue-36-yaw-tripwire-eliminate` (already deleted on origin via squash-merge --delete-branch).
- Production env hygiene: `range_min_m = 4.5` in `tracker.toml` (operator decision, validated). `GODO_PHASE0=1` override.conf still ON (consider removal at thirty-first session if PHASE0 promoted to default-on).
- Untracked at close: `/tmp/phase0_*.log` backup files (host-local, not committed).
