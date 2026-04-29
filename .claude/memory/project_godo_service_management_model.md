---
name: GODO service management model — SPA-controlled systemd services
description: Operator's intended ops model is "boot-time systemd auto-start + SPA System tab as the SOLE start/stop/restart UI". Direct script-launch via `scripts/run-pi5-*.sh` was a temporary workaround while the System tab was incomplete; it is NOT the long-term operational pattern.
type: project
---

## Operator's intent (verbatim, 2026-04-30 KST clarification)

> 라이브 환경에서는 클라이언트로 웹에 접속해서 사용하기 때문. 또한 테스트시에도 웹 환경에서 GODO 관련 프로세스들을 재시작/종료/시작 등이 가능해야 작업이 원할하기 때문이야. 그동안 script로 직접 한 것은 웹 서버가 구동이 안된 상태거나, 아직 system 탭에서 프로세스 현황이 제대로 보이지 않았기 때문이야.

## Auto-start policy (operator decision, 2026-04-30 KST)

- **Boot-time auto-start**: `godo-irq-pin.service` + `godo-webctl.service`.
  Reasons: irq-pin is a oneshot oneshot CPU 3 isolation prerequisite (no
  runtime risk); webctl is the operator's UI gateway and MUST be reachable
  before tracker can be started.
- **Manual-start only via SPA**: `godo-tracker.service`. Reasons: tracker
  is the heaviest RT process (mlocked memory, SCHED_FIFO 50, CPU 3
  pinned, opens RPLIDAR USB device). If a unit-file regression caused
  it to fail at boot, the system could enter a fail loop or block the
  SPA from coming up cleanly. Operator pushes the green Start button
  on the SPA System tab when they want the tracker live.
- **Implementation**: `systemctl enable --now` is run on `godo-irq-pin`
  and `godo-webctl` only. `godo-tracker.service` is `install`ed but
  NOT enabled — it is reachable by name (so polkit + SPA call can
  find it) but does not start at boot.

## Implication for design + sequencing

- **Production target**: every GODO service runs under systemd as the
  control plane. RPi 5 boot → `godo-irq-pin` (oneshot) → `godo-webctl`
  come up automatically; operator opens SPA → clicks Start to bring
  `godo-tracker` online. Operator never SSHs in to start anything in
  normal operation.
- **`scripts/run-pi5-*.sh` are DEV / DIAGNOSTIC tools.** They stay
  useful for `gdb`-attached runs, jitter benchmarks, smoke tests. They
  are NOT the operator's runtime path.
- **`/opt/godo-tracker/godo_tracker_rt` and `/opt/godo-webctl/` are
  the production paths** the systemd units invoke. The repo's
  `production/RPi5/build/` tree is the build cache, not the runtime
  binary.
- **The webctl admin endpoint `POST /api/system/service/{name}/{action}`
  + the operator-local sibling are first-class operator UI**, not
  optional. Their happy path REQUIRES the polkit rule (PR-A).
- **System tab process monitor + extended resources (PR-B, queued)**
  are the same need from a different angle: visibility of what's
  running so the operator does not need a terminal.

## How to apply

- When planning service-related work, default to "user opens browser →
  SPA → click button" as the operator path. Do not propose
  CLI-first workflows unless the user is in a debug context.
- Don't gate user-visible features on direct script execution. If the
  feature requires that the operator runs something on the host, that's
  a sign it's missing its SPA half.
- For testing/staging, the same systemd plumbing applies; the SPA
  service-control buttons are the primary loop.
