# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-05 late-afternoon KST (twenty-sixth-session close — 3 PRs merged: #91 issue#34 doc hierarchy weekly archives + #92 issue#34.1 CLAUDE.md polish + nav footers + #93 issue#28.1 B-MAPEDIT-3 follow-up backlog. Live mode CPU thrashing surface during HIL → motivates issue#11 re-prioritisation).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-05 late-afternoon KST)

1. **★ issue#11 — Live pipelined-parallel multi-thread** (now top priority — empirical motivator captured this session). News-pi01 HIL revealed ONE cold-path thread sustaining 40-60% on a single core while CFS migrates it between cores 0/1/2 (RT hot path on isolated CPU 3 stays at 0.25%, fine). Operator flagged this as the "장시간 운용 부담" concern. Plan + Mode-A round 1 fold preserved at `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`. **Empirical data**: `.claude/memory/project_live_mode_cpu_thrashing_2026-05-05.md`. Re-prioritise: was paused awaiting issue#26 capture; operator now wants to resume directly with the CPU thrashing observation as motivation, decoupled from issue#26 timing baseline.

2. **issue#28.2 — SSE producer-side end-to-end pin** (NEW, from PR #93 Mode-B M1). The B2/B3/B4 SSE tests landed in PR #93 pin only the broadcaster *relay* (frame inject → frame relay), not the *producer* side (`/api/map/edit/coord` handler emitting frames with proper shape). A regression that drops `request_id` from server-side publish, returns "rejected" without `reason`, etc., would NOT be caught. Recommended fix: one integration test that subscribes to `/sse/map-edit/progress` then fires `/api/map/edit/coord`, asserts the actual emitted sequence. ~30-min add. Reviewer flagged as non-blocking for PR #93 merge but worth queuing.

3. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Round 2 + Writer + HIL is half-day at broadcasting-room wired LAN. Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. NOTE: issue#11 may now be unblocked from this — operator decision pending.

4. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment.

5. **issue#4 — AMCL silent-converge diagnostic** — comprehensive HIL baseline through nineteenth-session.

6. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow**. Spec at `/doc/shotoku_base_move_and_recal_design.md`. issue#30 dependency resolved (twenty-fourth) → can resume planning.

7. **issue#17 — GPIO UART direct connection** (perma-deferred).

8. **Bug B — Live mode standstill jitter ~5cm widening** — analysis-first.

9. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic.

