---
name: issue#30 HIL 2026-05-05 — rotation direction bug + mapping pipeline open question + pristine sidecar misclassification
description: Three findings from operator HIL on PR #84 (issue#30 pick-anchored YAML normalization). (1) AFFINE matrix in map_transform.py rotates bitmap CCW for typed +θ, but lock requires CW. 1-line fix. (2) Mapping pipeline: LIDAR initial pose rotated CCW produces map rotated CCW (expected CW per slam_toolbox world-frame=initial-pose convention). PGM preview vs SPA also differ by 90°. Likely same root cause (CW↔CCW convention drift in driver/launch). (3) recovery_sweep mis-classifies pristine maps (no derived-pattern filename) as kind=synthesized.
type: project
---

## Context

PR #84 (`feat/issue-30-yaml-normalization`) shipped backend math + frontend
UX + 3-tier review pipeline (Planner R1-R3, Mode-A R1-R3, Writer R1-R2,
Mode-B R1-R2 → APPROVE WITH MINOR). Operator deployed to news-pi01 and
discovered three issues during HIL. PR is OPEN (not merged); twenty-fourth
session resumes here.

## Finding 1 — issue#30 AFFINE rotation direction is BACKWARDS

### Symptom

Operator typed a yaw delta on `test_v4` (pristine yaw=1.604 rad) using
the new pick-anchored Apply pipeline. Bitmap rotated **opposite to PR #81's
direction** for the same typed value.

### Root cause (analyzed)

`godo-webctl/src/godo_webctl/map_transform.py:314-334` passes
`+theta_rad` to `_affine_matrix_for_pivot_rotation`:

```python
theta_deg = cumulative_from_pristine.rotate_deg   # operator-typed CCW intent
theta_rad = math.radians(theta_deg)
affine = _affine_matrix_for_pivot_rotation(i_p, j_p, x_min, y_min, theta_rad)
```

`_affine_matrix_for_pivot_rotation` (lines 458-475) constructs Pillow's
output→input matrix:
```python
a = cos_t; b = -sin_t; d = sin_t; e = cos_t
```

For `theta_rad = +π/2`: `(a, b, d, e) = (0, -1, 1, 0)`. Concrete trace
on a 2×2 input `ABCD`:
- output (0,0) sourced from input (1,0)='B'
- output (1,0) sourced from input (1,1)='D'
- output (0,1) sourced from input (0,0)='A'
- output (1,1) sourced from input (0,1)='C'

Output is `BDAC` arrangement = visual **CCW 90° rotation** of input. (Same
as `Image.rotate(+90)` per Pillow docs.)

### Locked semantic vs current behavior

Plan §D5 + Q2 lock + design analysis §7:
> "operator's typed +θ means 'rotate the world frame by +θ'; bitmap
> content rotates by −θ relative to the source so a wall at +θ in pristine
> ends up at 0° (the new +x) in derived"

Operator types +90° → world frame rotates CCW → bitmap content visually
rotates **CW** by 90°.

Current code visually rotates **CCW** for typed +90°. **Sign-flipped.**

PR #81 round-1 was correct because it used `Image.rotate(-typed_yaw_deg)`
which negated the angle. Issue#30 round-2 dropped the negation when
moving to `Image.transform(AFFINE)`.

### Fix (1-line)

Pass `-theta_rad` to `_affine_matrix_for_pivot_rotation`:
```python
affine = _affine_matrix_for_pivot_rotation(i_p, j_p, x_min, y_min, -theta_rad)
```

OR equivalently, negate inside the helper body. The 1-line fix is
preferable for clarity at the call site.

### Test impact

`test_affine_matrix_golden_4x4_theta45` was hand-derived assuming the
current (CCW) direction. Golden bytes need re-computation against the
CW direction.

`test_typed_delta_shifts_picked_point_off_origin` and
`test_apply_pipeline_pickpoint_lands_at_world_origin_via_http` both pin
**world-coord placement** (not visual direction) so they should still
pass after the fix — but verify after the rebuild.

`test_pickpoint_lands_at_world_origin[θ=...,oθ_p=...]` parametric: also
pins world-coord placement, should remain green.

`test_pick_cascade_associativity` operates on `compose_cumulative` algebra
(not the AFFINE matrix); independent of the fix.

