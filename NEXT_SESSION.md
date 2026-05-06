# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-06 18:00 KST (twenty-eighth-session close — issue#11 main shipped as PR #99 `64a2abb`; production cold-path 7.34 → 11.52 Hz +57% verified post-fix; range-proportional deadline pattern locked; AMCL deep-dive doc written but kept untracked for separate next-session PR).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-06 18:00 KST)

1. **★ issue#19 — EDT 2D Felzenszwalb 3-way parallelization** (TOP PRIORITY now that issue#11 main is shipped). Reuses issue#11's `ParallelEvalPool` primitive with a `parallel_for_with_scratch<S>` API extension for per-worker `(v, z)` scratch buffers (Mode-A round 1 C6 surfaced this requirement). ~80 LOC: ~30 LOC pool API extension + ~50 LOC EDT integration. Projected lift: 11.52 → ~21 Hz (LF rebuild p50 40 → ~14 ms). LF rebuild is now 46% of TOTAL (40 / 87 ms) post-issue#11 — biggest remaining slice. Plan likely re-uses range-proportional deadline pattern (`project_range_proportional_deadline_pattern.md`) since EDT workload scales with W × H grid size.

2. **AMCL algorithm analysis docs PR** — `/doc/amcl_algorithm_analysis.md` already written this session (853 lines, 11 Parts × 32 sections, file:line cited from main `129ad3f` + branch HEAD; bit-equality 5-step proof + Felzenszwalb 1D EDT decoded + tuning cheat sheet). Operator decision-locked: NOT in PR #99; separate docs PR in next session. **Action**: branch `docs/amcl-algorithm-analysis` from main → commit single file → open PR. Untracked file already at `/home/ncenter/projects/GODO/doc/amcl_algorithm_analysis.md` — just `git add` + commit. ~5 minute task; can be opener for next session.

3. **issue#13 — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Orthogonal to issue#11/19 (modifies `evaluate_scan` body, not the caller); composes with Option C without re-design. Standalone single-knob algorithmic experiment.

4. **issue#35 (still candidate)** — UDS hang after RPLIDAR I/O fallback. Sample size 2 from 27th-session, but NOT reproduced in 28th-session despite build+ctest CPU saturation. Track for next reproduction; investigate `cold_writer.cpp::run_cold_writer` exception path's interaction with `uds_server.cpp` accept loop. Symptom: `ss -lx` `LISTEN 0 0`. Recovery: `systemctl restart godo-tracker`. Medium priority — surfaces only under artificial cpu saturation.

5. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. Independent of issue#11 now (Phase-0 produced the in-tracker breakdown; issue#26 measures the cross-device wire-time only).

6. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow**. Spec at `/doc/shotoku_base_move_and_recal_design.md`. issue#30 dependency resolved (twenty-fourth) → can resume planning anytime.

7. **issue#21 — NEON/SIMD vectorization of `evaluate_scan` per-beam loop**. Pi 5 Cortex-A76 has NEON; bilinear coordinate transform is 4-double-vectorizable. Projected ~2-3× per-particle speedup, orthogonal to issue#11 fork-join (still benefits even with pool active). Compatible with future issues.

8. **issue#22 — KLD-sampling adaptive N**. The "A" of AMCL — adaptive sample size. Reduces N during Live steady-state (often N≈100 sufficient once cloud has tightened). Big payoff potentially exceeds issue#11+#19 combined; intricate machinery.

9. **issue#23 — LF prefetch / gather-batch**. Cache-miss mitigation in `evaluate_scan`. `__builtin_prefetch` 4-8 beams ahead OR 4-particle lockstep gather. ~1.5-2× single-core speedup, very orthogonal.

10. **issue#7 — boom-arm angle masking** (optional, contingent on issue#4 diagnostic).

11. **issue#17 — GPIO UART direct connection** (perma-deferred).

12. **Bug B — Live mode standstill jitter ~5cm widening** (analysis-first, operator-driven HIL needed).

13. **PR #96 / Phase-0 cleanup decision point**. TEMPORARY contract honored if reverted; OR promote to permanent diag via documented mid-life path (Phase0BreakdownSnapshot Seqlock + UDS getter + webctl `/api/system/phase0` endpoint + `[phase0-publisher-grep]` build-grep + invariant `(s)` promotion). Defer until next operator HIL run uses GODO_PHASE0=1 again.

