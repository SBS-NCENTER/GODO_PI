# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-03 00:50 KST (seventeenth-session close — issue#16 PR #69 merged + issue#15 PR #70 in flight).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-03 00:50 KST)

1. **★ Tier A — issue#16.1 + issue#10 bundle (operator-deferred to eighteenth session)**
   - **issue#16.1** — t5 trap-timeout: `docker stop --time=20` grace can be shorter than the entrypoint trap's `map_saver_cli` cycle on long mapping sessions. Operator t5 incident 22:27:16 KST 2026-05-02 lost a 2h 5min mapping to SIGKILL because the trap took >20s. Fix path: separate `mapping_stop_systemctl_timeout_s` (≥45s, currently uses generic `SUBPROCESS_TIMEOUT_S=10s`) + bump schema-default ladder (docker_grace 20→30, systemd_timeout 30→45, webctl_stop_timeout 35→50). LOC ~30. Risk: data loss on long-running mapping. Tracked in v5/v7 commit messages + `godo-webctl/CODEBASE.md` v5/v7 entries' "Out of scope" sections.
   - **issue#10** — udev rule `/dev/rplidar` symlink. `/etc/udev/rules.d/99-rplidar.rules` matching `idVendor=10c4 idProduct=ea60 serial=2eca2bbb4d6eef1182aae9c2c169b110` → `SYMLINK+="rplidar"`; tracker.toml's `serial.lidar_port` flips from `/dev/ttyUSB0`/`ttyUSB1` to `/dev/rplidar`. Eliminates USB-renumbering ops bugs (operator already swapped twice during HIL). LOC ~20 + 1 udev file. Note: deprecated by issue#17 (GPIO direct) if/when shipped.

2. **issue#15 — Config tab domain grouping + edit-input bg swap** — PR #70 in flight (awaiting operator deploy + HIL). Frontend-only ~190 LOC. 8 groups (amcl / smoother / serial / network / rt / gpio / ipc / webctl), `<details open>` per group, input bg swap (enabled = elev = 흰, disabled = bg = 회색).

3. **issue#16.2 (NEW)** — preview `.tmp` cleanup. Seventeenth-session silent-error scan found `/var/lib/godo/maps/.preview/v11.pgm.tmp` left behind from a SIGTERM-during-fsync race in `preview_dumper.py:54-64`. No data loss (the actual `v11.pgm` saved correctly), pure housekeeping. Fix path: glob-delete `*.tmp` in webctl `mapping.start()` Phase 1 OR systemd ExecStartPre, OR add SIGTERM handler in preview_dumper. ~10 LOC.

4. **issue#11 — Live pipelined-parallel multi-thread** — Operator HIL insight from PR #62: "OneShot처럼 정밀하게 + CPU pipeline like 계산". With carry-hint locked basin (issue#5), deeper schedule per tick is feasible if K-step distributed across cores 0/1/2 (CPU 3 RT-isolated). Reference: `.claude/memory/project_pipelined_compute_pattern.md`.

5. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment. Particularly relevant after fifteenth-session's σ-tighten experiment confirmed standstill jitter floor is map-cell quantization, NOT σ.

6. **issue#4 — AMCL silent-converge diagnostic** — Now has fifteenth/sixteenth/seventeenth HIL data as comprehensive baseline (Live ±5 cm stationary / ±10 cm motion / yaw ±1°). Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

7. **issue#6 — B-MAPEDIT-3 yaw rotation** — Frame redefinition (Problem 2 per `feedback_two_problem_taxonomy.md`). Spec: `.claude/memory/project_map_edit_origin_rotation.md` §B-MAPEDIT-3.

8. **issue#17 — GPIO UART direct connection** (on-demand) — long-term `cp210x` removal. Operator-locked: only ship if issue#10 + issue#16 mitigations are insufficient post deployment. Spec: `doc/RPLIDAR/RPi5_GPIO_UART_migration.md` + `.claude/memory/project_gpio_uart_migration.md`.

9. **Bug B — Live mode standstill jitter ~5cm widening** — operator measurement data needed (current σ setting, jitter window, motion vs stationary). Not yet code; analysis-first work item.

10. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern.

**Next free issue integer: `issue#18`**.

## Where we are (2026-05-03 00:50 KST — seventeenth-session close)

**main = `c091ba4`** — 1 PR merged this session:

| PR | issue | What | Merge style |
|---|---|---|---|
| #69 | issue#16 | Mapping pre-check gate + cp210x driver recovery + ProcessTable refinement (v0..v7 hot-fix series) | squash |

**Open PRs**: PR #70 (issue#15 — Config tab domain grouping + edit-input bg swap, awaiting operator deploy/HIL).

