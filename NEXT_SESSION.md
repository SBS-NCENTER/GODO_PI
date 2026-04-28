# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-28 evening. PR-13 (Track E) on the launch pad; Track D queued behind it.

## TL;DR

**Priority order (user-set 2026-04-28 evening close)**:

1. **★ PR-13 LAN-browser check + merge** — `feat/p4.5-track-e-map-management` ahead of main by 2 commits. https://github.com/SBS-NCENTER/GODO_PI/pull/13. Open `http://192.168.3.22:8080/map` from a LAN PC at the office, expect the new `MapListPanel` above the map canvas with at least `studio_v1` and `studio_v2` rows (active badge on whichever the symlink resolves to). If clean → `gh pr merge 13 --rebase`.
2. **★ Track D (Live LIDAR overlay) — full pipeline (planner → Mode-A → writer → Mode-B → PR-D)**. First cross-language (C++ tracker) PR since Track B; design already locked in FRONT_DESIGN §8.
3. Track E follow-ups (small, optional bundle into a docs PR or an opportunistic next PR — see "Mode-B carry-overs" below).
4. Phase 2 (AMCL convergence) — still hardware-gated on LiDAR pivot-center remount.

## Where we are (2026-04-28 evening close)

**main = `1f5f3c4`** — PR-A (backend) + PR-B (SPA + Track F + Mode-B fold + FRONT_DESIGN §8 Track D/E) merged.

**Open**:
- **PR-13** at `feat/p4.5-track-e-map-management` ahead of main by 2 commits — https://github.com/SBS-NCENTER/GODO_PI/pull/13.
  - `d7b9281` — feat(track-e): multi-map management — 5 endpoints, atomic symlink swap, SPA panel.
  - `d4fe79d` — fix(track-e): Mode-B folds — M4 unit test + corpus parity + WARN pin + count fix.
  - 256 pytest / 37 vitest / 14 playwright / ruff+eslint+prettier+build all clean.

**Local artifacts (gitignored, post-merge candidates for cleanup)**:
- `.claude/tmp/plan_track_e_map_management.md` — Mode-A folded final plan (~52 KB).
- `.claude/tmp/review_mode_a_track_e.md` — Mode-A reviewer output (APPROVE-WITH-NITS).
- `.claude/tmp/review_mode_b_track_e.md` — Mode-B reviewer output (APPROVE-WITH-NITS).
- Earlier `.claude/tmp/plan_p0_frontend.md` + the four P0/PR-B review files — historical fold reference; safe to delete after PR-13 merges if `.claude/tmp/` size becomes a concern.

