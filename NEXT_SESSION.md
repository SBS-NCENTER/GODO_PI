# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-04 06:00 KST (twenty-first-session close — issue#27 ships PR #79 at `c28bc1d`; docs PR #80 awaiting operator merge).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-04 06:00 KST)

1. **★ issue#28 — B-MAPEDIT-3 yaw rotation (full)** (operator-locked priority #1). Two structural prerequisites surfaced during issue#27 HIL must ship together:
   - **(a) Wire YAML `origin[2]` through to AMCL frame transform.** Tracker currently reads `cfg.amcl_origin_yaw_deg` (Tier-2 config) at `cold_writer.cpp:371,377,385,515,521,529,649,655,663`, NOT the YAML's third element. `occupancy_grid.cpp:113-130` parses but never propagates. Lean: replace `cfg.amcl_origin_yaw_deg` consumption with YAML `origin[2]` reading (cleaner SSOT). Alt: transactional dual-write of YAML + config (preserves backward compat).
   - **(b) Pose + Yaw + LiDAR scan dots render coherently together** when YAML theta changes (operator-locked 2026-05-04 KST: "B-MAPEDIT-3 구현하면 POSE, Yaw를 함께 랜더링 할 수 있도록 해야 해. 시간이 좀 걸려도 괜찮으니까."). The shared `MapUnderlay` + `lib/poseDraw.ts` from issue#27 makes this straightforward.
   - PGM bilinear resample (sole-owner module, operator-locked spec ~250-350 LOC for resample alone).
   - Theta UI gate `THETA_EDIT_ENABLED=false` flips back on as part of this PR.
   - Spec: `.claude/memory/project_map_edit_origin_rotation.md` B-MAPEDIT-3 section + "Critical pre-implementation findings — issue#27 HIL surfaced" subsection.

2. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Round 2 + Writer + HIL is half-day after issue#28. Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. Operator drives HIL at broadcasting-room wired LAN. Memory: `.claude/memory/project_issue26_measurement_tool.md` for full Critical-finding table + resumption procedure.

3. **issue#11 — Live pipelined-parallel multi-thread** (PAUSED awaiting issue#26 first capture). Round 1 plan + Mode-A round 1 fold preserved at `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`. Comprehensive analysis SSOT at `/doc/issue11_design_analysis.md`. Memory: `.claude/memory/project_issue11_analysis_paused.md`. Resumes with empirical Live-tick breakdown data.

4. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment.

5. **issue#4 — AMCL silent-converge diagnostic** — comprehensive HIL baseline accumulated through nineteenth-session. Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

6. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow** (NEW deferred, 2026-05-04 KST). Spec at `/doc/shotoku_base_move_and_recal_design.md` (242 lines, UART migration pattern). Three cases: (A) base translation = current 1-shot calibrate ✓; (B) base rotation = unhandled, math + workflow proposed; (C) SHOTOKU two-point re-cal = re-anchor workflow proposed. **Depends on issue#28 plumbing fix** (same YAML `origin[2]` consumer gap blocks both). Trigger to ship: production base rotation incident OR two-point re-cal frequency increase OR PIXOTOPE rotation issue surfacing.

7. **issue#17 — GPIO UART direct connection** (perma-deferred) — only ship if cp210x mitigations (issue#10 + #10.1 + #16 + #16.2 + #18) prove insufficient. Effectively shelved unless field evidence accumulates.

8. **Bug B — Live mode standstill jitter ~5cm widening** — analysis-first. May be subsumed by issue#11's pipelined work.

9. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern.

