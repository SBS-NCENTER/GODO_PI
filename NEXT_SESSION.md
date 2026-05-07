# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-07 ~08:30 KST (twenty-ninth-session close — issue#19 EDT 2D Felzenszwalb 3-way parallelization shipped via PR #104 `7a91806`; production cold-path 11.52 → 13.77 Hz +19% measured on news-pi01; 1.43× LF speedup vs plan's 3× projection — memory-bandwidth ceiling identified; 0 [pool-degraded] events; bit-equality preserved. Two doc typos (env var `GODO_PHASE0_TRIM_ON` → `GODO_PHASE0`; grep `\[phase0\]` → `PHASE0 path=`) found mid-HIL and folded back. Two memory entries added on yaw tripwire design flaw + OneShot-vs-MAP-EDIT origin yaw clarification).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-07 KST)

1. **★ issue#19.5 — EDT cache locality / SIMD optimisation** (TOP PRIORITY post-issue#19 ship). Trigger: 1.43× memory-bandwidth ceiling measured during issue#19 HIL on news-pi01 (vs plan's 3× projection). Felzenszwalb 1D EDT does column-major reads through `intermediate[y*W+x]` with large strides → cache miss heavy → 3 workers in parallel saturate DDR4 memory bus on Pi 5 → sub-linear scaling. Candidate paths (bench-driven exploration first, then commit to a path):
   - **NEON SIMD** vectorisation of `edt_1d` inner loop (Cortex-A76 NEON, 4-double parallelism on the parabola lower-envelope intersection math)
   - **`__builtin_prefetch`** directives 4-8 cells ahead in column pass
   - **Transpose-tile** cache locality (block-process 64×64 tiles to keep working set in L1d)
   - **Row-major rewrite** of column pass (transpose-on-seed, eliminate column-stride reads entirely)

   Stacks on issue#19's `parallel_for_with_scratch<S>` infrastructure (no API change needed). Reuses range-proportional deadline pattern. `issue#19.1` (`EdtScratch` hoist into `Amcl`) is dormant — current measurement shows no cold-call regression — so issue#19.5 can land standalone.

2. **issue#36 — `cold_writer.cpp` yaw tripwire elimination or threshold raise**. Operator-locked design flaw per `.claude/memory/project_yaw_tripwire_design_flaw.md`. LiDAR sits on crane pan-axis center → LiDAR yaw follows pan rotation 1:1 by physical invariant (CLAUDE.md §2/§9) → tripwire fires every Live tick whenever camera is panned > 5° from OneShot time. Designed for "BASE rotates" scenarios that physical invariants rule out. 2994 events / 5 minutes during issue#19 HIL = unacceptable noise. Operator preference: **eliminate** (option 1 of 3 in the memory file). Trivial PR (~10 LOC removal in `cold_writer.cpp` + remove `apply_yaw_tripwire` references in `amcl_result.cpp`) but Mode-A should validate that no other code reads the tripwire's stderr output.

3. **issue#13 — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Orthogonal to issue#11/#19/#19.5 (modifies `evaluate_scan` body, not the caller); composes with Option C without re-design. Standalone single-knob algorithmic experiment.

4. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. Independent of issue#11/#19 now (Phase-0 produced the in-tracker breakdown; issue#26 measures the cross-device wire-time only).

5. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow**. Spec at `/doc/shotoku_base_move_and_recal_design.md`. issue#30 dependency resolved (twenty-fourth) → can resume planning anytime.

6. **issue#21 — NEON/SIMD vectorization of `evaluate_scan` per-beam loop**. Pi 5 Cortex-A76 has NEON; bilinear coordinate transform is 4-double-vectorizable. Projected ~2-3× per-particle speedup, orthogonal to issue#11 fork-join + issue#19 EDT (still benefits even with pool active). May overlap with issue#19.5's NEON candidate — sequencing TBD when issue#19.5 plan is written.

7. **issue#22 — KLD-sampling adaptive N**. The "A" of AMCL — adaptive sample size. Reduces N during Live steady-state (often N≈100 sufficient once cloud has tightened). Big payoff potentially exceeds issue#11+#19+#19.5 combined; intricate machinery.