10. **Future: SPA Config tab search input** (not in current scope but operator surfaced during PR #93 HIL — there's no in-page search box; manual scroll required to find a key. Track as low-priority UX follow-up; verify if `project_config_tab_grouping.md` (issue#15 candidate) covers this or if it's a separate ask).

**Next free issue integer: `issue#35`** (issue#34 = doc hierarchy MERGED PR #91; issue#34.1 = CLAUDE.md polish MERGED PR #92; issue#28.1 = B-MAPEDIT-3 backlog MERGED PR #93; issue#28.2 = SSE producer-side pin candidate).

## Where we are (2026-05-05 late-afternoon KST — twenty-sixth-session close)

**main = `27669fc`** — PR #93 merged. Three back-to-back ships this session (each squash-merged):
- `6870475` — PR #91 issue#34 (Phase A doc hierarchy weekly archives — 5 master files: 16,586 → 2,623 lines; 14 weekly archives + 5 READMEs created via 5 parallel code-writer subagents)
- `7cb76e8` — PR #92 issue#34.1 (Phase A.5 CLAUDE.md polish 459 → 371 + per-stack nav footers + RPi5 stale "as of 2026-04-26" Module map fix)
- `27669fc` — PR #93 issue#28.1 (B-MAPEDIT-3 follow-up backlog: 13 items B1..B13 = 6 missing tests + 4 trivial cleanups + 3 deletion/hard-removal items including `cfg.amcl_origin_yaw_deg` hard-remove + `flat` legacy key removal from `/api/maps`)

**Open PRs**: docs/2026-05-05-twenty-sixth-session-close (this PR, after merge → main rolls forward).

**Live system on news-pi01**: webctl + frontend + tracker on `27669fc`. PR #93 HIL passed across all 7 scenarios:
- `/api/maps` response no longer carries `flat` key (B13 verified)
- Map list / Activate / Map Edit / OverlayToggleRow toggles persist through hard reload (B6 migration verified)
- `journalctl` clean post-restart (no DEPRECATED warning, no parse error — B12 hard-remove verified)
- Calibrate / Live mode toggles work
- All other features continue working

**B12 preflight regex bug + recovery (the session's near-miss)**: my published preflight `sed -i '/^amcl\.origin_yaw_deg/d'` matched ZERO lines because `/var/lib/godo/tracker.toml` uses TOML **table syntax** (`[amcl]\norigin_yaw_deg = 0`), not the dotted form the regex expected. Tracker entered 70+ count auto-restart loop on first install. Recovery: `sudo sed -i '/^origin_yaw_deg = /d' /var/lib/godo/tracker.toml` (bare key — schema for `origin_yaw_deg` is unique to the `[amcl]` section so this is safe). `feedback_toml_branch_compat.md` extended with the table-syntax lesson. **Memory candidate (next session, NOT yet written)**: a separate "preflight commands must be tested against actual file shape, not the documented schema mental model" feedback — the existing `feedback_toml_branch_compat.md` boost may be sufficient.

## Twenty-sixth-session merged-PR summary

### PR #91 (`6870475`, MERGED): issue#34 — Phase A doc hierarchy weekly archive migration
- 5 master files restructured into lean (invariants/scaffold + Index) + weekly archives:
  - godo-webctl/CODEBASE.md  4293 → 1034 (-3259)
  - godo-frontend/CODEBASE.md 3920 → 611 (-3309)
  - production/RPi5/CODEBASE.md 4992 → 761 (-4231)
  - PROGRESS.md  1420 → 196 (-1224)
  - doc/history.md  1961 → 21 (-1940) [Korean]
- 14 weekly archives + 5 READMEs created (W17, W18, W19 spans).
- Migration via 5 parallel `code-writer` subagents (one per file). Conservation verified per agent: line/entry counts exact match, sha256 byte-identical for PROGRESS.md (1232 lines), Korean encoding intact for doc/history.md.
- CLAUDE.md §5 directory structure + §6 cascade-edit rule absorb new convention. `.claude/agents/{code-writer, code-reviewer, code-planner}.md` updated. `.claude/memory/feedback_codebase_md_freshness.md` "How to apply" rewritten.
- Operator-locked Option (b): master files keep invariants + Index ONLY — NO inline most-recent dated entry. Cascading doc links carry navigation.
- Pipeline: direct parallel-writer (5 agents in parallel — `code-writer` + verbatim shared schema). No Mode-A on plan; no Mode-B on output (mechanical work, Parent verified post-write).

### PR #92 (`7cb76e8`, MERGED): issue#34.1 — Phase A.5 CLAUDE.md polish + per-stack nav footers
- CLAUDE.md 459 → 371 lines (-88):
  - §3 Phases ASCII timeline → 1-paragraph current-phase line + PROGRESS pointer.
  - §4 Hardware connection sub-section folded into 1 line.
  - §5 Directory tree (56 lines) → 13-line "Doc hierarchy at a glance" bulleted nav (full tree lives in root CODEBASE.md).
  - §9 Open questions table (mostly resolved) → 6-line summary (Q4/Q5 still open).
  - KEEP: §6 Golden Rules, §7 Agent pipeline, §8 Deploy, §10 References (operating-rule core).
- Per-stack nav footers (godo-webctl, godo-frontend, production/RPi5 masters) added — mirrors PROGRESS.md `## Quick reference links` pattern operator approved at PR #91 close. Each footer points at: project guide, cross-stack scaffold, relevant design doc, sibling stacks (with one-line "how stacks connect" hint), project state, recent week archive, README.
- production/RPi5/CODEBASE.md:30 stale "Module map (current — as of 2026-04-26 Phase 4-2 D Wave B)" + "per-date entries below this section" claim fixed (post-archive, both inaccurate).
- Pipeline: direct-writer + Parent self-verify (small surface, no test impact).

### PR #93 (`27669fc`, MERGED): issue#28.1 — B-MAPEDIT-3 follow-up backlog batch (B1..B13)
- 49 files; +1028 / -956. 4 deletions (2 components + 2 mount tests), 3 new test files (12 new test cases all green).
- B1-B6 tests; B7-B9 trivial cleanups; B11-B13 deletions including `cfg.amcl_origin_yaw_deg` hard-remove (9 source-tree sites + 8 test sites; schema array size + static_assert + 5 cross-stack mirrors all 68→67) and `/api/maps` `flat` legacy key removal (backend + frontend coupled).
- Build clean across 3 stacks: tracker 48/48 ctest, webctl 1056 pytest, frontend 473 vitest, build 217 modules.
- Pipeline: full (Planner → direct-Writer (in this session, the planner output from start was used as spec; no Mode-A round on it because operator authorised scope explicitly) → Mode-B APPROVE with M1 (queued as issue#28.2) + 3 Minor non-blocking findings).
- HIL near-miss recovered: TOML preflight regex bug + tracker auto-restart loop → operator + Parent diagnosed via direct UDS test (`ConnectionRefusedError`) + journal showing `unknown TOML key 'amcl.origin_yaw_deg'` → corrected sed regex → tracker green.

## Live mode CPU thrashing observation (NEW this session — escalating)

**Initial empirical capture (~16:35 KST, ~minutes into Live mode)**:
- TID 3438307 (cold-path AMCL kernel) sustains 40-60% CPU on a single core. utime/stime ratio = 99.8% user-mode.
- CFS migrates this thread between cores 0/1/2 every few seconds — operator's "한 코어 100% → 다른 코어 100%" pattern.
- RT hot path TID 3438312 (cpus_allowed=3, prio=-51) stays at 0.25% — hot path isolation working AT THIS POINT.
- System load avg 7.35 (4-core box).

**Long-running follow-up (~18:00 KST, ~1-2 hours into Live mode — NEW)**:
- **All four cores pegged at 100%, including CPU 3.** RT isolation appears broken under sustained operation.
- Possible mechanisms: particle-cloud growth over time, cache thrashing, scan backlog buildup, or `isolcpus=` kernel parameter not applied on this host.
- Open question: is SCHED_FIFO + CPU 3 affinity alone sufficient, or does the project need full `isolcpus=3 nohz_full=3 rcu_nocbs=3` kernel cmdline? `cat /proc/cmdline` at next session start will answer.

This is the empirical motivator for issue#11 (Live pipelined-parallel multi-thread) AND raises a separate concern about CPU 3 isolation completeness (`project_cpu3_isolation.md` may need extension). Mode-A round 1 of issue#11 REJECTed on numerical foundations (K≈16 not K=1, N=500 not N=10000). Re-running with this CPU data + the issue#30 σ-schedule resolution should land cleaner.

Full memory + diagnostic command snippets: `.claude/memory/project_live_mode_cpu_thrashing_2026-05-05.md`.

## Quick memory bookmarks (★ open these first on cold-start)

This session updated/added 2 memory entries:

1. ★ **NEW** `.claude/memory/project_live_mode_cpu_thrashing_2026-05-05.md` — empirical CPU data (per-thread + core migration). Open this first when resuming issue#11.
2. **UPDATED** `.claude/memory/feedback_toml_branch_compat.md` — appended TOML table-syntax sed regex trap section (PR #93 HIL incident lesson; operator hit 70-count auto-restart loop because the dotted-form regex matched zero lines).

Carryover (still active from prior sessions):
- `project_pipelined_compute_pattern.md` ★ — issue#11 reference design pattern.
- `project_cpu3_isolation.md` — RT hot path isolation (verified working at TID 3438312).
- `project_issue11_analysis_paused.md` — full Mode-A round 1 REJECT context.
- `project_issue26_measurement_tool.md` — paused at Mode-A round 1 REJECT.
- `project_rplidar_cw_vs_ros_ccw.md` ★ 5-path SSOT (load-bearing for any LIDAR-angle code).
- `project_pick_anchored_yaml_normalization_locked.md` ★ issue#30 SSOT for pick-anchored semantic + yaw direction lock.
- `project_issue30_hil_findings_2026-05-05.md` — full Finding 1/2/3 history with all 3 fix rounds.
- `project_pristine_baseline_pattern.md`, `feedback_overlay_toggle_unification.md`.
- `feedback_timestamp_kst_convention.md`, `project_amcl_yaw_metadata_only.md`.
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`, `feedback_ssot_following_discipline.md`, `feedback_deploy_branch_check.md`, `feedback_relaxed_validator_strict_installer.md`, `feedback_post_mode_b_inline_polish.md`, `feedback_verify_before_plan.md`, `feedback_helper_injection_for_testability.md`, `feedback_build_grep_allowlist_narrowing.md`, `feedback_ship_vs_wire_check.md`, `feedback_docstring_implementation_drift.md`, `feedback_manual_maps_backup_pre_hil.md`.
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`.
- `frontend_stack_decision.md`, `reference_history_md.md`.
- `project_lidar_overlay_tracker_decoupling.md`.
- `project_amcl_sigma_sweep_2026-04-29.md`.
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`.
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`, `project_config_tab_grouping.md`.
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`.
- `project_repo_canonical.md`, `project_tracker_down_banner_action_hook.md`, `project_restart_pending_banner_stale.md`.
- `project_amcl_multi_basin_observation.md`, `project_calibration_alternatives.md`, `project_hint_strong_command_semantics.md`, `project_gpio_uart_migration.md`, `project_mapping_precheck_and_cp210x_recovery.md`, `project_uds_bootstrap_audit.md`.

## Quick orientation files for next session

1. **CLAUDE.md** §6 Golden Rules + §7 Agent pipeline + §8 Deployment (now lean — 371 lines).
2. **`CODEBASE.md`** (root) — cross-stack scaffold. Updated this session with weekly-archive convention.
3. **`DESIGN.md`** (root) — TOC. UNCHANGED.
4. **`.claude/memory/MEMORY.md`** — full index (~57 entries; +1 added, 1 updated this session).
5. **PROGRESS/2026-W19.md** — twenty-fifth + twenty-sixth session blocks (chronicler will rotate the most-recent one in here at session-close).
6. **doc/history/2026-W19.md** — corresponding Korean narratives.
7. **`.claude/tmp/plan_issue_11_live_pipelined_parallel.md`** — issue#11 Round 1 plan + Mode-A round 1 fold; load-bearing for next session's resume.
8. **`.claude/tmp/plan_issue_28.1_and_doc_hierarchy.md`** — this session's plan; useful reference for cascade pattern + parallel-agent migration template.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 35); decimal for sub-issues (e.g. `issue#28.1`, `issue#28.2`, `issue#30.1`, `issue#34.1`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

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
- `issue#28.1` — B-MAPEDIT-3 follow-up backlog — **DONE in PR #93**.
- `issue#28.2` — SSE producer-side end-to-end pin — candidate (Mode-B M1 carryover).
- `issue#29` — SHOTOKU base-move + two-point cal-reset workflow.
- `issue#30` — YAML normalization to (0, 0, 0°) per Apply — DONE in PR #84 (3 HIL fold rounds).
- `issue#30.1` — PR #84 Mode-B round 2 backlog — DONE in PR #87.
- `issue#31` (candidate) — Vector map representation feasibility study (perma-deferred research).
- `issue#32` — Backup TS regex + frontend formatter KST transition — DONE in PR #88.
- `issue#33` — Apply-on-pristine lineage init + backup map-name column — DONE in PR #89.
- `issue#34` — Doc hierarchy weekly archive migration — **DONE in PR #91**.
- `issue#34.1` — CLAUDE.md polish + per-stack nav footers — **DONE in PR #92**.

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions**:
- `plan_issue_28.1_and_doc_hierarchy.md` — full Phase A + Phase B plan with operator decisions baked in. Useful template for future "doc reorg + code cleanup combo" PRs and for the parallel-agent migration pattern.
- `plan_issue_11_live_pipelined_parallel.md` — Round 1 plan + Mode-A round 1 fold. **Reload for next session** (top priority).
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold.
- `plan_issue_30_yaml_normalization.md` — 1101 lines including all 5 review folds (issue#30 family). Still load-bearing for issue#29 (SHOTOKU base-move).
- `plan_issue_30.1_mode_b_backlog.md` — Mode-B-backlog cleanup pattern reference.

**Delete when convenient** (older plans no longer referenced):
- `plan_issue_28_b_mapedit3_yaw_rotation.md` (PR #81 reference — superseded by issue#30 lock + issue#28.1 close)
- `plan_issue_27_map_polish_and_output_transform.md` (PR #79 reference)
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference)
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference)
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference)

## Tasks alive for next session

- **★ issue#11 — Live pipelined-parallel** (TL;DR #1 — RESUMED with empirical CPU motivator)
- **issue#28.2 — SSE producer-side pin** (TL;DR #2 — NEW carryover from PR #93 Mode-B)
- **issue#26 — measurement tool round 2 + Writer + HIL** (TL;DR #3 — may be unblocked / re-prioritized)
- **issue#13 — distance-weighted likelihood** (TL;DR #4)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #5)
- **issue#29 — SHOTOKU base-move** (TL;DR #6)
- **issue#17 — GPIO UART migration** (TL;DR #7 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #8)
- **issue#7 — boom-arm angle masking** (TL;DR #9)
- **SPA Config tab search input** (TL;DR #10 — UX follow-up)

## Twenty-seventh-session warm-up note

Twenty-sixth was a single afternoon arc (~3.5 h, 13:30–17:00 KST) that shipped 3 PRs:
- One pure-doc PR (#91, issue#34 weekly archive migration) using 5 parallel writer subagents — first time the project used parallel agents for a coordinated reorg. Pattern: each agent gets one file + verbatim shared schema + 7-step verify; Parent integrates afterwards. Worked cleanly; conservation verified per agent (sha256 byte-identical for PROGRESS.md). Re-usable for future bulk-reorg.
- One follow-up doc-polish PR (#92, issue#34.1) — direct-writer, no formal pipeline.
- One feature PR (#93, issue#28.1) — single full-scope writer, then Mode-B APPROVE-WITH-NITS.

Near-miss: TOML preflight regex bug nearly bricked the production tracker on news-pi01 (auto-restart loop hit count 70+). Recovery was clean (5 min — direct UDS test + journal grep + corrected sed). Lesson absorbed into `feedback_toml_branch_compat.md`. The Mode-B reviewer should add a "preflight commands must be tested against actual file shape" check to the deploy-readiness review block.

Live-mode CPU thrashing is the new lead. Issue#11 plan is ready; the next session can open with that as the top priority.

**Cold-start sequence for twenty-seventh session**:

1. Read CLAUDE.md (now lean — 371 lines after PR #92).
2. Read this NEXT_SESSION.md.
3. **★ Open `.claude/memory/project_live_mode_cpu_thrashing_2026-05-05.md`** + `project_pipelined_compute_pattern.md` + `.claude/tmp/plan_issue_11_live_pipelined_parallel.md` for issue#11 resume.
4. PR #91/#92/#93 history is in this NEXT_SESSION.md plus per-stack `<stack>/CODEBASE/2026-W19.md` weekly archive entries.

**Most likely first task**: TL;DR #1 (issue#11 — Live pipelined-parallel). Operator may pivot to issue#28.2 (SSE producer-side pin, ~30 min add) as a warm-up before tackling the heavier issue#11 plan.

## Session-end cleanup (twenty-sixth)

- NEXT_SESSION.md: rewritten as a whole per cache-role rule. Stale TL;DR #1 (issue#28.1) absorbed → MERGED in PR #93. New TL;DR #1 = issue#11 (RESUMED) + new TL;DR #2 = issue#28.2 (SSE producer-side pin). issue#34 / 34.1 / 28.1 added to issue-label reservation table as DONE.
- `.claude/memory/`: 1 new entry (`project_live_mode_cpu_thrashing_2026-05-05.md`), 1 updated (`feedback_toml_branch_compat.md` appended TOML table-syntax sed regex section). Index in `MEMORY.md` updated.
- `.claude/tmp/plan_issue_28.1_and_doc_hierarchy.md`: kept (reference for future doc-reorg + cleanup combo + parallel-agent migration template).
- PROGRESS / doc/history: chronicler will write the 26th-session block at session-close — Parent territory done here in NEXT_SESSION.md + memory.
- Per-stack CODEBASE.md masters: each PR added its weekly archive entry inline — 2026-W19.md gained 3 dated entries on godo-webctl + 3 on godo-frontend + 2 on production/RPi5 spread across the 3 PRs. Master files unchanged (Option (b) lock).
- SYSTEM_DESIGN.md / FRONT_DESIGN.md: PR #93 updated both (B11 past-tense + B12 §13.8 hard-removal section). chronicler may add a session-close cross-ref but no design decisions introduced.
- Root CODEBASE.md: PR #91 + #92 updated. PR #93 did not touch.
- Branches: 3 feature branches squash-merged with `--delete-branch` on origin (chore/issue-34-doc-hierarchy-weekly-archives, chore/issue-34.1-claude-md-polish-and-nav-footers, feat/issue-28.1-mapedit3-followup-backlog); local copies cleaned via `git branch -d`.
