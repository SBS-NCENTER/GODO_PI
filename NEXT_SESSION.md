# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-29 second close (after studio install + first AMCL convergence smoke).
> P2 Step 1+2 + stability hardening + regex fix shipped. AMCL convergence on real studio map verified to FAIL as expected per Phase 2 hardware-gated. PR 2 (service observability) writer + B-MAPEDIT writer queued. **Next session starts in tmux** (agreed).

## TL;DR (priority order)

1. **★ Setup: tmux wrapper at session start** — agreed 2026-04-29. SSH disconnect cascades to background subagents (real loss vector observed). First step on session start: `tmux new -A -s godo && claude`. Optional auto-attach in ~/.bashrc snippet (already proposed in §"tmux setup" below; do NOT add without explicit confirmation).

2. **★ PR 2: service observability** — plan + Mode-A fold ready at `.claude/tmp/plan_service_observability.md`. Writer kickoff is the FIRST coding task. **NEW (2026-04-29 user req fold-in)**: extend scope with admin-callable restart action buttons on /system tab (currently /local loopback admin-only) — coordinated with Task #28 polkit rules. See task #19 description for fold notes. Baselines after this session's merges: backend 431 / frontend unit 111. Branch from main; ~580 LOC + 30-60 for action buttons.

3. **★ Phase 4.5 P2 Step 3: B-MAPEDIT** — plan + Mode-A fold ready at `.claude/tmp/plan_track_b_mapedit.md`. Decision LOCKED: I2 + brush + restart-required (no hot reload). Writer kickoff AFTER PR 2 merges. ~950 LOC; single PR.

