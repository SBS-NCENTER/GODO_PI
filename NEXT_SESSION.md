# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-03 15:30 KST (twentieth-session close — analytical session, NO PRs merged. Plans + Mode-A folds + new SSOT docs in flight; main = `7668c14` from PR #77 nineteenth-session docs).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-03 15:30 KST)

1. **★ issue#6 — B-MAPEDIT-3 yaw rotation + B-MAPEDIT-2 origin pick polish** (operator-locked priority #1 next session). Concrete SPA feature, immediately verifiable in browser, no algorithmic dependency on measurement data. Spec: `.claude/memory/project_map_edit_origin_rotation.md`. Frame redefinition (Problem 2 per `feedback_two_problem_taxonomy.md`).

2. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT; resumes after issue#6 ships). Round 2 + Writer + HIL is half-day effort. Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. Operator drives HIL at office tomorrow on broadcasting-room wired LAN. Memory: `.claude/memory/project_issue26_measurement_tool.md` for full Critical-finding table + resumption procedure.

3. **issue#11 — Live pipelined-parallel multi-thread** (PAUSED awaiting issue#26 first capture). Round 1 plan + Mode-A round 1 fold preserved at `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`. Comprehensive analysis SSOT at `/doc/issue11_design_analysis.md`. Memory: `.claude/memory/project_issue11_analysis_paused.md`. Resumes with empirical Live-tick breakdown data; architectural choice (Option A/B/C/D) is provisional pending data.

4. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment.

5. **issue#4 — AMCL silent-converge diagnostic** — fifteenth/sixteenth/seventeenth/eighteenth/nineteenth HIL data accumulated as comprehensive baseline (Live ±5 cm stationary / ±10 cm motion / yaw ±1°). Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

6. **issue#17 — GPIO UART direct connection** (perma-deferred) — long-term `cp210x` removal. Operator-locked: only ship if cp210x stack of mitigations (issue#10 + #10.1 + #16 + #16.2 + #18) proves insufficient post deployment. Effectively shelved unless field evidence accumulates.

7. **Bug B — Live mode standstill jitter ~5cm widening** — analysis-first. May be subsumed by issue#11's pipelined work once issue#11 resumes.

8. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern.

