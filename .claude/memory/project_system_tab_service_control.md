---
name: System tab — service control + process monitor
description: Operator (2026-04-29 24:00 KST close) requested System tab extensions: (a) make GODO Start/Stop/Restart buttons actually work, (b) add live process list / resource monitor (CPU + GPU). Goal: ops convenience for debug/test cycles + duplicate-process defense-in-depth.
type: project
---

## Operator's request (verbatim, paraphrased)

> 시스템 탭의 GODO 서비스들을 실제로 modify 가능하도록 구현. 디버깅/테스트할 때 프로세스 재실행이 편해서.
> 시스템 탭에 htop / ps -ef 같은 실행중인 프로세스 목록 + CPU/GPU 사용률 확인. 중복 실행 방지를 논리적으로 막더라도 모니터링하면 미연에 방지 가능.

## Current state (2026-04-29 close)

- **Backend endpoint exists**: PR #27 added admin-non-loopback `POST /api/system/service/{name}/{action}` for start/stop/restart.
- **It fails today**: `subprocess_failed` because (a) systemd unit files for `godo-tracker.service` / `godo-webctl.service` / `godo-irq-pin.service` don't exist on the host, (b) polkit policy not set up for `ncenter` to call privileged systemd actions.
- **System tab UI** shows the three services as "inactive" because `systemctl status` returns "unit not found".

## (1) Service control — implementation surface

**Status (2026-04-30 00:30 KST close)**: PR-A SHIPPED in repo. Awaiting
news-pi01 install + HIL verification.

Reality vs the original plan: items 1-3 (unit files) had ALREADY landed
in earlier PRs (`production/RPi5/systemd/` + `godo-webctl/systemd/`).
The actual scope was just the polkit half + installer wiring.

| Step | Status | Notes |
|---|---|---|
| 1. `godo-tracker.service` unit file | shipped pre-PR-A | committed `2026-04-26` per git. RuntimeDirectory=godo + User=ncenter + Ambient caps for SCHED_FIFO. |
| 2. `godo-webctl.service` unit file | shipped pre-PR-A | committed `2026-04-26`. After=godo-tracker.service. |
| 3. `godo-irq-pin.service` unit file | shipped pre-PR-A | committed `2026-04-26`. Type=oneshot. |
| 4. polkit `.rules` file | **PR-A shipped** | `production/RPi5/systemd/49-godo-systemctl.rules` — `ncenter` group, 3 units × 3 verbs (start/stop/restart). |
| 5. Install on news-pi01 | **awaiting operator** | `sudo bash production/RPi5/systemd/install.sh` (now 5 steps incl. polkit). Verification: `pkcheck --action-id org.freedesktop.systemd1.manage-units --process $$ --detail unit godo-tracker.service --detail verb start` AS ncenter → `OK`. |
| 6. Tests | shipped pre-PR-A | webctl integration tests `test_post_system_service_*` + `test_local_service_*` mock `services.control` so they were green; the HIL is the new gate. |

LOC actual: ~50 LOC effective (49-rule file + install.sh delta + README §7 + CODEBASE invariant (o)). Way under the original ~120 LOC estimate because the unit files were already there.

Cross-language SSOT: `services.py::ALLOWED_SERVICES × ALLOWED_ACTIONS`
must equal the (unit, verb) cross-product the polkit rule allows. See
`production/RPi5/CODEBASE.md` invariant **(o) godo-systemctl-polkit-discipline**.

## (2) Process monitor — implementation surface

Operator wants live "what's running right now" + CPU/GPU usage for ops awareness.

### Backend (webctl)

- New endpoint `GET /api/system/processes` → returns `[{name, pid, cmdline, cpu_pct, rss_mb, etime_s}]` for processes matching a GODO whitelist (`godo-tracker`, `godo-webctl`, `godo-irq-pin`, `godo_freed_passthrough`, `godo_smoke`, `godo_jitter`).
  - Implementation: parse `/proc/<pid>/stat` + `/proc/<pid>/cmdline` + `/proc/<pid>/status`. Stdlib only, no `psutil` dependency.
  - Refresh cadence: 1 Hz via SSE stream `GET /api/system/processes/stream`.
  - Pin **single-instance violation alert**: if more than one PID matches the same expected name, the response payload sets `duplicate_alert=true`. Frontend draws a red banner.
- New endpoint `GET /api/system/resources/extended` → returns `{cpu_per_core: [pct...], cpu_aggregate_pct, mem_total_mb, mem_used_mb, gpu_pct, gpu_temp_c, disk_pct}`.
  - CPU per-core: `/proc/stat` delta sample.
  - GPU on RPi 5: `/sys/devices/platform/soc/107c000000.v3d/...` or `vcgencmd measure_clock v3d` + `vcgencmd measure_temp` + `/sys/class/drm/...` activity. Verify the actual sysfs path on Trixie.
  - SSE stream sibling: `GET /api/system/resources/stream`.

### Frontend (SPA)

- New "Processes" sub-tab inside System: scrollable table; sortable by CPU; duplicate-alert banner.
- New "Extended resources" widget: per-core CPU bars (4 cores), GPU bar, mem ring, disk ring.

LOC estimate: ~300 LOC backend + ~250 LOC SPA. Medium PR. Keep restart-pending hidden — these are read-only views.

## Why duplicate-detection matters

CLAUDE.md §6 mandates per-process pidfile locking on every long-running module (`/run/godo/<service>.pid` + `flock`). That's the **logical** prevention. But pidfiles can leak (e.g., if a process is killed with SIGKILL the lock file stays — though `flock` advisory locks auto-release on FD close, leaving only the file content). And humans can launch a binary twice from different shells before the lock is acquired (race window).

The process monitor is the **observation** layer: if the operator opens System tab and sees two `godo-tracker` PIDs, they get an immediate red banner. Defense-in-depth.

## Sequencing

Combine both into one PR if scope manageable; otherwise:
- PR-A: service control (unit files + polkit + integration test). **Smaller, ships first.**
- PR-B: process monitor + extended resources (read-only views). Independent of PR-A's lifecycle.

Both fit "Phase 4-5 ops polish" theme — neither blocks B-MAPEDIT or annealing follow-ups.