**Next free issue integer: `issue#30`** (issue#28 = B-MAPEDIT-3 yaw rotation; issue#29 = SHOTOKU base-move design).

## Where we are (2026-05-04 06:00 KST — twenty-first-session close)

**main = `c28bc1d`** — PR #79 (issue#27) merged. Working tree on `docs/2026-05-04-twenty-first-session-close` for the chronicler bundle (PR #80, awaiting operator merge).

**Open PRs**: PR #80 (this twenty-first-session docs bundle).

**Prior session (twentieth) PRs already merged**: #78 (`f23b5c7 issue11, 26 분석`, operator web upload). Twenty-first-session merged: #79 (issue#27).

## Live system on news-pi01 (post twenty-first-session close)

CHANGED this session (issue#27):

- **godo-tracker.service**: rebuilt from main `c28bc1d`. New `udp::output_transform` stage between `apply_offset_inplace` and `udp.send`. New `Seqlock<LastOutputFrame>` published per tick. Restarted via SPA System tab post-deploy. 12 new `output_transform.*` schema rows + 3 new `origin_step.*` rows; live `tracker.toml` does not yet carry them — defaults flow from `config_defaults.hpp` (per `feedback_toml_branch_compat.md`, gracefully default-fills).
- **godo-webctl.service**: redeployed from main, restarted. SSE multiplexes `{pose, output}` envelope per wrap-and-version pattern. New UDS command `get_last_output` + REST endpoint `GET /api/last_output`. `LAST_OUTPUT_FIELDS` regex-pinned against C++ `format_ok_output`.
- **godo-frontend** (`/opt/godo-frontend/dist/`): redeployed. `<LastPoseCard/>` mounted on Dashboard (replaces inline pose readout) + Map + MapEdit. Hover-coord moved to top-right + always-on across Edit/Overview/Hint modes (Mode-A M2 lock: shared `MapViewport.hoverWorld`). Edit-tab pose dot via `MapUnderlay` `ondraw` hook (shared `lib/poseDraw.ts`). `<OriginPicker/>` x_m / y_m +/- buttons live; theta UI gated `THETA_EDIT_ENABLED=false` (commit `2b4c3fe`).
- **Jitter post-deploy**: p99 = 18.5 µs (samples 2048), p50 = 3.0 µs, p95 = 12.9 µs, max = 24.2 µs, mean = 5.0 µs. Phase 4-1 baseline 12.7 µs vs +5.8 µs / +45% — within absolute ceiling ≤ 30 µs but baseline is 6 months stale across PR #58/#66/#75 etc. Output_transform's per-tick cost is ~100 ns by static analysis; the 5.8 µs delta is dominated by other accumulated factors. Not a merge blocker; flagged for separate tracking.

UNCHANGED:
- godo-irq-pin, godo-cp210x-recover, godo-mapping@active, polkit (14 rules), Docker `godo-mapping:dev`, `/etc/udev/rules.d/99-rplidar.rules`, `/run/godo/`, journald.

## Quick memory bookmarks (★ open these first on cold-start)

This session added **1 NEW memory entry** + updated 1 existing + added 1 new design doc:

1. ★ `.claude/memory/feedback_subtract_semantic_locked.md` — operator-intuitive (0,0)-marker → SUBTRACT direction. ADD on YAML literal is dev-frame, not operator-frame. When in doubt, ask "does typing positive value make the picked point closer to (0,0)?" If yes → SUBTRACT.
2. ★ `.claude/memory/project_map_edit_origin_rotation.md` — added "Critical pre-implementation findings — issue#27 HIL surfaced" subsection under B-MAPEDIT-3. **MUST READ before issue#28 Planner kickoff** — spells out (a) plumbing fix + (b) coherent rendering requirement.
3. ★ `/doc/shotoku_base_move_and_recal_design.md` (NEW, NOT memory) — issue#29 deferred design doc. UART migration pattern. 8 sections: 3 cases + math + workflows + 7 open questions + ship triggers + dependencies.
4. `.claude/memory/MEMORY.md` — index updated with `feedback_subtract_semantic_locked` entry.

Carryover (still active):
- `project_pipelined_compute_pattern.md`, `project_cpu3_isolation.md`, `project_amcl_multi_basin_observation.md`, `project_calibration_alternatives.md`, `project_hint_strong_command_semantics.md`, `project_gpio_uart_migration.md` (issue#17 perma-deferred spec)
- `project_issue11_analysis_paused.md`, `project_issue26_measurement_tool.md` (paused-spec memories)
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
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UPDATED this session (`udp/output_transform` added to C++ tracker).
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN. UNCHANGED.
4. **`.claude/memory/MEMORY.md`** — full index (~47 entries; 1 added this session).
5. **PROGRESS.md** — current through 2026-05-04 twenty-first-session close.
6. **doc/history.md** — Korean narrative through 스물 한 번째 세션.
7. **★ `.claude/memory/project_map_edit_origin_rotation.md`** — issue#28 Planner brief MUST start here.
8. **★ `/doc/shotoku_base_move_and_recal_design.md`** — issue#29 design doc (when surfaced).
9. **`production/RPi5/CODEBASE.md`** — UPDATED (invariant `(v) output-transform-sole-owner-discipline`).
10. **`godo-webctl/CODEBASE.md`** — UPDATED (invariants `(ab) origin-yaml-theta-passthrough — partial relax`, `(ac) last-output-fields-regex-pinned-against-cpp`).
11. **`godo-frontend/CODEBASE.md`** — UPDATED (invariants `(v) hover-coord-via-shared-viewport`, `(w) pose-draw-shared-helper`, `(x) last-pose-card-sole-pose-display`, `(aa) origin-picker-dual-input — issue#27 update incl. THETA_EDIT_ENABLED gate`).
12. **`SYSTEM_DESIGN.md`** — UPDATED (§6.2.2 Final-output transform stage).
13. **`FRONT_DESIGN.md`** — UPDATED (SSE channel row for wrap-and-version).

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 30); decimal for sub-issues (e.g. `issue#16.1`, `issue#16.2`, `issue#10.1`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

**Reservations from /doc/issue11_design_analysis.md §8** (DO NOT use these integers for new issues):
- `issue#19` — EDT 2D Felzenszwalb parallelization.
- `issue#20` — Track D-5-P (deeper σ schedule for OneShot, staggered-tier).
- `issue#21` — NEON/SIMD vectorization of `evaluate_scan` per-beam loop.
- `issue#22` — Adaptive N (KLD-sampling).
- `issue#23` — LF prefetch / gather-batch.
- `issue#24` — Phase reduction 3→1 in Live carry (TOML-only).
- `issue#25` — `amcl_anneal_iters_per_phase` 10→5 (TOML-only).
- `issue#26` — Cross-device GPS-synced measurement tool.
- `issue#27` — output_transform + SUBTRACT origin + LastOutput SSE — **DONE in PR #79 this session**.
- `issue#28` — B-MAPEDIT-3 yaw rotation (full plumbing + coherent render).
- `issue#29` — SHOTOKU base-move + two-point cal-reset workflow.

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions** (referenced by paused memories):
- `plan_issue_11_live_pipelined_parallel.md` — Round 1 plan + Mode-A round 1 fold. Round 2 NOT persisted.
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold. Round 2 deferred.
- `plan_issue_27_map_polish_and_output_transform.md` — Plan + Mode-A fold + Parent-decisions fold + Mode-B fold. **Keep for one more cycle as B-MAPEDIT-3 reference** (theta plumbing rationale + SUBTRACT semantic derivation + helper-injection patterns).

**Delete when convenient** (older plans no longer referenced):
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference, two cycles old).
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference, two cycles old).
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference, two cycles old).