8. **issue#23 — LF prefetch / gather-batch**. Cache-miss mitigation in `evaluate_scan`. `__builtin_prefetch` 4-8 beams ahead OR 4-particle lockstep gather. ~1.5-2× single-core speedup, very orthogonal. Like issue#21, may overlap with issue#19.5's prefetch candidate.

9. **issue#7 — boom-arm angle masking** (optional, contingent on issue#4 diagnostic).

10. **issue#17 — GPIO UART direct connection** (perma-deferred).

11. **Bug B — Live mode standstill jitter ~5cm widening** (analysis-first, operator-driven HIL needed).

12. **PR #96 / Phase-0 cleanup decision point**. TEMPORARY contract honored if reverted; OR promote to permanent diag via documented mid-life path (Phase0BreakdownSnapshot Seqlock + UDS getter + webctl `/api/system/phase0` endpoint + `[phase0-publisher-grep]` build-grep + invariant `(s)` promotion). Defer until next operator HIL run uses `GODO_PHASE0=1` again. Note the **correct** env var name is `GODO_PHASE0` (NOT `GODO_PHASE0_TRIM_ON` as earlier docs incorrectly claimed; corrected this session).

13. **issue#19.2 / 19.3 / 19.4 (deferred follow-ups)**:
    - issue#19.2 — production-runtime fold-rate telemetry (m2 HIL ask; opens after operator HIL ratifies the 2000×2000 anchor downgrade rule with a larger map)
    - issue#19.3 — aligned-vs-naive partition 1-shot wallclock A/B (D-bench-2; opens once production isolcpus=3 boot is HIL-confirmed for an extended window)
    - issue#19.4 — `RUN_SERIAL TRUE` bench harness + strict floor restoration for both `bench_lf_rebuild` (1.6×) and `bench_amcl_converge` (1.5× / 1.2×) — fixes the 4-core dev-box ctest oversubscription flake without lowering bias-blocking strength

