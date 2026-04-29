# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-29 16:34 KST (afternoon session — third close, ~12:33–16:34 KST).
> **Mapping pipeline is now correct** (PR #28). rf2o laser odometry replaced the static identity TF that had been silently breaking every map for ~24h. **Service observability shipped** (PR #27). B-MAPEDIT was paused mid-session (writer's partial output discarded clean) when the mapping bug surfaced; it's queued for next-session pickup as the first coding task. **Late-session discovery (~16:30 KST)**: scan-overlay 5× scale + suspected Y-flip bug in PoseCanvas — diagnosed but not yet fixed; planner spec drafted in head, queued as Track D fix.

## TL;DR (priority order)

1. **★ Track D scale + Y-flip fix (NEW, 2026-04-29 16:30 KST discovery)** — small, focused, blocks operator trust in `/map` overlay. **Bug**: `MAP_PIXELS_PER_METER = 100` (`godo-frontend/src/lib/constants.ts:98`) hardcodes 0.01 m/cell, but our slam_toolbox maps are 0.05 m/cell → scan overlay renders at **5×** the PGM image size. PoseCanvas at `:165-167` draws the image as `naturalWidth × zoom` (no resolution scaling), while `worldToCanvas` at `:120` uses `MAP_PIXELS_PER_METER`. Suspected secondary bug: PGM Y-axis goes down (image convention) but world Y goes up (ROS convention) → image is vertically mirrored vs scan rays without explicit flip. **Fix path**: SPA must derive pixels-per-meter from YAML `resolution` field (SSOT), and apply Y-flip on image draw OR on world transform. Webctl already has `GET /api/maps/{name}/yaml` (`app.py:804`) — SPA can fetch + parse client-side, OR add `GET /api/map/metadata` returning JSON `{resolution, origin, width, height}`. ~150-250 LOC: PoseCanvas image-draw rewrite + new metadata fetch + scanTransform.ts test fixes + `MAP_PIXELS_PER_METER` constant deletion.

2. **★ Phase 4.5 P2 Step 3: B-MAPEDIT** — plan + Mode-A fold ready at `.claude/tmp/plan_track_b_mapedit.md`. **Mode-A fold §8 already applied** (M1-M3 + S1-S3 + T1-T4 + N1-N3, including invariant letter shift to webctl `(y)` + frontend `(u)` after PR #27 landed). Writer kickoff branch from `f311218`. ~950 LOC; single PR. Now meaningful because the underlying map is real. **Note**: an earlier writer pass (2026-04-29 ~13:00 KST) wrote ~600 LOC of source + tests but was paused mid-stream when the mapping bug surfaced; that work was discarded clean (`git checkout .` + `git clean -fd`) — no stash. Re-run writer fresh from the §8-folded plan.

3. **★ AMCL re-test on real map (Phase 2 hardware-gated check)** — Track D scale fix unblocks visual debugging of AMCL pose accuracy. Empirical observation 2026-04-29 ~16:00 KST: with the new `04.29_v3.pgm` (two-lap walk + loop closure, 2978 occupied / 60.7% free), AMCL `calibrate` converges roughly **1 in 15 attempts** when LiDAR is at first-scan position. When it doesn't converge, pose lands completely outside the studio. This pattern (sporadic convergence, drift to map periphery) is the classic Phase 2 hardware-gated signature: LiDAR pivot offset (currently ~20 cm off-axis) + un-tuned AMCL Tier-2 params. The good news: the **map quality is no longer the bottleneck** — that was the question PR #28 answered. The next blocker is on the hardware/algorithm axis.

4. **★ Privilege escalation audit** (Task #28 from prior session) — webctl Shutdown/Reboot button + service-control still broken (`subprocess_failed` because `ncenter` can't call privileged ops). Polkit + `systemctl poweroff/reboot` + `systemctl restart godo-*` recommended. Now also coordinated with PR #27's new admin-non-loopback `POST /api/system/service/{name}/{action}` endpoint (subprocess fails until polkit lands; auth + transition gate already work).

5. **★ tracker SIGTERM handler** (Task #33 from prior session) — verified gap in PR #25: SIGTERM kills tracker without triggering RAII PidFileLock dtor → pidfile + UDS socket linger on disk (functionally OK, cosmetic). Fix: install SIGTERM/SIGINT handler in main.cpp, mirror godo-webctl pattern.

6. **rf2o follow-up watch** — upstream `MAPIRlab/rf2o_laser_odometry` PR #41 (package.xml format-3 migration) still open. When it merges, drop the in-Dockerfile sed patch and bump SHA in `godo-mapping/Dockerfile`. No urgency.

7. **Live mode (Phase 4-2 D)** — operator confirmed today: `/map` Live toggle has no effect (pose stays outside studio + scan overlay never renders in Live mode). This is **expected**: CLAUDE.md §1 row 4 explicitly says "Implementation deferred to Phase 4-2 D". UI ships the toggle as future-stub. Defer to its own milestone after AMCL Phase 2 fix.

8. **Session-end docs reconciliation** (Task #27 from prior session) — cascade pass on FRONT_DESIGN.md + 2 CODEBASE.md after B-MAPEDIT lands.

## Where we are (2026-04-29 16:34 KST — third close, afternoon session)

**main = `f311218`** — PR #27 service observability + PR #28 mapping fatal bug fix merged. **2 PRs merged this (third) session**:

| PR | What | LOC | Notes |
|---|---|---|---|
| #27 | Track B-SYSTEM PR 2 — service observability + admin-non-loopback service action endpoint | +2855 | Mode-A folds M1-M6 + S1-S7 + N1-N5 + T1-T6 + §8 (Option C admin endpoint) S1+S2+TB1. webctl invariants (v)+(w)+(x). Frontend (t). |
| #28 | replace static identity TF with rf2o laser odometry | +255 | Fatal mapping bug fix. Mode-A folds M1-M5 + S1-S4 + N1. godo-mapping invariant (h). HIL validated. |

**Open PRs**: 0.

## Mapping fatal bug timeline (2026-04-29 afternoon)

The bug was hidden for ~24h. Diagnosis + fix arc, in this session's KST timeline:

1. **~14:30 KST — Discovery**: user opened `0429_2.pgm` as image, saw a single fan-shape from one position despite walking + loop closure. ("이상하다, 분명 이동하면서 지도를 만들었는데...")
2. **~14:35 KST — Statistical confirmation**: 4 maps under `godo-mapping/maps/` showed 63-114 occupied pixels each (vs thousands expected), all single-fan signatures.
3. **~14:45 KST — Root cause** (`godo-mapping/launch/map.launch.py:44-50`): a static identity TF `odom→laser` (added 2026-04-28 to "close the TF chain" without external odom) silently lied to slam_toolbox about motion. slam_toolbox's `minimum_travel_distance: 0.5` (Jazzy default) gate fired against odom-derived motion = 0; only 1 scan ever integrated.
4. **~15:00 KST — Plan A chosen** ("정석대로 가자"): rf2o_laser_odometry overlay build + launch rewrite. Plan written to `.claude/tmp/plan_mapping_pipeline_fix.md`, Mode-A folded M1-M5 + S1-S4 + N1.
5. **~15:30 KST — Writer build-first gate passed**: rf2o ros2 SHA `b38c68e4…`, colcon `1 package finished [47.3s]`, no warnings. Dockerfile + launch.py + rf2o.yaml + slam_toolbox YAML doc + CODEBASE.md (h) + README.md edits all green. PR #28 opened.
6. **~15:45 KST — Mode-B reproduced**: docker build green (image SHA `92b3076da18e…`), live ROS 2 param binding confirmed (`base_frame_id=laser` overrides constructor default `base_link`), all 7 source-declared rf2o parameters match YAML keys verbatim.
7. **~15:55 KST — HIL run 1**: user walked ~3m (walkable area limit), `test_rf2o_v.pgm` shows: occupied 1390 (13× the 107 broken baseline), free 51.7% (9× the 5.7% broken baseline), unknown 47% (vs 94% broken). Visual: rectangular room outline + corners + doorway/passage at bottom + secondary section at top-right. **User confirmed: "좋아 완전 맞아 저 장소 맞다"** — rendered map matches actual studio geometry.
8. **~16:00 KST — PR #28 merged** as `f311218`.
9. **~16:05 KST — HIL run 2 (`04.29_v3`, two-lap walk)**: 2978 occupied, 60.7% free, 36.5% unknown. Map shape further refined — corner/passage features more confidently localized due to repeat-visit averaging.
10. **~16:20 KST — AMCL convergence test on `04.29_v3`**: tracker started, calibrate run repeatedly. Converged ~1 in 15 attempts. When non-converging, pose drifts completely outside studio. Confirms map quality is no longer the bottleneck — Phase 2 hardware-gated levers now isolated as the actual blocker (LiDAR pivot offset + AMCL Tier-2 tuning).
11. **~16:30 KST — Track D bug discovered**: while the user was visually validating AMCL, scan-overlay showed at ~5× scale + rotated relative to the PGM. Diagnosed as `MAP_PIXELS_PER_METER = 100` hardcoding 0.01 m/cell vs actual 0.05 m/cell. Fix queued for next session.

The 5000-occupied target from the original plan was calibrated for a 20×13m studio with a full walk; the actual walkable area is ~3m radius, so 1390 cells representing the room perimeter (run 1) is consistent with a successful 3m walk. Run 2's two-lap walk pushed it to 2978. Visual confirmation supersedes the numeric threshold.

## tmux setup (cold-start)

Same as prior session — `tmux new -A -s godo && claude` at session start. Currently still running inside tmux session `godo` (created Wed Apr 29 12:33). Optional auto-attach `~/.bashrc` snippet still suggested but not added without confirmation.

## Live system on news-pi01 (post-session)

- webctl: running (started 2026-04-29 12:11). PID changes per session — check `cat ~/.local/state/godo/godo-webctl.pid`. Log `/tmp/godo-webctl.log`. Pidfile under `$HOME/.local/state/godo/` (not `/run/godo/` until systemd unit lands per Task #32).
- godo-tracker: NOT running (gracefully stopped at end of prior session).
- `/run/godo/`: exists, owned by ncenter (one-time `sudo chown` from prior session). Survives reboot only via systemd RuntimeDirectory; manual chown needed after boot until Task #32.
- godo-mapping container image: rebuilt this session with rf2o overlay. New image SHA `92b3076da18e…` (caches cleanly; see PR #28 CODEBASE.md change-log for the build summary).
- `~/.bashrc` venv auto-activate observed for godo-webctl (suspected from prior `.bashrc` setup; not touched this session).
- Active map: still `0429_2.pgm` (the broken one!). Tracker config can stay pointed there — it loads at boot and won't regen on its own. Operator should regenerate a real map (e.g., `0429_3` via the fixed pipeline) before doing the AMCL re-test from TL;DR #4.
- LAN-IP path blocked at SBS_XR_NEWS AP client-isolation; Tailscale `100.127.59.15` still works. Pi tailscale IP confirmed `100.127.59.15`.

**Working tree**: clean on main `f311218`.

## B-MAPEDIT writer kickoff brief (for next session, just paste into Agent dispatch)

Plan is in `.claude/tmp/plan_track_b_mapedit.md`. §1-§7 is the body, §8 is the Mode-A fold (M1 webctl invariant `(y)`, M2 activity log type `"map_edit"`, M3 restart-pending writer/reader split prose, S1-S3 atomic-write + backup_ts disk match + restart_required value pin, T1-T4 greyscale boundary + content-length-before-decode + sentinel-not-on-failure + DPR mask-array index, N1-N3 cosmetic).

Branch from main `f311218`. Single PR, ~950 LOC budget (likely ~1050 per Mode-A N3 estimate). Tracker C++ untouched. Pillow already transitive — `pyproject.toml` unchanged. Decision LOCKED: I2 + brush + restart-required (no hot reload).

Pre-existing baselines after PR #27 + #28 (third close):
- Backend: 491 passed, 1 skipped.
- Frontend unit: 143 passed.
- Frontend e2e: 36 passing (1 pre-existing config.spec.ts unrelated).

## Quick orientation files

1. **CLAUDE.md** §6 Golden Rules + §7 agent pipeline.
2. **PROGRESS.md** — should gain a 2026-04-29 entry for the mapping fix saga + PR #27/#28.
3. **doc/history.md** — likewise.
4. **FRONT_DESIGN.md** — §I-Q1 + §4.2 supersession blocks (PR #24) still pending fold-into-main-text after B-MAPEDIT.
5. **godo-webctl/CODEBASE.md** invariants (a)–(x) live; B-MAPEDIT will add `(y)`.
6. **godo-frontend/CODEBASE.md** invariants (a)–(i)/(j out-of-order)/(k)–(q)/(t)/(v)/(w) live; B-MAPEDIT will add `(u)`.
7. **godo-mapping/CODEBASE.md** invariants (a)–(h) live; (h) is the new "odom→laser TF is rf2o-published, never static" rule that locks in PR #28's fix and lists Plan B/C as legitimate fallbacks.
8. **production/RPi5/CODEBASE.md** invariants (a)–(l) — unchanged this session.

## Throwaway scratch (`.claude/tmp/`)

**Keep until B-MAPEDIT ships**:
- `plan_track_b_mapedit.md` — Mode-A folded, ready for writer (next-session task).

**Keep for one more cycle, then prune**:
- `plan_service_observability.md` — PR #27 reference (shipped).
- `plan_mapping_pipeline_fix.md` — PR #28 reference (shipped). Includes Mode-A fold + the empirical-build-first decision tree that proved valuable.

**Delete when convenient**:
- Anything pre-2026-04-29 not in the above list.

## Tasks alive for next session

- **#3** (pending) — B-MAPEDIT writer kickoff (THE first coding task). Plan + §8 fold ready.
- Privilege escalation audit (polkit) — coordinated with PR #27's admin endpoint.
- tracker SIGTERM handler (audit other RAII members in main.cpp).
- AMCL re-test on a fresh real map (regen via fixed pipeline first).
- Session-end docs cascade after B-MAPEDIT ships.

## Session-end cleanup

NEXT_SESSION.md itself: refresh in place each session; never delete (drives every cold-start).

PROGRESS.md + doc/history.md updates: still TODO before final session close — should now include the mapping fix saga as its own section.
