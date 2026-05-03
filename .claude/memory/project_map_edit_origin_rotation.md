---
name: Map Edit feature spec — brush, origin pick, rotation
description: B-MAPEDIT family spec — brush erase (P0), origin pick with GUI+numeric input (P1), rotation with GUI+numeric input (deferred). Covers UX, data model, and dual-input requirement.
type: project
---

## Sign convention update — 2026-05-04 KST (issue#27, SUBTRACT)

**SUPERSEDES the 2026-04-30 ADD lock below.** Operator HIL on 3
sequential picks (PICK#1 → PICK#3) showed the ADD direction drifted
the resulting pose by `2 × typed_offset` instead of moving to `(0, 0)`.
The fix is direction-only; magnitude was already correct. Operator
confirmed 2026-05-03 23:30 KST.

**Locked rule:** typed `(x_m, y_m)` names the *world coord of the point
that should become the new (0, 0)*. Backend computes
`new_yaml_origin = old_yaml_origin - typed`; AMCL pose at next restart
moves to `new_pose = old_pose - typed`.

**SPA path:** delta mode resolves frontend-side via
`lib/originMath.resolveDeltaFromPose(currentPose, dx, dy)` → absolute,
then sends `mode="absolute"` to the backend so the backend stays dumb.
Backend's delta branch is a fallback for non-SPA clients.

**HIL pins** — `godo-webctl/tests/test_map_origin.py::
test_apply_origin_edit_absolute_subtracts_pose_pick_{2,3}` and
`godo-frontend/tests/unit/originMath.test.ts::"PICK#2 …"` /
`"PICK#3 …"`.

See `.claude/memory/feedback_subtract_semantic_locked.md` for the full
rationale + cross-stack pin list.

---

The Map Edit feature ships as three separate PRs to keep each change reviewable and rollback-able. All three operate on the active PGM/YAML pair under `cfg.maps_dir` and require a tracker restart to take effect (tracker reads map at boot only — see godo-webctl invariant on restart-pending sentinel).

## B-MAPEDIT (P0, brush erase) — current

- Operator paints a circular brush over fixtures to ignore (people, moved equipment, transient clutter); Apply rewrites masked pixels to canonical "free" value (254).
- Auto-backup before edit; one-click undo via `/backup`.
- Plan: `.claude/tmp/plan_track_b_mapedit.md` (Mode-A folded, ~950-1050 LOC).
- Branch: `feat/p4.5-track-b-mapedit`.
- Status (2026-04-30): writer kickoff in progress.

## B-MAPEDIT-2 (P1, origin pick) — DUAL INPUT

**Purpose**: re-set the world (0,0) origin without re-mapping. YAML `origin: [x, y, theta]` field update only — NO bitmap rewrite, pure metadata edit. Use case: operator places a pole at the chroma studio's physical center, scans, then either clicks the resulting point OR types in a known offset → studio center becomes origin.

**Why:** operator request 2026-04-29 23:45 KST + reaffirmed 2026-04-30. The dual-input requirement was added because GUI click is fast but lossy (pixel-grid quantization, ~5 cm per click at typical resolutions); for fine corrections operators want to type in a measured offset directly.

**How to apply:** when planning B-MAPEDIT-2, the SPA page MUST expose BOTH input modes side-by-side, NOT one or the other:

- **Mode A — GUI pick**: click a pixel on the rendered PGM. Frontend converts pixel → world coords using current YAML `resolution` + `origin`, then pre-fills the numeric fields. Operator can adjust before Apply.
- **Mode B — numeric entry**: two number inputs `x_m` + `y_m` with absolute / delta toggle. Locale-friendly decimal handling (period, not comma). Sub-mm precision in input but display rounds to 1 mm. Negative values allowed.

  **Sign convention (PREVIOUS spec, superseded 2026-05-04 KST)**: in `delta` mode the typed `(x_m, y_m)` was specified as the *offset of the new origin from the current origin* — i.e. `new_origin = current_origin + (x_m, y_m)`. Operator phrasing: "실제 원점 위치는 여기서 (x, y)만큼 더 간 곳". This spec was operator-locked on 2026-04-30 KST but reversed by issue#27 SUBTRACT lock above (HIL data on 3 sequential picks showed the ADD direction was wrong — pose drifted by `2 × typed_offset`). Preserved here as historical context; the LIVE spec is the SUBTRACT note at the top of this file.

Apply path is unified: both modes resolve to a single `(new_x, new_y)` pair → backend updates YAML `origin[0]` and `origin[1]` only. PGM bytes unchanged. Auto-backup of the YAML (PGM does not need backup since it's not touched). Restart-pending sentinel touched.

LOC estimate: ~150 LOC (90 was original GUI-only estimate; numeric input adds ~60 for the input form, validation, and unit toggle).

Endpoint shape (provisional): `POST /api/map/origin` admin-gated, JSON body `{x_m: float, y_m: float, mode: "absolute" | "delta"}`. Response `{ok, backup_ts, prev_origin: [x, y], new_origin: [x, y], restart_required: true}`.

## B-MAPEDIT-3 (rotation, queued P0 as PR γ after PR β) — DUAL INPUT

**Purpose**: rotate the map (and YAML `origin[2]` theta) to align with the studio's reference axes. Operator hint: ±1-2° residual rotation observed in scan overlay vs walls on `04.29_v3.pgm`.

**Status (2026-04-30 KST eleventh-session full close + PR-β-kickoff)**: operator un-deferred. Stacks AFTER PR β (shared map viewport + Map Edit LiDAR overlay) so the rotation gizmo can leverage the shared canvas affordance and the operator sees the LiDAR overlay update live during rotation.

**LOC estimate**: ~250-350 LOC. CPU-bound bilinear resample at typical map sizes is ~50-200 ms — first cut uses plain CPU resample. VideoCore VII GPU acceleration is research-grade follow-up (`.claude/memory/project_videocore_gpu_for_matrix_ops.md`); not in PR γ scope.

**Sign convention (operator-locked 2026-04-30 KST, ADD)**: in `delta` mode the typed `theta_deg` is the *offset* — `new_theta = current_theta + theta_deg`. Both negative AND positive values must be supported (operator phrasing: "음수, 양수 모두 계산 가능해야 해"). Sign axis: **CCW-positive** matching ROS REP-103 (math convention; negative = clockwise). Same ADD pattern as B-MAPEDIT-2 origin pick — keep the convention uniform across all Map Edit mutations.

**How to apply:** dual-input rule (mandatory) — the SPA page MUST expose:

- **Mode A — GUI rotate**: drag-rotate handle on the rendered PGM, or two-point pick (click two points on a wall → backend computes the angle to make them axis-aligned). On click/drag end, GUI flips Mode B toggle to `absolute` and pre-fills the numeric field (mirroring B-MAPEDIT-2 `setCandidate` pattern).
- **Mode B — numeric entry**: single `theta_deg` input, sub-degree precision, absolute/delta toggle, negative allowed. ADD sign convention; CCW-positive. Locale-friendly decimal handling (period only).

Apply path: PGM bilinear resample (sole-owner module `map_rotate.py`) + YAML `origin[2]` update + auto-backup of BOTH files (PGM bytes change in this PR — unlike B-MAPEDIT-2 which kept PGM intact). Restart-pending sentinel. Same backup-FIRST 3-step contractual sequence as B-MAPEDIT-2.

### Critical pre-implementation findings — issue#27 HIL surfaced (2026-05-04 KST)

Operator HIL during issue#27 ship verified two structural gaps that B-MAPEDIT-3 must close:

1. **Tracker does NOT consume YAML `origin[2]` at boot.** Verified by grep: `cold_writer.cpp:371,377,385,515,521,529,649,655,663` reads `cfg.amcl_origin_yaw_deg` (Tier-2 config knob), NOT the YAML origin's third element. `occupancy_grid.cpp:113-130` parses the third value into the struct but never propagates it to AMCL frame transform. → Editing `origin[2]` via B-MAPEDIT-2's theta_deg parameter currently has ZERO effect on tracker pose output (operator confirmed: theta edit + restart → LiDAR raw yaw unchanged). B-MAPEDIT-3 MUST either (a) wire YAML `origin[2]` through to AMCL replacing `cfg.amcl_origin_yaw_deg`, OR (b) auto-update both YAML AND `cfg.amcl_origin_yaw_deg` together as a single transactional Apply. (a) is cleaner SSOT; (b) preserves backward compat. Lean (a). Either way, the test pin must verify "edit theta → restart → raw yaw shifts by edited delta".

2. **Pose + Yaw must render together on the rotated map.** Operator-locked 2026-05-04 KST: when B-MAPEDIT-3 ships the PGM bilinear resample, the rendered overlay (pose dot + heading arrow + LiDAR scan dots) MUST stay coherent with the rotated bitmap throughout the operator's interaction. No "rotate the bitmap, but the pose stays in the old frame" intermediate state. The shared `MapUnderlay` + `lib/poseDraw.ts` extracted in issue#27 makes this straightforward (the draw layer reads world coords, the underlay handles pixel-space transform); B-MAPEDIT-3 plan must include a Vitest pin that demonstrates pose + scan + bitmap all rotate together when YAML theta changes.

These two findings tighten the B-MAPEDIT-3 spec: the rotation is not just a UI feature, it's a backend-tracker plumbing fix with a UI on top. Until both land, the existing `MapUnderlay.svelte:402-406` theta-warning banner is the operator's only signal that theta != 0 produces inconsistent state.

issue#27 mitigation: theta UI gated `THETA_EDIT_ENABLED=false` in `OriginPicker.svelte` (commit `2b4c3fe`) so operators can't trigger the silent breakage. Backend `theta_deg` parameter + `origin_step.yaw_deg` schema row remain — B-MAPEDIT-3 lights up the UI by flipping the constant.

## Dual-input rationale (recurring pattern)

The dual-input requirement (GUI + numeric) is intentional and applies to EVERY future Map Edit feature where a continuous correction value is involved. GUI is good for coarse exploration; numeric is good for fine reproduction (the operator already has a measurement from a tape or known reference). Locking the page to one mode forces the other workflow into a workaround. Future plans for similar features should default to dual-input from the start; flag any single-input proposal as a regression.
