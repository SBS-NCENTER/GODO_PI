# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-01 20:30 KST (fifteenth-session full close — 3 PRs merged: #62 + #63 + #64; main = `d810e78`).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-01 20:30 KST)

1. **★ issue#14 — SPA Mapping pipeline + monitoring (P0, full pipeline)** — Plan authored this session. 1393-line plan body + Parent S1-S6 SSE-separation amendment in `.claude/tmp/plan_issue_14_mapping_pipeline_spa.md`. Mode-A deferred to sixteenth per operator's "Plan까지만 진행하자". Estimated ~2000 LOC across 4 stacks (webctl + godo-mapping + frontend + production/RPi5/systemd). 14 operator-locked decisions L1-L14: Map sub-tabs (Overview/Edit/Mapping), system-level Mapping mode, tracker auto-stop on entry, LiDAR USB shared via tracker's `serial.lidar_port`, regex `^[A-Za-z0-9._\-(),]+$` 1-64 chars, bind-mount `/var/lib/godo/maps/`, manual activate post-mapping, `godo-mapping@<name>.service` template, Python rclpy 1 Hz preview node, Docker socket via `usermod -aG docker ncenter`, polkit rule. Parent S1-S6: Mapping monitor SSE Docker-only (NOT combined with RPi5 stats), no fallback polling, SPA strip splits RPi5 (always live) + Docker (live ↔ "중단됨" frozen on close). **Sixteenth-session = Mode-A → Writer → Mode-B → PR → multi-stack deploy → HIL Scenarios A-F.** Full Planner output is the cold-start input.

2. **issue#10 — udev rule for stable LiDAR symlink** — Acute after fifteenth-session USB swap incident (16:15:45 → ttyUSB0 → ttyUSB1, broke tracker until operator updated `serial.lidar_port` in tracker.toml). `/etc/udev/rules.d/99-rplidar.rules` matching `idVendor=10c4 idProduct=ea60 serial=2eca2bbb4d6eef1182aae9c2c169b110` → `SYMLINK+="rplidar"`; tracker.toml then points at `/dev/rplidar`. Small standalone PR; eliminates a recurring class of operational bugs.

3. **issue#11 — Live pipelined-parallel multi-thread** — Operator HIL insight from PR #62: "OneShot처럼 정밀하게 + CPU pipeline like 계산". With carry-hint locked basin (issue#5 ship), deeper schedule per tick is feasible if K-step distributed across cores 0/1/2 (CPU 3 RT-isolated). Reference: `project_pipelined_compute_pattern.md` "Why sequential ships first" — pipelined-parallel was the always-deferred follow-up. Architectural impact comparable to issue#5 (PR #62).

4. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Memory: `project_calibration_alternatives.md` "Distance-weighted AMCL likelihood." Standalone single-knob algorithmic experiment; could ship before issue#11. Relevant after fifteenth-session's σ-tighten experiment confirmed standstill jitter floor is map-cell quantization, NOT σ — distance-weighted likelihood is a complementary axis to attack the same floor.

5. **issue#4 — AMCL silent-converge diagnostic** — Now has fifteenth's HIL data as comprehensive baseline (Live ±5 cm stationary / ±10 cm motion / yaw ±1°). Metric to detect "converged but wrong" cases. Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

6. **issue#6 — B-MAPEDIT-3 yaw rotation** — Frame redefinition (Problem 2 per `feedback_two_problem_taxonomy.md`). Operator-locked direction: revisit hint UI's two-point pattern as candidate UX. Spec: `.claude/memory/project_map_edit_origin_rotation.md` §B-MAPEDIT-3.

7. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern.

