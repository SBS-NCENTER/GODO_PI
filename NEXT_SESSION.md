# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-28 close. Phase 4.5 P0 frontend operator surface fully in flight.

## TL;DR

**Priority order (user-set 2026-04-28 evening)**:

1. **★ PR-B merge** — user LAN-checks `feat/p4.5-frontend-pr-b-spa` at office tomorrow → `gh pr merge 12 --rebase` (or via UI).
2. **★ Track E (Multi-map management) — Mode-A fold + writer + Mode-B + push**. Plan + reviewer findings on disk; pipeline picks up at "fold Mode-A findings into plan".
3. Track D (Live LIDAR overlay) — single-PR, designed in FRONT_DESIGN §8, picks up after Track E merges.
4. Phase 2 (AMCL convergence) — deferred until LiDAR remount at pan-pivot center; today's user-visible map confirms the sparse-feature root cause from yesterday's failed test.

## Where we are (2026-04-28 close)

**main = `097d4a7`** — PR-A merged (P4.5 backend foundations: 14 endpoints + 2 SSE + JWT + systemd + tests).

**Open**:
- **PR-B** at `feat/p4.5-frontend-pr-b-spa` ahead of main by 8 commits — https://github.com/SBS-NCENTER/GODO_PI/pull/12. Vite+Svelte SPA + Mode-B fold + Track F (anon read; login-gated mutations) all bundled. 21 KB gzipped, 29/29 vitest unit + 11/11 playwright e2e + 174 backend pytest pass, ruff/eslint/prettier clean. User has eyeballed it on Tailscale + LAN-pending.
- **Track E branch** `feat/p4.5-track-e-map-management` at `ff60f9e` (off PR-B). Has nothing committed yet beyond the PR-B base; `.claude/tmp/plan_track_e_map_management.md` (~620 lines) is the working plan.

