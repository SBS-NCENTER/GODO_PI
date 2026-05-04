---
name: issue#30 HIL 2026-05-05 — three findings, all resolved in PR #84 fold
description: Three findings from operator HIL on PR #84 (issue#30 pick-anchored YAML normalization), all root-caused and fixed 2026-05-05 KST in the same PR. (1) AFFINE rotation sign in map_transform.py — fixed via -theta_rad at call site. (2) rplidar_ros driver `M_PI - θ` extra 180° rotation — fixed via Dockerfile sed patch + commit pin. (3) recovery_sweep mis-classified pristine maps as kind=synthesized — fixed via DERIVED_NAME_REGEX guard + cleanup pass.
type: project
---

## Context

PR #84 (`feat/issue-30-yaml-normalization`) shipped backend math + frontend
UX + 3-tier review pipeline (Planner R1-R3, Mode-A R1-R3, Writer R1-R2,
Mode-B R1-R2 → APPROVE WITH MINOR). Operator deployed to news-pi01 and
discovered three issues during HIL on 2026-05-05 KST. Twenty-fourth
session (2026-05-05) root-caused all three and folded fixes into the
same PR.

## Finding 1 — issue#30 AFFINE rotation direction sign-flipped — RESOLVED

### Symptom

Operator typed a yaw delta on `test_v4` (pristine yaw=1.604 rad) using
the new pick-anchored Apply pipeline. Bitmap rotated **opposite to PR #81's
direction** for the same typed value.

### Root cause

`godo-webctl/src/godo_webctl/map_transform.py` had a sign mismatch
between the bbox sizing and the AFFINE transform direction:

- `_off_center_bbox` (line 425) rotated corners by `-theta_rad` →
  canvas sized for visual CW rotation.
- `_affine_matrix_for_pivot_rotation` (line 458) used `+theta_rad` →
  visual CCW rotation.

Pillow's `Image.transform(AFFINE)` uses output→input convention. The
helper builds the matrix from `R(+α)` coefficients, which when applied
output→input produces a visual `-α` rotation of the source. To honour
the Q2 lock (operator typed +θ → bitmap visually rotates CW by θ), the
helper must be called with `-theta_rad` so the visual rotation is `+θ` in
the matrix-α space, which corresponds to `-θ` visual = CW.

### Fix

`map_transform.py:333` — pass `-theta_rad` instead of `+theta_rad`:

```python
affine = _affine_matrix_for_pivot_rotation(i_p, j_p, x_min, y_min, -theta_rad)
```

The helper itself (`_affine_matrix_for_pivot_rotation`) is untouched, so
`test_affine_matrix_golden_4x4_theta45` (which calls the helper directly)
still passes.

### Test impact

- `test_affine_matrix_golden_4x4_theta45`: helper-level, untouched. ✓
- `test_pickpoint_lands_at_world_origin[*]`: pivot doesn't move under
  rotation around itself. ✓
- `test_typed_delta_shifts_picked_point_off_origin`: θ=0 path. ✓
- `test_apply_pipeline_pickpoint_lands_at_world_origin_via_http`: pivot
  invariant. ✓

## Finding 2 — `rplidar_ros` driver extra 180° rotation — RESOLVED

### Symptom (operator HIL)

Three fresh pristine maps (`05.05_v1/v2/v3`) created by physically
rotating the LIDAR 90° CCW between each. SPA showed map content
rotating in the **same direction** as the LIDAR (CCW), opposite of
slam_toolbox's "world frame = initial scan pose" convention which
predicts a CW rotation in the new world frame.

### Direct verification (`test_180check_left_obstacle`, 2026-05-05 KST)

Single-fan mapping with controlled physical setup:
- 1 m wall physically in front of LIDAR ▲ marker
- Additional obstacles physically to the LIDAR's left side

Result PGM (`/var/lib/godo/maps/test_180check_left_obstacle.pgm`):
- World span `x ∈ [-1.15, +10.25]` — +x had 10 m of free space; -x cut at 1.15 m (the actual physical wall).
- Operator confirmed: 1 m wall (physically +x_forward) appeared at PGM **−x_world**; left-side obstacles appeared at PGM **−y_world**.

Fingerprint: every beam endpoint at `(x, y) → (−x, −y)` = origin point-reflection. This is exactly what `ψ = π − θ` produces (= correct conversion `−θ` + extra 180° rotation around origin).

### Root cause

`Slamtec/rplidar_ros` upstream `src/rplidar_node.cpp:247-251`:
```cpp
scan_msg->angle_min =  M_PI - angle_max;
scan_msg->angle_max =  M_PI - angle_min;
```
The `M_PI -` adds a 180° offset on top of the correct CW→CCW conversion.
Per SLAMTEC datasheet `sources/SLAMTEC_rplidar_datasheet_C1_v1.2_en.pdf` page 11 (Figure 2-4): ▲ marker = +x = scanner forward, θ CW from +x, left-handed. Correct conversion to REP-103 is `ψ = -θ` (single negation).