**Next free issue integer: `issue#27`** (issue#19-25 reserved as missed-alternative follow-ups in `/doc/issue11_design_analysis.md` §8; issue#26 = measurement tool).

## Where we are (2026-05-03 15:30 KST — twentieth-session close)

**main = `7668c14`** — NO PRs merged this session. Two `.claude/tmp/` plan files + Mode-A folds + new memory entries + new `/doc` analysis doc all in working tree, awaiting operator commit on the docs PR branch (`docs/2026-05-03-twentieth-session-close`).

**Open PRs**: docs PR (this twentieth-session bundle, awaiting operator commit + push + merge).

**Prior session (nineteenth) PRs already merged**: #75 (issue#18), #76 (issue#16.2), #77 (nineteenth-session docs).

## Live system on news-pi01 (post twentieth-session close — UNCHANGED)

All surfaces UNCHANGED from nineteenth-session close. Listed for reference:

- **godo-irq-pin.service**: enabled, auto-start.
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. Live `/opt/godo-webctl/` from PR #76.
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. Binary at `/opt/godo-tracker/godo_tracker_rt` from PR #75.
- **godo-mapping@active.service**: timing UNCHANGED (still 30/45/45/50 from issue#16.1).
- **godo-cp210x-recover.service**: existing (PR #69).
- **`/opt/godo-frontend/dist/`**: UNCHANGED.
- **polkit**: 14 rules unchanged.
- **Docker image**: `godo-mapping:dev` unchanged.
- **`/var/lib/godo/tracker.toml`**: unchanged from nineteenth-session close. Operator may update `network.ue_port = 50003` before tomorrow's broadcasting-room measurement (currently `6666` from schema default; operator mentioned 50003 in conversation but had not applied).
- **`/etc/udev/rules.d/99-rplidar.rules`**: regenerated from template; `/dev/rplidar` symlinks reliably.
- **`/run/godo/`**: clean — `ctl.sock`, `godo-tracker.pid`, `godo-webctl.pid`. No stale `.tmp` files.
- **journald**: persistent storage active. UDS audit log line + Mi4 directory case discriminator confirmed live.
- **Branch**: `main @ 7668c14`. Local working tree on `docs/2026-05-03-twentieth-session-close` (chronicler bundle, awaiting operator commit).

## Quick memory bookmarks (★ open these first on cold-start)

This session added **2 NEW memory entries** + updated 1 existing:

1. ★ `.claude/memory/project_issue11_analysis_paused.md` — UART-migration-style paused-spec. Reading order + resumption trigger + WHAT NOT TO DO on cold-start.
2. ★ `.claude/memory/project_issue26_measurement_tool.md` — UART-migration-style paused-spec. Full 7-Critical table + resumption procedure + key Mode-A insights worth preserving (asymmetry-is-unobservable / SO_TIMESTAMPNS_NEW / interface auto-detect).
3. `.claude/memory/MEMORY.md` — index updated with both new entries.

Also NEW reference doc (NOT memory but worth bookmarking): **`/doc/issue11_design_analysis.md`** — 8 sections, comprehensive SSOT for issue#11 design analysis. This is the single document a future cold-start reads to understand the 5 architectures, Mode-A findings, cross-analysis, operator direction shift, and missed alternatives (issue#19-26 reservations).

Carryover (still active):
- `project_pipelined_compute_pattern.md` (★ still authoritative for the broader pipelined-pattern roadmap; sites 2-5 stay open for staggered-tier idiom)
- `project_cpu3_isolation.md` (★ RT invariant for any future Live-side work)
- `project_map_edit_origin_rotation.md` (★ drives next session's issue#6)
- `project_amcl_multi_basin_observation.md` (drives issue#4)
- `project_calibration_alternatives.md`
- `project_hint_strong_command_semantics.md`
- `project_gpio_uart_migration.md` (issue#17 perma-deferred spec)
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`, `feedback_ssot_following_discipline.md`, `feedback_deploy_branch_check.md`, `feedback_relaxed_validator_strict_installer.md`, `feedback_post_mode_b_inline_polish.md`, `feedback_verify_before_plan.md` (★ MOST-VIOLATED — reread on every Planner brief), `feedback_helper_injection_for_testability.md`, `feedback_build_grep_allowlist_narrowing.md`
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`
- `frontend_stack_decision.md`, `reference_history_md.md`
- `project_lidar_overlay_tracker_decoupling.md`, `project_rplidar_cw_vs_ros_ccw.md`
- `project_amcl_sigma_sweep_2026-04-29.md`
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`
- `project_repo_canonical.md`, `project_tracker_down_banner_action_hook.md`, `project_restart_pending_banner_stale.md`
- `project_config_tab_grouping.md` (issue#15 — DONE in PR #70; historical)
- `project_uds_bootstrap_audit.md` (issue#18 — DONE in PR #75; historical)
- `project_mapping_precheck_and_cp210x_recovery.md` (issue#16 family — historical)

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §8 Deployment + PR workflow + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UNCHANGED this session.
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN. UNCHANGED this session.
4. **`.claude/memory/MEMORY.md`** — full index (~46 entries; 2 added this session).
5. **PROGRESS.md** — current through 2026-05-03 twentieth-session close.
6. **doc/history.md** — Korean narrative through twentieth-session.
7. **`/doc/issue11_design_analysis.md`** — ★ NEW SSOT for issue#11 analysis. 8 sections covering everything analytical from this session.
8. **`production/RPi5/CODEBASE.md`** — UNCHANGED this session.
9. **`godo-webctl/CODEBASE.md`** — UNCHANGED this session.
10. **`godo-frontend/CODEBASE.md`** — UNCHANGED this session.
11. **`SYSTEM_DESIGN.md`** — UNCHANGED this session.
12. **`FRONT_DESIGN.md`** — UNCHANGED this session.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 27); decimal for sub-issues (e.g. `issue#16.1`, `issue#16.2`, `issue#10.1`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

**Reservations from /doc/issue11_design_analysis.md §8** (DO NOT use these integers for new issues):
- `issue#19` — EDT 2D Felzenszwalb parallelization (requires `parallel_for_with_scratch<S>` API extension).
- `issue#20` — Track D-5-P (deeper σ schedule for OneShot, staggered-tier) — low priority since OneShot scope dropped.
- `issue#21` — NEON/SIMD vectorization of `evaluate_scan` per-beam loop.
- `issue#22` — Adaptive N (KLD-sampling).
- `issue#23` — LF prefetch / gather-batch.
- `issue#24` — Phase reduction 3→1 in Live carry (TOML-only).
- `issue#25` — `amcl_anneal_iters_per_phase` 10→5 (TOML-only).
- `issue#26` — Cross-device GPS-synced measurement tool (THIS session's tool, paused).

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions** (referenced by paused memories):
- `plan_issue_11_live_pipelined_parallel.md` — Round 1 plan + Mode-A round 1 fold. Round 2 NOT persisted (deemed obsolete by operator scope shift). The Mode-A fold's 7 Critical findings + cross-analysis verdicts are durable reference.
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold. The Mode-A fold's 7 Critical findings + clock-sync algorithm scrutiny are the resumption input for round 2.

**Keep for one more cycle, then prune**:
- `plan_issue_18_uds_bootstrap_audit.md` — PR #75 reference for helper-injection / verify-before-Plan / build-grep allow-list patterns.
- `plan_issue_10.1_lidar_serial_config_row.md` — PR #73 reference for relaxed-validator-strict-installer pattern.
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` — PR #72 reference.

**Delete when convenient** (older plans no longer referenced).

## Tasks alive for next session

- **issue#6 — B-MAPEDIT-3 yaw rotation + B-MAPEDIT-2 origin pick polish** (TL;DR #1 — primary scope, SPA-only, immediately verifiable)
- **issue#26 — measurement tool round 2 + Writer + HIL** (TL;DR #2 — half-day, after issue#6)
- **issue#11 — Live pipelined-parallel** (TL;DR #3 — PAUSED; resumes after issue#26 capture)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #4)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #5)
- **issue#17 — GPIO UART migration** (TL;DR #6 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #7 — analysis-first; may be subsumed)
- **issue#7 — boom-arm angle masking** (TL;DR #8 — optional, contingent)

## Twenty-first-session warm-up note

Twentieth-session was a focused afternoon ~3-hour analytical block. **Zero PRs merged**, but produced the foundation for the next 2-3 sessions of work. Two REJECT-rework iterations (issue#11 round 1, issue#26 round 1) both root-caused to `feedback_verify_before_plan.md` honored-in-spirit-not-execution. Operator scope-shifted twice mid-session: OneShot dropped from value equation, measurement-first promoted as the path forward.

Three potential new memory candidates surfaced but **not yet locked** (Parent will decide whether to add in twenty-first session):
- Stronger phrasing of `feedback_verify_before_plan.md` OR a build-step that requires Planner to cite source line:column for each numeric premise.
- New `feedback_measurement_first.md` capturing the issue#11 → issue#26 flip pattern.
- New `project_clock_sync_limits.md` capturing the structural unobservability of asymmetry with 4-timestamp NTP.

**Cold-start sequence for twenty-first session (issue#6 path)**:
1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. Open `.claude/memory/project_map_edit_origin_rotation.md` — full B-MAPEDIT-2/3 spec.
4. Open `.claude/memory/project_map_viewport_zoom_rules.md` — operator-locked map UX rules (shared component for /map and /map-edit).
5. Standard pipeline: Planner → Mode-A → Writer → Mode-B → operator HIL (per `feedback_pipeline_short_circuit.md`; B-MAPEDIT-3 is feature-scale + interactive-canvas surface, not a candidate for short-circuit).

**If operator brings issue#26 first instead** (e.g., they want to ship the test tool same-day as broadcasting-room visit):
1. Read `.claude/memory/project_issue26_measurement_tool.md`.
2. Read `.claude/tmp/plan_issue_26_latency_measurement_tool.md` Mode-A fold (lines 634-849).
3. Run **Planner round 2** with brief that absorbs every Critical fix + Major reframe inline. The 7 Criticals + ~10 Major fixes are well-scoped (~half-day).
4. Mode-A round 2.
5. Writer + Mode-B.
6. Operator HIL on news-pi01 + MacBook in broadcasting-room.

## Session-end cleanup (twentieth)

- NEXT_SESSION.md: rewritten as a whole per cache-role rule. Stale TL;DR items (issue#11 #1 with 3-axis brief) absorbed into `/doc/issue11_design_analysis.md` SSOT + `.claude/memory/project_issue11_analysis_paused.md`, then pruned. issue#6 promoted to TL;DR #1 with full SPA-only spec pointer.
- PROGRESS.md twentieth-session block added at top of session log (chronicler).
- doc/history.md 스무 번째 세션 한국어 block added (chronicler).
- SYSTEM_DESIGN.md / FRONT_DESIGN.md / per-stack CODEBASE.md: UNCHANGED (no design landed, no source touched).
- `.claude/memory/`: 2 new entries (`project_issue11_analysis_paused.md`, `project_issue26_measurement_tool.md`); MEMORY.md index updated.
- `/doc/`: 1 new file (`issue11_design_analysis.md` — 8 sections SSOT for issue#11 analysis).
- `.claude/tmp/`: 2 plan files in flight (`plan_issue_11_*` + `plan_issue_26_*`), kept as durable reference per memory entries.
- Branches: NO feature branches deleted (no PRs this session). Working tree on `docs/2026-05-03-twentieth-session-close` for the chronicler bundle, awaiting operator commit.
