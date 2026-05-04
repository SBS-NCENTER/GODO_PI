---
name: grid.origin_yaw_deg is metadata-only — NOT consumed by AMCL likelihood
description: AMCL particle filter operates as if origin_yaw=0; YAML origin[2] is consumed only by apply_yaw_tripwire (informational diagnostic) and compute_offset (output-stage subtraction from pose.yaw to produce FreeD output dyaw). Discovered during PR #81 PICK#1/PICK#2 cascade analysis. Explains why Option B (bake-into-bitmap) is the only correct path for yaw correction.
type: project
---

A surprising structural property of the GODO tracker discovered
during issue#28 (B-MAPEDIT-3) HIL: the `grid.origin_yaw_deg` field
introduced as the YAML SSOT for AMCL frame yaw is consumed in only
TWO sites by the tracker, neither of which is the AMCL likelihood
field cell mapping.

**Sites that DO read `grid.origin_yaw_deg`:**

1. `production/RPi5/src/localization/cold_writer.cpp:374` →
   `apply_yaw_tripwire(result.pose, grid.origin_yaw_deg, yaw_tripwire)`
   — informational diagnostic. Fires a stderr log when the converged
   pose yaw drifts more than `yaw_tripwire` from the YAML origin yaw,
   suggesting "Studio base may have rotated." Does NOT influence pose
   estimation.
2. `production/RPi5/src/localization/cold_writer.cpp:389` (and 534,
   669) → `origin.yaw_deg = grid.origin_yaw_deg` then
   `result.offset = compute_offset(result.pose, origin)`. The
   `compute_offset` body at `amcl_result.cpp:39` is just
   `off.dyaw = canonical_360(current.yaw_deg - origin.yaw_deg)`.
   This is the OUTPUT offset sent to FreeD — purely a static
   subtraction at the output stage.

**Sites that do NOT read it:**

- `production/RPi5/src/localization/scan_ops.cpp::evaluate_scan` —
  the heart of AMCL likelihood evaluation. Lines 84-85:
  ```cpp
  const int cx = static_cast<int>((xw - field.origin_x_m) * inv_res);
  const int cy = static_cast<int>((yw - field.origin_y_m) * inv_res);
  ```
  Only `origin_x_m` and `origin_y_m` are used; `origin_yaw_deg` is
  IGNORED. World coords project to map cell coords as if
  origin_yaw were 0.
- All other particle math (`jitter_inplace`, `resample`,
  `gaussian_proposal`) — all operate purely in world frame; never
  reference origin yaw.

**Why this matters — implications for yaw correction (Option A vs B):**

When the operator wants to apply a yaw correction to "make the
picked direction become +x", two paths exist:

| Path | Bitmap | YAML yaw | AMCL pose result | Wall direction in world |
|---|---|---|---|---|
| **Option A** (metadata-only) | unchanged | `prev - typed` | unchanged (AMCL ignores yaw_deg in cell mapping) | unchanged |
| **Option B** (bake-into-bitmap) | rotated by `-typed` (CW visual) | unchanged (or 0) | shifts because likelihood field content moved | rotated by `+typed` |

Option A produces the wrong result: pose dyaw output to FreeD changes
(because `compute_offset` subtracts the new YAML yaw), but the AMCL
particle filter still finds the same physical pose because the
likelihood field is unchanged. Operator's intent ("make this direction
the new +x") never reaches the pose math.

Option B is the only path that actually moves the wall in the
operator's world frame: rotating the bitmap content shifts the
likelihood field, AMCL sees the new geometry, pose adjusts.

This is captured in PR #81's `app.py::_apply_map_edit_pipeline` by
passing `theta_deg=None` to `apply_origin_edit_in_memory` (so YAML
yaw stays at pristine value) and rotating the bitmap with
`-typed_yaw_deg` (HIL fix round 4 commit `87af3bc`).

**How to apply** — when designing future yaw-related features:

- If you need the operator's pose output to reflect a yaw change,
  rotate the bitmap (Option B), not the YAML metadata (Option A).
- If you only need to change the FreeD output dyaw (e.g., a
  pre-AMCL-fixed calibration offset), Option A suffices but the
  operator-visible AMCL pose will not move.
- The "1-shot calibrate" in §4 of CLAUDE.md (operator-triggered
  pose anchor) does NOT need this distinction — it directly seeds
  AMCL particles around a target pose.
- The "issue#30 YAML normalization" path (Option Q from PICK#1/PICK#2
  cascade) requires Option B's bitmap rotation PLUS bitmap translation
  PLUS canvas adjustment, because the operator's mental model (new
  YAML reads (0, 0, 0°)) means the picked point IS the new world (0, 0)
  by definition.

**Cross-link**: `project_map_edit_origin_rotation.md` (B-MAPEDIT-3
spec). `project_rplidar_cw_vs_ros_ccw.md` (separate angle convention
issue at the LIDAR scan input layer; this metadata-only finding is at
a different layer).

**File anchors** (verified 2026-05-04 KST):
- `production/RPi5/src/localization/cold_writer.cpp:374, 389, 520,
  534, 655, 669` (only 6 reads total — 3 tripwire calls + 3
  `origin.yaw_deg = grid.origin_yaw_deg` for `compute_offset`)
- `production/RPi5/src/localization/scan_ops.cpp::evaluate_scan:84-85`
  (no origin_yaw read)
- `production/RPi5/src/localization/amcl_result.cpp::compute_offset:39`
  (`off.dyaw = canonical_360(current.yaw_deg - origin.yaw_deg)`)