### Fix

`godo-mapping/Dockerfile` patches the driver source before `colcon build`:
```dockerfile
&& git clone https://github.com/Slamtec/rplidar_ros.git \
&& cd rplidar_ros \
&& git checkout 24cc9b6dea97e045bda1408eaa867ce730fd3fc3 \
&& sed -i 's|M_PI - angle_max|-angle_max|g; s|M_PI - angle_min|-angle_min|g' \
   src/rplidar_node.cpp \
```

Same `git clone` + commit-pin + sed pattern as `rf2o_laser_odometry` (existing precedent in same Dockerfile). Container rebuild required (`docker build -t godo-mapping:dev .`, ~8 min).

### Live tracker unaffected

Live tracker uses vendored `rplidar_sdk` directly + `scan_ops.cpp:53` correct `-angle` negation. Only the docker mapping pipeline (which goes through ROS driver → /scan → slam_toolbox) was buggy.

See also `project_rplidar_cw_vs_ros_ccw.md` for full pipeline angle-convention SSOT.

## Finding 3 — `recovery_sweep` pristine misclassification — RESOLVED

### Symptom

After PR #84 deploy, all 3 fresh pristine maps + 4 older pristine maps got auto-generated bogus sidecars classified as `kind=synthesized, lineage.kind=synthesized, gen=-1`. Pristines should have NO sidecar (they are root nodes with no parent reference).

### Root cause

`godo-webctl/src/godo_webctl/sidecar.py:recovery_sweep` invoked `synthesize_for_orphan_pair` on every PGM+YAML pair without a sidecar. The synthesize helper's heuristic:
- Filename matches `<base>.YYYYMMDD-HHMMSS-<memo>` → `auto_migrated_pre_issue30`
- Else → `synthesized` ← caught pristine maps too

### Fix (two parts)

1. **Forward-fix**: `recovery_sweep` now skips orphan pairs whose stem doesn't match `DERIVED_NAME_REGEX`. Pristine maps fall through with no sidecar.
2. **Cleanup pass**: same function now unlinks any pre-existing sidecar attached to a pristine-named stem (idempotent). On first webctl restart after deploy, the 7 bogus sidecars (`0429_1`, `0429_2`, `04.29_v3`, `05.05_v1/v2/v3`, `studio_v1`) are auto-removed.

### Operator-visible impact (pre-fix)

- LineageModal showed misleading "synthesized (gen=-1)" for pristine root nodes.
- AMCL itself unaffected (doesn't read sidecars).
- Cascade chain becomes confusing if PICK is performed on a misclassified pristine.

## Working-tree state at fix completion (2026-05-05 KST)

- Branch `feat/issue-30-yaml-normalization` (PR #84) folded all 3 fixes:
  - `godo-webctl/src/godo_webctl/map_transform.py` — Finding 1 sign flip
  - `godo-mapping/Dockerfile` — Finding 2 driver patch + commit pin
  - `godo-webctl/src/godo_webctl/sidecar.py` — Finding 3 guard + cleanup
- Memory: this file + `project_rplidar_cw_vs_ros_ccw.md` updated.
- Backup of pre-fix HIL pristines: `/home/ncenter/maps_backup_2026-05-05_pre_issue30_debug/` (3 PGM + 3 YAML + 3 sidecar — bogus sidecars preserved as historical record).

## Operator HIL re-verification scenario (post-fix)

After deploy + container rebuild:
1. Same physical setup as `test_180check_left_obstacle` (1 m wall in front, left-side obstacles).
2. Short mapping (30 s, LIDAR static).
3. Verify in resulting PGM:
   - 1 m wall at LIDAR origin's **+x_world (right side)** — pixel col ≈ LIDAR_col + 40 (at 2.5 cm/cell).
   - Left-side obstacles at LIDAR origin's **+y_world (top)**.
4. Test issue#30 yaw rotation: pick a non-pristine map, type +30° yaw, Apply → bitmap visually rotates **CW** by 30°.
5. webctl restart logs should show 7 misclassified pristine sidecars unlinked + 0 new pristine sidecars created.

## Confidence

HIGH for all three findings. Each is independently verified by:
- Finding 1: bbox/affine sign mismatch + Q2 lock derivation match operator's mental model after fix.
- Finding 2: SLAMTEC datasheet + REP-103 derivation + visual HIL fingerprint (point-reflection) + world-span asymmetry all converge.
- Finding 3: pre-fix vs post-fix is a clean filename-pattern guard.
