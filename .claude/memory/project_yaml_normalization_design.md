> ★ SUPERSEDED 2026-05-04 KST. This memory's (1)/(2) framing is
> historical only. The chosen design is interpretation (3)
> "pick-anchored + canvas-expand", surfaced during the
> twenty-third-session opening cold-start question.
> Live spec: `.claude/memory/project_pick_anchored_yaml_normalization_locked.md`
> + `/doc/issue30_yaml_normalization_design_analysis.md`.

---
name: issue#30 YAML normalization to (0, 0, 0°) per Apply — design spec
description: Operator-locked deferred design from PR #81 PICK#1/PICK#2 cascade analysis. Every Apply produces a derived map whose YAML origin is (0, 0, 0°) — picked point IS the new world origin by definition. Requires bitmap translation + canvas adjustment + cumulative-typed tracking from pristine, beyond the current PR #81 implementation.
type: project
---

## Background

PR #81 (B-MAPEDIT-3) ships with the SUBTRACT-from-pristine semantic:
`new_yaml = pristine_yaml - typed`. This NEVER produces YAML = (0, 0, 0°)
unless the operator types values that exactly equal pristine YAML —
which they don't, because they're typing world coords for the picked
point, not values designed to zero out the YAML.

Operator's PICK#1/PICK#2 cascade test on 2026-05-04 KST late-night:

```
Pristine origin: (-4.600, -8.600, 91.9°), pose (6.03, -1.79, 180.0°)

PICK#1 typed (0.275, -0.275, 91.7°):
  YAML origin → (-4.875, -8.325, 91.9°)   [pristine - typed for x/y;
                                            yaw stays at pristine per
                                            Option B]
  Pose → (2.02, -4.95, 88.2°)             [bitmap rotation moved it]

PICK#2 typed (5.95, -2.725, 0):
  YAML origin → (-10.55, -5.875, 91.9°)   [pristine - typed; YAML yaw
                                            still pristine; theta=0
                                            means no bitmap rotation
                                            so pose returns to ~180°]
  Pose → (0.07, 0.93, 179.9°)
```

Operator's reaction:

> "우리가 원점을 변경하여 적용한 맵은 새로 정렬되었을테니 현재
> origin은 당연히 (0, 0, 0°)로 나와야 하는 것 아닌가요?"

Operator-locked decision (twenty-second-session late-night): the
correct semantic — "the picked point IS the new world (0, 0) by
definition" — is queued for issue#30 in twenty-third-session as a
NEW PR opening.

## Design intent

After Apply:
- New derived YAML's origin = `(0, 0, 0°)`.
- New derived bitmap content represents the same physical environment
  but in a new world frame where:
  - The operator's picked point is at world (0, 0).
  - The operator's picked direction (P1 → P2 vector) is along world +x.
  - The map's bitmap pixel (0, 0) (bottom-left) corresponds to world
    (0, 0) only if YAML origin literally is (0, 0, 0°). Operator's
    studio extends in BOTH +x and -x from the picked point typically,
    so a strict (0, 0, 0°) YAML would require placing the picked
    point at the bitmap's bottom-left corner — which means the rest
    of the studio MUST be in the bitmap's +x, +y quadrant.

Two viable interpretations:

### Interpretation 1 — strict (0, 0, 0°), translate + crop

YAML origin = literally `(0, 0, 0°)`. Bitmap is rotated AND translated
so that the picked point ends up at bitmap pixel (0, 0). Studio
content that ends up in negative world coords is cropped (or padded
with "unknown" 205).

- Pros: simplest YAML interpretation; new map IS the canonical world
  frame.
- Cons: cropping loses studio content; operator's typical use case
  (pick a center point) would lose 75% of the bitmap.

### Interpretation 2 — quasi-(0, 0, 0°), translate to centre origin

YAML origin = `(-bbox_w/2, -bbox_h/2, 0°)` so world (0, 0) lands at
the bitmap's center. Picked point ends up at bitmap center. Studio
content extends in all four quadrants from the picked point.

- Pros: no cropping; bitmap fully utilised.
- Cons: YAML origin is not literally (0, 0, 0°), only the yaw is.
  Operator's "(0, 0, 0°)" expectation needs clarification — they
  probably mean the **operator-visible offset / rotation labels read
  zero** (as in "no further correction needed"), not the literal
  YAML field.