14. **Future: SPA Config tab search input** (low-priority UX follow-up surfaced during PR #93 HIL — there's no in-page search box; manual scroll required). Verify if `project_config_tab_grouping.md` (issue#15 candidate) covers this or if it's a separate ask.

**Next free issue integer: `issue#37`** (issue#19 main DONE in PR #104 29th-session; issue#36 reserved 2026-05-07 for yaw tripwire elimination; issue#19.1–.5 are decimal sub-issues per CLAUDE.md §6 scheme; issue#35 candidate still tracking — sample size 2 from 27th-session, 0 reproductions in 28th + 29th sessions).

## Where we are (2026-05-07 ~08:30 KST — twenty-ninth-session close)

**main = `1af71ee`** — PR #105 merged (chronicler output; 29th-session close docs cascade). Recent shipping order (most recent first):

- `1af71ee` — PR #105 chronicler 29th-session close (2026-05-07 ~08:20 KST)
- `7a91806` — PR #104 issue#19 main (2026-05-07 ~08:00 KST)
- `2579b4c` — PR #103 docs cleanup AMCL line count footer (2026-05-06 ~19:30 KST)
- `9d95dda` — PR #102 AMCL doc body (2026-05-06 ~19:23 KST)
- `a8516e4` — PR #101 28th-session Parent territory (2026-05-06 ~19:11 KST)

**Open PRs at session-close**: none (PR #105 already merged before this rewrite). Parent's chore-cleanup PR (this rewrite + local branch cleanup) opens immediately after this commit.

**Live system on news-pi01**: webctl + frontend + tracker all on `7a91806` (PR #104 deployed via `install.sh` 2026-05-07 ~07:30 KST). Tracker last restarted ~07:41 KST after env-var typo fix (`GODO_PHASE0_TRIM_ON` → `GODO_PHASE0`). Mode = whatever operator left it in (likely Live mode for HIL capture; no explicit toggle off observed in chat). PHASE0 emit = ON (`GODO_PHASE0=1` in `/etc/systemd/system/godo-tracker.service.d/override.conf`) — operator may want to remove the override and restart at start of next session if PHASE0 is no longer wanted.

**Production verification (post-issue#19, 5-min Phase-0 capture, 3588 scans)**:

- LF rebuild p50: **28.09 ms** (vs 40.03 issue#11 baseline — 1.43× lift)
- LF rebuild p99: 47.07 ms
- Eval p50: 43.34 ms (≈ same as issue#11 baseline, no regression ✓)
- TOTAL p50: **72.64 ms** (vs 86.80 issue#11 baseline)
- Cold-path Hz: **13.77 Hz** (vs 11.52 issue#11 baseline, **+19%**)
- `[pool-degraded]` events: **0**
- Iters/scan mean: 16.0 (convergent)

## Twenty-ninth-session merged-PR summary

### PR #103 (`2579b4c`, MERGED): docs cleanup — AMCL doc line count footer 1100 → 853

- Quick session-opener cleanup. PR #102 commit body promised this small follow-up.
- 5 edits across 3 files (NEXT_SESSION.md + PROGRESS/2026-W19.md + doc/history/2026-W19.md). `.claude/memory/MEMORY.md` was named in PR #102's commit body but grep found no actual reference there — confirmed clean.
- Pipeline: Parent direct (small docs cleanup, no agent invocation).

### PR #104 (`7a91806`, MERGED): issue#19 EDT 2D Felzenszwalb 3-way parallelization

- 8 commits squashed into 1 line on main (P4-2-19-1..-6 + Mode-B fold + HIL fold). 22 files / +1758 / -60 LOC.
- Reuses issue#11's `ParallelEvalPool` primitive with new `parallel_for_with_scratch<Scratch>` template extension (caller-owned per-worker scratch, type-erased shim, ABI-stable Impl boundary). issue#11 surface byte-identical (regression pin via test_parallel_eval_pool case (e)).
- `build_likelihood_field(grid, σ, pool=nullptr)` overload partitions both 1-D Felzenszwalb passes 3-way; column pass uses 16-float (64 B) cache-aligned partition with last-worker-takes-residue (D4); row pass uses naive y-block (naturally aligned). `EdtScratch` POD in `likelihood_field.cpp` anonymous namespace (D7).
- New Tier-1 constants `EDT_PARALLEL_DEADLINE_BASE_NS = 50 ms` + `EDT_PARALLEL_ANCHOR_DIM = 1000` (`max(W, H)` is the dispatch range; m2 fallback rule reserves anchor=750 if 2000×2000 worker p99 > 80 ms).
- `Amcl::pool()` accessor added (m1 fold; +1 LOC). 3 cold_writer call sites at `:177, :339, :852` thread `amcl.pool()` or the existing `pool` parameter.
- New build-grep `[edt-scratch-asserted]` enforces unconditional `fprintf + std::abort` in `parallel_eval_pool.cpp` function definition AND rejects `assert(.*per_worker|.*scratch)` AND rejects `#if(n)?def NDEBUG` near the guard. D1 ban on `assert(...)` macro is structural.
- 13 new test cases + 1 new bench: test_parallel_eval_pool +5 cases (a-e); test_likelihood_field_parallel new (6 cases — 16×16 brute-force regression + 256×256 + 1000×1000 FNV-1a memcmp + degraded fallback + workers=0 rollback bit-equal); test_amcl_parallel_eval +2 cases (g, h); bench_lf_rebuild new (sequential vs parallel + parallel-vs-sequential bit-equality at 1000×1000 production scale).
- Bench CI floor 1.1× (m5 deviation from plan's 1.6×; 4-core dev-box ctest concurrent run oversubscribes; reserved as `issue#19.4` for `RUN_SERIAL TRUE` migration).
- HIL on news-pi01 (5-min Phase-0, 3588 samples) measured 1.43× LF lift / +19% Hz / 0 pool-degraded. Operator decision: ship; reserve `issue#19.5` for cache-locality / SIMD optimisation.
- Two doc typos surfaced + folded during HIL: env var `GODO_PHASE0_TRIM_ON` → `GODO_PHASE0`; grep `\[phase0\]` → `PHASE0 path=`. Lesson: Mode-A audit hooks A2/A4 must grep source for exact literals.
- Pipeline: full (Planner → Mode-A round 1 → Writer (single wave + API 529 mid-burst, second invocation resumed) → Mode-B → operator HIL → HIL fold-in → squash-merge).

### PR #105 (`1af71ee`, MERGED): chronicler 29th-session close docs cascade

- 3 files / +166 / -42. PROGRESS/2026-W19.md + doc/history/2026-W19.md + production/RPi5/CODEBASE/2026-W19.md.
- W19 archive's issue#19 main entry HIL section merged with actual measurements + 2 typo fixes + 6 follow-up reservations. Duplicate h3 HIL fold (mistakenly placed at EOF by earlier append-at-EOF) cleaned so issue#30 verification entry above remains intact.
- Master CODEBASE.md / SYSTEM_DESIGN.md / FRONT_DESIGN.md / root scaffolds UNCHANGED (no family-shape shift).

## Quick memory bookmarks (★ open these first on cold-start)

This session updated/added 2 memory entries (Parent territory):

1. ★ **NEW** `.claude/memory/project_yaw_tripwire_design_flaw.md` — operator-locked 2026-05-07 KST. LiDAR sits on crane pan-axis center → LiDAR yaw follows pan rotation 1:1 by physical invariant (CLAUDE.md §2/§9). Tripwire designed for "BASE rotates" scenarios that physical invariants rule out; fires every Live tick (2994 events / 5 min during HIL). issue#36 reserved for elimination.
2. ★ **NEW** `.claude/memory/project_oneshot_vs_mapedit_origin_yaw.md` — operator-locked 2026-05-07 KST. OneShot calibrates (x, y) only; origin.yaw is changed exclusively via MAP EDIT (issue#28/#30 lineage). Standard workflow: OneShot → Live Mode every session. Rules out the "OneShot to silence yaw tripwire" misconception.

Carryover (still active from prior sessions):

- `project_range_proportional_deadline_pattern.md` ★ — issue#19 row marked DONE; reusable site list now includes issue#19 EDT 2D 3-way as the second instance of the pattern.
- `project_pipelined_compute_pattern.md` ★ — issue#11 reference design pattern (still active for Live tracker / FreeD smoother / map activate / Phase 5 UE).
- `project_issue11_analysis_paused.md` — flipped from PAUSED to DONE at 28th-session close; preserved as historical anchor.
- `project_cpu3_isolation.md` — RT hot path isolation. (validated again this session: jitter unchanged from baseline post-issue#19, cpu3 < 5% busy)
- `project_phase0_instrumentation_pattern.md` ★ — Phase-0 trim pattern. Validated again this session via fresh re-capture (post-issue#19 deploy).
- `feedback_cross_section_consistency_after_round_2_adds.md` ★ — issue#11 §3.7/§4 sibling lesson. Updated this session: literal-vs-claim grep rule (Mode-A A2/A4 must grep source for env-var + emit literals).
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
4. **`.claude/memory/MEMORY.md`** — full index (~64 entries; 2 added this session).
5. **PROGRESS/2026-W19.md** — twenty-sixth + 27th + 28th + 29th session blocks.
6. **doc/history/2026-W19.md** — corresponding Korean narratives.
7. **`production/RPi5/CODEBASE.md`** invariant `(s)` + `(s.1)` body — ParallelEvalPool ownership + worker pinning + M1 spirit + range-proportional deadline rule + EDT 2D parallelisation extension.
8. **`production/RPi5/SYSTEM_DESIGN.md`** §6.6 + §6.6.1 — pool architecture page + EDT 2D parallelisation subsection.
9. **`production/RPi5/CODEBASE/2026-W19.md`** 2026-05-07 01:00 KST entry + merged HIL section — empirical anchor for the issue#19 narrative.
10. ★ **`.claude/memory/project_yaw_tripwire_design_flaw.md`** + **`.claude/memory/project_oneshot_vs_mapedit_origin_yaw.md`** — fresh operator-locked memory; load when planning issue#36 or any code touching `cold_writer.cpp` yaw logic.
11. ★ **`.claude/memory/feedback_cross_section_consistency_after_round_2_adds.md`** — updated with literal-vs-claim grep rule (A2/A4 audit hook discipline). Load before any Mode-A round on a plan that mentions env vars OR emit literals.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = **37**); decimal for sub-issues; Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

**Reservations from `/doc/issue11_design_analysis.md` §8 + this session** (DO NOT use these integers for new issues):

- `issue#19` — EDT 2D Felzenszwalb parallelization. **DONE in PR #104 (`7a91806`, 2026-05-07 29th-session)**.
- `issue#19.1` — `EdtScratch` lifetime hoist into `Amcl` (R5 mitigation; dormant — no cold-call regression measured).
- `issue#19.2` — production-runtime fold-rate telemetry (m2 HIL ask).
- `issue#19.3` — aligned-vs-naive partition 1-shot wallclock A/B (D-bench-2).
- `issue#19.4` — `RUN_SERIAL TRUE` bench harness + strict floor restoration.
- **`issue#19.5`** — EDT cache locality / SIMD optimisation. **TOP PRIORITY post-issue#19**.
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
- `issue#11` main — DONE in PR #99 (`64a2abb`, 2026-05-06 28th-session).
- **`issue#36`** — `cold_writer.cpp` yaw tripwire elimination (operator-locked design flaw, 2026-05-07).
- `issue#35` (candidate) — UDS hang after RPLIDAR I/O fallback. Sample size 2 (27th-session) + 0 (28th + 29th sessions). Track for next reproduction; not yet a GH issue.

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions**:

- `plan_issue_19_edt_parallelization.md` — 812 lines including Mode-A round 1 fold + final HIL fold. Reference for issue#19 journey + reusable template for "small follow-up that stacks on a recently-shipped primitive" pattern + reusable Phase-0-grounded plan rewrite reference.
- `plan_issue_11_live_pipelined_parallel.md` — 1258 lines (full issue#11 journey). Still load-bearing for future fork-join workloads + range-proportional deadline pattern reference.
- `plan_issue_11_phase0_instrumentation.md` — trim path resolution + reusable trim instrumentation reference.
- `plan_issue_28.1_and_doc_hierarchy.md` — full Phase A + Phase B plan with operator decisions baked in.
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold.
- `plan_issue_30_yaml_normalization.md` — 1101 lines including all 5 review folds (issue#30 family). Still load-bearing for issue#29 (SHOTOKU base-move).
- `plan_issue_30.1_mode_b_backlog.md` — Mode-B-backlog cleanup pattern reference.
- `phase0_results_*.md` (3 files) — main HIL dataset for issue#11 Mode-A round 2.

**Delete when convenient** (older plans no longer referenced):

- `plan_issue_28_b_mapedit3_yaw_rotation.md` (PR #81 reference — superseded)
- `plan_issue_27_map_polish_and_output_transform.md` (PR #79 reference)
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference)
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference)
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference)

## Tasks alive for next session

- **★ issue#19.5 EDT cache locality / SIMD optimisation** (TL;DR #1 — TOP)
- **★ issue#36 yaw tripwire elimination** (TL;DR #2 — operator-preferred resolution: eliminate; ~10 LOC PR)
- **issue#13 distance-weighted likelihood** (TL;DR #3)
- **issue#26 measurement tool round 2** (TL;DR #4 — paused)
- **issue#29 SHOTOKU base-move** (TL;DR #5)
- **issue#21 NEON/SIMD `evaluate_scan`** (TL;DR #6 — may overlap with issue#19.5)
- **issue#22 KLD-sampling adaptive N** (TL;DR #7)
- **issue#23 LF prefetch / gather-batch** (TL;DR #8 — may overlap with issue#19.5)
- **issue#7 boom-arm masking** (TL;DR #9)
- **issue#17 GPIO UART** (TL;DR #10 — perma-deferred)
- **Bug B Live mode standstill jitter** (TL;DR #11)
- **PR #96 / Phase-0 cleanup decision** (TL;DR #12)
- **issue#19.2 / 19.3 / 19.4** (TL;DR #13 — deferred follow-ups)

## Thirtieth-session warm-up note

Twenty-ninth was a **single-issue + chronicler session** (~13 hours wall-clock 2026-05-06 19:00 KST → 2026-05-07 ~08:30 KST, sleep included):

- Operator brief on session-open: "이제 다음 작업 시작하자요 / 최신 상태 확인부터 git 고고고."
- Quick docs cleanup PR #103 (1100 → 853 line count footer, ~5 min) before main work.
- Full agent pipeline run on issue#19: code-planner → code-reviewer Mode-A round 1 (APPROVE WITH MINOR REVISIONS, 5m + 8n folded into plan) → code-writer (P4-2-19-1..-6, 8 commits; first writer wave hit API 529 mid-P4-2-19-5, second wave resumed cleanly) → code-reviewer Mode-B round 1 (APPROVE WITH MINOR REVISIONS, 3m docs-only + 1n folded inline at 2f3e7cb) → operator HIL on news-pi01 → HIL fold-in commit `4dafd5b` → PR #104 squash-merge.
- Operator HIL caught 2 doc typos (env var + grep pattern) — both folded into PR body + W19 archive + plan; new lesson on Mode-A audit-hook A2/A4 (literal-vs-claim grep rule).
- 1.43× LF lift measured (vs plan's 3× projection) — algorithmic ceiling identified as memory-bandwidth bound on Pi 5; operator decided to ship + reserve issue#19.5 for SIMD/cache work.
- Yaw tripwire mid-HIL spam (2994 events / 5 min) → operator brief reclassified as design flaw; 2 new memory entries; issue#36 reserved.
- chronicler PR #105 wrapped the session.

**Cold-start sequence for thirtieth session**:

1. Read `CLAUDE.md` (operating rules).
2. Read this `NEXT_SESSION.md`.
3. ★ Read `.claude/memory/project_yaw_tripwire_design_flaw.md` + `project_oneshot_vs_mapedit_origin_yaw.md` (if planning issue#36 or any cold_writer yaw work).
4. ★ Read `feedback_cross_section_consistency_after_round_2_adds.md` (updated with A2/A4 literal-grep rule — load before any Mode-A round mentioning env vars or emit literals).
5. ★ For issue#19.5 planning: read `production/RPi5/src/localization/likelihood_field.cpp:33-78` (`edt_1d` body, the SIMD/prefetch target) + `parallel_eval_pool.hpp` (existing API) + `bench_lf_rebuild.cpp` (bench skeleton to extend with SIMD/prefetch variants).
6. PR #104 / #105 history in `PROGRESS/2026-W19.md` + `doc/history/2026-W19.md` + per-stack `production/RPi5/CODEBASE/2026-W19.md`.

**Most likely first task**: TL;DR #1 (issue#19.5 planning kickoff) OR TL;DR #2 (issue#36 quick PR — ~10 LOC removal, can be opener if operator wants a fast win before deep SIMD work). Issue#36 first then issue#19.5 is a natural sequencing — clears Live mode log noise that would otherwise pollute issue#19.5 HIL captures.

## Session-end cleanup (twenty-ninth — Parent territory follow-up commit)

- This file (`NEXT_SESSION.md`): rewritten as a whole per cache-role rule. Stale TL;DR items absorbed (issue#19 → DONE in PR #104; AMCL doc PR → DONE in PR #102 prior session). New TL;DR ordering reflects post-issue#19 priorities (issue#19.5 elevated to TOP; issue#36 added at #2).
- `.claude/memory/`: 2 new entries (`project_yaw_tripwire_design_flaw.md`, `project_oneshot_vs_mapedit_origin_yaw.md`) added in PR #104. `MEMORY.md` Index updated for both.
- `.claude/tmp/plan_issue_19_edt_parallelization.md`: kept (full journey reference + Mode-A fold + HIL fold). Reusable template for "small follow-up stacking on a recently-shipped primitive" + Phase-0-grounded plan rewrites.
- PROGRESS / doc/history: chronicler wrote the 29th-session block in PR #105 (`1af71ee`).
- Per-stack CODEBASE.md weekly archives: PR #104 added the issue#19 entry (P4-2-19-6); PR #105 enriched with the merged HIL section + cleaned the duplicate EOF h3 fold. Master files unchanged (Option (b) lock).
- SYSTEM_DESIGN.md / FRONT_DESIGN.md: UNCHANGED (PR #104 added §6.6.1 in P4-2-19-6 commit; no FRONT_DESIGN touchpoint this session).
- Root CODEBASE.md / DESIGN.md: UNCHANGED (no family-shape shift).
- Branches: 2 feature branches squash-merged with `--delete-branch` on origin (`chore/amcl-doc-line-count-fix` for PR #103; `feat/issue-19-edt-parallel` for PR #104). 1 docs branch (`docs/2026-05-07-twenty-ninth-session-close`) merged via PR #105 + local cleanup. This Parent-cleanup branch (`chore/2026-05-07-twenty-ninth-session-cleanup`) opens for the NEXT_SESSION rewrite + local stale branch cleanup.
- Production env hygiene: `GODO_PHASE0=1` override.conf is currently ON (operator may want to remove the override.conf and restart at start of next session if PHASE0 is no longer wanted). Note: do NOT use `GODO_PHASE0_TRIM_ON` — that name was a typo and is not recognised by the source code.
- Untracked at close: none.
