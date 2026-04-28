# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-29 close. Phase 4.5 P0 + P0.5 + P1 all shipped; P2 next.

## TL;DR

**Priority order (user-set 2026-04-29 close)**:

1. **★ Phase 4.5 P2** — B-SYSTEM → B-BACKUP → B-MAPEDIT, in that order (easiest first).
2. **Phase 2 (AMCL convergence)** — still hardware-gated on LiDAR pivot-center remount + a higher-quality mapping pass.
3. Optional opportunistic touches: deferred Mode-B nits, the cold_writer test observability extension, the atomic-writer fault-injection mock seam.

## Where we are (2026-04-29 close)

**main = `265f5f6`** — Phase 4.5 P0 + P0.5 + P1 all merged. 8 feature/fix commits + 1 post-merge UX hotfix landed this session.

**Open**: nothing. All 4 P1 PRs merged (Track D #14, B-DIAG #18, PR-CONFIG-α #19, PR-CONFIG-β #20).

**Local artifacts (not in git, gitignored throwaways under `.claude/tmp/`)**:
- `plan_track_d_live_lidar.md` + `review_mode_a_track_d.md` + `review_mode_b_track_d.md`
- `plan_track_b_diag.md` + `review_mode_a_track_b_diag.md` + `review_mode_b_track_b_diag.md`
- `plan_track_b_config.md` + `review_mode_a_track_b_config.md` + `review_mode_b_track_b_config_alpha.md` + `review_mode_b_track_b_config_beta.md`
- Older session artefacts (Track E, P0 frontend, Track B-repeat, Phase 4-2/4-3) safe to delete.

**Live system on news-pi01**:
- webctl on `0.0.0.0:8080` (`setsid` detached, log: `/tmp/godo-webctl.log`), SPA bundle `index-B1VL4OVo.js` (28.07 KB gzipped). PID changes per session — `pgrep -f godo_webctl` to find current.
- godo-tracker NOT running (deliberate; banner expected).
- maps_dir: `/home/ncenter/projects/GODO/godo-mapping/maps/` (overrides default `/var/lib/godo/maps/` via `GODO_WEBCTL_MAPS_DIR` env). Track E auto-migration created `active.pgm` + `active.yaml` symlinks → `studio_v2`.
- LAN-IP path (`192.168.3.22:8080`) blocked at SBS_XR_NEWS AP client-isolation — use Tailscale `100.127.59.15:8080` for browser access.

## Phase 4.5 P2 — start here

### Step 1: B-SYSTEM (smallest, leverages existing endpoints)

FRONT_DESIGN.md §C / §8 row "B-SYSTEM". The page combines:
- 5-min CPU temp graph (sparkline using `<DiagSparkline/>` from B-DIAG)
- mem / disk numbers (already in `/api/system/resources`)
- journald tail (already in `/api/logs/tail`, allow-list = `services.ALLOWED_SERVICES`)
- Reboot / Shutdown buttons (P0 endpoints `/api/system/reboot`, `/api/system/shutdown` — admin only, confirm dialog reuses `<ConfirmDialog/>`)

**Backend**: probably nothing new — all endpoints exist.
**Frontend**: ~250 LOC (route + 1-2 components). Reuses DIAG infra heavily.

Pipeline: planner → Mode-A → fold → writer → Mode-B → fold → PR. Single PR, ≤300 LOC, will not need splitting.

### Step 2: B-BACKUP

`/api/map/backup` POST already exists from Phase 4-3. Need:
- `GET /api/map/backup/list` — enumerate `/var/lib/godo/map-backups/<UTC ts>/` directories.
- `POST /api/map/backup/<ts>/restore` — atomic copy back to `cfg.maps_dir`.
- SPA route `/backup` with table + restore confirm dialog.

**Backend**: ~200 LOC + tests.
**Frontend**: ~200 LOC + tests.
**~400 LOC total**, single PR.

### Step 3: B-MAPEDIT

Open question §I-Q1 needs to resolve first (mask method): rectangle erase / flood fill / brush. Recommend brush (simplest UX, simplest implementation — circular kernel paint into a mask, then erase pixels above 200 = free in PGM).

**Backend**: `POST /api/map/edit` body `{ops: [{type: erase|fill|flood, mask: [[x,y]...]}]}` with numpy + Pillow. Atomic write back to `<map>.pgm` (reuse Track E's symlink swap pattern). Backup before edit.
**Frontend**: `<MapEditor/>` with brush drawing on canvas; `Map.svelte` toggle "Edit mode". ~400 LOC SPA.

**~700 LOC total**, ≤1500 borderline → single PR is fine.

## Phase 2 (AMCL convergence) — still hardware-blocked

Pre-requisites unchanged from previous NEXT_SESSION:
- LiDAR mounted at pan-pivot center (currently 20 cm offset).
- Mapping pass with explicit loop closure + slow walk + retro-reflector landmarks (per `.claude/memory/project_studio_geometry.md`).
- Then evaluate (a) ICP-based initial pose seed, (b) tightened `amcl_sigma_seed_xy_m` ~30 cm, (c) AMCL config tuning per new feature density.

P1 SPA visualization (Diagnostics page) now lets the operator watch AMCL convergence stats live + see RT jitter; once tracker is up + mapped properly, this is the page to debug from.

## Stacked-PR merge mechanics — lesson learned

`gh pr merge --rebase --delete-branch` deletes the head branch. If a downstream PR has base = that branch, GitHub **auto-closes** it on base-branch deletion (does NOT auto-retarget to main). Workaround for next time:

```bash
# BEFORE merging upstream PR:
gh pr edit <downstream> --base main
# Then merge upstream:
gh pr merge <upstream> --rebase --delete-branch
# Downstream still open + retargeted, just needs rebase on the new main:
git checkout <downstream-head> && git rebase origin/main && git push --force-with-lease
```

Order matters: retarget → merge → rebase. If you skip the retarget step, the downstream PR will close and you need to recreate it.

## Quick orientation files

1. **CLAUDE.md** §6 Golden Rules + §7 agent pipeline.
2. **PROGRESS.md** — 2026-04-29 session entry has all 4 PR details.
3. **doc/history.md** — last entry 2026-04-29 — Korean narrative ("왜 / 무엇을 결정했는가" centric).
4. **FRONT_DESIGN.md** ★ — §6.4 (Tracker C++ changes table), §7.1 (HTTP endpoint living table — every Track D/B-DIAG/B-CONFIG row marked `(있음)`), §8 (Phase plan — P2 rows still untouched).
5. **production/RPi5/CODEBASE.md** — invariants (a)–(p) — (l) hot-path config, (m) hot-config publisher, (n) atomic TOML writer, (o)/(p) cold_writer HotConfig reader migration.
6. **godo-webctl/CODEBASE.md** — invariants (a)–(t) — Track F + 4 PR-DIAG endpoints + 4 PR-CONFIG endpoints + restart_pending + journald subprocess discipline.
7. **godo-frontend/CODEBASE.md** — invariants (a)–(s) — (l) arrival-wall-clock freshness (DiagFrame + LastScan), (s) RestartPendingBanner single-mount in App.svelte.

## Throwaway scratch (`.claude/tmp/`)

Keep until next session:
- `plan_track_d_live_lidar.md` + reviews — referenced by 2026-04-29 PROGRESS entry.
- `plan_track_b_diag.md` + reviews — referenced by 2026-04-29 PROGRESS entry.
- `plan_track_b_config.md` + reviews — referenced by 2026-04-29 PROGRESS entry.

Delete when convenient (older session artefacts, no longer load-bearing):
- `plan_p0_frontend.md` + `review_mode_*_p0_frontend*.md` — pre-this-session.
- `plan_track_e_map_management.md` + `review_mode_*_track_e.md` — Track E shipped 2 sessions ago.
- `plan_track_b_repeatability.md` + `review_track_b_repeatability_*.md` — Track B legacy.
- `plan_phase4_2_*.md`, `plan_phase4_3.md` — older phase plans.
- `apply_*.sh` — Phase 4-1 RT bring-up scripts (one-time).

## Session-end cleanup

Closeout commit `1` (post-merge UX hotfix `265f5f6`) + closeout commit `2` (this docs commit) are local on `main` but NOT pushed. Run `git push origin main` to land them.

NEXT_SESSION.md itself: refresh in place each session; never delete this file (drives every cold-start). P2 status updates each session.