14. **Future: SPA Config tab search input** (low-priority UX follow-up surfaced during PR #93 HIL — there's no in-page search box; manual scroll required). Verify if `project_config_tab_grouping.md` (issue#15 candidate) covers this or if it's a separate ask.

**Next free issue integer: `issue#36`** (issue#11 P4-2-11-0 was DONE in PR #96; issue#11 main DONE in PR #99 28th-session; issue#35 candidate still tracking — sample size 2 from 27th-session, 0 reproductions in 28th-session).

## Where we are (2026-05-06 18:00 KST — twenty-eighth-session close)

**main = `64a2abb`** — PR #99 merged (issue#11 main implementation, squash, 9 commits → 1 line). Recent shipping order (most recent first):
- `64a2abb` — PR #99 issue#11 main (2026-05-06 ~17:20 KST)
- `129ad3f` — PR #98 27th-session Parent territory updates (2026-05-06 morning)
- `3428431` — PR #97 27th-session close docs (2026-05-06 ~10:30 KST)
- `53453f5` — PR #96 issue#11 P4-2-11-0 trim Phase-0 (2026-05-06 ~09:30 KST)
- `a0a3113` — PR #95 issue#28.2 SSE producer pin (2026-05-06 ~02:00 KST)

**Open PRs at session-close**:
- PR #100 — `docs/2026-05-06-twenty-eighth-session-close` (chronicler output: weekly archive updates only). Awaits operator merge.

**Live system on news-pi01**: webctl + frontend + tracker all on `64a2abb` (PR #99 install + range-prop fix). Tracker last restarted at GODO_PHASE0 cleanup (~17:30 KST) running in normal mode now. Mode = Idle (operator may toggle Live in SPA on next ops session). PHASE0 emit = OFF (override.conf removed; verified `Environment=` empty + 0 PHASE0 lines in journal).

**Production verification (post-issue#11, 5-min Phase-0 capture, 2989 scans)**:
- eval p50: **45.11 ms** (vs sequential 94.85 ms — 2.10× speedup ✓)
- LF rebuild p50: 40.03 ms (unchanged — issue#19 territory)
- TOTAL p50: **86.80 ms** (vs sequential 136.15 ms — 1.57× speedup)
- Cold-path Hz: **11.52 Hz** (vs sequential 7.34 Hz — +57% ✓)
- `[pool-degraded]` events: **0** (range-proportional fix verified)
- CPU 0/1/2 mean busy: 65.3 / 67.5 / 66.5% (workers balanced)
- CPU 3 mean busy: 0.1% (RT contract preserved)

## Twenty-eighth-session merged-PR summary

### PR #99 (`64a2abb`, MERGED): issue#11 main implementation — Live mode pipelined-parallel AMCL particle eval pool

- 9 commits squashed into 1 line on main (P4-2-11-1 ~ -7 + diagnostics + Mode-B docs + range-prop fix). 38 files / +2376 / -57 LOC.
- New static lib `production/RPi5/src/parallel/godo_parallel`. ParallelEvalPool: 3 worker threads pinned CPU {0, 1, 2}, CPU 3 hard-vetoed at ctor; pimpl-clean header (cold writer M1 grep preserved); empty `cpus_to_pin` ⇒ inline-sequential rollback (`= 1` TOML semantic).
- AMCL integration: `Amcl(cfg, lf, ParallelEvalPool* pool = nullptr)`; `step()` branches on pool with sequential fallback if `parallel_for` returns false. `weighted_mean()` body unchanged sequential summation in i-order — bit-equality preserved (§3.6 5-step proof, pinned by `tests/test_amcl_parallel_eval.cpp::case 1` via IEEE 754 byte memcmp).
- New TOML key `amcl.parallel_eval_workers` Int [1, 3] default 3 Recalibrate-class. Schema row count 67 → 68.
- New UDS endpoint `get_parallel_eval` + dedicated `Seqlock<ParallelEvalSnapshot>` (NOT extending `JitterSnapshot` per Mode-A round 2 M9 decision). Diag pump samples per-dispatch: dispatch_count, fallback_count, p99_us, max_us, degraded.
- Tests: 9 unit (`test_parallel_eval_pool`) + 5 integration (`test_amcl_parallel_eval`) + 2 bench (`bench_amcl_converge`). 52/52 hardware-free pass; 10/10 build-greps clean.
- Post-deploy critical defect caught: §3.7 (~190 ms parallel projection for N=5000) vs §4 (flat 50 ms hard timeout) self-inconsistency → permanent fallback within 1m 49s of deploy on first N=5000 dispatch. Fixed via range-proportional deadline `kJoinTimeoutBaseNs × max(1, range / kJoinTimeoutAnchorN)` (commit `bfbf671` within PR #99 squash).
- Pipeline: full (Planner Round 2 → Mode-A round 2 → Writer → Mode-B → post-deploy fix → squash-merge).

## Quick memory bookmarks (★ open these first on cold-start)

This session updated/added 3 memory entries:

1. ★ **NEW** `.claude/memory/feedback_cross_section_consistency_after_round_2_adds.md` — operator-locked 2026-05-06 KST. The §3.7/§4 missed-by-3-passes lesson. Cross-multiplication audit must follow any late-stage section add.
2. ★ **NEW** `.claude/memory/project_range_proportional_deadline_pattern.md` — reusable recipe for fork-join workloads varying by 10× across modes. Forensic anchor: issue#11 commit `bfbf671`.
3. **UPDATED** `.claude/memory/project_issue11_analysis_paused.md` — flipped from PAUSED to DONE. Description + body rewritten as historical anchor; the "paused" semantics is gone, but the journey (20th → 27th → 28th) is preserved for context.

Carryover (still active from prior sessions):

- `project_pipelined_compute_pattern.md` ★ — issue#11 reference design pattern (now also a closed instance, but pattern remains live for issue#19 / Live tracker / FreeD smoother / map activate / Phase 5 UE).
- `project_cpu3_isolation.md` — RT hot path isolation. (validated this session: jitter unchanged from baseline post-issue#11, cpu3 0.1% busy)
- `project_phase0_instrumentation_pattern.md` ★ — Phase-0 trim pattern. Validated again this session via fresh re-capture.
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
- `project_amcl_multi_basin_observation.md`, `project_calibration_alternatives.md`, `project_hint_strong_command_semantics.md`, `project_gpio_uart_migration.md`, `project_mapping_precheck_and_cp210x_recovery.md`, `project_uds_bootstrap_audit.md`.
- `project_live_mode_cpu_thrashing_2026-05-05.md`, `project_issue26_measurement_tool.md`.

## Quick orientation files for next session

1. **CLAUDE.md** §6 Golden Rules + §7 Agent pipeline + §8 Deployment.
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UNCHANGED this session.
3. **`DESIGN.md`** (root) — TOC. UNCHANGED this session.
4. **`.claude/memory/MEMORY.md`** — full index (~62 entries; 2 added + 1 updated this session).
5. **PROGRESS/2026-W19.md** — twenty-sixth + twenty-seventh + twenty-eighth session blocks.
6. **doc/history/2026-W19.md** — corresponding Korean narratives.
7. **`production/RPi5/CODEBASE.md`** invariant `(s)` — ParallelEvalPool ownership + worker pinning + M1 spirit + range-proportional deadline rule.
8. **`production/RPi5/SYSTEM_DESIGN.md`** §6.6 — pool architecture page (data flow / cache topology / bit-equality / diag surface / rollback / cross-applicability).
9. **`production/RPi5/CODEBASE/2026-W19.md`** 2026-05-06 14:34 KST entry + Post-deploy HIL section — empirical anchor for the issue#11 narrative.
10. ★ **`/doc/amcl_algorithm_analysis.md`** (untracked at session-close) — ready to commit + open as standalone docs PR. 853 lines.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = **36**); decimal for sub-issues; Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

**Reservations from /doc/issue11_design_analysis.md §8** (DO NOT use these integers for new issues):

- `issue#19` — ★ EDT 2D Felzenszwalb parallelization. **TOP PRIORITY post-issue#11**.
- `issue#20` — Track D-5-P (deeper σ schedule for OneShot, staggered-tier).
- `issue#21` — NEON/SIMD vectorization of `evaluate_scan` per-beam loop.
- `issue#22` — Adaptive N (KLD-sampling).
- `issue#23` — LF prefetch / gather-batch.
- `issue#24` — Phase reduction 3→1 in Live carry (TOML-only).
- `issue#25` — `amcl_anneal_iters_per_phase` 10→5 (TOML-only).
- `issue#26` — Cross-device GPS-synced measurement tool.
- `issue#27` — output_transform + SUBTRACT origin + LastOutput SSE — DONE in PR #79.
- `issue#28` — B-MAPEDIT-3 yaw rotation — DONE in PR #81.
- `issue#28.1` — B-MAPEDIT-3 follow-up backlog — DONE in PR #93.
- `issue#28.2` — SSE producer-side end-to-end pin — DONE in PR #95.
- `issue#29` — SHOTOKU base-move + two-point cal-reset workflow.
- `issue#30` — YAML normalization to (0, 0, 0°) per Apply — DONE in PR #84 (3 HIL fold rounds).
- `issue#30.1` — PR #84 Mode-B round 2 backlog — DONE in PR #87.
- `issue#31` (candidate) — Vector map representation feasibility study (perma-deferred research).
- `issue#32` — Backup TS regex + frontend formatter KST transition — DONE in PR #88.
- `issue#33` — Apply-on-pristine lineage init + backup map-name column — DONE in PR #89.
- `issue#34` — Doc hierarchy weekly archive migration — DONE in PR #91.
- `issue#34.1` — CLAUDE.md polish + per-stack nav footers — DONE in PR #92.
- `issue#11 P4-2-11-0` — Trim Phase-0 cold-path component instrumentation — DONE in PR #96 (TEMPORARY; cleanup decision after next HIL needs it again).
- **`issue#11` main — DONE in PR #99 (`64a2abb`, 2026-05-06 28th-session)**. Live mode pipelined-parallel AMCL particle eval pool.
- `issue#35` (candidate) — UDS hang after RPLIDAR I/O fallback. Sample size 2 (27th-session) + 0 (28th-session). Track for next reproduction; not yet a GH issue.

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions**:

- `plan_issue_11_live_pipelined_parallel.md` — full plan including Round 1 + Mode-A round 1 fold + Round 2 empirical fold (Parent) + Round 2 review fold (code-reviewer) + Mode-B fold + post-deploy fold. Reference for the entire issue#11 journey + reusable template for future Phase-0-grounded plan rewrites.
- `plan_issue_11_phase0_instrumentation.md` — trim path resolution + reusable trim instrumentation reference.
- `plan_issue_28.1_and_doc_hierarchy.md` — full Phase A + Phase B plan with operator decisions baked in. Useful template for future "doc reorg + code cleanup combo" PRs and parallel-agent migration pattern.
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold.
- `plan_issue_30_yaml_normalization.md` — 1101 lines including all 5 review folds (issue#30 family). Still load-bearing for issue#29 (SHOTOKU base-move).
- `plan_issue_30.1_mode_b_backlog.md` — Mode-B-backlog cleanup pattern reference.
- `phase0_results_*.md` (3 files) — main HIL dataset for issue#11 Mode-A round 2.

**Delete when convenient** (older plans no longer referenced):

- `plan_issue_28_b_mapedit3_yaw_rotation.md` (PR #81 reference — superseded by issue#30 lock + issue#28.1 close)
- `plan_issue_27_map_polish_and_output_transform.md` (PR #79 reference)
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference)
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference)
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference)

## Tasks alive for next session

- **★ issue#19 EDT 2D 3-way parallelization** (TL;DR #1 — TOP, reuses ParallelEvalPool)
- **★ AMCL doc PR** (TL;DR #2 — open + commit + push, ~5min task)
- **issue#13 distance-weighted likelihood** (TL;DR #3)
- **issue#35 candidate — UDS hang after RPLIDAR fallback** (TL;DR #4 — track for reproduction)
- **issue#26 measurement tool round 2** (TL;DR #5 — paused, no longer blocking)
- **issue#29 SHOTOKU base-move** (TL;DR #6)
- **issue#21 NEON/SIMD `evaluate_scan`** (TL;DR #7)
- **issue#22 KLD-sampling adaptive N** (TL;DR #8)
- **issue#23 LF prefetch / gather-batch** (TL;DR #9)
- **issue#7 boom-arm masking** (TL;DR #10)
- **issue#17 GPIO UART** (TL;DR #11 — perma-deferred)
- **Bug B Live mode standstill jitter** (TL;DR #12)
- **PR #96 / Phase-0 cleanup decision** (TL;DR #13 — defer until next GODO_PHASE0=1 use)

## Twenty-ninth-session warm-up note

Twenty-eighth was a **focused single-issue session** (~4.5 hours, 13:30 → 18:00 KST):

- Operator brief on session-open: "Phase-0 데이터 측정 완료, 정밀 분석하고 issue#11 Mode-A round 2 들어가자".
- Full agent pipeline run: code-planner (Round 2 plan rewrite with Phase-0 numbers) → code-reviewer Mode-A round 2 (APPROVE WITH MINOR REVISIONS, 4 minors inline-folded) → code-writer (P4-2-11-1 ~ -7, 6 commits, 38 files / +2376 / -57) → diagnostics fix → code-reviewer Mode-B (APPROVE WITH MINOR REVISIONS, 2 docs-fix recommendations) → PR #99 squash-merge.
- Critical post-deploy defect caught at HIL — `[pool-degraded] range=[0,5000)` within 1m 49s. Plan §3.7/§4 self-inconsistency. Fixed via range-proportional deadline pattern, shipped same-day as commit `bfbf671` within PR #99 squash.
- Fresh 5-min Phase-0 re-capture verified +57% cold-path Hz lift (7.34 → 11.52 Hz).
- AMCL deep-dive doc (853 lines) written as parallel work during capture. Operator decided separate PR.
- 2 new memory entries (`feedback_cross_section_consistency_after_round_2_adds.md`, `project_range_proportional_deadline_pattern.md`) + 1 updated (`project_issue11_analysis_paused.md` → DONE).

**Cold-start sequence for twenty-ninth session**:

1. Read `CLAUDE.md` (operating rules).
2. Read this `NEXT_SESSION.md`.
3. ★ Open `/doc/amcl_algorithm_analysis.md` (untracked) — operator may want a quick glance / edit before opening as standalone PR.
4. ★ Read `production/RPi5/CODEBASE.md` invariant `(s)` body for the live ParallelEvalPool + range-proportional deadline narrative.
5. PR #99 / #100 history in `PROGRESS/2026-W19.md` + `doc/history/2026-W19.md` + per-stack `<stack>/CODEBASE/2026-W19.md` weekly archive entries.

**Most likely first task**: TL;DR #2 (AMCL doc commit + PR) as opener, then TL;DR #1 (issue#19 planning kickoff). Issue#19 ~80 LOC is small enough to short-circuit through pipelined planner-on if the operator wants speed; full pipeline if they want thoroughness.

## Session-end cleanup (twenty-eighth — Parent territory follow-up commit)

- This file (`NEXT_SESSION.md`): rewritten as a whole per cache-role rule. Stale TL;DR items absorbed (issue#11 Mode-A round 2 → DONE inline through full pipeline; issue#11 main → DONE in PR #99). New TL;DR ordering reflects post-issue#11 priorities (issue#19 elevated to TOP; AMCL doc PR added as #2 quick task).
- `.claude/memory/`: 2 new entries (`feedback_cross_section_consistency_after_round_2_adds.md`, `project_range_proportional_deadline_pattern.md`); 1 updated (`project_issue11_analysis_paused.md` → DONE narrative). `MEMORY.md` Index updated for all three.
- `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`: kept (full journey reference, reusable template for future Phase-0-grounded rewrites).
- PROGRESS / doc/history: chronicler wrote the 28th-session block in PR #100 (already opened on `docs/2026-05-06-twenty-eighth-session-close` branch).
- Per-stack CODEBASE.md weekly archives: PR #99 added the issue#11 entry; PR #100 enriched with Post-deploy HIL section. Master files unchanged (Option (b) lock).
- SYSTEM_DESIGN.md / FRONT_DESIGN.md: UNCHANGED (PR #99 already added §6.6 in cb97618 before squash; no FRONT_DESIGN touchpoint this session).
- Root CODEBASE.md / DESIGN.md: UNCHANGED (no family-shape shift).
- Branches: 1 feature branch squash-merged with `--delete-branch` on origin (`feat/issue-11-parallel-eval-pool`). 1 docs branch (`docs/2026-05-06-twenty-eighth-session-close`) currently open for PR #100 merge.
- Production env hygiene: `GODO_PHASE0=1` override.conf removed; `Environment=` empty; PHASE0 emit OFF verified.
- Untracked at close: `/doc/amcl_algorithm_analysis.md` — kept untracked per operator decision; AMCL docs PR is the first task for next session.