**Live system on news-pi01**:
- webctl on `0.0.0.0:8080` (`setsid` detached), serving `studio_v2.pgm`, JWT/users under `~/.local/state/godo/auth/`. NOT under systemd; PID is whatever was running at session close.
- godo-tracker NOT running (banner showing in SPA is the documented expected state).
- After PR-13 merge, the live webctl will need a restart to pick up `cfg.maps_dir` (env var addition optional — default `/var/lib/godo/maps` matches today's symlink layout once the operator runs `scripts/godo-maps-migrate` once).

## Frontend track — start here

### Step 1: LAN check + merge PR-13

Open `http://192.168.3.22:8080/map` from a LAN PC at the office:
- Expect: `MapListPanel` table above the map canvas, ≥ 2 rows (`studio_v1`, `studio_v2`), one with the active badge.
- Click a non-active row's preview → `<PoseCanvas/>` re-renders with that map.
- (Admin only — log in as `ncenter`) "기본으로 지정" opens the activate confirm dialog. On the LAN PC the `godo-tracker 재시작` button will be **hidden** (per M4 hostname check); only "재시작하지 않음" + cancel render. That is the expected behaviour.
- "삭제" disabled on the active row (tooltip: 활성 맵은 삭제할 수 없습니다).

If clean: `gh pr merge 13 --rebase`. main advances; cleanup `feat/p4.5-track-e-map-management` locally.

### Step 2: Track D (Live LIDAR overlay)

Plan in FRONT_DESIGN §8. After PR-13 merges, run the full pipeline (planner → Mode-A → fold → writer → Mode-B → fold → PR-D). Spans:
- **godo-tracker C++**: new `get_last_scan` UDS handler (seqlock read of latest scan ring buffer; μs-level read, hot-path 0 impact). First C++ touch since Track B — verify-no-hw checks must still pass.
- **webctl**: `/api/last_scan` GET + `/api/last_scan/stream` SSE @ 5 Hz.
- **SPA**: `PoseCanvas` 3rd canvas layer + `Map.svelte` toggle button.
- **~350 LOC + tests** estimate per FRONT_DESIGN §8.

Cross-language SSOT: `LastScan` struct mirror chain (C++ canonical → `protocol.py` mirror → `lib/protocol.ts` mirror) following the `LastPose` precedent from Track B.

### Step 3: Track E follow-ups (Mode-B carry-overs)

Four items intentionally deferred from PR-13. Bundle into a small Track E follow-up PR or fold into Track D opportunistically:

1. **`cfg.map_path is None` dead-code branch** (`godo-webctl/src/godo_webctl/app.py:197,229`). Either drop the `is None` half (Settings type is `Path`, not `Path | None`) or change `Settings.map_path` to `Path | None` with a `_parse_optional_path` parser. Latter lets operators disable the legacy path via empty string; cleaner.
2. **Stub server Track F drift** (`godo-frontend/tests/e2e/_stub_server.py:336,392,381`). `/api/last_pose`, `/api/local/services`, `/api/activity` still gate on `_claims_or_401` / `_require_admin` in the stub; backend made these anonymous-readable per Track F. Pre-PR-B drift, not regressed by Track E. Align stub with backend.
3. **e2e shared global stub state** (`map.spec.ts`). Tests run in declaration order under `workers=1`; future parallelism would flake. Add a `POST /__test/reset` stub endpoint + `test.beforeEach` reset.
4. **Concurrent-flock test 40 ms wall-clock budget** (`test_set_active_serializes_under_flock`). Tight under load. Switch to a `threading.Event` signaling pattern or bump the slop to 25 ms.

None block PR-13 merge.

### Step 4: Phase 2 (AMCL convergence)

Stays deferred. Pre-requisites unchanged from previous NEXT_SESSION:
- LiDAR mounted at pan-pivot center (currently 20 cm offset — temp install).
- Mapping pass with explicit loop closure + slow walk + retro-reflector landmarks at the step corners (per `.claude/memory/project_studio_geometry.md`).
- Then evaluate: (a) ICP-based initial pose seed, (b) tightened `amcl_sigma_seed_xy_m` ~30 cm, (c) AMCL configuration tuning per the new feature density.

PR-13 SPA visualisation continues to confirm the sparse-feature diagnosis visually. Phase 2 work is not blocked on more code today; it's blocked on hardware reseat + a higher-quality mapping pass.

## State of the dev host (news-pi01, 2026-04-28 evening close)

- LiDAR `/dev/ttyUSB0` connected, dialout group OK.
- Docker: `godo-mapping:dev` image current (used today for the v2 pass).
- C++ tracker: built at `production/RPi5/build/src/godo_tracker_rt/godo_tracker_rt`. Setcap NOT applied this session. Stop/start workflow per `production/RPi5/scripts/setup-pi5-rt.sh`.
- maps/: `studio_v{1,2}.{pgm,yaml}` (root-owned 644 — webctl runs as `ncenter` and reads via the open mode bits, no chown needed). After PR-13 merge, the operator needs to run `godo-webctl/scripts/godo-maps-migrate <pgm-path>` once to copy these into `/var/lib/godo/maps/` and create the `active.{pgm,yaml}` symlinks; OR keep the existing `/home/ncenter/projects/GODO/godo-mapping/maps/` mount and override `GODO_WEBCTL_MAPS_DIR` to that path (cheaper for dev — but `systemctl edit godo-webctl` then needs `ReadWritePaths=` extension once we systemd-install it).
- systemd: nothing GODO-related installed.
- webctl runs in foreground via `setsid` from this session — `pgrep -f "python.* -m godo_webctl"` to find the PID. After PR-13 merge, restart picks up `cfg.maps_dir` (default `/var/lib/godo/maps`).

## Quick orientation files

1. **CLAUDE.md** §6 Golden Rules + §7 agent pipeline.
2. **PROGRESS.md** — last entry "2026-04-28 evening (PR-B merge + Track E PR-13 delivered)" — full session record.
3. **doc/history.md** — last entry 2026-04-28 — Korean narrative; needs a continuation entry for tonight's work next session.
4. **FRONT_DESIGN.md** ★ — frontend SSOT. §7.1 living API/SSE table (Track E rows now `(있음)` after merge), §8 phase plan + Track D + Track E.
5. **godo-webctl/CODEBASE.md** — invariants now (a)–(p) — (n) Track F, (o) maps.py leaf, (p) atomic symlink discipline (after PR-13 merge).
6. **godo-frontend/CODEBASE.md** — SPA invariants + (l) `<ConfirmDialog/>.secondaryAction` extension.

## Throwaway scratch (`.claude/tmp/`)

Keep until next session:
- `plan_track_e_map_management.md`, `review_mode_a_track_e.md`, `review_mode_b_track_e.md` — referenced by this session's PROGRESS entry.

Delete after PR-13 merges (size 200 KB+; not durable):
- All `plan_p0_frontend.md` + `review_mode_a_p0_frontend.md` + `review_mode_b_p0_frontend_pr_{a,b}.md` — historical fold reference, no longer needed.
- `plan_track_b_repeatability.md`, `review_track_b_repeatability_*` — Track B legacy.
- `plan_phase4_2_*.md`, `plan_phase4_3.md` — older phase plans.
- `apply_*.sh` — Phase 4-1 RT bring-up scripts (one-time, applied months ago).

## Session-end cleanup recommendation

Tonight's session left `PROGRESS.md` + `NEXT_SESSION.md` modified in the working tree on `feat/p4.5-track-e-map-management` (UNCOMMITTED — user declined adding more commits to PR-13 before the LAN check). Next session, after PR-13 merges to main:
- Switch to main, `git pull` (PR-13 lands).
- The two doc files will be UNCOMMITTED on main (carried across the branch switch). Stage + commit them on main as a single docs commit — `git add PROGRESS.md NEXT_SESSION.md`.
- ALSO write the `doc/history.md` Korean narrative entry for tonight's PR-13 delivery + tomorrow's merge as part of the same commit.
- Push to main.

NEXT_SESSION.md itself: refresh in place each session; never delete this file (drives every cold-start). Track-D / Track-E follow-ups / Phase 2 status updates each session.

## Phase 2 carry — localization (still deferred)

Today's PR-13 SPA visualisation (after merge) will continue to corroborate the sparse-feature diagnosis visually. No new data point this session.

Phase 2 levers unchanged — see PROGRESS.md 2026-04-28 + 2026-04-27 entries. Hardware blocker (LiDAR pivot-center mount) stays the gating item.
