---
name: Studio lens context
description: Broadcast studio uses wide-angle ENG zoom lenses; entrance pupil movement per zoom is significant and must be isolated from LiDAR errors in Phase 5 testing.
type: project
---

The chroma studio operates with wide-angle broadcast ENG zoom lenses (Canon HJ / Fujinon XA / UA class), which is the broadcast norm.

**Why:** Wide-angle zooms have notable entrance pupil ("nodal point" in industry usage) shift along the optical axis across the zoom range — typically several cm, up to ~10 cm. Any residual error in the lens file's zoom-dependent nodal offset LUT will show up at the screen edges because of the wide FOV, and will be indistinguishable from a LiDAR (dx, dy) error at the output stage.

**How to apply:**
- Our LiDAR correction layer (base x, y) is orthogonal to entrance pupil correction (lens file + zoom encoder LUT). They live at different stages of the XR pipeline.
- During Phase 5 integration testing, lock zoom and focus to a known value and verify with a single lens configuration first. This isolates LiDAR localization error from lens-file error.
- The 1–2 cm target in CLAUDE.md refers to base position accuracy. On-screen composite offset in UE will additionally depend on entrance pupil calibration and is not part of our system's error budget.
- If the user reports "calibration looks off" at integration, triage in this order: (1) zoom/focus locked? (2) lens file nodal offset correct? (3) LiDAR (dx, dy) suspect?