### NOT fix (would compound)

Do NOT change `compose_cumulative` sign convention. The Mode-A round-2
reviewer numerically verified the algebra (4e-16 m residual) under the
locked CCW convention. Cumulative tracking is correct; only the
output-stage AFFINE direction is wrong.

## Finding 2 — Mapping pipeline rotation convention (open question)

### Symptom

Operator created 3 fresh pristine maps (`05.05_v1/v2/v3`) by rotating
the LIDAR's initial physical orientation 90° CCW each time before
starting slam_toolbox. Observation:
- LIDAR rotated CCW → SPA's rendered map content also rotated CCW (same
  direction).
- PGM preview during mapping (Docker rviz?) vs SPA application view
  differ by **90°**: SPA view = mapping preview rotated CW 90°.

### Operator's expectation (consistent with our analysis)

slam_toolbox typically sets world frame = LIDAR's initial pose. So:
- LIDAR rotates CCW → world frame rotates CCW
- A physical wall's world coords change such that the bitmap drawn in
  the new world frame shows the wall at a 90° CW position vs the
  default-LIDAR map.
- **Expected: map rotates CW when LIDAR rotates CCW.**

Operator observed the **opposite** (same direction).

### Hypotheses (none verified)

1. **`rplidar_ros2` driver CW→CCW conversion has a sign bug.** Memory
   `project_rplidar_cw_vs_ros_ccw.md` documented a similar bug in
   `production/RPi5/src/localization/scan_ops.cpp:48,73-74` (CCW math
   on raw CW angles → Y-flipped scan endpoints). The Docker mapping
   pipeline was claimed clean ("uses official driver which converts
   CW→CCW at driver level") but may have its own conversion bug.
2. **slam_toolbox launch config has a frame transform with wrong
   sign** somewhere between `base_link → laser_frame` or world-frame
   initialization.
3. **RPLIDAR's triangle marker orientation differs from the
   datasheet** (manufacturing variance — unlikely for SLAMTEC).

### PGM preview vs SPA 90° offset

Possibly same root cause OR independent display convention difference
(rviz default frame orientation vs ROS standard). Need to inspect
mapping container's rviz config + operator's actual screen captures.

### Investigation plan

1. Capture a single scan with the LIDAR in a known orientation (e.g.,
   triangle marker pointing at a specific wall). Log the raw beam
   angles + endpoint world coords.
2. Compare with `rplidar_ros2` driver's published `LaserScan` topic
   to confirm CW→CCW conversion is correct (or not).
3. Check slam_toolbox launch file in `production/RPi5/docker/`
   (or wherever `godo-mapping:dev` is built) for any `tf_static` /
   `frame_id` overrides that could introduce a sign flip.
4. Open mapping container's rviz config to determine what default
   orientation it uses for `Map` display (vs ROS REP-103).

### Out of issue#30 scope

This is NOT a regression introduced by issue#30 — it pre-dates the PR.
Operator's HIL on the pre-existing pipeline produced this finding while
testing issue#30 (because they made fresh maps to verify rotation
behavior). Likely candidate for `issue#32` standalone investigation.

**HOWEVER**: if this convention bug is fixed, issue#30's typed-θ
behavior must be re-validated end-to-end. The two issues are coupled
in the operator's mental model (and operator explicitly noted this:
"이 회전 문제들이 거의 동일한 원인인 것 같은데. 어느 한쪽만 수정하면
나중에 더 꼬일 수도 있어").

## Finding 3 — recovery_sweep mis-classifies pristine maps as `kind=synthesized`

### Symptom

After deploy, all 3 fresh pristine maps got auto-generated sidecars:
```
05.05_v1.sidecar.json: kind=synthesized, lineage.kind=synthesized, gen=-1
05.05_v2.sidecar.json: kind=synthesized, lineage.kind=synthesized, gen=-1
05.05_v3.sidecar.json: kind=synthesized, lineage.kind=synthesized, gen=-1
```

These ARE pristine (operator-intended), not synthesized.

### Root cause

`recovery_sweep` heuristic per plan §D1 + round-3 patch P2:
- Filename matches `<base>.YYYYMMDD-HHMMSS-<memo>` → `auto_migrated_pre_issue30`
- Else → `synthesized`