4. **★ Privilege escalation audit** (Task #28) — webctl Shutdown/Reboot button + service-control still broken (`subprocess_failed` because `ncenter` can't call privileged ops). Polkit + `systemctl poweroff/reboot` + `systemctl restart godo-*` recommended. Coordinated with Task #32 systemd unit install + Task #19 PR 2 admin action buttons.

5. **★ tracker SIGTERM handler** (Task #33, NEW 2026-04-29) — verified gap in PR #25: SIGTERM kills tracker without triggering RAII PidFileLock dtor → pidfile + UDS socket linger on disk (functionally OK, cosmetic). Fix: install SIGTERM/SIGINT handler in main.cpp, mirror godo-webctl pattern. Audit other C++ RAII members.

6. **Session-end docs reconciliation** (Task #27) — cascade pass on FRONT_DESIGN.md + 2 CODEBASE.md after all P2 PRs land.

## Where we are (2026-04-29 second close)

**main = `6b26b4a`** — Phase 4.5 P2 Step 1 + Step 2 + stability hardening + regex fix + housekeeping all merged. **6 PRs merged this session**:

| PR | What | LOC |
|---|---|---|
| #21 | B-SYSTEM page (/system) — Phase 4.5 P2 Step 1 | +645 |
| #22 | agent color casing fix + fail-fast BLOCKED-report discipline | +103 |
| #23 | B-BACKUP page (/backup) — Phase 4.5 P2 Step 2 | +1641 |
| #24 | FRONT_DESIGN I-Q1 / §4.2 supersession (I2 + restart-required) | +27 |
| #25 | single-instance pidfile locks + UDS atomic bind + backup flock + CLAUDE.md §6 rule | +700 |
| #26 | MAPS_NAME_REGEX allow `.`, `(`, `)` (still reject leading `.`) | +100 |

**Open PRs**: 0.

## Studio install + AMCL smoke (2026-04-29)

User installed in studio + powered Pi back on. Workflow exercised:
1. webctl started via dev script (with `GODO_WEBCTL_PIDFILE=$HOME/.local/state/godo/godo-webctl.pid` inline export).
2. Two mapping passes via godo-mapping container — `04.29_1` (~103 KB), `04.29_2` (~90 KB). Stops via `docker stop godo-mapping` → SIGTERM trap saves PGM+YAML.
3. Pre-PR-#26 webctl regex rejected dot-named maps → renamed to `0429_1` / `0429_2` as workaround. After PR #26 merge + webctl restart, regex now allows dot/parens.
4. Active map = `0429_2` (set via webctl `/map` activate dialog, "재시작하지 않음" path).
5. godo-tracker started: `build/src/godo_tracker_rt/godo_tracker_rt --amcl-map-path /home/ncenter/projects/GODO/godo-mapping/maps/active.pgm` (UDS + pidfile under `/run/godo/` after one-time `sudo chown ncenter:ncenter /run/godo`).
6. webctl ↔ tracker handshake OK: `{"webctl":"ok","tracker":"ok","mode":"Idle"}`.
7. Login admin (ncenter/ncenter) → `POST /api/calibrate` → mode Idle → OneShot → Idle (1 s).

**AMCL result (expected fail)**:
```
pose:         x = -3.47 m, y = 1.65 m, yaw = 101.29°
xy_std:       6.16 m    ← particles essentially uniform across map
yaw_std:      169.86°   ← yaw essentially uniform circular
iterations:   25 / 25   ← max iters hit
converged:    0
forced:       1
```

Map area ~20 × 13 m → uniform-spread σ ≈ 5.8 m matches measured 6.16 m → particles failed to cluster. Aligned with Phase 2 hardware-gated state per CLAUDE.md / NEXT_SESSION:
- LiDAR not at pan-pivot center (20 cm offset).
- Mapping pass too short / no loop closure.
- AMCL Tier-2 params not tuned (tightened `amcl_sigma_seed_xy_m`, `amcl_sigma_hit_m` etc.).

**Side observation**: `cold_writer: yaw tripwire fired — pose.yaw=101.288 deg vs origin.yaw=0.000 deg (tripwire=5.000 deg)` log line. The tripwire compares AMCL yaw vs `amcl_origin_yaw_deg` (default 0°). For a fresh map where 0° is not the calibrated origin yaw, this tripwire is spurious. Worth a Tier-2 default review when Phase 2 lands.

## Maps inventory (godo-mapping/maps/)

| Name | Size | Active | Origin (m) | Provenance |
|---|---|---|---|---|
| `studio_v1` | 85 KB | no | (older session) | 2026-04-28 |
| `studio_v2` | 81 KB | no | (older session) | 2026-04-28 |
| `0429_1` | 103 KB | no | [-11.430, -5.623, 0] | 2026-04-29 first walk |
| `0429_2` | 90 KB | **yes** | [-10.379, -6.448, 0] | 2026-04-29 second walk |

After PR #26 merged, dot/paren names work too — for next mapping session, can use e.g. `04.29_3` directly.

## tmux setup (cold-start)

```bash
# At session start on news-pi01:
tmux new -A -s godo  # -A: attach if exists, else create
claude               # inside tmux

# Detach with Ctrl+B, D — tmux server keeps claude alive across SSH disconnect
# Reattach later with: tmux attach -t godo
```

Optional auto-attach `~/.bashrc` snippet (suggest, don't auto-add):
```bash
# Auto-attach to godo tmux session on interactive SSH login
if [[ -n "$SSH_CONNECTION" && -z "$TMUX" && $- == *i* ]]; then
    tmux new -A -s godo
fi
```

## Live system on news-pi01 (post-session)

- webctl: running (PID 386474/386478). `0.0.0.0:8080`. Pidfile `$HOME/.local/state/godo/godo-webctl.pid`. Log `/tmp/godo-webctl.log`. Started via `bash godo-webctl/scripts/run-pi5-webctl-dev.sh background`.
- godo-tracker: NOT running (gracefully stopped via SIGTERM at session close; manually cleaned `/run/godo/{ctl.sock,godo-tracker.pid}` due to PR #25 SIGTERM-handler gap, see Task #33).
- `/run/godo/`: exists, owned by ncenter (one-time `sudo chown` performed this session — survives only until reboot, since /run is tmpfs; will need redo on next boot OR Task #32 systemd installation handles via `RuntimeDirectory=godo`).
- `~/.bashrc` aliases: `godo-up`, `godo-down` (SIGTERM, updated this session), `godo-log`.
- Active map: `0429_2.pgm`.
- LAN-IP path (`192.168.3.22:8080`) blocked at SBS_XR_NEWS AP client-isolation — Tailscale `100.127.59.15:8080` is the working browser path.

**Working tree**: clean on main.

## PR 2 — service observability (NEXT in pipeline)

**Plan**: `.claude/tmp/plan_service_observability.md` — 580 LOC plan + Mode-A 6 majors + 7 should-fix + 5 nits + 6 test-bias all folded. Verdict: APPROVED for writer kickoff.

**Scope**:
- Backend: `GET /api/system/services` (anon, redacted env vars via 6-pattern allow-list, 1s TTL cache); `POST /api/local/service/<name>/start|restart` returns 409 `service_starting` + Korean detail when ActiveState=`activating`; same for `stop` during `deactivating`. Korean particle convention LOCKED in fold (한국어 발음 기준): tracker가 / webctl이 / irq-pin이 / local-window가.
- Frontend: B-SYSTEM 5번째 panel "GODO 서비스" — 4×1Hz cards via polling (NO SSE), uptime + memory + redacted env collapsible. ServiceCard.svelte 409 toast. `lib/serviceStatus.ts` chip-class SSOT.
- Webctl invariants `(v)` + `(w)` (NOT `(u)+(v)` — PR 1 took `(u)`).
- `FRONT_DESIGN.md §7.1` 7-column row format pinned.
- Branch: `feat/p4.5-service-observability`.

**Important fold-mandated**: Korean particles per Korean reading convention (트래커→가, 웹씨티엘→이). 7-column FRONT_DESIGN row format. 7-field dataclass + 7 systemd properties. NO 503 path (per-service `active_state="unknown"` on partial failure). R11 reasoning corrected (systemd idempotency, NOT invariant (e)).

## B-MAPEDIT — Phase 4.5 P2 Step 3 (after PR 2)

**Plan**: `.claude/tmp/plan_track_b_mapedit.md` — Mode-A fold pending; do that next session before writer kickoff.

**Scope**: brush mask painter + `POST /api/map/edit` (admin, multipart, atomic PGM rewrite via `map_edit.py` SOLE owner) + auto-backup-first + restart-required banner. Tracker C++ NOT touched. `MapMaskCanvas.svelte` + `routes/MapEdit.svelte` + new constants. Webctl invariant `(v)` (after PR 2's `(v)+(w)` lands → B-MAPEDIT becomes `(x)`; verify letter at writer time).

**Decision LOCKED**: I2 + restart-required, NO hot reload (FRONT_DESIGN.md §I-Q1 + §4.2 already supersession-annotated by PR #24).

**~950 LOC, single PR** — borderline against 1500 LOC ceiling, fine.

## Privilege escalation audit (Task #28)

**Bug observed**: web Shutdown Pi button → `subprocess_failed`. Root cause: `webctl`이 `ncenter` 사용자로 실행 + `subprocess.run(["shutdown", "-h", "+0"])` → 권한 거부.

**Recommended fix path** (polkit + systemctl):
1. `/etc/polkit-1/rules.d/50-godo-webctl.rules` allowing `ncenter` to use `org.freedesktop.login1.{power-off,reboot}`.
2. `services.py`'s `SHUTDOWN_*_ARGV` switches from `shutdown -h +0` to `systemctl poweroff` / `systemctl reboot`.
3. Same polkit pattern for `org.freedesktop.systemd1.manage-units` so service start/stop/restart works for the 3 (or 4) godo-* units.

**Install script automation**: bake the polkit + sudoers files into a bring-up step (somewhere under `production/RPi5/scripts/` or `godo-webctl/install.sh`). User: "파일과 OS 동작, 프로세스 관리 등 관련된 것들은 sudo 권한이 필요할 수 있겠다. 잘 확인해줘 다음 세션에" (2026-04-29).

**Workaround until then**: SSH-based shutdown (`ssh news-pi01 sudo shutdown -h now`).

## tmux setup (cold-start)

```bash
# At session start on news-pi01:
tmux new -s godo  # or: tmux attach -t godo
claude            # inside tmux

# Detach with Ctrl+B, D — tmux server keeps claude alive across SSH disconnect
# Reattach later with: tmux attach -t godo
```

Optional `~/.bashrc` snippet for auto-attach (suggest to user; do NOT add without confirmation):
```bash
# Auto-attach to godo tmux session on interactive SSH login
if [[ -n "$SSH_CONNECTION" && -z "$TMUX" && $- == *i* ]]; then
    tmux new -A -s godo
fi
```

## Session-end docs reconciliation (Task #27)

After all current P2 + observability + B-MAPEDIT PRs merge, do a single coherent reconciliation pass:

- **`FRONT_DESIGN.md`** — full rewrite of §C / §6.4 / §7.1 / §8 to match shipped state (B-MAPEDIT body update); verify all P0/P1/P2 rows are accurate. The §I-Q1 / §4.2 supersession blocks (PR #24) can be folded into the main text once B-MAPEDIT ships.
- **`godo-webctl/CODEBASE.md`** — invariant letter scheme normalization. Currently `(a)`–`(u)` are used + Track B-CONFIG's change-log subsection has `(n)`–`(q)` duplicates that PR 1 explicitly punted. Decide: rename the duplicates OR leave them (with explicit acknowledgment that the change-log subsection's lettering is local to that block).
- **`godo-frontend/CODEBASE.md`** — same audit. Confirm change-log entries chronological + invariants (a)-(t) consistent.

User explicit (2026-04-29): "front design 과 백엔드, 프론트엔드 각각의 CODEBASE.md 파일도 cascade하게 모두 수정 부탁".

## Live system on news-pi01

- webctl on `0.0.0.0:8080` (currently running manually as `ncenter`, `setsid` detached, log: `/tmp/godo-webctl.log`). PID changes per session — `pgrep -f godo_webctl` to find current.
- godo-tracker NOT running.
- maps_dir: `/home/ncenter/projects/GODO/godo-mapping/maps/` (overrides default `/var/lib/godo/maps/`).
- LAN-IP path (`192.168.3.22:8080`) blocked at SBS_XR_NEWS AP client-isolation — use Tailscale `100.127.59.15:8080` for browser access.
- **NEW** in PR #25: pidfile locks active. If you start a second webctl manually it WILL exit 1. Check `/run/godo/godo-webctl.pid` for held PID.

## Quick orientation files

1. **CLAUDE.md** §6 Golden Rules + §7 agent pipeline. **NEW**: §6 "Single-instance discipline" sub-bullet (PR #25).
2. **PROGRESS.md** — should be updated next session start with the 2026-04-29 entry.
3. **doc/history.md** — reverse chronological narrative; due an entry for 2026-04-29.
4. **FRONT_DESIGN.md** — §I-Q1 + §4.2 supersession (PR #24); rest awaiting B-MAPEDIT.
5. **godo-webctl/CODEBASE.md** invariants (a)–(u); changelog rich.
6. **godo-frontend/CODEBASE.md** invariants (a)–(s) + (v)+(w) (Track B-SYSTEM).
7. **production/RPi5/CODEBASE.md** invariants (a)–(l) (NEW (l) tracker-pidfile-discipline).

## Throwaway scratch (`.claude/tmp/`)

**Keep until B-MAPEDIT ships**:
- `plan_service_observability.md` — PR 2 plan + fold (writer input)
- `plan_track_b_mapedit.md` — B-MAPEDIT plan + fold (writer input after PR 2)
- `plan_single_instance_locks.md` — PR 1 plan + fold (reference, PR shipped)
- `plan_track_b_backup.md` — Step 2 plan + fold (reference, PR shipped)
- `plan_track_b_system.md` — Step 1 plan + fold (reference, PR shipped)

**Delete when convenient** (older session artefacts):
- Anything pre-2026-04-29 not in the above list.

## Tasks alive for next session

- #15 (pending) — B-MAPEDIT writer (queued behind PR 2)
- #19 (in_progress) — PR 2 service observability (writer kickoff is the first coding task)
- #26 (pending) — tmux wrapper setup (do at session start)
- #27 (pending) — session-end docs cascade reconciliation
- #28 (pending) — privilege escalation audit (PR after PR 2 + B-MAPEDIT, before Phase 5)

## Session-end cleanup

NEXT_SESSION.md itself: refresh in place each session; never delete (drives every cold-start).

PROGRESS.md + doc/history.md updates: TODO before session close.