**Local artifacts (not in git)**:
- `.claude/tmp/plan_track_e_map_management.md` — Track E plan, **adjusted post-Track F** (read endpoints anon, mutations admin).
- `.claude/tmp/review_mode_a_track_e.md` — Mode-A review file from the running reviewer agent (or stub if it didn't finish — check before resuming).
- Earlier `.claude/tmp/plan_p0_frontend.md` + `.claude/tmp/review_mode_b_p0_frontend_pr_{a,b}.md` — historical, fine to keep for fold-history reference.

**Live system on news-pi01**:
- webctl on `0.0.0.0:8080` (`setsid` detached), serving `studio_v2.pgm` (250×323 px), JWT/users under `~/.local/state/godo/auth/`. Not under systemd; PID is whatever was running at session close.
- godo-tracker NOT running (deliberate — `banner` showing in SPA is the documented expected state).
- No PROGRESS.md / NEXT_SESSION.md / `.claude/memory/` files committed during this session except the FRONT_DESIGN updates that landed on PR-B branch.

## Frontend track — start here

### Step 1: Verify PR-B in LAN browser, then merge

The user already confirmed the SPA UX over Tailscale (UI / theme toggle / login form / map underlay / tracker-unreachable banner). LAN check tomorrow validates the HTTPS-warning theory (Chrome HTTPS-First mode auto-upgrade rather than any real cert issue) — open `http://192.168.3.22:8080/` in Chrome on a LAN PC, expect plain HTTP without interstitial.

If that's clean: `gh pr merge 12 --rebase` (or via UI). main advances; cleanup `feat/p4.5-frontend-pr-b-spa`.

### Step 2: Resume Track E

```text
Branch: feat/p4.5-track-e-map-management (rebase onto new main after PR-B merge)
Plan:   .claude/tmp/plan_track_e_map_management.md  (Track F-aligned)
Review: .claude/tmp/review_mode_a_track_e.md         (CHECK STATE FIRST)
```

The Mode-A reviewer was launched as a background agent at session close; it may have completed or been killed when the session ended. **First action**: read `.claude/tmp/review_mode_a_track_e.md` to see if findings landed. If the file is missing or empty, re-launch the Mode-A reviewer with the same brief.

Then:
1. **Fold Mode-A findings** inline into `plan_track_e_map_management.md` (top of file, structured "Mode-A fold (2026-04-29)" block — same convention as the prior PR-A/PR-B plans).
2. **Run `code-writer` agent** with the folded plan. Branch is `feat/p4.5-track-e-map-management`; rebase onto current main FIRST.
3. **Run `code-reviewer` Mode-B** on the implementation.
4. **Fold Mode-B findings**, run `cd godo-webctl && uv run pytest && uv run ruff check src tests` + `cd godo-frontend && npm run lint && npm run test:unit && npm run build` → all green.
5. `git push -u origin feat/p4.5-track-e-map-management` + `gh pr create` → PR-C.

### Step 3: Track D (Live LIDAR overlay)

Plan in FRONT_DESIGN §8. Pick up after Track E merges. Spans:
- godo-tracker C++: `get_last_scan` UDS handler (seqlock read, μs-level, hot-path 0 impact)
- webctl: `/api/last_scan` GET + `/api/last_scan/stream` SSE @ 5 Hz
- SPA: `PoseCanvas` 3rd layer + `Map.svelte` toggle button
- ~350 LOC + tests

This requires C++ tracker changes — first cross-language SSOT-touching PR since Track B. Run full pipeline (planner → Mode-A → fold → writer → Mode-B → fold → PR-D).

### Step 4: Phase 2 (AMCL convergence)

Stays deferred. Pre-requisites for re-attempting:
- LiDAR mounted at pan-pivot center (currently 20 cm offset — temp install).
- Mapping pass with explicit loop closure + slow walk + retro-reflector landmarks at the step corners (per `.claude/memory/project_studio_geometry.md`).
- Then evaluate: (a) ICP-based initial pose seed, (b) tightened `amcl_sigma_seed_xy_m` ~30 cm, (c) AMCL configuration tuning per the new feature density.

Today's PR-B SPA visualisation confirmed the sparse-feature diagnosis visually (user: "v2도 얼추 비슷한 직선만"). Phase 2 work is not blocked on more code today; it's blocked on hardware reseat + a higher-quality mapping pass.

## State of the dev host (news-pi01, 2026-04-28 close)

- LiDAR `/dev/ttyUSB0` connected, dialout group OK.
- Docker: `godo-mapping:dev` image current (used today for the v2 pass).
- C++ tracker: built at `production/RPi5/build/src/godo_tracker_rt/godo_tracker_rt`. Setcap NOT applied this session. Stop/start workflow per `production/RPi5/scripts/setup-pi5-rt.sh`.
- maps/: `studio_v{1,2}.{pgm,yaml}` (root-owned 644 — webctl runs as `ncenter` and reads via the open mode bits, no chown needed).
- systemd: nothing GODO-related installed.
- webctl runs in foreground via `setsid` from this session — `pgrep -f "python.* -m godo_webctl"` to find the PID. `kill -9 <pid>` to clean before restarting (the cmdline contains `GODO_WEBCTL_*` env vars, so `pkill -f godo_webctl` kills the launcher too).

## Quick orientation files

1. **CLAUDE.md** §6 Golden Rules + §7 agent pipeline.
2. **PROGRESS.md** — last entry "2026-04-28 (Phase 4.5 P0 frontend …)" — full session record.
3. **doc/history.md** — last entry 2026-04-28 — Korean narrative, "왜 / 무엇을 결정했는가" centric.
4. **FRONT_DESIGN.md** ★ — frontend SSOT. §7 living API/SSE table, §8 phase plan + Track D + Track E.
5. **`.claude/tmp/plan_track_e_map_management.md`** ★ — implementation plan (Track F-aligned).
6. **`.claude/tmp/review_mode_a_track_e.md`** ★ — Mode-A review (CHECK STATE).
7. **godo-webctl/CODEBASE.md** — invariants (a)–(n). (n) is the Track F auth model.
8. **godo-frontend/CODEBASE.md** — SPA invariants + N8/N9 dispositions.

## Throwaway scratch (`.claude/tmp/`)

Keep:
- `plan_track_e_map_management.md` — referenced by next session.
- `review_mode_a_track_e.md` — referenced by next session.
- `plan_p0_frontend.md` + `review_mode_a_p0_frontend.md` + `review_mode_b_p0_frontend_pr_{a,b}.md` — historical fold reference; safe to delete after Track E merges if size becomes a concern.

Delete when convenient:
- `plan_track_b_repeatability.md`, `review_track_b_repeatability_*` — Track B legacy.
- `plan_phase4_2_*.md`, `plan_phase4_3.md` — older phase plans.
- `apply_*.sh` — Phase 4-1 RT bring-up scripts (one-time, applied months ago).

## Session-end cleanup recommendation

Commit + push at end of next session:
- `PROGRESS.md` (this session log entry — already in working tree at session close)
- `doc/history.md` (Korean narrative entry — already in working tree)
- `NEXT_SESSION.md` (this file — refreshed each time)

**Where**: these go on PR-B branch (currently checked out) as a single docs commit BEFORE merge, OR on main directly after PR-B merges. Either is fine; the user's call. The diff is doc-only.

NEXT_SESSION.md itself: refresh in place each session; never delete this file (drives every cold-start). Track-D / Track-E status updates each session.

## Phase 2 carry — localization (still deferred)

Today's data point (visually confirmed via PR-B SPA on `studio_v2.pgm`):
- v2 map shows mostly straight wall lines; sparse fine features.
- Yesterday's AMCL test result (xy_std 5.9 m, 10 000 particles × 200 iter no convergence) is now visually corroborated.
- Diagnosis is the geometry + map-quality combo, not a configuration issue.

Phase 2 levers unchanged — see PROGRESS.md 2026-04-28 + 2026-04-27 entries. Hardware blocker (LiDAR pivot-center mount) stays the gating item.