Pristine filenames (`05.05_v1.pgm`, `studio_v1.pgm`, etc.) don't match
the derived pattern → fall through to `synthesized`. The heuristic
conflates "post-issue#30 crash-window orphan" (intended for `synthesized`)
with "operator-mapped pristine" (should have NO sidecar).

### Design intent (per plan)

Pristine maps should NOT have sidecars. Sidecars are emitted only for
derived (operator Apply output) and backup. The recovery_sweep was
intended to handle ONLY orphan derived pairs, not pristine maps.

### Fix options (issue#30.1 backlog)

(a) **Skip pristine names entirely**: recovery_sweep iterates only
   filenames matching the derived pattern. Non-matching names are not
   touched (no sidecar created). This requires `<base>` validation
   to ensure ambiguous names like `studio_v1` aren't mistaken.
(b) **Explicit pristine recognition heuristic**: if PGM is operator-
   created (e.g., owned by `root` or has specific timestamp pattern),
   treat as pristine. Less robust.
(c) **Only sidecar maps that have a parent reference**: pristine has
   no parent so no sidecar; derived always has a parent so always
   sidecar. This is the cleanest invariant.

Recommend (a) — sweep only operates on derived-pattern filenames; everything
else is left alone. `kind="synthesized"` only fires for actual orphan
derived pairs (filename matches but no sidecar AND no provable parent).

### Operator-visible impact

The mis-classified sidecars on `05.05_v1/v2/v3` aren't immediately
broken — AMCL doesn't read sidecars. But:
- LineageModal shows misleading "synthesized (gen=-1)" for what should
  be pristine root nodes.
- If operator does PICK on `05.05_v1`, the system reads the bogus
  sidecar's `cumulative_from_pristine` (probably zero) and proceeds.
  Should work, but the lineage chain becomes confusing.

### Cleanup

Operator should manually `rm` the 3 mis-classified sidecars before
next mapping session, OR the fix's recovery_sweep refactor can detect
+ remove them on next startup.

## Working-tree state at handoff (2026-05-05 KST)

- Branch `feat/issue-30-yaml-normalization` pushed to origin (PR #84).
  PR is OPEN (not merged).
- Branch `docs/2026-05-05-issue30-hil-handoff` (this file commit) carries
  NEXT_SESSION.md + memory updates.
- Backups of the 3 fresh pristine maps preserved at
  `/home/ncenter/maps_backup_2026-05-05_pre_issue30_debug/` (3 PGM + 3
  YAML + 3 sidecar) so any later destructive operation can be reverted.

## Next-session entry plan

1. Open this memory file FIRST.
2. Investigate Finding 2 (mapping pipeline rotation convention) BEFORE
   patching Finding 1 — if the mapping convention has a sign flip, the
   issue#30 fix needs to align with that flip OR fix both together.
3. Based on Finding 2 outcome, decide:
   - (a) Both fixes land in PR #84 → re-review Mode-B → operator HIL → merge.
   - (b) Finding 1 fix in PR #84; Finding 2 split as `issue#32`.
4. Address Finding 3 (sidecar misclassification) inline in PR #84
   regardless — small fix, related code area.

## Related artifacts

- `.claude/memory/project_rplidar_cw_vs_ros_ccw.md` — prior CW/CCW
  convention bug in scan_ops.cpp + frontend scanTransform.ts (frontend
  fixed; tracker C++ fix never landed).
- `.claude/memory/project_amcl_yaw_metadata_only.md` — AMCL is
  yaw-blind in cell mapping; YAML origin yaw is metadata-only.
- `doc/RPLIDAR/RPLIDAR_C1.md:125-130` — RPLIDAR's left-handed
  coord system + θ=0° = scanner forward + θ increases CW.
- `/var/lib/godo/maps/05.05_v{1,2,3}.{pgm,yaml,sidecar.json}` —
  HIL test fixtures.
- `/home/ncenter/maps_backup_2026-05-05_pre_issue30_debug/` —
  backup of the 3 fresh pristines.
- `.claude/tmp/plan_issue_30_yaml_normalization.md` — plan with all 5
  review folds (host-local; not committed; on news-pi01 only).
- PR #84 — `https://github.com/SBS-NCENTER/GODO_PI/pull/84`.
