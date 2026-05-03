# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-03 09:30 KST (eighteenth-session close — 2 PRs merged: #72 + #73; main = `4b1c0af`. Docs PR #74 awaiting operator merge).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-03 09:30 KST)

1. **★ issue#18 — UDS bootstrap audit (broader scope)** — PR #73 shipped a `lstat → unlink-if-non-socket` quick guard before `rename()` in `uds_server.cpp`. The broader audit fixes the stale-state ROOT CAUSE (still unconfirmed), adds rename-failure path-aware logging (current path only `throw`s), atexit/destructor `unlink(ctl.sock)` semantics, mapping@active socket parity check, and documents the `ss -lxp` historical-bind-path display quirk. **~50-100 LOC**. Operator-locked priority #1. Operator quote: "stale ctl.sock 경합을 보니 UDS를 전반적으로 점검하는 것이 좋겠어". Spec: `.claude/memory/project_uds_bootstrap_audit.md` (full scope + open questions + must/should/could-fix decomposition).

2. **issue#16.2 — preview `.tmp` cleanup** — `/var/lib/godo/maps/.preview/v11.pgm.tmp` left behind from SIGTERM-during-fsync race in `preview_dumper.py:54-64`. No data loss; pure housekeeping. Fix path: glob-delete `*.tmp` in webctl `mapping.start()` Phase 1 OR systemd ExecStartPre, OR add SIGTERM handler in preview_dumper. ~10 LOC. Trivial — direct writer pipeline candidate per `feedback_pipeline_short_circuit.md`.

3. **issue#11 — Live pipelined-parallel multi-thread** — Operator HIL insight from PR #62: "OneShot처럼 정밀하게 + CPU pipeline like 계산". With carry-hint locked basin (issue#5), deeper schedule per tick is feasible if K-step distributed across cores 0/1/2 (CPU 3 RT-isolated). Reference: `.claude/memory/project_pipelined_compute_pattern.md`.

4. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment. Particularly relevant after fifteenth-session's σ-tighten experiment confirmed standstill jitter floor is map-cell quantization, NOT σ.

5. **issue#4 — AMCL silent-converge diagnostic** — fifteenth/sixteenth/seventeenth/eighteenth HIL data accumulated as comprehensive baseline (Live ±5 cm stationary / ±10 cm motion / yaw ±1°). Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

6. **issue#6 — B-MAPEDIT-3 yaw rotation** — Frame redefinition (Problem 2 per `feedback_two_problem_taxonomy.md`). Spec: `.claude/memory/project_map_edit_origin_rotation.md` §B-MAPEDIT-3.

7. **issue#17 — GPIO UART direct connection** (perma-deferred) — long-term `cp210x` removal. Operator-locked: only ship if issue#10 + issue#10.1 + issue#16 mitigations are insufficient post deployment. Post eighteenth-session, cp210x stack has full operator coverage (udev symlink + tunable serial + cp210x recovery service + UDS guard) so issue#17 effectively shelved unless field evidence accumulates. Spec: `doc/RPLIDAR/RPi5_GPIO_UART_migration.md` + `.claude/memory/project_gpio_uart_migration.md`.

8. **Bug B — Live mode standstill jitter ~5cm widening** — operator measurement data needed (current σ setting, jitter window, motion vs stationary). Not yet code; analysis-first work item.

9. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern.

**Next free issue integer: `issue#19`**.

## Where we are (2026-05-03 09:30 KST — eighteenth-session close)

**main = `4b1c0af`** — 2 PRs merged this session:

| PR | issue | What | Merge style |
|---|---|---|---|
| #72 | issue#16.1 + issue#10 | mapping stop ladder bump (30/45/45/50 + new systemctl_subprocess row + 3-site validator + install.sh pre-deploy gate) + udev /dev/rplidar symlink + 도움말 sub-tab follow-up | squash |
| #73 | issue#10.1 | LiDAR udev serial schema row + udev rule template (`__LIDAR_SERIAL__`) + install.sh templating + 도움말 second card + UDS stale-socket guard + Config "~37" → `{schema.length}` | squash |

**Open PRs**: PR #74 (eighteenth-session docs close — chronicler bundle, awaiting operator merge).