## Tasks alive for next session

- **issue#28 — B-MAPEDIT-3 yaw rotation (full)** (TL;DR #1 — primary scope, multi-stack: tracker plumbing fix + frontend rotation gizmo + PGM bilinear resample backend)
- **issue#26 — measurement tool round 2 + Writer + HIL** (TL;DR #2)
- **issue#11 — Live pipelined-parallel** (TL;DR #3 — PAUSED)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #4)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #5)
- **issue#29 — SHOTOKU base-move + cal-reset** (TL;DR #6 — NEW deferred, depends on issue#28)
- **issue#17 — GPIO UART migration** (TL;DR #7 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #8)
- **issue#7 — boom-arm angle masking** (TL;DR #9)

## Twenty-second-session warm-up note

Twenty-first-session was a focused multi-hour cross-stack ship (~7 hours including HIL). 1 PR (#79, issue#27) merged at `c28bc1d`. Two HIL discoveries forced spec corrections: (1) ADD origin spec was sign-wrong (now SUBTRACT in `feedback_subtract_semantic_locked.md`); (2) tracker doesn't consume YAML `origin[2]` (folded into B-MAPEDIT-3 spec as critical prerequisite). One follow-up commit (`2b4c3fe`) gated theta UI to prevent operator from triggering the silent breakage.

**Cold-start sequence for twenty-second session (issue#28 path)**:

1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. **★ Open `.claude/memory/project_map_edit_origin_rotation.md`** — full B-MAPEDIT-3 spec + the new "Critical pre-implementation findings — issue#27 HIL surfaced" subsection. Both prerequisites (a) plumbing + (b) coherent rendering MUST be in the issue#28 brief.
4. Open `.claude/memory/project_map_viewport_zoom_rules.md` — operator-locked map UX rules.
5. Open `.claude/memory/feedback_subtract_semantic_locked.md` — sign convention applies to theta_deg too (CCW-positive per existing B-MAPEDIT-3 spec, but the SUBTRACT direction follows from the operator-(0,0)-marker model).
6. Verify-before-Plan: read `cold_writer.cpp:371,377,385,515,521,529,649,655,663` to confirm the `cfg.amcl_origin_yaw_deg` consumption is still the gap. Read `occupancy_grid.cpp:113-130` to confirm YAML `origin[2]` parser.
7. Standard pipeline: Planner → Mode-A → Writer → Mode-B → operator HIL (per `feedback_pipeline_short_circuit.md`; B-MAPEDIT-3 is feature-scale + multi-stack).

**If operator brings issue#26 first** (broadcasting-room same-day ship):
1. Read `.claude/memory/project_issue26_measurement_tool.md`.
2. Read `.claude/tmp/plan_issue_26_latency_measurement_tool.md` Mode-A fold (lines 634-849).
3. Run **Planner round 2** with brief that absorbs every Critical fix + Major reframe inline.
4. Mode-A round 2 → Writer → Mode-B → Operator HIL on news-pi01 + MacBook in broadcasting-room.

## Session-end cleanup (twenty-first)

- NEXT_SESSION.md: rewritten as a whole per cache-role rule. Stale TL;DR #1 (issue#6) absorbed into PR #79 merge state + B-MAPEDIT-3 spec, then promoted issue#28 (full B-MAPEDIT-3 with prerequisites surfaced) to TL;DR #1.
- PROGRESS.md twenty-first-session block added at top of session log (chronicler PR #80).
- doc/history.md 스물 한 번째 세션 한국어 block added (chronicler PR #80).
- SYSTEM_DESIGN.md / FRONT_DESIGN.md / per-stack CODEBASE.md: UPDATED in PR #79 (Writer) + chronicler PR #80 (godo-frontend/CODEBASE.md `(aa)` invariant gate fix).
- `.claude/memory/`: 1 new entry (`feedback_subtract_semantic_locked.md`, Writer); MEMORY.md index updated; `project_map_edit_origin_rotation.md` enriched with B-MAPEDIT-3 critical findings (chronicler PR #80).
- `/doc/`: 1 new file (`shotoku_base_move_and_recal_design.md` — issue#29 deferred spec, UART migration pattern); §5.1 added in chronicler PR #80.
- `.claude/tmp/`: `plan_issue_27_map_polish_and_output_transform.md` retained as B-MAPEDIT-3 reference for one more cycle.
- Branches deleted (PR squash-merge cleanup): `feat/issue-27-map-overlay-and-output-transform` (origin auto-deleted via `--delete-branch`).
