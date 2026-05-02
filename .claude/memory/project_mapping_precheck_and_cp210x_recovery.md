---
name: Mapping pre-check gate + cp210x auto-recovery (issue#16 candidate)
description: Short-term mitigation for the CP2102N USB CDC stale-state race surfaced during issue#14 mapping pipeline HIL. Pre-check endpoint + Start gate + cp210x driver unbind/rebind + dockerd/containerd ProcessTable classification policy. Spec for the next PR after issue#14 close.
type: project
---

## What

Add a pre-mapping safety gate so the operator can't trigger Start while
the system isn't ready, and auto-recover the CP2102N USB CDC stale
state that issue#14 HIL surfaced (~10s wait between tracker stop and
mapping start was empirically required).

Three patches bundled into one PR (issue#16):

1. **Pre-check endpoint** (`GET /api/mapping/precheck`) — webctl checks
   readiness conditions; SPA polls 1Hz and gates the Start button.
2. **cp210x auto-recovery** — webctl detects the stale state and runs
   driver unbind/rebind via sysfs.
3. **ProcessTable classification refinement** — distinguish
   always-running daemons (dockerd, containerd) from container child
   processes; current N1 fix marks both as "godo-family", but daemons
   are always running regardless of mapping state.

## Why (decisions worth remembering)

### CP2102N stale state from issue#14 HIL (operator quote 2026-05-02)

- godo_tracker_rt cleanup is verified clean (`drv->stop()` + 200ms +
  `setMotorSpeed(0)` + close).
- Yet `dmesg: cp210x ttyUSB1: failed set request 0x12 status: -110`
  during mapping start.
- rplidar_node `code 80008004 (RESULT_OPERATION_TIMEOUT)`.
- Empirical workaround: `sleep 10` between tracker stop and mapping
  start.
- Hardware-software race at the USB CDC layer; not in our code, but
  we OWN the user experience.

### Operator decision (2026-05-02 KST)

> "지금 당장은 1단계로 하자. 2단계는 to-do issue로 잡아놓고 추후 내가
> 필요하면 말할테니 작업 가능하도록 하자."

- 1단계 = issue#16 (this entry) = single-PR webctl + frontend bundle.
- 2단계 = issue#17 (`project_gpio_uart_migration.md`) = hardware
  re-wire, on-demand only if cp210x stale state still hurts ops post
  issue#16.

### Pre-check checks (operator-discussed, 2026-05-02)

| Check | Method | Failure UX |
|---|---|---|
| LiDAR device readable | `os.open(/dev/<lidar>, O_RDWR\|O_EXCL)` then close | "LiDAR USB 정리 중… 5초 후 재시도" |
| godo-tracker fully stopped | `systemctl is-active` + UDS unreachable | "tracker 정지 중…" |
| Docker image present | `docker image inspect godo-mapping:dev` | "이미지 빌드 필요: cd godo-mapping && docker build -t godo-mapping:dev ." |
| /var/lib/godo/maps writable + ≥500MB free | `df` + `os.access(W_OK)` | "디스크 공간 부족" |
| Same map name not already on disk (or confirm overwrite) | client-side regex + `maps.list_pairs` | "이미 존재 — 다른 이름 또는 덮어쓰기 확인" |
| state.json clean (no stale Starting) | reconcile via `mapping.status` | auto-recover or force-acknowledge UI |

Endpoint shape:

```json
GET /api/mapping/precheck
{
  "ready": true,
  "checks": [
    {"name": "lidar_readable", "ok": true},
    {"name": "tracker_stopped", "ok": true},
    {"name": "image_present", "ok": true, "tag": "godo-mapping:dev"},
    {"name": "disk_space_mb", "ok": true, "value": 9500},
    {"name": "name_available", "ok": null}
  ]
}
```

SPA polls at 1Hz from Map > Mapping sub-tab. Start button disabled
unless all checks `ok=true` (name check `ok=null` means pending input).
Failed check renders red ✗ next to the check label.

### cp210x auto-recovery design

Two approaches, choose one:

- **Option A — driver unbind/rebind via sysfs** (recommended): when
  `lidar_readable` check fails AND state ≠ Idle in mid-recovery, webctl
  invokes:
  ```bash
  USBPATH=$(basename $(readlink /sys/class/tty/<port>/device | sed 's/\/tty.*//'))
  sudo bash -c "echo $USBPATH > /sys/bus/usb/drivers/cp210x/unbind && sleep 1 && echo $USBPATH > /sys/bus/usb/drivers/cp210x/bind"
  ```
  Requires polkit rule for the sysfs write (or `usbreset` setuid binary).

- **Option B — sleep + retry** (fallback): wait 10s between tracker stop
  and mapping start; surface "Cleaning up LiDAR USB…" in SPA.

**Operator default**: implement A as primary; B as fallback if sysfs
permission complications.

### ProcessTable classification refinement

Current N1 fix: `docker`, `dockerd`, `containerd`, `containerd-shim*`
ALL classify as "godo" → bold + accent in ProcessTable. Operator
post-HIL feedback: "mapping이 끝났는데도 dockerd, containerd가 계속
구동 중이네" — these are background daemons always running, not
mapping-specific.

Refinement options:
- (a) classify `dockerd` + `containerd` as "general" (not godo); only
  `docker run --name godo-mapping ...` parent + `containerd-shim*`
  children stay "godo" (active during mapping).
- (b) introduce new category "godo-daemon" (less prominent style than
  "godo") for dockerd/containerd; "godo" for active mapping processes.
- (c) keep current classification + add tooltip/legend explaining.

**Recommendation**: (a) — simplest, matches operator mental model.

## How to apply

When implementing issue#16:

1. Add `mapping.precheck()` to `mapping.py`:
   - Returns `PrecheckResult(ready: bool, checks: list[CheckRow])`.
   - Each check is a small async function (LiDAR open, tracker is_active,
     docker inspect, df, maps.list_pairs scan).
2. Wire `GET /api/mapping/precheck` in `app.py` — anonymous-readable.
3. Frontend: `precheckStore` (1Hz polling, mirror of mappingStatus
   pattern). MapMapping.svelte gates Start button via `precheck.ready
   && nameValid && state === 'idle'`.
4. cp210x recovery: extend `mapping.start()` Phase 2 — if first docker
   inspect fails with rplidar timeout signal, invoke unbind/rebind
   path before giving up. Polkit rule for `/sys/bus/usb/drivers/cp210x/{bind,unbind}`.
5. ProcessTable: `protocol.py` split `DOCKER_MAPPING_PROCESS_NAMES` into
   `DOCKER_DAEMON_NAMES = {"dockerd", "containerd"}` (general) +
   `DOCKER_CONTAINER_NAMES = {"docker"}` + prefix for `containerd-shim*`
   (godo). Update `classify_pid`.

### Test pins

- `tests/test_mapping_precheck.py` — each check, happy + failure, mocked subprocess.
- `tests/test_mapping_cp210x_recovery.py` — driver unbind/rebind invocation argv pin.
- `tests/test_processes.py` — `dockerd` / `containerd` classify as "general"; `docker` / `containerd-shim*` classify as "godo".
- `godo-frontend/tests/unit/precheckStore.test.ts` — polling cadence + Start gate behaviour.

## Cross-references

- `doc/RPLIDAR/RPi5_GPIO_UART_migration.md` — issue#17 long-term spec
  (this issue is the short-term path).
- `.claude/memory/project_gpio_uart_migration.md` — issue#17 decision
  context.
- `production/RPi5/CODEBASE.md` 2026-05-02 entry — issue#14 round 2
  context (Maj-1 timing ladder, Maj-2 flock narrowing, etc.).
- `godo-webctl/CODEBASE.md` 2026-05-02 entry — Settings augmenter
  pattern (Mode-B C1 fix); precheck endpoint should follow the same
  module conventions.
- `feedback_pipeline_short_circuit.md` — issue#16 is ≤200 LOC, can ship
  with planner-short-circuit (direct writer + Mode-B fast path).