**Prior session (seventeenth) PRs already merged**: #69 (issue#16 v0..v7 series), #70 (issue#15 Config tab grouping), #71 (seventeenth-session docs).

## Live system on news-pi01 (post eighteenth-session close)

- **godo-irq-pin.service**: enabled, auto-start (unchanged).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. Live `/opt/godo-webctl/` carries issue#10.1 source EXCEPT `EXPECTED_ROW_COUNT` was patched 53→52 mid-session via emergency hotfix `sed`. After this session's docs PR #74 merge + clean redeploy from main, the in-place patch resolves naturally to 53 (matching the 53-row tracker schema).
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. Binary at `/opt/godo-tracker/godo_tracker_rt` rebuilt + redeployed by PR #73's install.sh run. **53-row schema** (issue#10.1's `serial.lidar_udev_serial` row added). UDS stale-socket guard active — verified via HIL stale-injection test (insert 0-byte regular file at `/run/godo/ctl.sock` → tracker start → guard logs `stale non-socket at '...' (mode=0100644, size=0); unlinking before atomic rename` → ctl.sock becomes socket type → tracker reachable).
- **godo-mapping@active.service**: NEW timing (issue#16.1) — `--time=30` / `TimeoutStopSec=45s`. Cross-quartet validator at 3 sites enforces `docker_grace < systemd_timeout < webctl_timeout` AND `systemctl_subprocess < webctl_timeout`.
- **godo-cp210x-recover.service**: existing (PR #69), unchanged this session.
- **`/opt/godo-frontend/dist/`**: rebuilt twice this session — first for 도움말 sub-tab (PR #72 follow-up commit), then for the second card + dynamic schema-length (PR #73). 4-sub-tab System layout (Overview / Processes / Extended / 도움말).
- **polkit**: 14 rules unchanged this session.
- **Docker image**: `godo-mapping:dev` unchanged (issue#16.1 timing fix is in webctl + systemd, not Docker image).
- **`/var/lib/godo/tracker.toml`**: contains operator overrides:
  - `[serial] lidar_port = "/dev/rplidar"` — schema default after PR #72 (was `/dev/ttyUSB0`).
  - `[serial] lidar_udev_serial = "2eca2bbb4d6eef1182aae9c2c169b110"` — issue#10.1 default value (verified live via `udevadm info`).
  - `[webctl] mapping_*_s` rows now (30, 45, 45, 50) — auto-rewritten by install.sh pre-deploy gate from legacy (20, 30, 35).
  - Backup file from auto-rewrite: `/var/lib/godo/tracker.toml.bak.1777755567` (~2026-05-03 05:59:27 KST).
- **`/etc/udev/rules.d/99-rplidar.rules`**: regenerated from `99-rplidar.rules.template` with substituted serial. `/dev/rplidar` symlinks to `/dev/ttyUSB0` reliably.
- **`/run/godo/`**: clean — `ctl.sock` (socket type, srw-rw----), `godo-tracker.pid`, `godo-webctl.pid`. No stale `.tmp` files.
- **journald**: persistent storage active (since seventeenth-session housekeeping). Future boots retain logs.
- **Branch**: `main @ 4b1c0af`. Local working tree on `docs/2026-05-03-eighteenth-session-close` (PR #74 in flight).

## Quick memory bookmarks (★ open these first on cold-start)

This session added **4 NEW memory entries**:

1. ★ `.claude/memory/feedback_deploy_branch_check.md` — Production rsync depends on git tree state. Caught mid-session when issue#10.1 working tree's 53-pin webctl deployed against 52-row tracker. SOP rule + `git stash → switch → deploy → switch back → stash pop` pattern.
2. ★ `.claude/memory/feedback_relaxed_validator_strict_installer.md` — Single-point-of-strict design pattern. Schema validator generic (type only); format-specific strict check at SOLE consumer (install.sh). Locked via issue#10.1.
3. ★ `.claude/memory/feedback_post_mode_b_inline_polish.md` — When OK to absorb post-Mode-B changes (4 criteria: contract unchanged, bounded LOC, tests pass, Mode-B verdict unchanged). Verified PR #72 + PR #73 both this session.
4. ★ `.claude/memory/project_uds_bootstrap_audit.md` — issue#18 spec context. Symptom analysis + open questions + must/should/could-fix decomposition.

Carryover (still active):
- `project_mapping_precheck_and_cp210x_recovery.md` (issue#16 family — historical context for issue#10.1 rationale)
- `project_hint_strong_command_semantics.md` (σ semantics locked both directions)
- `project_calibration_alternatives.md` (Live carry hint + Far-range rough hint sections)
- `project_pipelined_compute_pattern.md` (drives issue#11 design)
- `project_amcl_multi_basin_observation.md` (drives issue#4)
- `project_gpio_uart_migration.md` (issue#17 perma-deferred spec)
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`, `feedback_ssot_following_discipline.md`
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`
- `project_cpu3_isolation.md`, `frontend_stack_decision.md`, `reference_history_md.md`
- `project_lidar_overlay_tracker_decoupling.md`, `project_rplidar_cw_vs_ros_ccw.md`
- `project_amcl_sigma_sweep_2026-04-29.md`
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`, `project_map_edit_origin_rotation.md`
- `project_repo_canonical.md`, `project_tracker_down_banner_action_hook.md`, `project_restart_pending_banner_stale.md`
- `project_config_tab_grouping.md` (issue#15 — DONE in PR #70; keep as historical reference)

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §8 Deployment + PR workflow + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UNCHANGED this session (no family-shape shift).
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN. UNCHANGED this session.
4. **`.claude/memory/MEMORY.md`** — full index (4 new entries this session, total ~37+).
5. **PROGRESS.md** — current through 2026-05-03 eighteenth-session close (chronicler PR #74).
6. **doc/history.md** — Korean narrative through eighteenth.
7. **`production/RPi5/CODEBASE.md`** — change log entries 2026-05-03 (PR #72 issue#16.1 + issue#10 bundle, PR #73 issue#10.1 — both at line ~753 + ~4576). Invariant `(t)` added: lidar-udev-serial-via-install.sh-template.
8. **`godo-webctl/CODEBASE.md`** — change log entries 2026-05-03 (PR #72 line 1028, PR #73 line 3440). `mapping-timing-ladder` invariant text updated to 30/45/50 + 4-row + 3-site validator.
9. **`godo-frontend/CODEBASE.md`** — change log entries 2026-05-03 (도움말 sub-tab line 606, 시리얼 카드 line 3061).
10. **`SYSTEM_DESIGN.md`** §12 — full mapping pipeline design (D1 mode coordinator, D3 tracker-stop race, etc.). UNCHANGED this session.
11. **`FRONT_DESIGN.md`** §8.6 — NEW: System tab 도움말 sub-tab pattern (4-sub-tab routing, card composition convention, Option A/B/C decision rationale, currently registered cards).
12. **`doc/RPLIDAR/RPi5_GPIO_UART_migration.md`** — issue#17 spec (305 lines). Effectively perma-deferred post eighteenth.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 19); decimal for sub-issues stacked on a parent (e.g. `issue#16.1`, `issue#16.2`, `issue#10.1`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis. issue#18 reserved at this session-close for UDS audit.

## Throwaway scratch (`.claude/tmp/`)

**Keep for one more cycle, then prune**:
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` — comprehensive PR #72 plan + Mode-A round 1 (REWORK) + Mode-A round 2 (APPROVE) + Mode-B (APPROVE) folds. Reference for next stack-touching PR (especially the 9-edit C++ tracker plumbing block — the deferred lesson from Mode-A round 1).
- `plan_issue_10.1_lidar_serial_config_row.md` — PR #73 plan + Mode-A (single round APPROVE) + Mode-B (APPROVE) folds. Reference for the relaxed-validator-strict-installer pattern.
- `plan_issue_14_mapping_pipeline_spa.md` — PR #67 reference (still useful for multi-stack PR scaffolding).

**Delete when convenient** (older plans no longer referenced).

## Tasks alive for next session

- **issue#18 — UDS bootstrap audit** (TL;DR #1 — primary scope, operator-locked)
- **issue#16.2 — preview `.tmp` cleanup** (TL;DR #2 — small)
- **issue#11 — Live pipelined-parallel multi-thread** (TL;DR #3)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #4)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #5)
- **issue#6 — B-MAPEDIT-3 yaw rotation** (TL;DR #6)
- **issue#17 — GPIO UART migration** (TL;DR #7 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #8 — analysis-first)
- **issue#7 — boom-arm angle masking** (TL;DR #9 — optional, contingent)

## Nineteenth-session warm-up note

Eighteenth-session was a focused early-morning marathon (04:30 KST → 09:30+ KST cross-day from seventeenth, ~5 hours active). Two PRs merged through full pipeline: #72 (issue#16.1 + issue#10 absorbed seventeenth's deferred Tier-A bundle, ~245 LOC, full pipeline with planner round 2) and #73 (issue#10.1 schema row + UDS guard + polish, ~340 LOC, single planner round). Three structural revelations + one process correction documented; four cross-cutting rules locked.

Notable mid-session live-system events (both recovered cleanly with hotfixes):
- **Config tab empty after operator's first redeploy** — caused by Parent's mid-PR working tree containing 53-pin webctl while live tracker was still 52-row. Hotfix: in-place sed at `/opt/godo-webctl/.../config_schema.py`. SOP lesson locked in `feedback_deploy_branch_check.md`.
- **Tracker unreachable after restart** — caused by stale 0-byte `ctl.sock` blocking webctl connect. Hotfix: stop tracker + `rm` stale UDS files + start. Same race motivated PR #73's lstat guard. Broader audit = issue#18.

Nineteenth-session can cold-start as:
1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. Open `.claude/memory/project_uds_bootstrap_audit.md` for issue#18 spec context.
4. Standard pipeline (per `feedback_pipeline_short_circuit.md`): if issue#18 ≤200 LOC and well-specified → direct writer + Mode-B fast path; otherwise full Planner → Mode-A → Writer → Mode-B.

**Operator's tracker.toml carries the post-PR-72 + post-PR-73 ladder + lidar serial state**. No pre-deploy migration needed for issue#18 (UDS audit is internal to tracker C++).

**`/opt/godo-webctl/` has the in-place 52-pin sed hotfix** that will need a clean redeploy from main after PR #74 docs merge to align to 53 (issue#10.1's actual count). Operator can do this any time — the live system is functional as-is.

## Session-end cleanup (eighteenth)

- NEXT_SESSION.md: rewritten as a whole per the cache-role rule. Stale TL;DR items (issue#16.1 + issue#10 + issue#15) absorbed into PROGRESS.md / doc/history.md / per-stack CODEBASE.md and pruned. issue#18 promoted to TL;DR #1.
- PROGRESS.md eighteenth-session block added at the top of the session log (PR #74).
- doc/history.md eighteenth-session 한국어 block updated from mid-session partial to full close (PR #74).
- FRONT_DESIGN.md §8.6 added — System tab 도움말 sub-tab pattern (PR #74).
- Per-stack CODEBASE.md files: writers added entries for both PRs during PR #72 + PR #73; chronicler did NOT re-touch.
- `.claude/memory/`: 4 new entries (`feedback_deploy_branch_check.md`, `feedback_relaxed_validator_strict_installer.md`, `feedback_post_mode_b_inline_polish.md`, `project_uds_bootstrap_audit.md`); `MEMORY.md` index updated.
- Branches: `feat/issue-16.1-trap-timeout-and-issue-10-udev` deleted on origin via squash-merge --delete-branch (PR #72); `feat/issue-10.1-lidar-serial-config-row` deleted on origin via squash-merge --delete-branch (PR #73). Local cleanup done. Current branch: `docs/2026-05-03-eighteenth-session-close` (PR #74 awaiting operator merge).
- Plan files location: `.claude/tmp/plan_issue_16.1_trap_timeout_and_issue_10_udev.md` + `.claude/tmp/plan_issue_10.1_lidar_serial_config_row.md` — both gitignored, survive across sessions.
- Live-system in-place patch: `/opt/godo-webctl/.../config_schema.py:111 EXPECTED_ROW_COUNT=52` (sed hotfix from session-mid). Will resolve naturally on next clean redeploy from main.
