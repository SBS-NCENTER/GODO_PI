---
name: Map Edit feature spec — brush, origin pick, rotation
description: B-MAPEDIT family spec — brush erase (P0), origin pick with GUI+numeric input (P1), rotation with GUI+numeric input (deferred). Covers UX, data model, and dual-input requirement.
type: project
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

  **Sign convention (operator-locked 2026-04-30 KST, ADD)**: in `delta` mode the typed `(x_m, y_m)` is the *offset of the new origin from the current origin* — i.e. `new_origin = current_origin + (x_m, y_m)`. Operator phrasing: "실제 원점 위치는 여기서 (x, y)만큼 더 간 곳". Use case: operator measures the studio's real center is at `(+0.32, -0.18)` in the *current* world frame, types those numbers in delta mode → new origin lands on the studio center → studio center reads as world `(0, 0)` in the NEW frame. **SUBTRACT is wrong** and was caught by Mode-A reviewer (would shift origin by `2× typed_offset`).

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

## Dual-input rationale (recurring pattern)

The dual-input requirement (GUI + numeric) is intentional and applies to EVERY future Map Edit feature where a continuous correction value is involved. GUI is good for coarse exploration; numeric is good for fine reproduction (the operator already has a measurement from a tape or known reference). Locking the page to one mode forces the other workflow into a workaround. Future plans for similar features should default to dual-input from the start; flag any single-input proposal as a regression.