**Prior session (sixteenth) PRs already merged**: #65 (NEXT_SESSION rewrite), #66 (backup + Config UX bundle), #67 (issue#14 mapping pipeline), #68 (sixteenth-close docs).

## Live system on news-pi01 (post seventeenth-session close)

- **godo-irq-pin.service**: enabled, auto-start (unchanged).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. `/opt/godo-webctl/` rsync'd from PR #69 v7. Started 2026-05-03 00:09:53 KST after RPi reboot, NRestarts=0.
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. PR #69 unchanged it.
- **godo-mapping@active.service**: NEW (from PR #67). PR #69 added v5..v7 hot-fixes (cp210x recovery via `godo-cp210x-recover.service`; `mapping_unit_clean` precheck row; status() reconcile transient docker states + ExecStartPre window handling). Currently inactive, not failed.
- **godo-cp210x-recover.service** (NEW from PR #69): oneshot helper for cp210x driver unbind/rebind. Polkit + helper script at `/opt/godo-tracker/share/godo-cp210x-recover.sh`.
- **`/opt/godo-frontend/dist/`**: rebuilt from PR #69 v7 (Mapping sub-tab + 7-row precheck panel + 확인 button + lastError clear + PRECHECK_DETAIL_KO tooltips).
- **polkit**: 14 rules + (c) `godo-mapping@active.service` start/stop/restart + (d) `godo-cp210x-recover.service` start by `ncenter` group.
- **Docker image**: `godo-mapping:dev` (slam_toolbox_async.yaml resolution 0.025 m/cell, rebuilt 2026-05-02).
- **`/var/lib/godo/tracker.toml`**: contains operator overrides:
  - `[serial] lidar_port = "/dev/ttyUSB0"` (will be obviated by issue#10 `/dev/rplidar` symlink).
  - 3 `webctl.mapping_*_s` rows at default values (20/30/35) — issue#16.1 will bump these.
- **Active map**: `04.29_v3.pgm` symlinked via `active.pgm` → `test_v4.pgm` (per current symlink). Operator made 16+ test maps this session (v7, v9~v16, t11, t2~t4 etc.) — all .pgm + .yaml pairs intact, P5 magic verified.
- **`/run/godo/mapping/`**: state.json idle.
- **journald**: now persistent (operator ran `mkdir /var/log/journal && systemctl restart systemd-journald` in seventeenth session). Future boots will retain logs across reboots — important for diagnosing future SIGKILL/false-Failed events.
- **Branch**: `main @ c091ba4`, local working tree clean.

## Quick memory bookmarks (★ open these first on cold-start)

This session added **0 new memory entries** (issue#16 v5..v7 hot-fix series captured in commit messages + per-stack CODEBASE.md change log; pattern locked there).

Carryover (still active):
- `project_mapping_precheck_and_cp210x_recovery.md` — issue#16 spec context (now mostly historical; v5..v7 hot-fix series details live in `godo-webctl/CODEBASE.md` change log entries 2026-05-02 19:30 / 19:50 / 20:15 / 22:50 / 23:30 / 2026-05-03 00:30).
- `project_hint_strong_command_semantics.md` (σ semantics locked both directions)
- `project_calibration_alternatives.md` (Live carry hint + Far-range rough hint sections)
- `project_pipelined_compute_pattern.md` (drives issue#11 design)
- `project_amcl_multi_basin_observation.md` (drives issue#4)
- `project_config_tab_grouping.md` (issue#15 spec — PR #70 references this)
- `project_gpio_uart_migration.md` (issue#17 long-term spec)
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`, `feedback_ssot_following_discipline.md`
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`
- `project_cpu3_isolation.md`, `frontend_stack_decision.md`, `reference_history_md.md`
- `project_lidar_overlay_tracker_decoupling.md`, `project_rplidar_cw_vs_ros_ccw.md`
- `project_amcl_sigma_sweep_2026-04-29.md`
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`, `project_map_edit_origin_rotation.md`
- `project_repo_canonical.md`, `project_tracker_down_banner_action_hook.md`, `project_restart_pending_banner_stale.md`

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §8 Deployment + PR workflow + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold + module roles. issue#16 added `godo-mapping/` row + `godo-cp210x-recover.service` cross-stack arrow.
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN.
4. **`.claude/memory/MEMORY.md`** — full index.
5. **PROGRESS.md** — current through 2026-05-02 sixteenth-session close (seventeenth not yet logged; see commit log + this file).
6. **doc/history.md** — Korean narrative through sixteenth.
7. **`godo-webctl/CODEBASE.md`** — invariants extended through v7 (mapping_unit_clean precheck row + status() reconcile transient handling + ExecStartPre window handling).
8. **`godo-frontend/CODEBASE.md`** — issue#15 PR #70 entry (config domain grouping + edit-input bg swap) + issue#16 v6/v7 entries.
9. **`production/RPi5/CODEBASE.md`** — invariants (a)..(r) + 2026-05-02 entry (3 webctl-owned mapping-timing schema rows + cross-trio invariant + cp210x recover script + service unit).
10. **`SYSTEM_DESIGN.md`** §12 — full mapping pipeline design.
11. **`FRONT_DESIGN.md`** §8.5 — Map > Mapping sub-tab UX.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 18); decimal for sub-issues stacked on a parent (e.g. `issue#16.1`, `issue#16.2`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

## Throwaway scratch (`.claude/tmp/`)

**Keep for one more cycle, then prune**:
- `plan_issue_14_mapping_pipeline_spa.md` — comprehensive plan + Mode-A fold + Mode-B fold. Reference for next multi-stack PR.
- `plan_issue_5_live_pipelined_hint.md` — PR #62 reference.
- `plan_latency_defaults_and_issue_5_flip.md` — PR #63 reference.

## Tasks alive for next session

- **issue#16.1 — t5 trap-timeout fix** (TL;DR #1a — primary scope, data-loss risk)
- **issue#10 — udev rule `/dev/rplidar`** (TL;DR #1b — operational ergonomics, bundle with #16.1)
- **issue#15 — Config tab domain grouping** (TL;DR #2 — PR #70 awaiting operator deploy/HIL)
- **issue#16.2 — preview `.tmp` cleanup** (TL;DR #3 — small housekeeping)
- **issue#11 — Live pipelined-parallel multi-thread** (TL;DR #4)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #5)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #6)
- **issue#6 — B-MAPEDIT-3 yaw rotation** (TL;DR #7)
- **issue#17 — GPIO UART migration** (TL;DR #8 — on-demand)
- **Bug B — Live mode standstill jitter** (TL;DR #9 — analysis-first)
- **issue#7 — boom-arm angle masking** (TL;DR #10 — optional, contingent)

## Eighteenth-session warm-up note

Seventeenth-session was a tight late-night 2026-05-02 21:30 KST → 2026-05-03 00:50 KST (~3 hours). Single PR merged (#69, issue#16 with v0..v7 hot-fix series) + 1 PR opened (#70, issue#15). Operator made 16+ test maps and verified the full mapping pipeline survives an RPi reboot cleanly. Three operator-driven housekeeping fixes also landed:
- journald → persistent storage (`/var/log/journal/` created)
- `/var/lib/godo/maps/.preview/v11.pgm.tmp` removed manually
- PR #69 squash-merged + branch deleted

Eighteenth-session can cold-start as:
1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. Open `godo-webctl/CODEBASE.md` v5..v7 entries for issue#16 hot-fix history (relevant if Tier A bundle needs to touch the same area).
4. Standard pipeline (per `feedback_pipeline_short_circuit.md`): if issue#16.1 + issue#10 bundle ≤200 LOC → direct writer + Mode-B fast path; otherwise full Planner → Mode-A → Writer → Mode-B.

**Operator's tracker.toml has `lidar_port = "/dev/ttyUSB0"` (post HIL USB swap)**. issue#10 will replace with `/dev/rplidar` symlink.

**Three timing schema rows at default 20/30/35** in tracker.toml — issue#16.1 bumps defaults to 30/45/50 (operator can override per-deploy via Config tab "Docker 맵 제작" group).

## Session-end cleanup (seventeenth)

- NEXT_SESSION.md: rewritten as a whole per the cache-role rule. issue#16 absorbed into PR #69 commit log + per-stack CODEBASE.md; pruned from TL;DR. New sub-issues #16.1 + #16.2 promoted from session-discovery. issue#15 retained as PR #70 in-flight.
- PROGRESS.md / doc/history.md: NOT yet updated for seventeenth (eighteenth-session can append; commit log + this file are the current SSOT).
- Per-stack CODEBASE.md files: `godo-webctl/CODEBASE.md` got v5/v6/v7 entries during the session (already in PR #69); `godo-frontend/CODEBASE.md` got an issue#15 entry (in PR #70).
- `.claude/memory/`: no new entries (v5..v7 hot-fix details captured in commit messages + per-stack CODEBASE.md, sufficient signal-density without a dedicated memory file).
- Branches: `feat/issue-16-mapping-precheck-cp210x-recovery` deleted on origin via squash-merge --delete-branch; local cleanup done. `feat/issue-15-config-domain-grouping` open on origin (PR #70).
- journald persistent storage activated by operator (out-of-band housekeeping, not in any PR).
- v11.pgm.tmp cleaned manually by operator (issue#16.2 will automate this for future runs).
