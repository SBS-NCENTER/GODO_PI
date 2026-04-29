# Next session — cold-start brief

> Throwaway. Delete the moment the next session picks up the thread.
> Refreshed 2026-04-29 close. P2 Step 1+2 shipped + stability hardening shipped. PR 2 (service observability) writer + B-MAPEDIT writer queued. User in studio install — Pi may be off when session starts.

## TL;DR (priority order)

1. **★ Setup: tmux wrapper for claude** — agreed 2026-04-29. SSH disconnect kills parent + cascades to background subagents (real loss vector observed). Wrap claude in tmux at session start so SSH can drop without losing in-flight pipeline. Consider `~/.bashrc` snippet for auto-attach to `godo` session.

2. **★ PR 2: service observability** — plan + Mode-A fold ready at `.claude/tmp/plan_service_observability.md`. Writer kickoff is the FIRST coding task. 408 backend / 117 frontend unit baselines (after merges). Branch from main; ~580 LOC.

3. **★ Phase 4.5 P2 Step 3: B-MAPEDIT** — plan + Mode-A fold ready at `.claude/tmp/plan_track_b_mapedit.md`. Decision LOCKED: I2 + brush + restart-required (no hot reload). Writer kickoff AFTER PR 2 merges. ~950 LOC; single PR.

4. **★ Privilege escalation audit** (Task #28) — webctl Shutdown/Reboot button currently broken (`subprocess_failed` because `ncenter` can't call `shutdown` directly). Polkit + `systemctl poweroff` route recommended; full audit covers shutdown/reboot/service-control/journalctl. Install script automation also needed so bring-up doesn't drift.

5. **Session-end docs reconciliation** (Task #27) — cascade pass on FRONT_DESIGN.md + 2 CODEBASE.md after all P2 PRs land.

## Where we are (2026-04-29 close)

**main = `70a51de`** — Phase 4.5 P2 Step 1 + Step 2 + stability hardening + housekeeping all merged. **5 PRs merged this session**:

| PR | What | LOC |
|---|---|---|
| #21 | B-SYSTEM page (/system) — Phase 4.5 P2 Step 1 | +645 |
| #22 | agent color casing fix + fail-fast BLOCKED-report discipline | +103 |
| #23 | B-BACKUP page (/backup) — Phase 4.5 P2 Step 2 | +1641 |
| #24 | FRONT_DESIGN I-Q1 / §4.2 supersession (I2 + restart-required) | +27 |
| #25 | single-instance pidfile locks (godo-webctl + godo-tracker) + UDS atomic bind + backup flock + CLAUDE.md §6 rule | +700 |

**Open PRs**: 0.

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
