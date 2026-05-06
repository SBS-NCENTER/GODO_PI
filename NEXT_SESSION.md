# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-06 morning KST (twenty-seventh-session close — 2 PRs merged: #95 issue#28.2 SSE producer-side pin + #96 issue#11 P4-2-11-0 trim Phase-0 instrumentation. Live mode CPU thrashing reclassified normal-as-designed via 12.5h monitoring. Phase-0 HIL captured 2,716 scans / 5-min main dataset → issue#11 Mode-A round 2 input ready).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-06 morning KST)

1. **★ issue#11 Mode-A round 2** — The numerical foundation gap that REJECTed Round 1 is CLOSED. PR #96 captured 2,716 scans across 3 windows on news-pi01 with `GODO_PHASE0=1`. Main dataset (5-min, 2166 scans, single PID): **p50 TOTAL = 136.15 ms / 7.34 Hz; evaluate_scan = 94.85 ms (69.7%); LF rebuild = 39.58 ms (29.1%); jitter+normalize+resample combined < 1%; residual 0.5%**. Cross-capture variance < 0.5% — empirically locked. **Action**: re-spin `.claude/tmp/plan_issue_11_live_pipelined_parallel.md` Round 2 fold with these numbers; replace back-of-envelope estimates; re-derive K-budget + σ-schedule + Option B/C/D scoring. Mode-A round 1 mechanical findings (C4 schema row count today is 67 → 68 / C5 invariant `(s)` / C6 EDT scratch buffer / C7 M1 spirit articulation) absorb into the new plan body. Capture results stored at `.claude/tmp/phase0_results_5min_20260506_095949.md` (main dataset) + 2 supplementary files.

2. **issue#11 main implementation** (post-Round-2-approve) — Option C fork-join particle eval pool. Architecture decision pre-validated by Phase-0 numbers: Option C alone projects **13.7 Hz** (37% margin over 10 Hz LiDAR). Plan elements that survived Round 1: ParallelEvalPool static lib (`src/parallel/`), 3 worker threads pinned to cpu 0/1/2, fork-join per `Amcl::step`, no Seqlock change (handoff seam unchanged). New TOML key `amcl.parallel_eval_workers` Recalibrate-class. ~280 LOC + tests. Writer task ordering already drafted in plan §10 (P4-2-11-1 through P4-2-11-8); skip P4-2-11-0 (already shipped as PR #96 trim form).

3. **issue#19 — EDT 2D Felzenszwalb 3-way parallelization** (★ ELEVATED from "follow-up" to "important secondary"). Phase-0 HIL revealed LF rebuild is **29% (39.58 ms)** of every scan — not a small slice. Option C alone gets to 13.7 Hz; **Option C + issue#19 → 21.4 Hz** (114% margin). Reuses the same `ParallelEvalPool` primitive (Mode-A round 1 C6 surfaced the `parallel_for_with_scratch<S>` API extension needed because `edt_1d`'s `(v, z)` scratch buffers aren't thread-safe). Sequence: ship issue#11 first (validates the pool primitive), then issue#19 as small follow-up (~80 LOC).

4. **issue#X (NEW) — UDS hang after RPLIDAR I/O fallback to Idle** (Medium priority — needs new-integer assignment, candidate is `issue#35` — see reservation table). Reproduced this session: artificial cpu 0/1/2 100% saturation (e.g., concurrent build) → `rplidar: grabScanDataHq failed 5 times in a row` → `cold_writer.cpp::run_cold_writer` falls back to Idle gracefully BUT UDS server thread's listen-backlog drops to 0 (kernel rejects accept; SPA + webctl see "tracker unreachable"). Tracker process alive, all threads state=S. Recovery: `systemctl restart godo-tracker`. **Investigation seam**: `src/localization/cold_writer.cpp` exception-catch path's interaction with `src/uds/uds_server.cpp` accept loop. Rare in normal ops (no cpu 100% saturation) but real bug worth fixing because it manifests as a "ghost" tracker that responds to nothing.