**Next free issue integer: `issue#15`** (issue#14 = mapping pipeline; partial issue#13 already used in PR #63).

## Where we are (2026-05-01 20:30 KST — fifteenth-session full close)

**main = `d810e78`** — 3 PRs merged this session:

| PR | issue | What | Merge style |
|---|---|---|---|
| #62 | issue#5 | feat(rpi5): Live mode pipelined-hint kernel | squash |
| #63 | issue#5 follow-up + #12 + #13-cand | issue#5 default-flip + issue#12 latency defaults + issue#13-cand mapping resolution + frontend timestamps + memory σ-tighten experiment | squash |
| #64 | docs | fifteenth-session close documentation cascade | squash |

**Open PRs**: none.

**Plan-only output**: `.claude/tmp/plan_issue_14_mapping_pipeline_spa.md` (1393 lines + Parent S1-S6 fold). Mode-A is sixteenth's first step.

## Live system on news-pi01 (post fifteenth-session close)

- **godo-irq-pin.service**: enabled, auto-start (unchanged).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. **Updated this session** — `/opt/godo-webctl/` rsync'd from PR #63 (webctl_toml.py new module + SSE pose/scan rate config-driven + `EXPECTED_ROW_COUNT` 46 → 48). Logs show `SSE pose stream rate = 30 Hz, scan stream rate = 30 Hz` at boot.
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. Binary at `/opt/godo-tracker/godo_tracker_rt` rebuilt by PR #62 + PR #63 (issue#5 Live carry-hint kernel + Config struct webctl_pose_stream_hz/webctl_scan_stream_hz fields). `/opt/godo-tracker/share/config_schema.hpp` install-time-mirrored at 48 rows.
- **`/opt/godo-frontend/dist/`**: rebuilt from PR #63 (formatDateTime helper + Map+Backup list timestamp format `YYYY-MM-DD HH:MM`).
- **polkit**: 14 rules (unchanged this session). issue#10 / issue#14 will add new rules.
- **`/var/lib/godo/tracker.toml`**: contains operator overrides:
  - `[amcl] live_carry_pose_as_hint = 1` (redundant — matches new default; harmless to leave or delete)
  - `[smoother] t_ramp_ms = 500` (**overrides new default 100 ms** — operator should edit to 100 OR delete to feel issue#12 latency improvement)
  - `[serial] lidar_port = "/dev/ttyUSB1"` (USB swap recovery; will be replaced by `/dev/rplidar` once issue#10 ships)
- **Active map**: `04.29_v3.pgm` with resolution 0.050 m/cell. Future SLAM runs pick up new default 0.025 (issue#13-cand partial via PR #63 commit `3225149`).
- **Branch**: `main @ d810e78`, working tree clean (after fifteenth-session-close docs PR + cold-start PR if pending).

## Quick memory bookmarks (★ open these first on cold-start)

Fifteenth session extended **one** existing memory entry; no new entries:

1. ★ `.claude/memory/project_hint_strong_command_semantics.md` — appended σ-tighten experiment finding (2026-05-01 PM KST). σ semantics now locked in BOTH directions (do NOT widen for AMCL search comfort, do NOT tighten beyond physical drift bounds). Future sessions probing σ to reduce standstill jitter should reflexively reject — the floor is map-cell quantization, not σ. PR #63 commit `6209b96`.

Carryover from fourteenth (now solidly on main):
- `project_hint_strong_command_semantics.md` baseline (still active; fifteenth extended it)
- `project_calibration_alternatives.md` (Live mode hint pipeline section is the spec issue#5 implemented; Far-range rough-hint section is still pending future work)
- `project_pipelined_compute_pattern.md` (drives issue#11 design)
- `project_amcl_multi_basin_observation.md` (drives issue#4)
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`
- `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`
- `project_repo_topology.md`, `project_overview.md`, `project_test_sessions.md`, `project_studio_geometry.md`, `project_lens_context.md`
- `project_cpu3_isolation.md`, `frontend_stack_decision.md`, `reference_history_md.md`
- `project_lidar_overlay_tracker_decoupling.md`, `project_rplidar_cw_vs_ros_ccw.md`
- `project_amcl_sigma_sweep_2026-04-29.md`
- `project_system_tab_service_control.md`, `project_godo_service_management_model.md`
- `project_videocore_gpu_for_matrix_ops.md`, `project_config_tab_edit_mode_ux.md`
- `project_silent_degenerate_metric_audit.md`, `project_map_viewport_zoom_rules.md`, `project_map_edit_origin_rotation.md`
- `project_repo_canonical.md`, `project_tracker_down_banner_action_hook.md`, `project_restart_pending_banner_stale.md`
- `feedback_toml_branch_compat.md`

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §8 Deployment + PR workflow + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold + module roles. Unchanged this session.
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN. Unchanged this session.
4. **`.claude/memory/MEMORY.md`** — full index (33 lines).
5. **PROGRESS.md** — current through 2026-05-01 fifteenth-session close.
6. **doc/history.md** — Korean narrative through fifteenth.
7. **`production/RPi5/CODEBASE.md`** invariants tail = `(r)` — webctl-owned schema rows: Config carries them verbatim; tracker logic never reads them. (issue#5 + issue#12 fold).
8. **`godo-webctl/CODEBASE.md`** invariants tail = `(ac)` — webctl-owned schema rows: webctl reads its own `webctl.*` keys from `/var/lib/godo/tracker.toml` via `webctl_toml.read_webctl_section`.
9. **`godo-frontend/CODEBASE.md`** invariants tail unchanged — only change-log entry (formatDateTime + Map/Backup timestamps include date).
10. **`godo-mapping/CODEBASE.md`** invariants tail unchanged — change-log entry only (resolution 0.05 → 0.025 m/cell default).
11. **`SYSTEM_DESIGN.md`** §6.4 (smoother default 100 ms note) + §11.5 NEW (Webctl-owned schema rows). Live mode pipelined-hint kernel section at line 405+.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme is in **CLAUDE.md §6**. Sequential integer for distinct units; decimal for sub-issues stacked on a parent; Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis. Next free integer: **issue#15**.

## Throwaway scratch (`.claude/tmp/`)

**Keep until issue#14 ships**:
- `plan_issue_14_mapping_pipeline_spa.md` — sixteenth-session P0 input. 1393 lines + Parent S1-S6 amendment fold.

**Keep for one more cycle, then prune**:
- `plan_issue_5_live_pipelined_hint.md` — PR #62 reference (most thorough plan in repo with full Mode-A + Mode-B + Parent decision folds).
- `plan_latency_defaults_and_issue_5_flip.md` — PR #63 reference (Mode-A REWORK → Route α adoption pattern; useful when issue#14 hits a similar webctl-namespaced-keys decision point).

**Delete when convenient**:
- Older plans (`plan_issue_3_pose_hint_ui.md`, `plan_track_b_*.md`, `plan_track_d_*.md`, `plan_phase4_2_*.md`, `plan_phase4_3.md`, `plan_p0_frontend.md`, `plan_pr_b_process_monitor.md`, `plan_pr_c_config_tab_edit_mode.md`, `plan_service_observability.md`, `plan_single_instance_locks.md`, `plan_mapping_pipeline_fix.md`, `plan_track_b_map_viewport_shared_zoom.md`, `plan_track_b_mapedit_2_origin_pick.md`, `plan_track_b_mapedit.md`, `plan_track_b_repeatability.md`, `plan_track_b_system.md`, `plan_track_d_3_cpp_amcl_cw_ccw.md`, `plan_track_d_5_sigma_annealing.md`, `plan_track_d_live_lidar.md`, `plan_track_d_scale_yflip.md`, `plan_track_e_map_management.md`).
- All `review_mode_a_*.md` predecessors of the current plan-fold pattern (now folded inline into plans).

## Tasks alive for next session

- **issue#14 — SPA Mapping pipeline + monitoring** (TL;DR #1 — P0 full pipeline, primary scope)
- **issue#10 — udev rule for stable LiDAR symlink** (TL;DR #2 — small standalone, can interleave)
- **issue#11 — Live pipelined-parallel multi-thread** (TL;DR #3)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #4)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #5)
- **issue#6 — B-MAPEDIT-3 yaw rotation** (TL;DR #6)
- **issue#7 — boom-arm angle masking** (TL;DR #7 — optional)

## Sixteenth-session warm-up note

The Plan #14 file is a complete handoff. Sixteenth-session can cold-start as:
1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. Open `.claude/tmp/plan_issue_14_mapping_pipeline_spa.md` (1393 lines — read end-to-end including §15 Mode-A fold AND Parent decision S1-S6 amendment).
4. Spawn Reviewer Mode-A on the plan. No re-Planner spawn needed.
5. Standard pipeline: Mode-A (verdict) → Writer (multi-stack) → Mode-B → PR → multi-stack deploy → HIL.

Operator's `tracker.toml` has redundant `t_ramp_ms = 500` override that should be edited to 100 (or deleted) to feel the issue#12 smoother latency improvement. Worth flagging in sixteenth's first operator interaction if not yet done.

## Session-end cleanup

- NEXT_SESSION.md: rewritten as a whole per the cache-role rule. 3-step absorb routine applied — issue#5 + issue#12 + issue#13-cand partial pruned (now on main and recorded in PROGRESS.md / doc/history.md / per-stack CODEBASE.md). issue#14 promoted to TL;DR #1 with full plan reference. issue#10/#11/#13(continued)/#4/#6/#7 carry over.
- PROGRESS.md fifteenth-session block added at the top of the session log (PR #64).
- doc/history.md fifteenth-session 한국어 block added (PR #64).
- Per-stack CODEBASE.md files: all four touched stacks (`production/RPi5/`, `godo-webctl/`, `godo-frontend/`, `godo-mapping/`) got change-log entries in PR #62 + PR #63 commits. New invariants: RPi5 `(q)` Live pipelined-hint kernel ownership + RPi5 `(r)` webctl-owned schema rows + webctl `(ac)` webctl_toml.py SSOT.
- `.claude/memory/`: 1 entry extended (`project_hint_strong_command_semantics.md` σ-tighten experiment finding, in PR #63 commit `6209b96`); MEMORY.md index unchanged (no new file).
- Branches cleaned: `feat/issue-5-live-pipelined-hint` deleted; `feat/latency-defaults-and-issue-5-flip` deleted; `docs/2026-05-01-fifteenth-session-close` deleted. Local: clean.
- Plan file location confirmed: `.claude/tmp/plan_issue_14_mapping_pipeline_spa.md` is gitignored (not tracked). Survives across sessions on the same host (news-pi01); next session reads from disk.