**Operator clarification needed at twenty-third-session opening.**
Lean toward Interpretation 2 (cumulative offsets stored elsewhere,
YAML stays canonical with origin centered or pristine-aligned).

## Implementation requirements

Whichever interpretation, the work spans:

1. **Pillow `Image.transform`** for affine (rotate + translate)
   instead of `Image.rotate` (rotate-only). PIL's `transform`
   accepts an `(a, b, c, d, e, f)` 2×3 affine matrix.
2. **Canvas adjustment**: rotate-and-translate output bbox depends on
   both the rotation angle AND the picked point's offset from
   bitmap center. Pre-compute new W, H.
3. **YAML origin update**: per chosen interpretation.
4. **Cumulative-typed tracking** from pristine: each derived stores
   its cumulative `(translate_x, translate_y, rotate_θ)` as part of
   its filename or sidecar metadata. Each Apply reads pristine
   bitmap + computes the NEW cumulative = previous + this Apply, then
   resamples pristine ONCE with the new cumulative transform.
   Quality stays at 1× resample regardless of cascade depth.
5. **Numeric input UX**: per operator's complaint #2 from the
   cascade analysis, input fields should default to "no change"
   (empty / 0) and the operator types incremental adjustments AGAINST
   the current view, not absolute world coords against pristine.
6. **Pose output**: AMCL pose values shift to reflect the new world
   frame. Existing pristine-baseline tests need updating.
7. **Pristine baseline pattern preserved** (operator-locked):
   `<base>.pgm` immutable, derived `<base>.YYYYMMDD-HHMMSS-<memo>.pgm`.

## Cross-stack scope

- **godo-webctl**:
  - `map_rotate.py` → extend to `map_transform.py` or add
    `transform_pristine_to_derived` accepting full affine matrix.
  - `map_origin.py` → re-think SUBTRACT semantics; may need to
    compute YAML origin from picked-point's pixel position rather
    than `pristine - typed`.
  - `app.py::_apply_map_edit_pipeline` → cumulative tracking
    (read previous derived's metadata, compose with this Apply).
- **godo-frontend**:
  - `OriginPicker.svelte` → input field defaults change (empty /
    placeholder = "current value", typed = new target).
  - `originMath.ts` → new helpers for cumulative composition.
  - `MapEdit.svelte` → fetch active YAML + display "current values"
    in OriginPicker placeholders.
- **production/RPi5** (tracker):
  - No code change expected. AMCL math is YAML-yaw-blind already
    (per `project_amcl_yaw_metadata_only.md`) and reads `origin_x_m`
    / `origin_y_m` for cell mapping. As long as the new YAML's
    origin x/y/yaw are self-consistent with the rotated+translated
    bitmap, AMCL converges correctly in the new frame.

## Risks

- **Bitmap rotation already lossy** — adding translation compounds
  unless we preserve pristine-baseline pattern (re-derive from
  pristine each Apply). Mode-A must pin this.
- **Test coverage gap** — current PR #81 tests assume `pristine -
  typed` math. issue#30 will need new pins for cumulative-from-
  pristine and (0, 0, 0°) YAML output.
- **Operator UX confusion** — switching from "typed = picked world
  coord" to "typed = incremental adjustment from current" is a
  semantic shift. UI labels + tooltip text need to clearly say
  which mode the input is in.
- **PICK cascade equivalence** — after issue#30, the operator's
  PICK#1 → PICK#2 cascade should leave the bitmap visually identical
  to PICK#1+2 applied at once. Pin with a regression test.

## Cross-references

- `project_map_edit_origin_rotation.md` — current B-MAPEDIT-3 spec
  (PR #81 ship state).
- `project_amcl_yaw_metadata_only.md` — explains why Option B is
  required and Option A doesn't move the pose.
- `feedback_subtract_semantic_locked.md` — current SUBTRACT semantic
  for x/y/yaw; issue#30 will likely supersede or extend with the
  cumulative-from-current alternative.
- `feedback_pipeline_short_circuit.md` — issue#30 is feature-scale
  multi-stack, full pipeline (Planner → Mode-A → Writer → Mode-B →
  HIL).
