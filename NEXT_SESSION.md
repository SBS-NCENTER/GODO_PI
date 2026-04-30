# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-30 10:08 KST (tenth-session close — 4 PRs landed in one session: #37 #35 #36 #38; main = `5d3cb95`).
> **System tab + Config tab fully functional end-to-end.** Reboot/Shutdown buttons work (PR-A1), Config tab shows live values for all 37 Tier-2 keys (PR-A2), System tab now has Processes / Extended resources sub-tabs (PR-B), Config tab has View/Edit safety gate with best-effort Apply (PR-C).
> **AMCL CONVERGENCE SOLVED** carried over from eighth-session marathon (PR #32): Track D-5 sigma annealing + auto-minima tracking, k_post 10/10 (was 0/10), σ_xy median 0.009m (was 6.679m).

## TL;DR (operator-set priority order, refreshed 2026-04-30 10:08 KST)

1. **★ B-MAPEDIT (P0, plan ready)** — `.claude/tmp/plan_track_b_mapedit.md` Mode-A folded. Brush erase + atomic save + restart-pending. ~950 LOC single PR. Re-run writer fresh from §8-folded plan; the earlier writer pass (2026-04-29 ~13:00 KST) was discarded clean during the AMCL crisis. **Now top priority** — PR-B (process monitor) shipped this session.

2. **★ B-MAPEDIT-2: origin pick (GUI click + numeric entry)** — operator's request 2026-04-29 23:45 KST, dual-input requirement reaffirmed 2026-04-30. Two input modes side-by-side, NOT one or the other: (Mode A) click any pixel on the rendered PGM → world-coord pre-fill in numeric fields → that becomes the new world (0,0); (Mode B) type `(x_m, y_m)` directly with absolute/delta toggle for fine reproduction from a measured offset. YAML origin field update only — pure translation, no bitmap rewrite. ~150 LOC (was 90; +60 for the numeric form, validation, and unit toggle). Use case: operator places a pole at the chroma studio's physical center, scans it, then either clicks or types the offset → studio center becomes origin. Spec: `.claude/memory/project_map_edit_origin_rotation.md`. **Dual-input is mandatory** for every continuous correction in the Map Edit family — single-input proposals are flagged as regression.

3. **Pipelined-pattern audit** (Task #9 carryover) — operator-requested systematic audit: where else does the variable-scope / CPU-pipeline pattern apply? Candidates per `.claude/memory/project_pipelined_compute_pattern.md`: SSE producer-consumer, FreeD smoother stages, UE 60Hz publish staging, map activate phased reload, AMCL Live mode tiered confidence monitor. Output: ranked table by (operator benefit, impl cost, RT-safety). Can run in parallel with B-MAPEDIT scoping.

4. **Wire-shape SSOT pin retrospective (PR-A2 lesson)** — PR-A2 fixed a wire-shape drift between C++ tracker (`{"ok":true,"keys":{...}}`) and Python projection. Latent because both unit + integration tests mocked the WRONG (flat) shape — hand-mirrored mocks drift from production wire silently. Investigate applying the cross-language SSOT pin pattern (regex-extract from C++ source, like PR-B's `test_godo_process_names_match_cmake_executables`) to wire-shape boundaries: `format_ok_*` functions in `json_mini.cpp` could each have a Python sibling test that decodes a captured production response. Low priority but high-ROI when applied — would have caught PR-A2's bug pre-merge.

5. **Admin password rotation** — operator's deferred task: `scripts/godo-webctl-passwd` to rotate the default `ncenter`/`ncenter` admin password. PR-C operator decision: rotate via Local-only endpoint OR SSH shell only (NOT via admin-non-loopback). Likely a follow-up "PR-D" — small (~50 LOC). Not blocking.

6. **B-MAPEDIT-3: map rotation (deferred, GUI + numeric)** — ~250 LOC, lower marginal value vs LOC. **Same dual-input rule as B-MAPEDIT-2**: drag-rotate handle OR two-point wall pick (Mode A) AND `theta_deg` numeric entry with sub-degree precision (Mode B); CCW-positive convention (ROS/REP-103). Operator suggested **VideoCore VII GPU acceleration** for matrix ops at this point (RPi 5 GPU mostly idle, single HDMI used). Spec: `.claude/memory/project_videocore_gpu_for_matrix_ops.md`. Recommendation: don't attempt without first measuring CPU baseline + POC dispatch on a single op. Research-grade work — schedule after Track 5 (UE integration) unless rotation blocks operator.

7. **Track D-5-Live (sigma annealing for Live mode)** — operator hinted Live could also benefit from variable-scope tracking. Track D-5 OneShot landed (eighth session); Live extension is its own plan. Lower priority — Live uses `seed_around` already which is annealing-light.

8. **Track D-5-P (parallel pipelined annealing)** — research-grade follow-up to Track D-5: multiple AMCL chains running concurrently at different σ values on cores 0/1/2. Useful for finding convergence-cliff σ adaptively + disambiguating false basins. Spec scaffolded in `.claude/memory/project_pipelined_compute_pattern.md`.

9. **`test_jitter_ring` flaky test** — observed 1× fail during D-5 build (RT timing-sensitive). Not regression. Investigate at low priority — likely needs tolerance bump or move to `hardware-required` label.

## Where we are (2026-04-30 10:08 KST — tenth-session close)

**main = `5d3cb95`** — four PRs merged this tenth session:

| PR | What | Notes |
|---|---|---|
| #37 | **PR-A2 — config keys envelope unwrap** | Hotfix for latent wire-shape drift; Config tab now shows live values |
| #35 | **PR-A1 — login1 polkit rule** | Reboot/Shutdown buttons now work (was HTTP 500) |
| #36 | **PR-B — System tab process monitor + extended resources** ★ | New Processes + Extended resources sub-tabs; all-PID enumeration with classification; pure stdlib /proc parsers |
| #38 | **PR-C — Config tab View/Edit safety gate + best-effort Apply** ★ | View mode default; admin-only EDIT; Cancel never PATCHes; (default) hint under each row; tracker-inactive banner |

**Open PRs**: 0.

## Live system on news-pi01 (post tenth-session close)

- **godo-irq-pin.service**: enabled, auto-start, IRQ pin via device-name lookup (resilient to reboot-time IRQ-number drift).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080, serving SPA from `/opt/godo-frontend/dist`. Owns `/run/godo/` via `RuntimeDirectory=godo` + `RuntimeDirectoryPreserve=yes`. Sees envfile via `/etc/godo/webctl.env`.
- **godo-tracker.service**: installed but NOT enabled per operator service-management policy (manual-start via SPA System tab Start button).
- **`/opt/`**: `/opt/godo-tracker/` (binary + helper + `share/config_schema.hpp`), `/opt/godo-webctl/` (rsync'd source + `.venv`), `/opt/godo-frontend/dist/` (SPA bundle — refreshed this session with PR-B sub-tabs + PR-C Edit mode).
- **polkit**: 14 rules loaded (12 default + rule (a) manage-units + rule (b) login1.{reboot,power-off}*).
- **Active map**: `04.29_v3.pgm`. Operator notes ±1-2° residual rotation in scan overlay vs walls — addressable by re-mapping with intentional initial heading OR origin pick + rotation feature (B-MAPEDIT-2 / -3).
- **Branch**: `main @ 5d3cb95`, working tree clean (after this session-close docs commit).
- **LAN-IP path**: blocked at SBS_XR_NEWS AP (client-isolation); Tailscale `100.127.59.15` works.
- **Default admin password rotation pending**: `scripts/godo-webctl-passwd` to rotate `ncenter`/`ncenter` per operator policy.
- **SPA verified end-to-end**: Config tab 37 keys live values + (default) hints + EDIT button (admin-gated). System tab Reboot/Shutdown 200 OK + Processes / Extended resources sub-tabs working.

## Throwaway scratch (`.claude/tmp/`)

**Keep until B-MAPEDIT ships**:
- `plan_track_b_mapedit.md` — Mode-A folded, ready for writer (next-session task #1).

**Keep for one more cycle, then prune**:
- `plan_pr_b_process_monitor.md` — PR #36 reference (shipped). Body + operator-fold + Mode-A fold + Final fold + Mode-B fold — useful four-fold template for future feature-scale plans.
- `plan_pr_c_config_tab_edit_mode.md` — PR #38 reference (shipped). Same four-fold pattern.
- `plan_service_observability.md` — PR #27 reference (shipped).
- `plan_mapping_pipeline_fix.md` — PR #28 reference (shipped).
- `plan_track_d_scale_yflip.md` — PR #29 reference (shipped).
- `plan_track_d_3_cpp_amcl_cw_ccw.md` — PR #31 reference (shipped).
- `plan_track_d_5_sigma_annealing.md` — PR #32 reference (shipped).

**Delete when convenient**:
- Anything pre-2026-04-29 not above.

## Quick memory bookmarks (★ open these first on cold-start)

Tenth session added one new in-repo memory entry; nine total active. Open in priority order:

1. `.claude/memory/project_godo_service_management_model.md` — operator's policy: SPA is the SOLE start/stop/restart UI.
2. `.claude/memory/project_config_tab_edit_mode_ux.md` — **NEW (tenth session)** — Config tab View/Edit gate operator-locked spec; documents WHY Cancel is client-side only and WHY best-effort over all-or-nothing. Read before touching Config tab edit logic.
3. `.claude/memory/feedback_codebase_md_freshness.md` — every implementation task updates relevant CODEBASE.md before commit/merge/push.
4. `.claude/memory/project_system_tab_service_control.md` — PR-B (process monitor + extended resources) spec. PR-B status now SHIPPED.
5. `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md` — empirical sweep table, convergence cliff, why D-3/D-4 weren't the root cause.
6. `.claude/memory/project_pipelined_compute_pattern.md` — operator's variable-scope / CPU-pipeline analogy. Architectural idiom; pinpoints Task #9 audit candidates.
7. `.claude/memory/project_map_edit_origin_rotation.md` — Map Edit feature spec: brush erase (B-MAPEDIT, P0 next session) + origin pick (~90 LOC, high-ROI) + rotation (deferred).
8. `.claude/memory/project_videocore_gpu_for_matrix_ops.md` — RPi 5 GPU offload candidates.
9. `.claude/memory/project_rplidar_cw_vs_ros_ccw.md` — D-2/D-3 hypothesis history.

Plus carryover: `project_studio_geometry.md`, `project_lens_context.md`, `project_repo_topology.md`, `feedback_pipeline_short_circuit.md`.

## Quick orientation files for next session

1. **CLAUDE.md** §6 Golden Rules + §7 agent pipeline.
2. **`.claude/memory/MEMORY.md`** — full index of all in-repo memory entries.
3. **PROGRESS.md** — current through 2026-04-30 tenth-session block.
4. **doc/history.md** — ditto, Korean narrative.
5. **`production/RPi5/CODEBASE.md`** invariants tail = `(o) godo-systemctl-polkit-discipline` (extended this session for login1).
6. **`godo-webctl/CODEBASE.md`** invariants tail = `(z)` (PR-B process monitor + extended resources backend).
7. **`godo-frontend/CODEBASE.md`** invariants tail = `(z)` (PR-C Config tab Edit-mode safety gate).

## Tasks alive for next session

- **B-MAPEDIT** writer kickoff (TL;DR item 1) — top priority.
- **B-MAPEDIT-2** origin pick (TL;DR item 2).
- **#9** (pending) — pipelined-pattern applicability audit (TL;DR item 3).
- **Wire-shape SSOT pin retrospective** (TL;DR item 4) — investigate applying regex-extract pattern to `json_mini.cpp::format_ok_*`.
- **Admin password rotation** (TL;DR item 5) — small follow-up PR.
- (deferred) B-MAPEDIT-3 rotation + GPU POC + Live annealing + parallel annealing.
- (low priority) `test_jitter_ring` flake fix.

## Session-end cleanup

- NEXT_SESSION.md itself: refreshed in place 2026-04-30 10:08 KST. Drives every cold-start.
- PROGRESS.md + doc/history.md updated 2026-04-30 10:08 KST with the tenth-session block (4 PRs).
- All three CODEBASE.md files (production/RPi5, godo-webctl, godo-frontend) carry the PR-A1 / PR-A2 / PR-B / PR-C change-log entries + new invariants (godo-webctl `(z)` for process monitor backend; godo-frontend `(z)` for Config tab Edit-mode gate; production/RPi5 `(o)` extended for login1).
- `.claude/memory/` gained one new entry: `project_config_tab_edit_mode_ux.md`. MEMORY.md index updated with PR-C bullet.
