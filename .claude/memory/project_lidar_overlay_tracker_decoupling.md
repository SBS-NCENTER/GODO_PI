---
name: LiDAR overlay should work without tracker
description: Operator wish (2026-04-29 18:11 KST) — `/map` LiDAR overlay should render even when godo-tracker is stopped. Currently scan SSE rides on the tracker process, so overlay = tracker dependency.
type: project
---

Operator stated 2026-04-29 18:11 KST during PR #29 HIL setup: "tracker를 켜는 것과 무관하게 라이다 오버레이도 됐으면 좋겠는데" — they'd like the SPA's `/map` LiDAR-scan overlay to render regardless of whether `godo-tracker` is running.

**Why:** Today the scan stream piggybacks on the same RT process that drives FreeD merge + AMCL, so a tracker-down state means no scan visibility at all. For map editing, calibration prep, or pure visualization, the operator wants a path where the LiDAR alone (Python prototype, lightweight C++ daemon, or webctl-side reader) feeds scans into the SSE — even if no pose / no AMCL / no FreeD merge is happening.

**How to apply:** Treat as a future ticket, not part of Track D / B-MAPEDIT. Two design hooks worth recording before it's lost:
- The RPLIDAR C1 SDK / rplidar_ros2 driver can run standalone — no need to spin up the full tracker hot path just to publish scans.
- Webctl's existing scan SSE (`/api/scan/stream`) currently consumes from the tracker UDS. A "scan source switch" in webctl could fall back to a direct serial / driver source when tracker is down.
- Scope decision pending: do we want overlay-without-pose (just raw scan dots in LiDAR-local frame, no map alignment), or overlay-with-stale-pose (last-known AMCL pose held while tracker is down)? The operator will need to clarify the use case before scoping.

NOT urgent — Track D + B-MAPEDIT come first. Park as a Phase 4-2 follow-up.
