# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-03 12:07 KST (nineteenth-session close — 2 PRs merged: #75 issue#18 + #76 issue#16.2; main = `a074395`. Docs PR #77 awaiting operator merge).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-03 12:07 KST)

1. **★ issue#11 — Live mode pipelined-parallel multi-thread** — Operator-locked priority #1 for next session. **Deeper algorithmic + RT-architecture session — full Planner pipeline expected.** Operator outlined three planning axes at this session-close (verbatim absorbed into `.claude/memory/project_pipelined_compute_pattern.md` "issue#11 planning axes" section):
   - **(a) Real-time-vs-accuracy trade-off minimization**: pipelined pattern should improve BOTH latency p99 AND steady-state pose error std-dev simultaneously, not trade one for the other. Sequential Live currently caps K refinement steps per tick; pipelined amortizes more steps across cores → tighter convergence per pose output without lengthening wallclock per tick.
   - **(b) Single-core deeper pipeline vs multi-core distributed pipeline (cascade-jitter risk)**: single-core (CPU 3 RT-isolated, deeper per-tick schedule) has no inter-core comm latency or cascade-jitter risk, but caps total throughput. Multi-core distributed (cores 0/1/2 host different pipeline stages, CPU 3 reserved for hot path) has higher aggregate compute but inter-core handoff adds ~µs-scale latency AND a stage stall ripples jitter through every downstream stage. Planner MUST propose stall-isolation strategy (per-stage deadline + skip-tick on overrun + bounded queue size) OR justify single-core fallback.
   - **(c) Non-Live computation paths audit**: also audit calibration (OneShot AMCL — Track D-5-P pipelined-parallel candidate), AMCL one-shot iteration loops (per-σ K-step refinement could distribute across cores within a single σ tier), and any other repetitive-pattern compute path discoverable via grep of "while" + "for k in range" patterns. Goal: a single architectural pattern usable across multiple compute sites, NOT a Live-mode-specific bolt-on.
   - **HIL baseline to beat**: Live ±5 cm stationary / ±10 cm motion / yaw ±1° (eighteenth-session HIL data); CPU 3 isolation invariant (`.claude/memory/project_cpu3_isolation.md`) must be respected.

2. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment. Particularly relevant after fifteenth-session's σ-tighten experiment confirmed standstill jitter floor is map-cell quantization, NOT σ.

3. **issue#4 — AMCL silent-converge diagnostic** — fifteenth/sixteenth/seventeenth/eighteenth/nineteenth HIL data accumulated as comprehensive baseline (Live ±5 cm stationary / ±10 cm motion / yaw ±1°). Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

4. **issue#6 — B-MAPEDIT-3 yaw rotation** — Frame redefinition (Problem 2 per `feedback_two_problem_taxonomy.md`). Spec: `.claude/memory/project_map_edit_origin_rotation.md` §B-MAPEDIT-3.

5. **issue#17 — GPIO UART direct connection** (perma-deferred) — long-term `cp210x` removal. Operator-locked: only ship if issue#10 + issue#10.1 + issue#16 + issue#16.2 + issue#18 mitigations are insufficient post deployment. Post nineteenth-session, the cp210x stack has full operator coverage (udev symlink + tunable serial + cp210x recovery service + UDS bootstrap audit + preview .tmp sweep) so issue#17 effectively shelved unless field evidence accumulates.

6. **Bug B — Live mode standstill jitter ~5cm widening** — operator measurement data needed (current σ setting, jitter window, motion vs stationary). Not yet code; analysis-first work item. May be subsumed by issue#11's Live pipelined work (the pipelined accuracy improvement should narrow the standstill jitter floor).

7. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern.

**Next free issue integer: `issue#19`**.

## Where we are (2026-05-03 12:07 KST — nineteenth-session close)

**main = `a074395`** — 2 PRs merged this session:

