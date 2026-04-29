# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-30 06:07 KST (ninth-session close — PR #34 squash-merged as `dcded7c`; main is now systemd-managed end-to-end).
> **AMCL CONVERGENCE SOLVED** (PR #32 — eighth-session marathon close): Track D-5 sigma annealing + auto-minima tracking, k_post 10/10 (was 0/10), σ_xy median 0.009m (was 6.679m).
> **PR-A LANDED on main** (PR #34, `dcded7c`): full systemd switchover + polkit rule + LAN bind + SPA dist deploy + cgroup_enable=memory cmdline + irq-pin device-name lookup + envfile-based env display + env_stale badge + ServiceStatusCard lastError UX + config_schema path tier resolution. Operator service-management policy adopted (tracker = manual-start via SPA; irq-pin + webctl auto-start). News-pi01 fully systemd-managed; SPA Start/Stop/Restart end-to-end working.

## TL;DR (operator-set priority order, refreshed 2026-04-30 06:07 KST)

1. **★ PR-B: process monitor + extended resources** — next P0 chunk. New `/api/system/processes` SSE stream (parse `/proc`, GODO whitelist, `duplicate_alert` flag if multiple PIDs match same expected name) + `/api/system/resources/extended` (per-core CPU + GPU + mem + disk). New System sub-tab in SPA. ~550 LOC. Defense-in-depth on top of CLAUDE.md §6's pidfile locking + the polkit-gated service control PR-A just shipped.
   - Spec details: `.claude/memory/project_system_tab_service_control.md`.

   **Carryover from PR-A**: default admin password `ncenter`/`ncenter` STILL needs `scripts/godo-webctl-passwd` rotation per operator policy. Flagged here so it doesn't slip — unrelated to PR-B but worth doing on the same news-pi01 visit.

2. **★ B-MAPEDIT (queued P0 from prior session, plan ready)** — `.claude/tmp/plan_track_b_mapedit.md` Mode-A folded. Brush erase + atomic save + restart-pending. ~950 LOC single PR. Re-run writer fresh from §8-folded plan; the earlier writer pass (2026-04-29 ~13:00 KST) was discarded clean during the AMCL crisis.

3. **★ B-MAPEDIT-2: origin pick** — operator's new request 2026-04-29 23:45 KST. Click any pixel on the rendered PGM in MapEdit mode → that pixel becomes the new world (0,0). YAML origin field update only — pure translation, no bitmap rewrite. ~90 LOC bolt-on to B-MAPEDIT (or its own small follow-up PR). Use case: operator places a pole at the chroma studio's physical center, scans it, clicks the resulting point on the map → studio center becomes origin. Spec: `.claude/memory/project_map_edit_origin_rotation.md`.

4. **★ Pipelined-pattern audit** (Task #9 carryover) — operator-requested systematic audit: where else does the variable-scope / CPU-pipeline pattern apply? Candidates per `.claude/memory/project_pipelined_compute_pattern.md`: SSE producer-consumer (`/api/scan/stream`, `/api/last_pose/stream`), FreeD smoother stages, UE 60Hz publish staging, map activate phased reload, AMCL Live mode tiered confidence monitor. Output: ranked table by (operator benefit, impl cost, RT-safety). Can run in parallel with B-MAPEDIT scoping.

6. **B-MAPEDIT-3: map rotation (deferred)** — ~250 LOC, lower marginal value vs LOC. Operator suggested **VideoCore VII GPU acceleration** for matrix ops at this point (RPi 5 GPU mostly idle, single HDMI used). Spec: `.claude/memory/project_videocore_gpu_for_matrix_ops.md`. Recommendation: don't attempt without first measuring CPU baseline + POC dispatch on a single op (likely EDT 1D pass via Vulkan compute). Research-grade work — schedule after Track 5 (UE integration) unless rotation blocks operator.

7. **Track D-5-Live (sigma annealing for Live mode)** — operator hinted Live could also benefit from variable-scope tracking (prev pose narrows search → fewer phases needed). Track D-5 OneShot landed; Live extension is its own plan. Lower priority — Live uses `seed_around` already which is annealing-light.

8. **Track D-5-P (parallel pipelined annealing)** — research-grade follow-up to Track D-5: multiple AMCL chains running concurrently at different σ values on cores 0/1/2 (CPU 3 RT-isolated). Useful for finding convergence-cliff σ adaptively + disambiguating false basins. Spec scaffolded in `.claude/memory/project_pipelined_compute_pattern.md`.

9. **`test_jitter_ring` flaky test** — observed 1× fail during D-5 build (RT timing-sensitive). Not regression from any code change in this session. Investigate at low priority — likely needs tolerance bump or move to `hardware-required` label.

## Where we are (2026-04-30 06:07 KST — ninth-session close)

**main = `dcded7c`** — one PR merged this ninth session, on top of the eighth-session marathon's five (PR #29, #30, #31, #32, #33):

| PR | What | Notes |
|---|---|---|
| #34 | **PR-A — full systemd switchover + polkit gate** ★ | unblocked SPA Start/Stop/Restart end-to-end; folded 9 bug fixes uncovered during HIL + post-merge UX/config_schema follow-ups |

**Open PRs**: 0.

## Sigma annealing timeline (2026-04-29 21:00–23:30 KST, the marathon arc)

The bug was misdiagnosed twice before being correctly identified. Timeline:

1. **~12:30 KST** — Operator HIL on PR #29 surfaces "overlay 5× scale + suspected Y-flip". Fixed via Track D-2 (SPA scan negate) and Track D-3 (C++ AMCL scan negate) + Track D-4 attempt (load_map row flip — turned out NOT needed and was reverted before merge).
2. **~19:20 KST** — Post Track D-2/D-3 deploy: σ_xy 6.7m persistently, k_post 0/10. Hypothesized as remaining map-row-order bug. Track D-4 implemented + tested → no improvement → reverted.
3. **~20:30 KST** — Decision tree: "if D-3+D-4 don't help, what does?" Operator suggested checking sigma_hit. Empirical sweep ran across σ ∈ {1.0, 0.5, 0.2, 0.1, 0.05}.
4. **~21:00 KST** — **Sweep verdict**: σ=0.2 = 9/10 converge but 3 basins; σ=1.0 = 2/10 single basin. Convergence cliff between 0.1 and 0.2. **sigma_hit tightness = real root cause.** D-3/D-4 were red herrings (D-3 still merged as defensive math; D-4 unmerged). Saved as `project_amcl_sigma_sweep_2026-04-29.md`.
5. **~21:30 KST** — Operator proposed annealing schedule: wide → narrow. Plan written, Mode-A reviewed, Writer implemented, PR #32 opened with default schedule `[1.0, 0.5, 0.2, 0.1, 0.05]`.
6. **~22:30 KST** — HIL on PR #32: k_post 0/10, σ_xy median 0.036m. Annealing finds basin (single-basin lock confirmed) but final phase σ=0.05 over-tightens into sub-cell discretization noise. Manual override `[1.0, 0.5, 0.2]` gives k_post 10/10.
7. **~23:00 KST** — Operator suggested **auto-minima tracking + patience-2 early break**. Implemented in `cold_writer.cpp::converge_anneal`, committed `7b5aec0`. **HIL: k_post 10/10, σ_xy median 0.009m, single basin** (1.15, ~0, yaw 173°).
8. **~23:30 KST** — PR #32 merged + PR #33 hotfix merged. Eight-session marathon close.

The auto-minima trick generalizes — operator can SAFELY granularize the schedule without worrying about over-tightening, because the algorithm self-stops at the empirical minimum. Pattern spec'd as a project-wide architectural idiom in `.claude/memory/project_pipelined_compute_pattern.md`.

## Live system on news-pi01 (post ninth-session close)

- **godo-irq-pin.service**: enabled, auto-start, IRQ pin via device-name lookup (resilient to reboot-time IRQ-number drift).
- **godo-webctl.service**: enabled, auto-start, listening 0.0.0.0:8080, serving SPA from `/opt/godo-frontend/dist`. Owns `/run/godo/` via `RuntimeDirectory=godo` + `RuntimeDirectoryPreserve=yes`. Sees envfile via `/etc/godo/webctl.env`.
- **godo-tracker.service**: installed but NOT enabled per operator service-management policy (manual-start via SPA System tab). Last manual start: AMCL converges to (1.15, ~0, 173°) on every calibrate. Map = `04.29_v3.pgm`.
- **`/run/godo/`**: owned by webctl now, populated with both pidfiles + (if tracker running) `ctl.sock`. Survives whichever service stops first.
- **`/etc/godo/`**: `tracker.env` + `webctl.env` seeded by installer; operator-edited values (LAN bind, active map path, SPA dist, config_schema path) persist across reboots.
- **`/opt/`**: `/opt/godo-tracker/` (binary + helper + `share/config_schema.hpp`), `/opt/godo-webctl/` (rsync'd source + `.venv`), `/opt/godo-frontend/dist/` (SPA bundle).
- **Active map**: `04.29_v3.pgm` (loop closure, two-lap walk, 2978 occupied / 60.7% free). Operator notes ±1-2° residual rotation in scan overlay vs walls — slam_toolbox build artifact. Addressable by re-mapping with intentional initial heading OR origin pick + rotation feature.
- **Branch**: `main @ dcded7c`, working tree clean.
- **LAN-IP path**: blocked at SBS_XR_NEWS AP (client-isolation); Tailscale `100.127.59.15` works.
- **Default admin password rotation pending**: `scripts/godo-webctl-passwd` to rotate `ncenter`/`ncenter` per operator policy.

## Throwaway scratch (`.claude/tmp/`)

**Keep until B-MAPEDIT ships**:
- `plan_track_b_mapedit.md` — Mode-A folded, ready for writer (next-session task #2).

**Keep for one more cycle, then prune**:
- `plan_service_observability.md` — PR #27 reference (shipped).
- `plan_mapping_pipeline_fix.md` — PR #28 reference (shipped).
- `plan_track_d_scale_yflip.md` — PR #29 reference (shipped).
- `plan_track_d_3_cpp_amcl_cw_ccw.md` — PR #31 reference (shipped).
- `plan_track_d_5_sigma_annealing.md` — PR #32 reference (shipped). Contains the planning history including misidentified root causes — useful trail for future debug-arc retrospectives.

**Delete when convenient**:
- Anything pre-2026-04-29 not above.

## Quick memory bookmarks (★ open these first on cold-start)

Eighth + ninth session produced eight new in-repo memory entries. Open in priority order:

1. `.claude/memory/project_godo_service_management_model.md` — operator's policy: SPA is the SOLE start/stop/restart UI; auto-start (irq-pin + webctl) vs manual (tracker). Read before any service-control change.
2. `.claude/memory/project_system_tab_service_control.md` — PR-B (process monitor + extended resources) spec. PR-A status now SHIPPED.
3. `.claude/memory/feedback_codebase_md_freshness.md` — every implementation task updates relevant CODEBASE.md before commit/merge/push.
4. `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md` — empirical sweep table, convergence cliff, why D-3/D-4 weren't the root cause. Read before touching any AMCL code.
5. `.claude/memory/project_pipelined_compute_pattern.md` — operator's variable-scope / CPU-pipeline analogy. Architectural idiom; pinpoints Task #9 audit candidates.
6. `.claude/memory/project_map_edit_origin_rotation.md` — Map Edit feature spec: brush erase (B-MAPEDIT, planned) + origin pick (~90 LOC, high-ROI) + rotation (deferred).
7. `.claude/memory/project_videocore_gpu_for_matrix_ops.md` — RPi 5 GPU offload candidates. Don't attempt without baseline measurement + POC.
8. `.claude/memory/project_rplidar_cw_vs_ros_ccw.md` — D-2/D-3 hypothesis history; useful retrospective for future debug arcs.

Plus carryover: `project_studio_geometry.md`, `project_lens_context.md`, `project_repo_topology.md`, `feedback_pipeline_short_circuit.md`.

## Quick orientation files for next session

1. **CLAUDE.md** §6 Golden Rules + §7 agent pipeline.
2. **`.claude/memory/MEMORY.md`** — full index of all in-repo memory entries.
3. **PROGRESS.md** — current through 2026-04-30 ninth-session block.
4. **doc/history.md** — ditto, Korean narrative.
5. **`production/RPi5/CODEBASE.md`** invariants tail = `(o) godo-systemctl-polkit-discipline`.
6. **`godo-webctl/CODEBASE.md`** invariants tail = `(x)` (admin-non-loopback service-control endpoint, NOW functional post-PR-A).

## Tasks alive for next session

- **PR-B** (TL;DR item 1) — top priority. process monitor + extended resources.
- **B-MAPEDIT** writer kickoff (TL;DR item 2).
- **B-MAPEDIT-2** origin pick (TL;DR item 3).
- **#9** (pending) — pipelined-pattern applicability audit (TL;DR item 4).
- (deferred) B-MAPEDIT-3 rotation + GPU POC + Live annealing + parallel annealing.
- (low priority) `test_jitter_ring` flake fix.
- (operator pending, unrelated) `scripts/godo-webctl-passwd` rotation of default `ncenter`/`ncenter` admin password.

## Session-end cleanup

- NEXT_SESSION.md itself: refreshed in place 2026-04-30 06:07 KST. Drives every cold-start.
- PROGRESS.md + doc/history.md updated 2026-04-30 06:07 KST with the ninth-session block (PR-A full systemd switchover).
- All three CODEBASE.md files (production/RPi5, godo-webctl, godo-frontend) carry the PR-A change-log entries + new invariant `(o) godo-systemctl-polkit-discipline` (production/RPi5) + frontend SPA addendum on env_stale + lastError UX.
- `.claude/memory/` gained two new entries: `feedback_codebase_md_freshness.md`, `project_godo_service_management_model.md`. MEMORY.md index updated.
