---
name: Module docstring vs implementation sign/direction drift
description: Mode-B reviewer checklist — when a module docstring or function header explicitly states a sign/direction convention, the corresponding implementation MUST match. From operator HIL round 4 on PR #81 where map_rotate.py docstring said "rotate by -typed_yaw_deg" but implementation passed +typed_yaw_deg.
type: feedback
---

When a module/function docstring spells out a sign or direction
convention (e.g., "rotate by `-θ`", "CCW positive", "subtract
origin"), the implementation MUST honour it byte-for-byte. The
docstring is the contract; an off-by-sign is a contract violation
the docstring author themselves can no longer audit.

**Why:** PR #81 round 4 HIL caught this clearly. `map_rotate.py:153-154`
docstring stated:

```
"""Rotate the pristine PGM by ``-typed_yaw_deg`` (world-frame:
operator's typed +θ rotates the world; the bitmap rotates by −θ)
"""
```

But line 217 implementation passed `+typed_yaw_deg` (no negation):

```python
rotated = img.rotate(
    typed_yaw_deg,    # <-- should be -typed_yaw_deg per docstring
    resample=resample,
    expand=True,
    fillcolor=MAP_ROTATE_THRESH_UNK,
)
```

Combined with a separate double-counting bug elsewhere (YAML SUBTRACT
applied IN ADDITION to bitmap rotation), the operator-visible symptom
was "yaw rotates the opposite direction." The docstring would have
made the right thing trivial to verify if a reviewer had checked it
against the call.

The drift is plausible because:
- Writer drafts docstring + implementation in different keystrokes.
- Pillow's `Image.rotate(angle)` semantic ("positive angle = CCW visual")
  is itself a convention worth getting wrong.
- Tests at `θ=0` pass either way (the only existing test for the
  rotation pipeline used `theta_deg=0.0`).

**How to apply** — Mode-B reviewer checklist:

- For every module that ships in the PR, **read its top-level
  docstring** (or the docstring of its core public function) for
  any explicit sign / direction / convention statement.
- Then **grep the actual implementation** for the relevant call
  (e.g., `Image.rotate(`, `np.cross(`, `atan2(`, `R(`).
- Confirm signature args match the convention. If the docstring
  says `-x` and the call passes `x`, flag as Critical.
- If the test suite has only `θ=0` or other identity-rotation
  cases, **request asymmetric pin** (e.g., 90° with a known dark
  cell location). The asymmetric pin would have caught this in
  CI.

Generalisations:
- Forward / inverse rotation matrix conventions (`R(θ)` vs `R(-θ)`).
- ADD vs SUBTRACT semantics (already pinned by
  `feedback_subtract_semantic_locked.md` for x/y/yaw).
- Coordinate-frame handedness (canvas Y-down vs world Y-up).
- Time-zone offset direction (UTC = local + offset OR local - offset).

**Cross-link**: `feedback_subtract_semantic_locked.md` (sign-flip
already documented for origin SUBTRACT). `feedback_verify_before_plan.md`
(MOST-VIOLATED — Mode-A should also verify docstring claims by
reading the cited code, not assuming).
