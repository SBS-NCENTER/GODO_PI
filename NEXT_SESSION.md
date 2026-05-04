# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-05-04 22:30 KST (twenty-second-session close — issue#28 ships PR #81 at `da78dd0`; docs PR #82 awaiting operator merge).
> Cache-role per `.claude/memory/feedback_next_session_cache_role.md` — SSOT = RAM (PROGRESS / history / per-stack CODEBASE.md / memory); this file is cache. 3-step absorb routine: read → record in SSOT → prune.

## TL;DR (operator-locked priority order, refreshed 2026-05-04 22:30 KST)

1. **★ issue#30 — YAML normalization to (0, 0, 0°) per Apply** (NEW, operator-locked twenty-second-session late-night). Spec at `.claude/memory/project_yaml_normalization_design.md` — full design candidate already drafted (must read before Planner kickoff). Two interpretation candidates need operator clarification at session opening:
   - **(1) strict (0, 0, 0°), translate + crop** — picked point lands at bitmap (0, 0); studio content in negative quadrants is cropped or padded with 205. Simple YAML, lossy bitmap.
   - **(2) quasi-(0, 0, 0°), translate to centre origin** — YAML origin = `(-bbox_w/2, -bbox_h/2, 0°)` so world (0, 0) lands at bitmap centre. No cropping; YAML yaw is 0 but origin x/y is not literally 0.
   - Implementation requires: Pillow `Image.transform` (affine, not just rotate), canvas adjustment for translate-and-rotate bbox, cumulative-typed tracking from pristine (preserves 1× resample quality), numeric input UX shift (defaults = "no change"). See spec memory §"Implementation requirements" for full cross-stack scope.
   - Depends on `project_amcl_yaw_metadata_only.md` finding (Option B is the only correct yaw path; metadata-only Option A doesn't move pose).

2. **issue#28.1 — B-MAPEDIT-3 follow-ups** (PR #81 Mode-B Major findings + cleanup). Half-day batch:
   - **MA1**: 4 missing pytests around asyncio.Lock + SSE protocol (`test_concurrent_apply_serialises`, `test_sse_progress_emits_monotonic_floats`, `test_sse_emits_rejected_on_canvas_overflow`, `test_sse_progress_frames_carry_request_id`).
   - **MA2**: Move `test_apply_reads_pristine_not_latest_derived` from unit (smoke) to integration (real exercise).
   - **MA3**: Fix docstring on `test_apply_origin_edit_subtracts_theta_wraps_at_180` (assertion correct, doc reads wrong direction).
   - **MA4**: Remove unused `LANCZOS_FILTER_NAME` constant (Pillow `rotate` rejects LANCZOS, BICUBIC actually used).
   - **MA6**: HIL-test overlay projection at extreme zoom; if overlays detach during pan/zoom, file `issue#28.2` to share PoseCanvas transform.
   - **MA7**: Document `/api/map/edit/coord` synchronous-vs-202 trade-off in webctl CODEBASE.md `(aj)` invariant.
   - **MA8**: Promote `kRadToDeg` from `pose.cpp` to `core/constants.hpp` (no-magic-numbers compliance, `occupancy_grid.cpp:379`).
   - **MA9**: Mark `amcl.origin_yaw_deg` schema row description as DEPRECATED so operator's config tab shows it.
   - **Cleanup**: Delete standalone `<OriginAxisOverlay>` + `<GridOverlay>` component files (no longer mounted; replaced by `lib/overlayDraw.ts` helpers in PR #81 round-4 HIL fix). Their tests can stay temporarily as math contract pins.
   - **Hard-removal**: Schedule `cfg.amcl_origin_yaw_deg` field deletion (C2 two-step deprecation — this PR is the second step).
   - **Cleanup**: `flat` backward-compat key removal from `/api/maps` (per webctl invariant `(ak)` one-release sunset).

3. **issue#26 — cross-device latency measurement tool** (PAUSED at Mode-A round 1 REJECT). Round 2 + Writer + HIL is half-day at broadcasting-room wired LAN. Plan + Mode-A fold ready at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. Memory: `.claude/memory/project_issue26_measurement_tool.md` for full Critical-finding table + resumption procedure.

4. **issue#11 — Live pipelined-parallel multi-thread** (PAUSED awaiting issue#26 first capture). Round 1 plan + Mode-A round 1 fold preserved at `.claude/tmp/plan_issue_11_live_pipelined_parallel.md`. Comprehensive analysis SSOT at `/doc/issue11_design_analysis.md`. Memory: `.claude/memory/project_issue11_analysis_paused.md`.

5. **issue#13 (continued) — distance-weighted AMCL likelihood** (`r_cutoff` near-LiDAR down-weight). Standalone single-knob algorithmic experiment.

6. **issue#4 — AMCL silent-converge diagnostic** — comprehensive HIL baseline accumulated through nineteenth-session. Source: `.claude/memory/project_amcl_multi_basin_observation.md` + `project_silent_degenerate_metric_audit.md`.

7. **issue#29 — SHOTOKU base-move + two-point cal-reset workflow** (NEW deferred 2026-05-04 KST). Spec at `/doc/shotoku_base_move_and_recal_design.md` (242 lines, UART migration pattern). **Depends on issue#30** (same YAML re-anchor math).

8. **issue#17 — GPIO UART direct connection** (perma-deferred) — only ship if cp210x mitigations prove insufficient.

9. **Bug B — Live mode standstill jitter ~5cm widening** — analysis-first. May be subsumed by issue#11.

10. **issue#7 — boom-arm angle masking (optional)** — Contingent on issue#4 diagnostic.

**Next free issue integer: `issue#31`** (issue#30 = YAML normalization).

## Where we are (2026-05-04 22:30 KST — twenty-second-session close)

**main = `da78dd0`** — PR #81 (issue#28) merged. Working tree on `docs/2026-05-04-twenty-second-session-close` for the chronicler bundle (PR #82, awaiting operator merge).

**Open PRs**: PR #82 (this twenty-second-session docs bundle).

**Twenty-second-session merged**: #81 (issue#28 — 54 files, +6746/-384, 1456/1456 tests). Longest pipeline stack to date (Planner → Mode-A → Writer × 3 → Mode-B → Writer fold-in → HIL × 5 rounds → 5 HIL-fix commits → squash-merge).

## Live system on news-pi01 (post twenty-second-session close)

CHANGED this session (issue#28):

- **godo-tracker.service**: rebuilt from main `da78dd0`. `cold_writer` now reads `grid.origin_yaw_deg()` (YAML SSOT); `cfg.amcl_origin_yaw_deg` retained as deprecated field with one-shot stderr warning if non-zero. Tier-2 schema row `amcl.origin_yaw_deg` still parseable. Operator pre-deploy: `sudo sed -i.bak '/^amcl\.origin_yaw_deg/d' /var/lib/godo/tracker.toml` to silence warning.
- **godo-webctl.service**: redeployed from main, restarted. NEW endpoints live — `POST /api/map/edit/coord` (JSON), `POST /api/map/edit/erase` (multipart), `GET /api/map/edit/progress` (SSE), `GET /api/maps` returns `{groups, flat}` grouped tree shape. NEW modules: `map_rotate.py`, `sse.py`. Extended: `map_origin.py` (theta SUBTRACT + `wrap_yaw_deg`), `maps.py` (pristine/derived classifier).
- **godo-frontend** (`/opt/godo-frontend/dist/`): redeployed. NEW components: `<EditModeSwitcher>`, `<OverlayToggleRow>`, `<ApplyMemoModal>`, `<MapList>`. NEW lib: `lib/overlayDraw.ts` (sole owner of overlay drawing). Old standalone overlay canvases removed; ondraw composition via MapUnderlay's hook. Orange pick previews live.

UNCHANGED:
- godo-irq-pin, godo-cp210x-recover, godo-mapping@active, polkit (14 rules), Docker `godo-mapping:dev`, `/etc/udev/rules.d/99-rplidar.rules`, `/run/godo/`, journald.

## Quick memory bookmarks (★ open these first on cold-start)

This session added **4 NEW memory entries** + updated MEMORY.md index:

1. ★ `.claude/memory/project_yaml_normalization_design.md` — **MUST READ before issue#30 Planner kickoff**. Full design spec for the deferred Option Q work, including 2 interpretation candidates needing operator clarification.
2. ★ `.claude/memory/project_amcl_yaw_metadata_only.md` — **MUST READ before any future yaw-related design**. AMCL particle filter ignores YAML yaw; explains why Option B (bake-into-bitmap) is required.
3. ★ `.claude/memory/feedback_ship_vs_wire_check.md` — Mode-A + Mode-B reviewer discipline addition. Surfaced from PR #81 round-2 HIL.
4. ★ `.claude/memory/feedback_docstring_implementation_drift.md` — Mode-B reviewer discipline addition. Surfaced from PR #81 round-4 HIL.
5. `.claude/memory/MEMORY.md` — index updated with 4 new entries above.

Carryover (still active):
- `project_pipelined_compute_pattern.md`, `project_cpu3_isolation.md`, `project_amcl_multi_basin_observation.md`, `project_calibration_alternatives.md`, `project_hint_strong_command_semantics.md`, `project_gpio_uart_migration.md` (issue#17 perma-deferred spec)
- `project_issue11_analysis_paused.md`, `project_issue26_measurement_tool.md` (paused-spec memories)
- `project_pristine_baseline_pattern.md`, `feedback_overlay_toggle_unification.md` (issue#28 spec carriers)
- `feedback_codebase_md_freshness.md`, `feedback_next_session_cache_role.md`, `feedback_check_branch_before_commit.md`, `feedback_two_problem_taxonomy.md`, `feedback_claudemd_concise.md`, `feedback_pipeline_short_circuit.md`, `feedback_emoji_allowed.md`, `feedback_toml_branch_compat.md`, `feedback_ssot_following_discipline.md`, `feedback_deploy_branch_check.md`, `feedback_relaxed_validator_strict_installer.md`, `feedback_post_mode_b_inline_polish.md`, `feedback_verify_before_plan.md` (★ MOST-VIOLATED — reread on every Planner brief), `feedback_helper_injection_for_testability.md`, `feedback_build_grep_allowlist_narrowing.md`, `feedback_subtract_semantic_locked.md`
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
- `project_map_edit_origin_rotation.md` (B-MAPEDIT-3 — DONE in PR #81; spec body still useful as historical reference, "★ Final spec lock" section is the SSOT for what shipped)

## Quick orientation files for next session

1. **CLAUDE.md** §3 Phases + §6 Golden Rules + §8 Deployment + PR workflow + §7 agent pipeline.
2. **`CODEBASE.md`** (root) — cross-stack scaffold. UNCHANGED this session (no family-shape shift).
3. **`DESIGN.md`** (root) — TOC for SYSTEM_DESIGN + FRONT_DESIGN. UNCHANGED.
4. **`.claude/memory/MEMORY.md`** — full index (~52 entries; 4 added this session).
5. **PROGRESS.md** — current through 2026-05-04 twenty-second-session close.
6. **doc/history.md** — Korean narrative through 스물 두 번째 세션.
7. **★ `.claude/memory/project_yaml_normalization_design.md`** — issue#30 Planner brief MUST start here.
8. **★ `.claude/memory/project_amcl_yaw_metadata_only.md`** — yaw-design design constraint.
9. **`production/RPi5/CODEBASE.md`** — UPDATED (invariant `(w) yaw-frame-ssot-via-yaml-origin`).
10. **`godo-webctl/CODEBASE.md`** — UPDATED (invariants `(ag) (ah) (ai) (aj) (ak)` + `(ab)` extension).
11. **`godo-frontend/CODEBASE.md`** — UPDATED (invariants `(aj) (ak) (al) (am) (an) (ao) (ap)` + `(u) (aa)` extensions).
12. **`SYSTEM_DESIGN.md`** — UPDATED (§14 change log — HIL retrospective entry added).
13. **`FRONT_DESIGN.md`** — UPDATED (§I3-bis-update — HIL round 4-5 viewport-tracking overlay architecture).

## Issue labelling reminder (CLAUDE.md §6 SSOT)

Operator-locked **issue#N.M** scheme. Sequential integer for distinct units (next free = 31); decimal for sub-issues (e.g. `issue#28.1`, `issue#28.2`); Greek letters deprecated; feature codes (B-MAPEDIT etc.) are a separate axis.

**Reservations from /doc/issue11_design_analysis.md §8** (DO NOT use these integers for new issues):
- `issue#19` — EDT 2D Felzenszwalb parallelization.
- `issue#20` — Track D-5-P (deeper σ schedule for OneShot, staggered-tier).
- `issue#21` — NEON/SIMD vectorization of `evaluate_scan` per-beam loop.
- `issue#22` — Adaptive N (KLD-sampling).
- `issue#23` — LF prefetch / gather-batch.
- `issue#24` — Phase reduction 3→1 in Live carry (TOML-only).
- `issue#25` — `amcl_anneal_iters_per_phase` 10→5 (TOML-only).
- `issue#26` — Cross-device GPS-synced measurement tool.
- `issue#27` — output_transform + SUBTRACT origin + LastOutput SSE — DONE in PR #79 (twenty-first-session).
- `issue#28` — B-MAPEDIT-3 yaw rotation (full plumbing + coherent render) — **DONE in PR #81 this session**.
- `issue#29` — SHOTOKU base-move + two-point cal-reset workflow.
- `issue#30` — YAML normalization to (0, 0, 0°) per Apply.

## Throwaway scratch (`.claude/tmp/`)

**Keep across sessions** (referenced by paused / queued memories):
- `plan_issue_11_live_pipelined_parallel.md` — Round 1 plan + Mode-A round 1 fold. Round 2 NOT persisted.
- `plan_issue_26_latency_measurement_tool.md` — Round 1 plan + Mode-A round 1 fold. Round 2 deferred.
- `plan_issue_28_b_mapedit3_yaw_rotation.md` — **DONE — keep one cycle** as reference for issue#30 Planner (Mode-A + Mode-B folds + Parent disposition table show how the multi-stack pipeline composed).

**Delete when convenient** (older plans no longer referenced):
- `plan_issue_27_map_polish_and_output_transform.md` (PR #79 reference, two cycles old).
- `plan_issue_18_uds_bootstrap_audit.md` (PR #75 reference, three cycles old).
- `plan_issue_10.1_lidar_serial_config_row.md` (PR #73 reference, three cycles old).
- `plan_issue_16.1_trap_timeout_and_issue_10_udev.md` (PR #72 reference, three cycles old).

## Tasks alive for next session

- **issue#30 — YAML normalization to (0, 0, 0°)** (TL;DR #1 — primary scope, multi-stack: webctl bitmap-transform extension + frontend numeric input UX shift + cumulative-typed tracking)
- **issue#28.1 — B-MAPEDIT-3 follow-ups + cleanup** (TL;DR #2 — half-day batch)
- **issue#26 — measurement tool round 2 + Writer + HIL** (TL;DR #3)
- **issue#11 — Live pipelined-parallel** (TL;DR #4 — PAUSED)
- **issue#13 (continued) — distance-weighted likelihood** (TL;DR #5)
- **issue#4 — AMCL silent-converge diagnostic** (TL;DR #6)
- **issue#29 — SHOTOKU base-move** (TL;DR #7 — depends on issue#30)
- **issue#17 — GPIO UART migration** (TL;DR #8 — perma-deferred)
- **Bug B — Live mode standstill jitter** (TL;DR #9)
- **issue#7 — boom-arm angle masking** (TL;DR #10)

## Twenty-third-session warm-up note

Twenty-second-session was a focused multi-round cross-stack ship (~16+ hours including 5 HIL rounds). 1 PR (#81, issue#28) merged at `da78dd0`. Two structural lessons surfaced (memory entries written this close):

1. **Components shipped without being mounted** — round-2 HIL caught `<MapList>` was created with full grouped-tree logic + Vitest pin but never mounted on Map.svelte. Lesson `feedback_ship_vs_wire_check.md` prescribes Mode-A + Mode-B grep checks.
2. **Yaw direction sign mismatch** — round-4 HIL caught `map_rotate.py` docstring said `-typed_yaw_deg` but implementation passed `+typed_yaw_deg`. Lesson `feedback_docstring_implementation_drift.md` prescribes Mode-B docstring-vs-implementation grep + asymmetric pin demand.

One structural revelation also documented (`project_amcl_yaw_metadata_only.md`): `grid.origin_yaw_deg` is metadata-only — AMCL particle filter ignores YAML yaw; only output-stage `compute_offset` + tripwire diagnostic read it. This determines the architectural shape of issue#30 (Option B bake-into-bitmap is the only correct path; Option A metadata-only doesn't move pose).

**Cold-start sequence for twenty-third session (issue#30 path)**:

1. Read CLAUDE.md (this file's parent) for operating rules.
2. Read this NEXT_SESSION.md.
3. **★ Open `.claude/memory/project_yaml_normalization_design.md`** — full issue#30 spec including 2 interpretation candidates (strict (0, 0, 0°) crop vs centred origin no-crop) needing operator clarification at session opening.
4. **★ Open `.claude/memory/project_amcl_yaw_metadata_only.md`** — explains why bitmap rotation is required, not metadata-only.
5. Open `.claude/memory/project_pristine_baseline_pattern.md` — pattern issue#30 must preserve.
6. Open `.claude/memory/feedback_subtract_semantic_locked.md` — current SUBTRACT semantic; issue#30 will likely supersede or extend with cumulative-from-current alternative.
7. Operator opens session: ASK FIRST about interpretation 1 vs 2 (literal (0, 0, 0°) crop vs centred origin no-crop). Cannot Plan without this lock.
8. Verify-before-Plan: read `godo-webctl/src/godo_webctl/map_rotate.py` for the existing `Image.rotate` call — issue#30 likely needs `Image.transform` (affine matrix) for combined rotate + translate.
9. Standard pipeline: Planner → Mode-A → Writer → Mode-B → operator HIL (per `feedback_pipeline_short_circuit.md`; issue#30 is feature-scale + multi-stack).

**If operator brings issue#28.1 first** (PR #81 follow-up cleanup):
1. Read PR #81 Mode-B fold in `.claude/tmp/plan_issue_28_b_mapedit3_yaw_rotation.md` for MA1-MA10 list.
2. Half-day Writer batch — no Plan needed (cleanup tickets).
3. Single PR for all 9 follow-ups + standalone overlay component file deletion + `cfg.amcl_origin_yaw_deg` hard-removal.

**If operator brings issue#26 first** (broadcasting-room ship):
1. Read `.claude/memory/project_issue26_measurement_tool.md`.
2. Read `.claude/tmp/plan_issue_26_latency_measurement_tool.md` Mode-A fold.
3. Run **Planner round 2** with brief that absorbs every Critical fix + Major reframe inline.
4. Mode-A round 2 → Writer → Mode-B → Operator HIL on news-pi01 + MacBook in broadcasting-room.

## Session-end cleanup (twenty-second)

- NEXT_SESSION.md: rewritten as a whole per cache-role rule. Stale TL;DR #1 (issue#28 itself) absorbed into PR #81 merge state + spec memory enrichment, then promoted issue#30 (YAML normalization) to TL;DR #1.
- PROGRESS.md twenty-second-session block added at top of session log (chronicler PR #82).
- doc/history.md 스물 두 번째 세션 한국어 block added (chronicler PR #82).
- SYSTEM_DESIGN.md / FRONT_DESIGN.md / per-stack CODEBASE.md: UPDATED in chronicler PR #82.
- `.claude/memory/`: 4 new entries (`project_yaml_normalization_design`, `project_amcl_yaw_metadata_only`, `feedback_ship_vs_wire_check`, `feedback_docstring_implementation_drift`); MEMORY.md index updated.
- `.claude/tmp/`: `plan_issue_28_b_mapedit3_yaw_rotation.md` retained one cycle as issue#30 reference.
- Branches deleted (PR squash-merge cleanup): `feat/issue-28-mapedit3-yaw-rotation` (deleted locally + auto-deleted on origin via `--delete-branch`).
