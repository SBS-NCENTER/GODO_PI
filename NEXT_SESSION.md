# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-28 close after AMCL first-real-test (mapping ✓, localization ✗ — algorithm work deferred per user).

## TL;DR

**Priority order (user-set 2026-04-28)**:

1. **★ Frontend full implementation** — code-planner already produced a plan; reviewer Mode-A approved with 2 majors + 9 nits. Two PRs (PR-A backend, PR-B SPA). Fold M1+M2 nits, then writer.
2. Localization integrity (Phase 2 algorithm work) — **deferred** until frontend ships.
3. PROGRESS / history / SYSTEM_DESIGN closeout for 2026-04-28 (small, can fold into the first frontend PR).

Track A/B/hotfixes all merged. Mapping toolchain verified end-to-end on real hardware. AMCL global localization confirmed non-convergent on hand-carried map + this studio geometry — a real Phase 2 problem, not a configuration issue.

## 이번 세션 진행 사항 (2026-04-28)

### A. PR cleanup — main에 3개 머지
1. **PR #7** (Track B) — rebase + delete-branch.
2. **PR #9** (FRONT_DESIGN.md, ~609 lines) — frontend planning SSOT. main에 올려서 planner agent의 reference로 사용.
3. **PR #10** (hotfix-c1-launch — C1 + slam_toolbox lifecycle + TF + saver ordering). 처음엔 옛 main 기반이라 rebase 필요. 머지 후 main = `b095765`.

### B. 프론트엔드 planner + reviewer Mode-A 진행
- **code-planner agent**: P0 페이지 셋 (DASH/MAP/AUTH/LOCAL) plan 생성 — 15 tasks / ~2,200 LOC / 2-PR split (PR-A backend ~900, PR-B SPA ~1300).
- **6 open questions** 중 3개 user 결정:
  - Q1 JWT secret → `/var/lib/godo/auth/jwt_secret` 자동생성 (32 B, 0600).
  - Q2 users.json (NOT sqlite) — 사용자 1-2명이라 단순 file + flock + atomic replace로 충분.
  - Q3 SSE auth → token-on-URL + access-log scrub (stream-ticket은 P1으로 defer).
- **code-reviewer Mode-A**: APPROVE-WITH-NITS. 0 critical, 2 major (M1 빠진 endpoint `/api/local/services/stream`, M2 webctl-internal 상수는 새 `webctl_constants.py`에 분리), 9 nits, 5 test-bias findings.
- writer는 다음 세션으로 미룸 (스튜디오에서 hardware 작업 우선시).

### C. 첫 실 매핑 — hardware 검증 완료
| 맵 | 크기 | 시간 | 결과 |
|---|---|---|---|
| `studio_v1.pgm` | 249×343 (12.45 m × 17.15 m) | ~72 s walk | ✅ 저장 |
| `studio_v2.pgm` | 250×323 (12.5 m × 16.15 m) | ~107 s walk + loop closure | ✅ 저장 |

YAML 키 `{image, mode, resolution, origin, negate, occupied_thresh, free_thresh}` — F11 SSOT audit PASS. **부조정실에서 재현됐던 5번째 issue (55 s walk → map_saver fail)는 이번 환경에선 재현 X** — 이전 carry close.

### D. AMCL 첫 실 테스트 — 빌드 OK, 수렴 X
build.sh 처음 실행 → 29 hardware-free tests PASS. PTY socat fake로 FreeD 우회, `--amcl-map-path`로 새 맵 load, UDS UNIX socket으로 commands.

| 시도 | particles | iters | xy_std | yaw_std | converged |
|---|---|---|---|---|---|
| 1st | 5,000 | 25 | 5.93 m | 183° | no |
| 2nd | 5,000 | 25 | 5.87 m | 161° | no |
| 3rd | 10,000 | 200 | 5.90 m | 190° | no |

16× compute로도 동일 결과 → fundamental limit. yaw가 매번 wildly 다른 값(278° / 88° / 335°) → **방의 회전 대칭성 또는 매핑 drift**가 주된 원인 의심. user 결정: 알고리즘 보강 필요 (Phase 2). 자세한 lever 후보는 §"Phase 2 carry" 참조.

### E. 메모리 + 문서 갱신
- `.claude/memory/feedback_emoji_allowed.md` — chat 이모지 허용.
- `.claude/memory/project_studio_geometry.md` — TS5 T자형 비대칭 + step corners + 문 위치 (Phase 2 landmark).
- 본 NEXT_SESSION.md — 우선순위 reorder + Phase 2 carry.

