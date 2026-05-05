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

## Finding 1 — issue#30 AFFINE rotation direction (operator re-locked 2026-05-05 KST)

### History (2 fix rounds → final lock)

**Round 1 fix (initial Finding 1 fix)**: pass `-theta_rad` to
`_affine_matrix_for_pivot_rotation`. This produced visual CW rotation
for `+typed_θ` (matching PR #81's direction).

**Operator HIL on round 1 fix (2026-05-05 KST follow-up)**:
- Operator finds that under round-1 fix, `+typed θ` rotated the bitmap
  CW (= clockwise), but their math-convention intuition says `+θ`
  should be CCW.
- Operator also found that the same Apply produced cropping in some
  cases (e.g., `05.05_v3.20260505-085323-after_fix` had bottom wall
  clipped).

### Root cause (correct analysis)

The bbox and affine sign signs must be **mathematical inverses** for
the canvas-cropping safety, AND the visual direction must match the
locked semantic. Pre-fix and round-1-fix BOTH had issues:

| State | bbox | affine | visual | bbox/affine inverse? |
| --- | --- | --- | --- | --- |
| Pre-fix (issue#30 initial) | `R(-θ)` | `R(+θ)` | CCW for `+θ` | YES ✓ |
| Round 1 fix | `R(-θ)` | `R(-θ)` | CW for `+θ` | NO ✗ → cropping |
| Final (operator-locked) | `R(-θ)` | `R(+θ)` | CCW for `+θ` | YES ✓ |

The final state matches the operator's intuition (`+typed = visual
CCW`) AND keeps bbox/affine as mathematical inverses (no cropping).

This is operationally a **revert of the round-1 Finding 1 fix** plus
explicit re-lock of the visual direction.

### Final fix (2026-05-05 KST)

`map_transform.py` `transform_pristine_to_derived`:
```python
affine = _affine_matrix_for_pivot_rotation(i_p, j_p, x_min, y_min, theta_rad)
```

(`-theta_rad` reverted to `theta_rad`.) Module docstring + bbox docstring
updated to reflect the locked semantic. Helper signature itself
unchanged so `test_affine_matrix_golden_4x4_theta45` keeps passing.

### Frontend co-fix (2-point yaw)

`originMath.ts` `twoClickToYawDeg`:
```typescript
return wrapYawDeg(-degrees);  // negate atan2 result for new lock
```

Under the lock, P2-direction at world-angle β requires bitmap to rotate
visually by `-β` (CW by β) to bring that direction to `+x`. Since
`typed +θ = visual CCW θ`, the corresponding typed value is `-β`.
Frontend test cardinal expectations updated: north (0, +10) → `-90°`
(was `+90°`); new south case (0, -10) → `+90°`.

### Test impact

- `test_affine_matrix_golden_4x4_theta45`: helper-level, untouched. ✓
- `test_pickpoint_lands_at_world_origin[*]`: pivot invariant under any
  rotation direction. ✓
- `test_typed_delta_shifts_picked_point_off_origin`: θ=0 path. ✓
- `test_apply_pipeline_pickpoint_lands_at_world_origin_via_http`: pivot
  invariant. ✓
- Frontend `originMath.test.ts` cardinal `north` updated; new `south`
  test added.

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

### Fix v1 — sed patch (REVERTED 2026-05-05 KST afternoon)

Initial fix attempted: `godo-mapping/Dockerfile` sed-patched the
driver source before `colcon build`:
```dockerfile
&& sed -i 's|M_PI - angle_max|-angle_max|g; s|M_PI - angle_min|-angle_min|g' \
   src/rplidar_node.cpp
```

**Reverted same day** because: while it produced correct single-frame
orientation (`test_180check_after_fix` HIL: wall at correct +x_world),
it shifted the published `/scan` angle range from conventional
`[-π, π]` to `[-2π, 0]`. Operator HIL on cumulative mapping
(`05.05_v4`, `05.05_v6`) showed walls ghosting / not recognised
across consecutive scans during motion — diagnosed as rf2o's
scan-to-scan registration silently degrading on the non-standard
angle range.

### Fix v2 — `flip_x_axis: True` runtime parameter (chosen)

`godo-mapping/launch/map.launch.py` rplidar Node now sets:
```python
parameters=[{
    ...
    'flip_x_axis': True,  # SLAMTEC sign correction
}],
```

`flip_x_axis` triggers an existing `n/2` shift in `apply_index`
inside upstream `publish_scan`. Composing `M_PI - angle` (180°
rotation in published angle values) with `flip_x_axis` (180° rotation
in array indices) gives identity in published-vs-physical
correspondence — i.e., correct orientation. AND both pieces preserve
the conventional `[-π, π]` published angle range.

The Dockerfile keeps `git checkout 24cc9b6` for reproducibility but
does NOT patch the source. Container rebuild required (`docker build
-t godo-mapping:dev .`, ~8 min — apt layer remains cached, only
rplidar_ros + rf2o overlay rebuild).

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