5. **issue#13 — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Orthogonal to issue#11 (modifies `evaluate_scan` body, not the caller); composes with Option C without re-design. Standalone single-knob algorithmic experiment. Phase-0 numbers don't change priority here.

6. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. Independent of issue#11 now (Phase-0 produced the in-tracker breakdown). Resume-when-needed; not blocking anything.

7. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow**. Spec at `/doc/shotoku_base_move_and_recal_design.md`. issue#30 dependency resolved (twenty-fourth) → can resume planning anytime.

8. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic.

9. **issue#17 — GPIO UART direct connection** (perma-deferred).

10. **Bug B — Live mode standstill jitter ~5cm widening** — analysis-first. Phase-0 may help by giving per-scan budget context; still operator-driven HIL needed.

11. **PR #96 / Phase-0 cleanup decision point** (after Mode-A round 2 absorbs the data): revert PR #96 (TEMPORARY contract honored — single-PR back-out clean) OR promote to permanent diagnostic via the documented mid-life path (Phase0BreakdownSnapshot Seqlock + UDS getter + webctl `/api/system/phase0` endpoint + `[phase0-publisher-grep]` build-grep + invariant `(s)` promotion). Operator decides post-round-2.

12. **Future: SPA Config tab search input** (not in current scope but operator surfaced during PR #93 HIL — there's no in-page search box; manual scroll required. Track as low-priority UX follow-up; verify if `project_config_tab_grouping.md` (issue#15 candidate) covers this or if it's a separate ask).

**Next free issue integer: `issue#35`** (issue#28.2 DONE in PR #95; issue#11 P4-2-11-0 DONE in PR #96; candidate issue#35 = UDS hang after RPLIDAR fallback).

## Where we are (2026-05-06 morning KST — twenty-seventh-session close)

**main = `3428431`** — PR #97 merged (twenty-seventh-session-close docs). Recent shipping order:
- `61fc445` — PR #94 (twenty-sixth-session close, 2026-05-05)
- `a0a3113` — PR #95 issue#28.2 (SSE producer-side pin, 2026-05-06 ~02:00 KST)
- `53453f5` — PR #96 issue#11 P4-2-11-0 (trim Phase-0 instrumentation, 2026-05-06 ~09:30 KST)
- `3428431` — PR #97 docs (twenty-seventh-session close, 2026-05-06 ~10:30 KST)

**Open PRs**: chore/2026-05-06-twenty-seventh-session-parent-territory (Parent territory follow-up, in progress at session-close).

**Live system on news-pi01**: webctl + frontend + tracker on `3428431`. Tracker most recently restarted at session-close to clear `GODO_PHASE0=1` env (override.conf removed via `rm`). Mode = Idle (operator may toggle Live in SPA on next ops session). Long-running monitor `/tmp/cpu_monitor.py` (PID 1779299, started 21:32:44 2026-05-05 KST) still emitting heartbeats but tracking dead PID 1708747 — kill via `kill 1779299` if desired (CSV at `/tmp/cpu_monitor.csv` preserved as re-occurrence baseline).

**Near-miss recovered (the session's only incident)**: tracker UDS hung after build-CPU-saturation triggered RPLIDAR USB scan-reader failures (5× consecutive `grabScanDataHq` timeouts → cold_writer fallback to Idle, BUT UDS listen-backlog dropped to 0). Recovery via `systemctl restart godo-tracker`. Documented as candidate **issue#35** for next-session investigation.

## Twenty-seventh-session merged-PR summary

### PR #95 (`a0a3113`, MERGED): issue#28.2 — SSE producer-side end-to-end pin for `/api/map/edit/coord`

- Closes PR #93 Mode-B M1 carryover (relay tests pinned only broadcaster relay, not handler emit shape).
- 2 integration test cases in `godo-webctl/tests/test_map_edit_sse_e2e.py` (177 LOC / 16 assertions): T1 happy path + T2 reject path. request_id consistency, monotonic progress, expected phase set, reason-on-rejection all pinned.
- Drive-by: `tests/test_app_hardware_tracker.py` auth fix (added `_login_admin` + Bearer header on `/api/calibrate`); `pyproject.toml` `addopts = "-ra -m 'not hardware_tracker'"` so the marker is genuinely default-skipped.
- 1058 webctl pytest pass + 1 deselected (default suite). Operator HIL: `uv run pytest -m hardware_tracker -v` → `1 passed in 2.31s` (calibrate auth fix verified end-to-end).
- Pipeline: direct-Writer (Parent) → Mode-B implicit via test execution → squash-merge.

### PR #96 (`53453f5`, MERGED): issue#11 P4-2-11-0 — Trim Phase-0 cold-path component instrumentation (TEMPORARY)

- env-var-gated (`GODO_PHASE0=1`) per-scan stderr emit of LF rebuild + jitter + evaluate_scan + normalize + resample ns slices.
- Output line: `PHASE0 path=<oneshot|live_legacy|live_pipelined> scan=N iters=K lf_rebuild_ns=... ... total_ns=...`.
- 6 files / +390 -6: new POD struct `Phase0InnerBreakdown` (32 B) in `core/rt_types.hpp`; new `Amcl::step` 5-arg + 3-arg overloads (existing 4-arg / 2-arg delegate with nullptr — zero-overhead path preserved); `cold_writer.cpp` env latch + thread-local accumulators + helpers + wire-in to all 3 wrappers; new test `tests/test_phase0_env.cpp` (3 cases / 16 assertions).
- 49/49 ctest hardware-free + 1/1 python-required pass. Build greps clean (`[m1-no-mutex]`, `[scan-publisher-grep]`, etc.) — no new grep added (stderr emit, not Seqlock).
- Mode-B reviewer APPROVE (zero blockers). HIL captured 3 windows totaling 2,716 scans → main dataset stored at `.claude/tmp/phase0_results_5min_20260506_095949.md`.
- Pipeline: full (Mode-A round 1 lane decision → trim path resolution → direct-Writer → Mode-B APPROVE → squash-merge).

### PR #97 (`3428431`, MERGED): docs — twenty-seventh-session close

- chronicler skill output: PROGRESS/2026-W19.md, doc/history/2026-W19.md, godo-webctl/CODEBASE/2026-W19.md, production/RPi5/CODEBASE/2026-W19.md, doc/issue11_design_analysis.md.
- Twenty-seventh-session block prepended (most recent first per weekly-archive convention). 281 insertions, 1 deletion.

## Phase-0 capture summary (2026-05-06 09:50–10:00 KST, 3 windows)

| Capture | Window | Scans | p50 TOTAL | LF % | eval % | residual |
|---|---|---|---|---|---|---|
| #1 | 90 s, 2 PIDs | 410 + 141 | 138 / 139 ms | 29.1% | 69.7% | 0.6% |
| #2 | 2 min, 2 PIDs | 148 + 608 | 139 / 139 ms | 29.0% | 69.6% | 0.6% |
| **#3 (main dataset)** | **5 min, 1 PID** | **2166** | **136.15 ms** | **29.1%** | **69.7%** | **0.5%** |

| Stage | p50 (5-min, 2166 scans) | p90 | p99 | max |
|---|---|---|---|---|
| evaluate_scan | 94.85 ms | 103.60 | 112.65 | 142.74 |
| LF rebuild | 39.58 ms | 42.70 | 46.20 | 62.44 |
| jitter | 0.77 ms | 0.82 | 1.30 | 5.30 |
| normalize | 0.14 ms | 0.15 | 0.21 | 0.88 |
| resample | 0.07 ms | 0.08 | 0.11 | 0.57 |
| **TOTAL** | **136.15 ms** | 147.99 | 158.85 | 207.04 |

Capture results paths (kept in `.claude/tmp/`, gitignored):
- `phase0_results_20260506_095254.md` (capture #1)
- `phase0_results_20260506_095403.md` (capture #2)
- `phase0_results_5min_20260506_095949.md` (★ main dataset — feed into Mode-A round 2 fold)

## Quick memory bookmarks (★ open these first on cold-start)

This session updated/added 3 memory entries:

1. **UPDATED** `.claude/memory/project_live_mode_cpu_thrashing_2026-05-05.md` — appended "Resume + reclassification" section (operator-locked normal-as-designed conclusion).
2. ★ **NEW** `.claude/memory/feedback_systemctl_edit_empty_content_no_save.md` — systemctl edit empty-content gotcha + safe directive removal options A (comment) and B (rm).
3. ★ **NEW** `.claude/memory/project_phase0_instrumentation_pattern.md` — Phase-0 trim instrumentation reusable pattern (env-var + thread-local + stderr emit + single-PR-revert clean) + promotion path to permanent diag.

Carryover (still active from prior sessions):

- `project_pipelined_compute_pattern.md` ★ — issue#11 reference design pattern.
- `project_cpu3_isolation.md` — RT hot path isolation. (validated again this session: jitter p99=18.5 µs, cpu3 idle 99.6%)
- `project_issue11_analysis_paused.md` — full Mode-A round 1 REJECT context (now closeable since Phase-0 numbers landed).
- `project_issue26_measurement_tool.md` — paused at Mode-A round 1 REJECT.
- `project_rplidar_cw_vs_ros_ccw.md` ★ 5-path SSOT (load-bearing for any LiDAR-angle code).
- `project_pick_anchored_yaml_normalization_locked.md` ★ issue#30 SSOT.
- `project_issue30_hil_findings_2026-05-05.md` — full Finding 1/2/3 history.
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

1. **CLAUDE.md** §6 Golden Rules + §7 Agent pipeline + §8 Deployment.
2. **`CODEBASE.md`** (root) — cross-stack scaffold.
3. **`DESIGN.md`** (root) — TOC. UNCHANGED this session.
4. **`.claude/memory/MEMORY.md`** — full index (~59 entries; 2 added + 1 updated this session).
5. **PROGRESS/2026-W19.md** — twenty-sixth + twenty-seventh session blocks.
6. **doc/history/2026-W19.md** — corresponding Korean narratives.
7. ★ **`.claude/tmp/plan_issue_11_live_pipelined_parallel.md`** — Round 1 plan + Mode-A round 1 fold + **Round 2 empirical fold (Parent — 2026-05-05 22:50 KST)**. Round 2 fold has the macroscopic 7 Hz / 137 ms / 16-iter empirical baseline; the new 5-min PHASE0 capture data fills in the per-stage decomposition.
8. ★ **`.claude/tmp/plan_issue_11_phase0_instrumentation.md`** — Round 1 plan + Mode-A round 1 fold + Trim path resolution. Records the lane decision and what got trimmed.
9. ★ **`.claude/tmp/phase0_results_5min_20260506_095949.md`** — main dataset for Mode-A round 2 fold.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = **35**); decimal for sub-issues (e.g. `issue#28.1`, `issue#28.2`, `issue#30.1`, `issue#34.1`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

**Reservations from /doc/issue11_design_analysis.md §8** (DO NOT use these integers for new issues):

- `issue#19` — EDT 2D Felzenszwalb parallelization. **★ ELEVATED to "important secondary"** (Phase-0 HIL: LF rebuild = 29% / ~40 ms per scan; issue#19 brings 13.7 Hz → 21.4 Hz).
- `issue#20` — Track D-5-P (deeper σ schedule for OneShot, staggered-tier).
- `issue#21` — NEON/SIMD vectorization of `evaluate_scan` per-beam loop. Phase-0 reveals eval is 70% so this stays viable (orthogonal to Option C).
- `issue#22` — Adaptive N (KLD-sampling).
- `issue#23` — LF prefetch / gather-batch.
- `issue#24` — Phase reduction 3→1 in Live carry (TOML-only).
- `issue#25` — `amcl_anneal_iters_per_phase` 10→5 (TOML-only).
- `issue#26` — Cross-device GPS-synced measurement tool.
- `issue#27` — output_transform + SUBTRACT origin + LastOutput SSE — DONE in PR #79.
- `issue#28` — B-MAPEDIT-3 yaw rotation — DONE in PR #81.
- `issue#28.1` — B-MAPEDIT-3 follow-up backlog — DONE in PR #93.
- `issue#28.2` — SSE producer-side end-to-end pin — **DONE in PR #95**.
- `issue#29` — SHOTOKU base-move + two-point cal-reset workflow.
- `issue#30` — YAML normalization to (0, 0, 0°) per Apply — DONE in PR #84 (3 HIL fold rounds).
- `issue#30.1` — PR #84 Mode-B round 2 backlog — DONE in PR #87.
- `issue#31` (candidate) — Vector map representation feasibility study (perma-deferred research).
- `issue#32` — Backup TS regex + frontend formatter KST transition — DONE in PR #88.
- `issue#33` — Apply-on-pristine lineage init + backup map-name column — DONE in PR #89.
- `issue#34` — Doc hierarchy weekly archive migration — DONE in PR #91.
- `issue#34.1` — CLAUDE.md polish + per-stack nav footers — DONE in PR #92.
- `issue#11 P4-2-11-0` — Trim Phase-0 cold-path component instrumentation — **DONE in PR #96** (TEMPORARY; cleanup decision after Mode-A round 2).
- **`issue#35` (candidate)** — UDS hang after RPLIDAR I/O fallback to Idle. Scope: investigate `cold_writer.cpp::run_cold_writer` exception path's interaction with `uds_server.cpp` accept loop; symptom `ss -lx` `LISTEN 0 0`; Medium priority.

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions**:

- `plan_issue_11_live_pipelined_parallel.md` ★ — Round 1 plan + Mode-A round 1 fold + Round 2 empirical fold. **Reload for next session** (top priority).
- `plan_issue_11_phase0_instrumentation.md` — Round 1 plan + Mode-A round 1 fold + Trim path resolution. Reference for trim pattern future re-use.
- `plan_issue_28.1_and_doc_hierarchy.md` — full Phase A + Phase B plan with operator decisions baked in. Useful template for future "doc reorg + code cleanup combo" PRs and for the parallel-agent migration pattern.
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

- **★ issue#11 Mode-A round 2** (TL;DR #1 — fold Phase-0 numbers into plan)
- **issue#11 main implementation** (TL;DR #2 — Option C fork-join particle eval pool, post-round-2 approve)
- **issue#19 EDT 3-way** (TL;DR #3 — ELEVATED, ships after issue#11)
- **issue#35 candidate — UDS hang after RPLIDAR fallback** (TL;DR #4 — NEW, Medium priority)
- **issue#13 distance-weighted likelihood** (TL;DR #5)
- **issue#26 measurement tool round 2** (TL;DR #6 — paused, no longer blocking)
- **issue#29 SHOTOKU base-move** (TL;DR #7)
- **issue#7 boom-arm masking** (TL;DR #8)
- **issue#17 GPIO UART** (TL;DR #9 — perma-deferred)
- **Bug B Live mode standstill jitter** (TL;DR #10)
- **PR #96 / Phase-0 cleanup decision** (TL;DR #11 — after Mode-A round 2)

## Twenty-eighth-session warm-up note

Twenty-seventh was a **single overnight arc** (12.5+ hours, evening 2026-05-05 → morning 2026-05-06):

- Started with operator merging twenty-sixth-session-close PR #94 + asking to continue Live mode CPU thrashing investigation.
- ~12 hours of monitoring + 1s fastcap definitively resolved the CPU pattern as normal-as-designed (no bug; CFS migration of single saturated thread).
- doc/issue11_design_analysis.md §2.6 added mid-session for operator's Option B vs C misunderstanding.
- 2 PRs landed in arc: #95 (issue#28.2 SSE producer pin, ~2 AM KST) and #96 (issue#11 P4-2-11-0 trim Phase-0, ~9:30 AM KST).
- HIL on PR #96: 3 capture windows totaling 2,716 scans on news-pi01, locked in p50 = 136.15 ms with 0.5% cross-capture variance.
- Near-miss recovered: tracker UDS hung after build-CPU-saturation triggered RPLIDAR fallback path bug; recovered via `systemctl restart`. Candidate issue#35 logged.
- 2 lessons surfaced into memory: `feedback_systemctl_edit_empty_content_no_save.md` + `project_phase0_instrumentation_pattern.md` (reusable trim pattern).

**Cold-start sequence for twenty-eighth session**:

1. Read `CLAUDE.md` (operating rules).
2. Read this `NEXT_SESSION.md`.
3. ★ Open `.claude/tmp/plan_issue_11_live_pipelined_parallel.md` Round 2 fold + `.claude/tmp/phase0_results_5min_20260506_095949.md` for the empirical numbers.
4. ★ Open `.claude/memory/project_phase0_instrumentation_pattern.md` for the reusable trim pattern (in case future measurement work needs it).
5. PR #95/#96/#97 history in `PROGRESS/2026-W19.md` + per-stack `<stack>/CODEBASE/2026-W19.md` weekly archive entries.

**Most likely first task**: TL;DR #1 (issue#11 Mode-A round 2). Drop the Phase-0 numbers into the plan's Round 2 fold, replace estimates with measurements, re-derive K-budget + σ-schedule trade-offs + Option B/C/D scoring under empirical foundation. Should be a focused half-day of planner + reviewer Mode-A pass.

## Session-end cleanup (twenty-seventh — Parent territory follow-up commit)

- This file (`NEXT_SESSION.md`): rewritten as a whole per cache-role rule. Stale TL;DR items absorbed (issue#28.2 → DONE in PR #95; issue#11 was top priority → now Mode-A round 2 specific with measurements ready). New TL;DR ordering reflects post-Phase-0 priorities (issue#19 elevated; issue#35 candidate logged).
- `.claude/memory/`: 2 new entries (`feedback_systemctl_edit_empty_content_no_save.md`, `project_phase0_instrumentation_pattern.md`); 1 updated (`project_live_mode_cpu_thrashing_2026-05-05.md` — Resume + reclassification). Index in `MEMORY.md` updated.
- `.claude/tmp/plan_issue_11_phase0_instrumentation.md`: kept (trim pattern reference).
- `.claude/tmp/phase0_results_*.md`: kept (Mode-A round 2 input data).
- PROGRESS / doc/history: chronicler wrote the 27th-session block in PR #97.
- Per-stack CODEBASE.md weekly archives: PR #95 added webctl entry; PR #96 added RPi5 entry. Master files unchanged (Option (b) lock).
- SYSTEM_DESIGN.md / FRONT_DESIGN.md: UNCHANGED (no design decisions introduced; Phase-0 is a TEMPORARY measurement, not a design SSOT entry).
- Root CODEBASE.md / DESIGN.md: UNCHANGED (no family-shape shift).
- Branches: 2 feature branches squash-merged with `--delete-branch` on origin (`feat/issue-28.2-sse-producer-side-pin`, `feat/issue-11-phase0-trim-instrumentation`). Local: cleanup in this Parent commit.
- Long-running monitor `/tmp/cpu_monitor.py` (PID 1779299): still emitting heartbeats but tracking dead PID 1708747 — operator may `kill 1779299` at convenience. CSV at `/tmp/cpu_monitor.csv` preserved as future re-occurrence comparison baseline.
