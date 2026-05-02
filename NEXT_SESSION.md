# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-02 16:30 KST (sixteenth-session full close — 3 PRs merged: #65 + #66 + #67; main = `f433889`).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-02 16:30 KST)

1. **★ issue#16 — Mapping pre-check gate + cp210x auto-recovery + dockerd/containerd classification** — Operator HIL on PR #67 surfaced a hardware-software race: `dmesg cp210x ttyUSB1: failed set request 0x12 status: -110` + rplidar SDK `code 80008004 (RESULT_OPERATION_TIMEOUT)` when mapping starts immediately after tracker stop. ~10s wait empirically required. Three patches: (1) `/api/mapping/precheck` endpoint + SPA Start gate (LiDAR readable / tracker stopped / image present / disk space / name-clash / state.json clean checks); (2) cp210x driver unbind/rebind via sysfs (polkit rule); (3) ProcessTable refinement: dockerd/containerd → "general" (always-running daemons), keep `docker run`/`containerd-shim*` → "godo" (mapping-active processes). Spec: `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`. Estimated ~200 LOC; planner-short-circuit eligible per `feedback_pipeline_short_circuit.md`.

2. **issue#15 — Config tab domain grouping** — operator UX request 2026-05-01: replace alphabetical schema-row listing with collapsible groups by dotted-name prefix (AMCL, smoother, hint, live, oneshot, webctl, serial, network). Frontend-only ~80 LOC. Spec: `.claude/memory/project_config_tab_grouping.md`.

3. **issue#10 — udev rule for stable LiDAR symlink** — `/etc/udev/rules.d/99-rplidar.rules` matching `idVendor=10c4 idProduct=ea60 serial=…` → `SYMLINK+="rplidar"`; tracker.toml then points at `/dev/rplidar`. Eliminates the recurring class of operational bugs from USB renumbering. **Note**: deprecated by issue#17 (GPIO direct connection) if/when that ships.

4. **issue#11 — Live pipelined-parallel multi-thread** — Operator HIL insight from PR #62: "OneShot처럼 정밀하게 + CPU pipeline like 계산". With carry-hint locked basin (issue#5), deeper schedule per tick is feasible if K-step distributed across cores 0/1/2 (CPU 3 RT-isolated). Reference: `.claude/memory/project_pipelined_compute_pattern.md`.

5. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment. Particularly relevant after fifteenth-session's σ-tighten experiment confirmed standstill jitter floor is map-cell quantization, NOT σ — distance-weighted likelihood is a complementary axis.

6. **issue#4 — AMCL silent-converge diagnostic** — Now has fifteenth's HIL data as comprehensive baseline (Live ±5 cm stationary / ±10 cm motion / yaw ±1°). Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

7. **issue#6 — B-MAPEDIT-3 yaw rotation** — Frame redefinition (Problem 2 per `feedback_two_problem_taxonomy.md`). Spec: `.claude/memory/project_map_edit_origin_rotation.md` §B-MAPEDIT-3.

8. **issue#17 — GPIO UART direct connection** (on-demand) — long-term `cp210x` removal. Operator-locked: only ship if issue#16 mitigation is insufficient post deployment. Spec: `doc/RPLIDAR/RPi5_GPIO_UART_migration.md` + `.claude/memory/project_gpio_uart_migration.md`.

9. **Bug B — Live mode standstill jitter ~5cm widening** — operator measurement data needed (current σ setting, jitter window, motion vs stationary). Not yet code; analysis-first work item.

10. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic confirming pan-correlated cluster pattern.

**Next free issue integer: `issue#18`**.

## Where we are (2026-05-02 16:30 KST — sixteenth-session full close)

**main = `f433889`** — 3 PRs merged this session:

| PR | issue | What | Merge style |
|---|---|---|---|
| #65 | docs | NEXT_SESSION cold-start cache rewrite for sixteenth | squash |
| #66 | hotfix | backup uses active.pgm + Config input preserves empty + UX bundle (backup-flash, no-op suppression, amber dot, Edit column) | squash |
| #67 | issue#14 | SPA mapping pipeline + monitor SSE + Map > Mapping sub-tab + System tab integration + Maj-1/Maj-2 + Mode-B C1+M1+M2 + post-HIL UX polish | squash |

**Open PRs**: PR #68 (docs sixteenth-session close — chronicler bundle, awaiting operator merge).

## Live system on news-pi01 (post sixteenth-session close)

