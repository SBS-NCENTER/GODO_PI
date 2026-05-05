> ★ issue#30 supersede 2026-05-04 KST. The "Sign convention update —
> 2026-05-04 KST (issue#27, SUBTRACT)" section below describes the
> PR #81 ship state, which has been superseded by the pick-anchored
> design from issue#30.
> Live spec: `.claude/memory/project_pick_anchored_yaml_normalization_locked.md`.
> The PR #81 sections remain valid as historical context for the
> tracker plumbing fix (prerequisite (a)) and coherent rendering
> (prerequisite (b)) which carry forward unchanged.

---
name: Map Edit feature spec — brush, origin pick, rotation
description: B-MAPEDIT family spec — brush erase (P0), origin pick with GUI+numeric input (P1), rotation with GUI+numeric input (B-MAPEDIT-3 issue#28). Covers UX, data model, dual-input requirement, pristine-baseline file scheme, segmented-control mode UI, and overlay toggle row.
type: project
---

## ★ Final spec lock — issue#28 kickoff (2026-05-04 KST)

OPERATOR-LOCKED in twenty-second-session opening Q&A. SUPERSEDES the
2026-04-30 single-Apply / single-mode B-MAPEDIT-3 sketch further down.
The "Critical pre-implementation findings — issue#27 HIL surfaced"
subsection remains valid — both prerequisites (a) tracker plumbing
fix and (b) coherent pose+yaw+scan rendering still apply.

### Edit-tab restructure (segmented control)

- The Edit sub-tab now hosts a **segmented control** at its top with
  two top-level modes: **Coordinate Edit** and **Erase**.
- Each mode owns its own **Apply** + **Discard** buttons. No global
  Apply.
- Switching modes does NOT auto-Discard the other mode's pending
  state (operator may toggle back and forth).

### Coordinate Edit mode — origin pick + yaw pick coexist

- Two **independent** picks within this mode. Operator may dirty
  only one and Apply; the other stays at its current YAML value.
  - **Origin pick (x, y)** — single click on the map; OR numeric
    `x_m` / `y_m` with +/- buttons (0.01 m step).
  - **Yaw pick (theta_deg)** — **two clicks** on the map; the vector
    P1 → P2 declares "this direction should become +x axis." Length
    is **ignored** (direction-only). OR numeric `theta_deg` with
    +/- buttons (0.01° step).
- SUBTRACT semantic for both translation AND yaw: typed value names
  the *world coord/direction in CURRENT frame that should become
  (0, 0) / +x axis*. Backend computes
  `new_yaml_origin = old_yaml_origin - typed`.
- Numeric / GUI dual-input is mandatory (per dual-input rationale
  section below).
- Test pin extension: ROTATE#1 / ROTATE#2 sequential picks must NOT
  drift by 2× typed offset (mirror of PICK#2 / PICK#3 from issue#27
  — see `feedback_subtract_semantic_locked.md`).

### Apply pipeline (Coordinate Edit) — bake into bitmap

The user-confirmed Option B: PGM bytes are physically rotated, not
just metadata-updated. Pristine baseline is preserved as a separate
file so quality loss is **always 1× resample** regardless of how many
times the operator iterates.

1. Operator clicks Apply → modal dialog opens.
2. Dialog asks for **postfix memo** (free-text input, validation
   `[A-Za-z0-9_-]+`, no Korean / spaces / dots / slashes — file-system
   safety).
3. Dialog disables tracker control buttons in the SPA System tab
   for the duration.
4. Backend pipeline (no cancel; commit-or-fail; atomic):
   - Load **pristine baseline PGM** from disk (never the
     previously-rotated file).
   - Compose transform: **translate first, then rotate** (operator
     intent: picked origin must land where clicked even after
     rotation).
   - Resample with **Lanczos-3 + re-threshold** to 3-class
     {free=254, unknown=205, occupied=0}. Time budget 30 s OK; at
     ~500×800 typical Lanczos-3 takes ~150-300 ms.
   - **Auto-expand canvas** to fit the rotated bounding box (long
     studios safe).
   - Write to `<base>.<YYYYMMDD-HHMM>-<memo>.pgm.tmp` →
     `fsync` → atomic `rename` to
     `<base>.<YYYYMMDD-HHMM>-<memo>.pgm` + matching `.yaml`.
   - The pair `<base>.pgm` / `<base>.yaml` is **never modified**;
     it is the immutable pristine baseline.
5. **SSE progress stream** (`progress` 0.0–1.0) drives a progress
   bar in the dialog so operator sees real-time advancement.
6. On completion the new variant appears in the map list but is
   **NOT auto-selected as active**.

### Erase mode — same pristine + derived pattern

Operator-locked Q3: Erase variants are infrequent enough (one cleanup
per studio session at most) that keeping them as derived files is
worth the file-system cost. Consistent UX with Coordinate Edit.

- Same pristine-baseline + derived-file pattern.
- Same postfix-memo Apply dialog.
- Same SSE progress (typically faster — no resample, just byte
  rewrite).
- Apply / Discard scoped to Erase mode only.

### File naming + map list UI

- **Pristine pair**: `<base>.pgm` + `<base>.yaml` — immutable,
  read-only after initial mapping.
- **Derived pairs**: `<base>.<YYYYMMDD-HHMM>-<memo>.pgm` +
  `<base>.<YYYYMMDD-HHMM>-<memo>.yaml` — one new pair per Apply.
  Both Coordinate Edit and Erase produce derived pairs.
- Map list UI is a **hybrid grouped tree**: pristine row is a parent;
  all derived variants render as **indented child rows** under their
  pristine parent. Each child row shows full filename + memo +
  timestamp.
- **Active map** carries a badge/star.
- **Active switch is manual + confirmed**: operator clicks any row →
  confirm dialog ("Switch active map to <name>? Tracker restart
  required to apply.") → on confirm, restart-pending sentinel
  touched. **Tracker is NOT auto-restarted** (operator decides when
  to restart from System tab).

### Tracker plumbing fix — prerequisite (a)

- Replace `cfg.amcl_origin_yaw_deg` consumption at
  `cold_writer.cpp:371,377,385,515,521,529,649,655,663` with reading
  the YAML `origin[2]` value parsed by `occupancy_grid.cpp:113-130`.
- Once wired, AMCL frame transform consumes
  `(origin[0], origin[1], origin[2])` as the SSOT.
- Tier-2 `amcl_origin_yaw_deg` knob is removed (cleaner SSOT path).
- Test pin: edit YAML `origin[2]` → restart tracker → raw yaw shifts
  by edited delta.

### Overlay toggle row (UI unification)

- New toggle row sits **on the same row as the segmented control** —
  one clean row at the top of every map-rendering sub-tab.
- Toggles available everywhere a map is rendered:
  - **Origin/Axis overlay** (NEW) — origin dot + +x red axis +
    +y green axis (ROS REP-103 colors). Axes extend to **screen
    edge**. World-frame anchored.
  - **LiDAR overlay** — migrated from existing per-tab location to
    this unified row.
  - **Grid overlay** (NEW) — see grid spec below.
- **All toggle states persist via localStorage** (per LiDAR overlay
  precedent).

### Grid overlay spec

- **World-frame aligned** — rotates with YAML theta (so the operator
  sees rotation in real time as they iterate).
- **Zoom-adaptive interval schedule** (Planner finalizes; sketch:
  zoom <0.3 → 5 m, 0.3–1.0 → 1 m, 1.0–3.0 → 0.5 m, ≥3.0 → 0.1 m).
- **Larger intervals slightly thicker**: e.g., 5 m → 1.5 px,
  1 m → 1 px, 0.1 m → 0.5 px.
- Subtle gray, low opacity to stay non-intrusive.

### Coherent rendering — prerequisite (b)

- Pose dot + heading arrow + LiDAR scan dots stay **coherent with
  the rotated bitmap** throughout operator interaction.
- Vitest pin must demonstrate "pose + scan + bitmap rotate together
  when YAML theta changes" (per shared `MapUnderlay` +
  `lib/poseDraw.ts` from issue#27).

### Pristine-baseline rationale (operator question 2026-05-04)

Operator asked whether per-pixel coordinate transformation could
preserve the original perfectly. The pristine-baseline pattern
*already does this*: the original PGM bytes are immutable; every
Apply re-renders fresh from the original with cumulative
(translate, rotate) parameters. Quality loss is always exactly **one
resample**, never compounding. Inverse-mapping (output pixel →
sample original) is the standard form — no holes, no scatter.

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
