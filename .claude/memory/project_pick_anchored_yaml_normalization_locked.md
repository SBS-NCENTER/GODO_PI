---
name: Pick-anchored YAML normalization (issue#30 SSOT)
description: Operator-locked semantic for Map Edit Coord-mode Apply (issue#30, PR #TBD). The picked point becomes world (0, 0); the picked direction becomes world +x; YAML yaw is 0; YAML x/y is `[-i_p'·res, -(H_d-1-j_p')·res]` so AMCL maps world (0, 0) to the picked-point pixel in the rotated bitmap. Supersedes the SUBTRACT semantic from PR #79 (issue#27) + PR #81 (issue#28).
type: project
---

Locked 2026-05-04 KST in twenty-third-session opening discussion.
Round 2 fold-ins (Q1/Q2 + math contract fixes) locked 2026-05-04 KST
later same day. The operator's mental model — "맵을 새로 정렬했으니
origin은 (0, 0, 0°)이 되어야 한다" — surfaced during PR #81
PICK#1/PICK#2 cascade analysis and is captured operationally as:

**Per Apply, the bitmap is rotated around the operator's picked-point
pivot and the canvas grows to absorb rotation overhang. The derived
YAML's origin is set so that world (0, 0) lands EXACTLY on the
picked-point pixel in the new bitmap, and YAML yaw is 0.**

This is interpretation (3) "pick-anchored + canvas-expand" in
`/doc/issue30_yaml_normalization_design_analysis.md` §4. It supersedes
the SUBTRACT semantic locked in `feedback_subtract_semantic_locked.md`
(now deleted).

## Backend formula (canonical SSOT in `godo-webctl/src/godo_webctl/map_transform.py`)

Given pristine `(W_p, H_p)` at resolution `res`, pristine YAML origin
`(ox_p, oy_p, oθ_p)` (oθ_p MAY be non-zero — informational baseline,
yaw-aware via `pristine_world_to_pixel`), and operator-typed
cumulative `(cum_tx, cum_ty, θ)` from pristine in pristine world
coordinates (θ is typed-θ accumulation only, NOT including oθ_p):

```
# Step 1 (yaw-aware world→pixel; oθ_p MAY be non-zero)
i_p, j_p_top = pristine_world_to_pixel(cum_tx, cum_ty, ox_p, oy_p, oθ_p, W_p, H_p, res)

# Step 2: off-center bbox by rotating four pristine corners around (i_p, j_p_top) by -θ
#   for each corner (x, y) ∈ {(0,0), (W_p,0), (0,H_p), (W_p,H_p)}:
#     dx = x - i_p
#     dy = y - j_p_top
#     x' = i_p + cos(-θ_rad)·dx − sin(-θ_rad)·dy
#     y' = j_p_top + sin(-θ_rad)·dx + cos(-θ_rad)·dy
#   take floor(min) / ceil(max).
W_d = x_max - x_min
H_d = y_max - y_min

# Step 3: picked-point's NEW pixel (column-from-left, row-from-top)
i_p' = i_p     - x_min
j_p' = j_p_top - y_min

# Step 5: derived YAML origin (Y-flip from row-from-top to row-from-bottom)
new_origin_x_m   = -i_p' · res
new_origin_y_m   = -((H_d - 1) - j_p') · res
new_origin_yaw_deg = 0.0
```

`Image.transform((W_d, H_d), Image.Transform.AFFINE, (a, b, c, d, e, f),
resample=BICUBIC, fillcolor=205)` performs the rotation around the
picked-point pivot. Matrix coefficients (`a = cos θ_rad`, `b = -sin θ_rad`,
`c = i_p + cos θ_rad·(x_min - i_p) - sin θ_rad·(y_min - j_p)`,
`d = sin θ_rad`, `e = cos θ_rad`,
`f = j_p + sin θ_rad·(x_min - i_p) + cos θ_rad·(y_min - j_p)`) are derived in
`map_transform.py::_affine_matrix_for_pivot_rotation` per the docstring's
math contract.

## Frontend formula (mirror in `godo-frontend/src/lib/originMath.ts`)

`pristineWorldToPixel(...)` mirrors the Python helper bit-identically.
`composeCumulative(parent, step)` computes the new
cumulative-from-pristine via the C-2.1 round-3 lock:
`cumulative.translate = picked_world − R(-θ_active)·typed_delta`.

## Cumulative tracking (sidecar JSON)

Each derived map carries a sidecar
`<base>.YYYYMMDD-HHMMSS-<memo>.sidecar.json` (schema
`godo.map.sidecar.v1`). The `cumulative_from_pristine.rotate_deg` field
stores the operator's typed-θ accumulation from pristine (NOT including
pristine yaw `oθ_p` — Q1 lock #5). Each new Apply reads the parent
derived's sidecar, composes the typed step (in active-at-pick frame)
with the parent's cumulative via the algebra in
`/doc/issue30_yaml_normalization_design_analysis.md` D3, and runs ONE
transform from pristine. **Image quality stays at 1× resample
regardless of cascade depth** (preserves
`project_pristine_baseline_pattern.md`).

## Frontend numeric input UX (Q2 lock #2)

The picked point on the canvas IS the new world `(0, 0)` by definition.
Input boxes default placeholder `0` / empty meaning "no further nudge".
Typed values are deltas applied ON TOP of picked-point-at-origin
baseline. Click on canvas does NOT pre-fill input boxes.

Operator-visible cumulative display reads "회전 (typed θ 누적)" — never
references pristine yaw, so the operator's mental cumulative matches
the JSON field exactly.

## Why this design is structurally clean

`project_amcl_yaw_metadata_only.md` documents that AMCL's likelihood
field cell mapping reads `origin_x_m` + `origin_y_m` only; YAML yaw is
informational. The pick-anchored design naturally aligns:
- YAML yaw = 0 → no hidden divergence with AMCL's yaw-blind cell
  mapping.
- YAML origin x/y = `(-i_p'·res, -(H_d-1-j_p')·res)` → AMCL maps world
  (0, 0) to the picked-point pixel.
- Output-stage `compute_offset` becomes `dyaw = current.yaw_deg - 0 =
  current.yaw_deg` → operator's FreeD-output dyaw reads cleanly in the
  new frame.

## How to apply when designing future map-mutation features

- Follow the pick-anchored semantic for any feature where the operator
  picks a "new world origin" point. Do NOT reintroduce a SUBTRACT
  branch — its sign confusion was the root cause of issue#27 +
  issue#30.
- All cumulative tracking goes through the sidecar JSON schema
  `godo.map.sidecar.v1`. Adding new fields requires a schema bump
  (`v2`).
- Atomic write protocol is C3-triple (PGM → YAML → JSON), not the old
  C3-pair. Sidecar is committed last (recoverable absence).
- Pristine yaw `oθ_p` MUST be honoured in `pristine_world_to_pixel`.
  Treat `oθ_p == 0` as a special case, never as the only case.

## Cross-references

- `/doc/issue30_yaml_normalization_design_analysis.md` — full design
  analysis (kept permanently per the doc's §"Permanence" lock).
- `.claude/memory/project_amcl_yaw_metadata_only.md` — AMCL
  yaw-blindness sub-finding.
- `.claude/memory/project_pristine_baseline_pattern.md` — invariant
  preserved by this design.
- `.claude/memory/project_yaml_normalization_design.md` — original
  spec memory (interpretations 1+2; superseded by interpretation 3).
- `.claude/memory/feedback_timestamp_kst_convention.md` — sidecar
  `created.iso_kst` field follows this lock.
