---
name: Origin pick — SUBTRACT semantic supersedes ADD (issue#27 lock)
description: When the operator-typed value names a "world coord that should become the new (0, 0)", the backend must SUBTRACT it from the old YAML origin. The earlier 2026-04-30 ADD lock had the wrong direction and shifted origin by 2× the typed offset. Locked again 2026-05-04 KST after PICK#2 / PICK#3 HIL data confirmed the SUBTRACT direction matches operator intent.
type: feedback
---

Locked 2026-05-04 KST after operator-supplied PICK#2 + PICK#3 HIL
data (`.claude/tmp/plan_issue_27_map_polish_and_output_transform.md`
§"Parent decisions fold C3"). Supersedes the 2026-04-30 ADD lock in
`.claude/memory/project_map_edit_origin_rotation.md`.

**The operator's mental model:** typed `(x_m, y_m)` is the *world coord
of the point that should become the new (0, 0)*. NOT the *offset* from
the old origin to the new origin (the earlier ADD interpretation).

**Backend SUBTRACT formula** (canonical, single source of truth in
`godo-webctl/src/godo_webctl/map_origin.py::apply_origin_edit`):

```python
# Absolute mode (the SPA's canonical wire shape):
new_yaml_origin = old_yaml_origin - typed
# Effect on the AMCL pose at the next restart:
new_pose = old_pose - typed
```

**Frontend resolution path** (issue#27 SPA):

```ts
// Delta mode resolves frontend-side via lib/originMath.ts:
//   resolveDeltaFromPose(currentPose, dx, dy) returns the absolute
//   world coord that the operator wants to be the new (0, 0).
// The SPA then sends mode="absolute" with the resolved value.
// Backend's delta branch is a fallback for non-SPA clients.
```

**HIL evidence pinning the convention** (operator-supplied 2026-05-03 KST):

```
PICK#2: typed=(7.86, 18.34) on origin=(2.01, 8.56)
        old_pose=(12.87, 15.49) → expected new_pose=(5.01, -2.85)
        new_yaml_origin = (2.01, 8.56) - (7.86, 18.34) = (-5.85, -9.78)

PICK#3: typed=(10.32, 28.86) on origin=(7.86, 18.34)
        old_pose=(18.72, 25.27) → expected new_pose=(8.40, -3.59)
        new_yaml_origin = (7.86, 18.34) - (10.32, 28.86) = (-2.46, -10.52)
```

Both pinned by `tests/test_map_origin.py::
test_apply_origin_edit_absolute_subtracts_pose_pick_{2,3}` (Python
backend) and `tests/unit/originMath.test.ts::"PICK#2 …"` /
`"PICK#3 …"` (frontend SUBTRACT semantic mirrors).

**Why the earlier ADD lock was wrong:** the 2026-04-30 spec memory
asked for "더해서" / `new_origin = current + typed`. Operator HIL on
3 sequential picks (PICK#1 → PICK#3 in chronological order) showed
the resulting pose drifted by `2 × typed_offset` instead of
moving to `(0, 0)`. The fix is direction-flipping; magnitude was
already correct. Operator confirmed 2026-05-03 23:30 KST.

**How to apply this when designing future origin / coord-pick flows:**

1. Decide whether the typed value is *the new (0, 0)* (SUBTRACT) or
   *an offset from the current origin* (ADD). The 2-mode question is
   "what does the operator's mental model say the typed value MEANS"?
2. SUBTRACT is the operator-locked default for picking-an-origin; ADD
   is appropriate for "shift everything by this delta" controls (rare).
3. Pin the direction with HIL data points in the test suite — a numeric
   regression test where the typed values have asymmetric x/y catches
   a sign flip immediately (zero-symmetric typed values like (1, 1) do
   NOT catch a flip).
4. SPA always resolves delta → absolute frontend-side and sends
   absolute. Backend stays dumb (single SUBTRACT formula).
5. Backend keeps a delta-fallback branch for non-SPA clients (e.g.
   `curl` debugging) but the SPA path never hits it.

**Cross-references:**
- `.claude/memory/project_map_edit_origin_rotation.md` — operator-locked
  spec including the 2026-05-04 supersede note.
- `production/RPi5/src/udp/output_transform.hpp` — separate sign-axis
  mechanism for the FreeD output channels (operator can flip Pan / X /
  etc. independently of the origin via `output_transform.*_sign`).