| PR | issue | What | Merge style |
|---|---|---|---|
| #75 | issue#18 | UDS bootstrap audit (MF1+MF2+MF3+SF2+SF3) — boot-time audit_runtime_dir log line + sweep_stale_siblings helper + rename-failure log_lstat_for_throw helper (header-exposed for testability per Mi3) + section H of production/RPi5/doc/uds_protocol.md (Bootstrap and operator forensics) + 6 new doctest cases. FULL pipeline. | squash |
| #76 | issue#16.2 | preview .pgm.tmp sweep on mapping.start() Phase 1 — best-effort glob+unlink under _coordinator_flock right after IDLE-state gate. ABBREVIATED pipeline. | squash |

**Open PRs**: PR #77 (nineteenth-session docs close — chronicler bundle + Parent territory follow-up commit, awaiting operator merge).

**Prior session (eighteenth) PRs already merged**: #72 (issue#16.1+#10), #73 (issue#10.1), #74 (eighteenth-session docs).

## Live system on news-pi01 (post nineteenth-session close)

- **godo-irq-pin.service**: enabled, auto-start (unchanged).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. Live `/opt/godo-webctl/` redeployed via rsync + uv sync + systemctl restart for issue#16.2. `mapping.start()` Phase 1 now sweeps `cfg.maps_dir / .preview / *.pgm.tmp` under `_coordinator_flock`.
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. Binary at `/opt/godo-tracker/godo_tracker_rt` rebuilt + redeployed for issue#18. New `main()` boot path: pidfile-lock → `audit_runtime_dir(cfg.uds_socket)` → `sweep_stale_siblings(cfg.uds_socket)` → banner → thread spawn. PR #73's lstat guard inside `UdsServer::open()` remains as second line of defence.
- **godo-mapping@active.service**: timing UNCHANGED (still 30/45/45/50 from issue#16.1).
- **godo-cp210x-recover.service**: existing (PR #69), unchanged this session.
- **`/opt/godo-frontend/dist/`**: UNCHANGED (no SPA changes this session).
- **polkit**: 14 rules unchanged.
- **Docker image**: `godo-mapping:dev` unchanged (issue#16.2 fix is in webctl host-side, NOT inside the Docker container's `preview_dumper.py`).
- **`/var/lib/godo/tracker.toml`**: contains operator overrides from prior sessions:
  - `[serial] lidar_port = "/dev/rplidar"` — schema default after PR #72.
  - `[serial] lidar_udev_serial = "2eca2bbb4d6eef1182aae9c2c169b110"` — issue#10.1 default.
  - `[webctl] mapping_*_s = (30, 45, 45, 50)` — issue#16.1 ladder.
- **`/etc/udev/rules.d/99-rplidar.rules`**: regenerated from template; `/dev/rplidar` symlinks reliably.
- **`/run/godo/`**: clean — `ctl.sock` (socket type, srw-rw----), `godo-tracker.pid`, `godo-webctl.pid`. No stale `.tmp` files. New boot-time audit log confirmed.
- **`/var/lib/godo/maps/.preview/`**: HIL-injected `test_studio_v99.pgm.tmp` confirmed swept at next mapping start; canonical `.pgm` files untouched.
- **journald**: persistent storage active. New MF3 audit log line + Mi4 directory case discriminator confirmed live.
- **Branch**: `main @ a074395`. Local working tree on `docs/2026-05-03-nineteenth-session-close` (PR #77 in flight).

## Quick memory bookmarks (★ open these first on cold-start)

This session added **3 NEW memory entries** + updated 2 existing:

1. ★ `.claude/memory/feedback_verify_before_plan.md` — When delegating to Planner from a memory-spec, ALWAYS inspect current code first and include "Context discovered (don't re-discover)" in the brief. Saved a wasted plan iteration on issue#18 MF1.
2. ★ `.claude/memory/feedback_helper_injection_for_testability.md` — Mi3 pattern. Hard-to-force-failure branches → extract per-branch helper to namespace-internal scope, test the helper directly with synthetic inputs. No mocks. No forcing-failure gymnastics.
3. ★ `.claude/memory/feedback_build_grep_allowlist_narrowing.md` — When a build-gate grep over-matches a legitimate use of the same syntactic pattern in a different domain, extend the allow-list with named per-file rationale comments. Single-point-of-strict + named exceptions.
4. ★ `.claude/memory/project_pipelined_compute_pattern.md` — Updated with "issue#11 planning axes" section absorbing operator's 3 axes (real-time-vs-accuracy / single-core-vs-multi-core cascade-jitter / non-Live audit).
5. `.claude/memory/project_uds_bootstrap_audit.md` — Description updated to "DONE in PR #75" (kept as historical context).

Carryover (still active):
- `project_mapping_precheck_and_cp210x_recovery.md` (issue#16 family — historical context)
- `project_hint_strong_command_semantics.md`
- `project_calibration_alternatives.md`
- `project_pipelined_compute_pattern.md` (★ drives issue#11 design — read first on cold-start)
- `project_amcl_multi_basin_observation.md` (drives issue#4)
- `project_gpio_uart_migration.md` (issue#17 perma-deferred spec)
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`, `feedback_ssot_following_discipline.md`, `feedback_deploy_branch_check.md`, `feedback_relaxed_validator_strict_installer.md`, `feedback_post_mode_b_inline_polish.md`, `feedback_verify_before_plan.md`, `feedback_helper_injection_for_testability.md`, `feedback_build_grep_allowlist_narrowing.md`
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`
- `project_cpu3_isolation.md` (★ relevant for issue#11 RT planning), `frontend_stack_decision.md`, `reference_history_md.md`
- `project_lidar_overlay_tracker_decoupling.md`, `project_rplidar_cw_vs_ros_ccw.md`
- `project_amcl_sigma_sweep_2026-04-29.md`
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`, `project_map_edit_origin_rotation.md`
- `project_repo_canonical.md`, `project_tracker_down_banner_action_hook.md`, `project_restart_pending_banner_stale.md`
- `project_config_tab_grouping.md` (issue#15 — DONE in PR #70; historical reference)
- `project_uds_bootstrap_audit.md` (issue#18 — DONE in PR #75; historical reference)

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §8 Deployment + PR workflow + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UNCHANGED this session.
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN. UNCHANGED this session.
4. **`.claude/memory/MEMORY.md`** — full index (3 new entries this session, total ~40+).
5. **PROGRESS.md** — current through 2026-05-03 nineteenth-session close (chronicler PR #77).
6. **doc/history.md** — Korean narrative through nineteenth.
7. **`production/RPi5/CODEBASE.md`** — change log entry 2026-05-03 (PR #75 issue#18). New invariant `(u) uds-bootstrap-stale-state-discipline`.
8. **`godo-webctl/CODEBASE.md`** — change log entry 2026-05-03 11:41 KST (PR #76 issue#16.2 preview .tmp sweep).
9. **`godo-frontend/CODEBASE.md`** — UNCHANGED this session.
10. **`SYSTEM_DESIGN.md`** §6.2.1 — NEW: UDS bootstrap path (issue#18, 2026-05-03). Documents pre-thread-spawn boot sequence, graceful-shutdown destructor unlink, log_lstat_for_throw forensic helper.
11. **`production/RPi5/doc/uds_protocol.md`** §H — NEW: Bootstrap and operator forensics (H.1 lifecycle, H.2 ss -lxp historical-bind-path quirk, H.3 journalctl + HIL recipes).
12. **`FRONT_DESIGN.md`** — UNCHANGED this session.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 19); decimal for sub-issues (e.g. `issue#16.1`, `issue#16.2`, `issue#10.1`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

## Throwaway scratch (`.claude/tmp/`)

**Keep for one more cycle, then prune**:
- `plan_issue_18_uds_bootstrap_audit.md` — Full plan + Mode-A fold (4 Mi absorbed inline) + Writer fold + Mode-B APPROVE 0 findings. Reference for the helper-injection-for-testability + verify-before-Plan + build-grep allow-list patterns now codified as feedback memories.
- `plan_issue_10.1_lidar_serial_config_row.md` — PR #73 reference for relaxed-validator-strict-installer pattern.
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` — PR #72 reference for 9-edit C++ tracker plumbing block.

**Delete when convenient** (older plans no longer referenced).

## Tasks alive for next session

- **issue#11 — Live pipelined-parallel multi-thread** (TL;DR #1 — primary scope, deeper algorithmic session, full Planner pipeline)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #2)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #3)
- **issue#6 — B-MAPEDIT-3 yaw rotation** (TL;DR #4)
- **issue#17 — GPIO UART migration** (TL;DR #5 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #6 — analysis-first; may be subsumed by issue#11)
- **issue#7 — boom-arm angle masking** (TL;DR #7 — optional, contingent)

## Twentieth-session warm-up note

Nineteenth-session was a focused late-morning marathon (09:30 KST → 12:07 KST, ~2.5 hours active). Two PRs merged through complementary pipelines:
- PR #75 (issue#18, ~800 LOC) — full Planner → Mode-A (4 Mi inline) → Writer → Mode-B (0 findings) pipeline. Full HIL Recipe 1 + Recipe 2 passed.
- PR #76 (issue#16.2, ~92 LOC) — abbreviated direct-writer + Parent self-verify pipeline. HIL: stale .tmp injection swept on next mapping start.

Three cross-cutting design lessons surfaced + locked into memory:
- verify-before-Plan
- helper-injection for testability
- build-grep allow-list narrowing

Twentieth-session opens directly into issue#11 algorithmic + RT-architecture work. **Cold-start sequence**:
1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. Open `.claude/memory/project_pipelined_compute_pattern.md` — full design spec including this session's "issue#11 planning axes" section (3 axes locked).
4. Open `.claude/memory/project_cpu3_isolation.md` — RT invariant constraint for any pipelined design.
5. Standard pipeline: full Planner → Mode-A → Writer → Mode-B (per `feedback_pipeline_short_circuit.md` — issue#11 is feature-scale + multi-module + design surface has open decisions).

**Operator's tracker.toml carries the current cumulative state** — no pre-deploy migration needed for issue#11 (all changes will be internal to tracker C++ RT layer).

**`/opt/godo-tracker/` and `/opt/godo-webctl/` are both up-to-date with main as of 12:07 KST** post HIL of PR #75 + PR #76.

## Session-end cleanup (nineteenth)

- NEXT_SESSION.md: rewritten as a whole per the cache-role rule. Stale TL;DR items (issue#18 + issue#16.2) absorbed into PROGRESS.md + doc/history.md + per-stack CODEBASE.md + SYSTEM_DESIGN.md §6.2.1 + 3 new feedback memories, then pruned. issue#11 promoted to TL;DR #1 with operator's 3 planning axes verbatim.
- PROGRESS.md nineteenth-session block added at top of session log (PR #77).
- doc/history.md 열아홉 번째 세션 한국어 block added (PR #77).
- SYSTEM_DESIGN.md §6.2.1 NEW subsection — UDS bootstrap path (PR #77).
- Per-stack CODEBASE.md files: writers added entries for both PRs during PR #75 + PR #76; chronicler did NOT re-touch.
- `.claude/memory/`: 3 new feedback entries (`feedback_verify_before_plan.md`, `feedback_helper_injection_for_testability.md`, `feedback_build_grep_allowlist_narrowing.md`); 2 existing updated (`project_pipelined_compute_pattern.md` + `project_uds_bootstrap_audit.md`); `MEMORY.md` index updated.
- Branches: `feat/issue-18-uds-bootstrap-audit` deleted on origin via squash-merge --delete-branch (PR #75); `fix/issue-16.2-preview-tmp-sweep` deleted on origin via squash-merge --delete-branch (PR #76). Local cleanup done. Current branch: `docs/2026-05-03-nineteenth-session-close` (PR #77 awaiting operator merge).
- Plan files location: `.claude/tmp/plan_issue_18_uds_bootstrap_audit.md` — gitignored, survives across sessions; valuable reference for the 3 newly-codified patterns.