## Where we are

**main = `b095765`** (after PR #6 Track A + PR #7 Track B + PR #8 set-u hotfix + PR #9 FRONT_DESIGN + PR #10 C1 hotfix all merged).

**Open / pending state**:
- **Plan + review on disk**: `.claude/tmp/plan_p0_frontend.md` + `.claude/tmp/review_mode_a_p0_frontend.md`. Both committed-style ready; not in git.
- **Local maps**: `godo-mapping/maps/studio_v1.{pgm,yaml}` (12 s stationary), `studio_v2.{pgm,yaml}` (107 s walk). Both root-owned (Docker artifact); chown to ncenter is optional.
- **Untracked**: `NEXT_SESSION.md` (this file).
- **Local C++ build artifacts**: `production/RPi5/build/` populated; binary built but not setcap'd. Not committed (gitignored).
- **systemd**: `godo-tracker.service`, `godo-webctl.service`, `godo-irq-pin.service` are NONE-installed on news-pi01. Earlier NEXT_SESSION.md said webctl was installed; that was stale.

## Frontend track — start here

### Step 1: Fold reviewer M1 + M2 into the plan (~5 min)

`.claude/tmp/review_mode_a_p0_frontend.md` flagged:

- **M1**: Plan misses `GET /api/local/services/stream` (P0 SSE per FRONT_DESIGN §7.2). Endpoint count 13 → 14.
- **M2**: webctl-internal Tier-1 constants (JWT_TTL, SSE_TICK, etc.) belong in a NEW `webctl_constants.py` module, NOT in `protocol.py`. `protocol.py`'s docstring (lines 4-13) reserves it for C++ wire SSOT mirrors. Decide before writer starts.

Also 5 test-bias nits worth folding (argv list-literal asserts, virtual-clock for SSE cadence, atomic-write failure modes, real-FastAPI contract test, see review file §"Test bias-blocking findings").

Edit the plan in place (`.claude/tmp/plan_p0_frontend.md`), then proceed to writer.

### Step 2: Run code-writer for PR-A (backend foundations + systemd)

```text
Tasks: P4.5-FE-1 … P4.5-FE-6 + P4.5-FE-14 (~900 LOC + ~50 tests)
Scope:
  - Auth module (auth.py): bcrypt + JWT (HS256, 6h TTL) + users.json + Depends(require_user/admin)
  - Loopback-only middleware (local_only.py)
  - Activity log (activity.py, deque size 50)
  - SSE last_pose_stream (sse.py @ 5 Hz, 15 s keepalive) + services_stream (per M1)
  - Map image PGM→PNG (map_image.py, 5-min LRU)
  - Services + system reboot/shutdown wrappers (services.py)
  - SPA static mount swap in app.py (legacy fallback retained per Q-OQ-6)
  - godo-local-window.service Chromium kiosk unit
Out of scope for PR-A:
  - Frontend SPA (PR-B)
  - tracker C++ changes (P1 timing)
  - prototype/ scaffold relocation (separate PR)
User decisions baked in:
  - JWT secret: /var/lib/godo/auth/jwt_secret, 32 bytes, 0600, lazy-generated
  - users.json (NOT sqlite) — flock + atomic replace, P0 has ~1-2 users
  - SSE auth: token-on-URL with access-log scrub
```

After PR-A: reviewer Mode-B → fold → push → merge → soak briefly.

### Step 3: Run code-writer for PR-B (SPA + docs)

```text
Tasks: P4.5-FE-7 … P4.5-FE-13 + P4.5-FE-15 (~1300 LOC + ~25 tests)
Depends on PR-A merged.
Scope: Vite + Svelte SPA, 4 P0 pages (DASH/MAP/AUTH/LOCAL), stores, lib/api/sse/auth, Confluence-style theme.
Mode-A may skip (design surface fully captured by FRONT_DESIGN + plan); Mode-B required (UI/role-gating bias risk).
```

### Step 4: 2026-04-28 docs closeout

Fold into PR-A or a separate small docs commit:
- **PROGRESS.md** — append "2026-04-28 (mapping verified + frontend planning)" block. Cover: Track B merge + FRONT_DESIGN merge + C1 hotfix merge + mapping smoke (studio_v1 12 s, studio_v2 107 s) + first AMCL real test result (xy_std 5.9 m, did not converge with 10000×200) + frontend planner+reviewer output on disk.
- **doc/history.md** — Korean narrative entry, "왜/무엇을 결정했는가" centric. Mention user's frontend-first priority and AMCL improvement deferral.
- **SYSTEM_DESIGN.md §7** — add "Track A C1 + lifecycle hotfix LANDED 2026-04-28" + flag Phase 2 AMCL improvements as the next localization milestone (with link back to the studio geometry memory).

## Phase 2 carry — localization (deferred)

Today's data points (real LiDAR on real map, news-pi01, 2026-04-28):

| Run | particles | iters | xy_std | yaw_std | converged |
|---|---|---|---|---|---|
| 1st | 5000 | 25 | 5.93 m | 183° | no |
| 2nd | 5000 | 25 | 5.87 m | 161° | no |
| 3rd | 10000 | 200 | 5.90 m | 190° | no |

Conclusion: 16× compute did not move the needle. Global AMCL on this map + this geometry has fundamental limits.

**Phase 2 levers to explore (next-next session)**:
- ICP-based initial pose seed: first LiDAR scan → match against distinctive map regions (T-step corners + doors) → AMCL only does local refinement around that prior. Drops the 25 vs 200 iter question entirely.
- Or: forced narrow seed mode (`amcl_origin_*` trusted + `amcl_sigma_seed_xy_m` shrunk to ~30 cm).
- Or: retro-reflector landmarks at the step corners during mapping → unambiguous reference points.
- Map quality lever (orthogonal): enforce loop closure during slam_toolbox, slower walk, multiple passes.

**Hardware carry**:
- LiDAR currently 20 cm offset from pan pivot (temp installation). Restore pivot-center mount before next localization attempt — see `.claude/memory/project_studio_geometry.md`.

## State of the dev host (news-pi01, 2026-04-28 close)

- LiDAR connected `/dev/ttyUSB0`, dialout group OK.
- Docker: `godo-mapping:dev` image current.
- C++ tracker: built at `production/RPi5/build/src/godo_tracker_rt/godo_tracker_rt`. NOT setcap'd. Capabilities script: `production/RPi5/scripts/setup-pi5-rt.sh` (sudo). Not needed for hardware-free dev work.
- maps/: `studio_v1.{pgm,yaml}`, `studio_v2.{pgm,yaml}` (root-owned).
- systemd: nothing GODO-related installed.
- Phase 4-1 RT setup applied at boot (`isolcpus=3 nohz_full=3 rcu_nocbs=3`).

## Quick orientation files

1. **CLAUDE.md** §6 Golden Rules.
2. **PROGRESS.md** — last entry "2026-04-27 (Track B closeout)". 2026-04-28 not yet folded (see Step 4).
3. **FRONT_DESIGN.md** ★ — frontend SSOT, the writer must respect §7 living API table.
4. **`.claude/tmp/plan_p0_frontend.md`** ★ — implementation plan.
5. **`.claude/tmp/review_mode_a_p0_frontend.md`** ★ — reviewer findings to fold.
6. **`.claude/memory/MEMORY.md`** — index. Now includes studio geometry entry.
7. **godo-webctl/CODEBASE.md** — current backend invariants (a)–(h); plan adds (i)–(m).
8. **production/RPi5/CODEBASE.md** — tracker invariants.

## Throwaway scratch (`.claude/tmp/`)

- `plan_track_b_repeatability.md`, `review_track_b_repeatability_{v1,v2}.md` — Track B legacy. Safe to delete.
- `plan_phase4_2_b.md`, `plan_phase4_2_d.md`, `plan_phase4_3.md` — older. Safe to delete (PROGRESS.md is the durable record).
- `apply_*.sh` — Phase 4-1 RT bring-up scripts. Safe to delete (one-time use, applied months ago).
- `plan_p0_frontend.md` + `review_mode_a_p0_frontend.md` — **KEEP**, referenced by next session.

## Session-end cleanup recommendation

Commit + push at end of this NEXT_SESSION.md update:
- `NEXT_SESSION.md` (this file)
- `.claude/memory/project_studio_geometry.md` (new)
- `.claude/memory/MEMORY.md` (index updated)

Optional: also commit `.claude/tmp/plan_p0_frontend.md` + `.claude/tmp/review_mode_a_p0_frontend.md` so they survive cross-machine session resume. They're under `.claude/tmp/` which may or may not be gitignored — verify before committing.

NEXT_SESSION.md itself: delete after the next session's Step 1 (M1+M2 fold) completes.