- **godo-irq-pin.service**: enabled, auto-start (unchanged).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080. **Updated this session** — `/opt/godo-webctl/` rsync'd from PR #67 (mapping coordinator + 3 new schema rows + Settings augmenter + ALLOWED_SERVICES extension + map_backup endpoint fix from PR #66).
- **godo-tracker.service**: installed, NOT enabled per operator service-management policy. Binary at `/opt/godo-tracker/godo_tracker_rt` rebuilt by PR #67 (3 new `webctl.mapping_*_s` Config struct fields + `validate_webctl_mapping_ladder` cross-trio check). `/opt/godo-tracker/share/config_schema.hpp` install-time-mirrored at 51 rows (was 48).
- **godo-mapping@active.service**: NEW — installed, NOT enabled. `--time=20` + `TimeoutStopSec=30s` (Maj-1 ladder bumped from 10s/20s/25s to 20s/30s/35s post Mode-B M5).
- **`/opt/godo-frontend/dist/`**: rebuilt from PR #67 (Mapping sub-tab + state badge + map zoom auto-fit + UX polish).
- **polkit**: 14 rules + new `(c)` for `godo-mapping@active.service` start/stop/restart by `ncenter` group.
- **Docker image**: `godo-mapping:dev` rebuilt 2026-05-02 (3 days ago build of slam_toolbox_async.yaml had stale `resolution: 0.05` — operator rebuilt during HIL, now 0.025 m/cell applied so PGMs are 4× larger).
- **`/var/lib/godo/tracker.toml`**: contains operator overrides:
  - `[serial] lidar_port = "/dev/ttyUSB0"` (after USB swap during HIL — was ttyUSB1 pre-HIL; will be obviated by issue#10 `/dev/rplidar` symlink)
  - 3 new `webctl.mapping_*_s` rows present at default values (20/30/35) — operator can tune via Config tab "Docker 맵 제작" group
- **Active map**: `04.29_v3.pgm` (0.05 m/cell, pre-issue#13-cand). New maps from this session (test_v4 etc., 0.025 m/cell, ~4× pixel count) sitting under `/var/lib/godo/maps/` ready to activate when operator chooses.
- **`/run/godo/mapping/`**: state.json idle, active.env stale from last test run (left behind — harmless).
- **Branch**: `main @ f433889`, local working tree clean (after sixteenth-session-close docs PR pending).

## Quick memory bookmarks (★ open these first on cold-start)

This session added **3 NEW memory entries** + extended none:

1. ★ `.claude/memory/feedback_ssot_following_discipline.md` — when multiple naming schemes exist for the same concept, follow the upstream SSOT verbatim (don't paraphrase / alias / invent parallel names). Reinforced via Mode-A C1 fix on issue#14 plan.
2. ★ `.claude/memory/project_gpio_uart_migration.md` — issue#17 long-term spec context. Trigger conditions, staged path, operator scenario fit.
3. ★ `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md` — issue#16 short-term spec context. Pre-check checks, cp210x recovery design, ProcessTable refinement.

Carryover (still active):
- `project_hint_strong_command_semantics.md` (σ semantics locked both directions)
- `project_calibration_alternatives.md` (Live carry hint + Far-range rough hint sections)
- `project_pipelined_compute_pattern.md` (drives issue#11 design)
- `project_amcl_multi_basin_observation.md` (drives issue#4)
- `project_config_tab_grouping.md` (issue#15 candidate spec)
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`
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
2. **`CODEBASE.md`** (root) — cross-stack scaffold + module roles. Includes `godo-mapping/` row + cross-stack arrow added in PR #67 round 1.
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN.
4. **`.claude/memory/MEMORY.md`** — full index (33+ lines).
5. **PROGRESS.md** — current through 2026-05-02 sixteenth-session close.
6. **doc/history.md** — Korean narrative through sixteenth.
7. **`production/RPi5/CODEBASE.md`** — invariants (a)..(r) + 2026-05-02 entry adds 3 webctl-owned mapping-timing schema rows + cross-trio invariant.
8. **`godo-webctl/CODEBASE.md`** — invariants extended (ad)/(ae)/(af) round 1; 2026-05-02 entry adds Settings augmenter + M2 hard-block + N1 docker-family classify + map dimensions reader.
9. **`godo-frontend/CODEBASE.md`** — invariants extended (ac)/(ad) round 1, plus new (ad)(ae) for godo-mapping system-tab readonly + godo-family color grouping.
10. **`godo-mapping/CODEBASE.md`** — preview node + LIDAR_DEV chain (round 1; round 2 didn't touch).
11. **`SYSTEM_DESIGN.md`** §12 — full mapping pipeline design (D1 mode coordinator, D3 tracker-stop race, D8 preview node, M4 singleton-ticker, L11 failure recovery, M5 stop-timeout ordering, L14 lock-out).
12. **`FRONT_DESIGN.md`** §8.5 — Map > Mapping sub-tab UX (3-sub-tab routing, L14 mode-aware gating, banner, S1 Docker-only monitor strip, S2 freeze-on-close, D5 PNG re-encode).
13. **`doc/RPLIDAR/RPi5_GPIO_UART_migration.md`** — issue#17 spec (305 lines): UART pinout, Pi 5 5V rail capacity, decoupling cap, config.txt + tracker.toml + container changes, ~1hr work estimate.

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme is in **CLAUDE.md §6**. Sequential integer for distinct units; decimal for sub-issues stacked on a parent; Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis. Next free integer: **issue#18**.

## Throwaway scratch (`.claude/tmp/`)

**Keep for one more cycle, then prune**:
- `plan_issue_14_mapping_pipeline_spa.md` — comprehensive plan + Mode-A fold + S1-S6 amendment + Mode-B fold (round 1 + round 2). Most thorough plan in repo. Reference for next multi-stack PR (especially issue#16 which mirrors the Settings augmenter pattern).
- `plan_issue_5_live_pipelined_hint.md` — PR #62 reference (full Mode-A + Mode-B + Parent decision folds).
- `plan_latency_defaults_and_issue_5_flip.md` — PR #63 reference (REWORK → Route α adoption pattern).

**Delete when convenient** (older plans no longer referenced).

## Tasks alive for next session

- **issue#16 — Mapping pre-check + cp210x auto-recovery + dockerd/containerd classification** (TL;DR #1 — primary scope)
- **issue#15 — Config tab domain grouping** (TL;DR #2 — small standalone)
- **issue#10 — udev rule for stable LiDAR symlink** (TL;DR #3)
- **issue#11 — Live pipelined-parallel multi-thread** (TL;DR #4)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #5)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #6)
- **issue#6 — B-MAPEDIT-3 yaw rotation** (TL;DR #7)
- **issue#17 — GPIO UART migration** (TL;DR #8 — on-demand)
- **Bug B — Live mode standstill jitter** (TL;DR #9 — analysis-first)
- **issue#7 — boom-arm angle masking** (TL;DR #10 — optional, contingent)

## Seventeenth-session warm-up note

Sixteenth-session was a marathon afternoon (~21:30 KST 2026-05-01 → 16:00 KST 2026-05-02 cross-day, ~18.5 hours of active conversation). Three PRs landed including issue#14 mapping pipeline (largest single feature in the project, ~2000 LOC × 4 stacks). Mode-A → Writer → Mode-B → operator HIL → multiple post-HIL hot-fixes pattern was repeated for both round 1 and round 2 of issue#14. Operator quote: "정말 고생 많았어~~ 무지 잘된다."

Seventeenth-session can cold-start as:
1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. Open `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md` for issue#16 spec context.
4. (Optional) `.claude/memory/project_gpio_uart_migration.md` for issue#17 deferred-spec context.
5. Standard pipeline (per `feedback_pipeline_short_circuit.md`): if issue#16 ≤200 LOC → direct writer + Mode-B fast path; otherwise full Planner → Mode-A → Writer → Mode-B.

**Operator's tracker.toml has `lidar_port = "/dev/ttyUSB0"` (post HIL USB swap)**. Will be obviated by issue#10 `/dev/rplidar` symlink (or issue#17 GPIO direct).

**Operator's `04.29_v3.pgm` (0.05 m/cell, pre-issue#13-cand) is still the active map**. New 0.025 m/cell maps (test_v4 etc.) sitting under `/var/lib/godo/maps/`; operator can activate when ready.

## Session-end cleanup

- NEXT_SESSION.md: rewritten as a whole per the cache-role rule. 3-step absorb routine applied — issue#14 (now done in PR #67) pruned from TL;DR; issue#16 + #17 promoted from session-discovery; issue#15 carryover from fifteenth retained.
- PROGRESS.md sixteenth-session block added at the top of the session log (PR #68).
- doc/history.md sixteenth-session 한국어 block added (PR #68).
- Per-stack CODEBASE.md files: 3 stacks (`production/RPi5/`, `godo-webctl/`, `godo-frontend/`) got new round 2 entries beyond what Writer wrote in round 1; godo-mapping/ unchanged in round 2 (round 1 entry from Writer is final).
- `.claude/memory/`: 3 new entries (`feedback_ssot_following_discipline.md`, `project_gpio_uart_migration.md`, `project_mapping_precheck_and_cp210x_recovery.md`); `MEMORY.md` index updated.
- Branches: `feat/issue-14-mapping-pipeline-spa` deleted on origin via squash-merge --delete-branch; local cleanup pending. `fix/backup-active-symlink-and-config-input-empty` deleted by PR #66 squash-merge. Local: clean after sixteenth-session-close docs PR push.
- Plan file location confirmed: `.claude/tmp/plan_issue_14_mapping_pipeline_spa.md` is gitignored (not tracked). Survives across sessions on the same host (news-pi01).
