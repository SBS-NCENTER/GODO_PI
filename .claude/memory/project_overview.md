---
name: GODO project overview (LiDAR camera tracking)
description: Snapshot of what this project is, the full system topology, and where current progress/design is tracked
type: project
originSessionId: 15c2bced-649b-4b8a-82b0-ececb12f3836
---

GODO = a studio camera tracker that uses an **RPLIDAR C1 to measure the SHOTOKU crane base's world (x, y)** and merges that as an offset into the FreeD packet stream.

**System topology (fixed 2026-04-21)**:

- A single Raspberry Pi 5 (8 GB, Debian 13 Trixie) hosts everything:
  - FreeD serial receive (absorbing the legacy Arduino R4 WiFi's role)
  - RPLIDAR C1 scan ingestion (official C++ SDK)
  - AMCL-based 2D localization against a pre-built map
  - 59.94 fps UDP send (`SCHED_FIFO` + CPU pinning + `mlockall`)
- The legacy Arduino firmware is kept as a **rollback card** — failure of the RPi 5 is recovered by swapping the cable.
- Map building is a one-time operation inside a Docker container (Ubuntu 24.04 + ROS 2 Jazzy + `slam_toolbox`).

**Algorithmic choices**:

- Yaw is resolved by 3-DOF LiDAR localization; the crane's internal encoder is not needed.
- Localization: O3 (pre-built map + AMCL) first, O4 (plus retro-reflector markers) as a later extension.
- FreeD Pan is base-local, but the wheels-parallel rule keeps dolly yaw constant, so we only add a (dx, dy) offset — Pan is left alone.

**Language strategy**:

- Phase 1~2: Python (UV) prototypes.
- Phase 3 onward: a single native C++ binary built with CMake, depending on Eigen, rplidar_sdk, and an in-house AMCL.

**Why**: moving the crane base invalidates the existing calibration, and the recalibration procedure is complex enough that the base is kept fixed in practice. RPLIDAR-based offset makes base moves a one-click operation. Target error: 1–2 cm.

**How to apply — new-session read order**:

1. `CLAUDE.md` — project guide.
2. `PROGRESS.md` — current state.
3. `SYSTEM_DESIGN.md` — end-to-end design (**core**).
4. `RPLIDAR/RPLIDAR_C1.md` — LiDAR hardware reference.
5. The rest of `.claude/memory/`.
