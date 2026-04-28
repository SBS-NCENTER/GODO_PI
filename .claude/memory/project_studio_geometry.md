---
name: TS5 chroma studio geometry
description: Studio shape is asymmetric — narrower top, wider bottom with doors on both bottom corners. Critical context for Phase 2 localization improvements.
type: project
---

TS5 chroma studio (production environment) is **vertically asymmetric** — narrower at the top, wider at the bottom, with two doors on the bottom-left and bottom-right corners. Approximate shape:

```text
  │     │       top: narrower
  │     │
  │     │
│         │     bottom: wider, with doors on both corner ends
```

Step on both sides where the room widens. Mapped extent ~12.5 m × 17 m (studio_v1 / studio_v2 maps in `godo-mapping/maps/`).

**Why:** User confirmed shape on 2026-04-28 after first AMCL global-localization attempt failed to converge despite running with 10000 particles × 200 iterations on a hand-carried walk map (studio_v2). User's prior intuition was "rectangular = easy for feature matching" but rectangles are 180°-symmetric and hence ambiguous; the actual T-shape (with step + door asymmetry) should be MORE distinctive once the algorithm exploits it.

**How to apply:**
- **Phase 2 localization improvements** should explicitly leverage the step corners (4 inside corners at the wide/narrow boundary) and the two door openings as ICP-friendly landmarks. Generic global AMCL with uniform particle scatter doesn't seem to disambiguate even with ~16× more compute (5000×25 vs 10000×200, both produced xy_std ~5.9 m, yaw spread across full circle).
- **Map quality matters**: hand-carried walking accumulates drift, so step corners may be slightly skewed from their true positions. A higher-quality map (loop closure enforced + slow walk + retro-reflectors at corners) is a complementary lever.
- **Door state asymmetry**: doors open during mapping vs closed during localization (or vice versa) flips the wall continuity at those corners. When evaluating localization quality, record door state in both runs.
- **Hardware caveat for current measurements**: As of 2026-04-28, the LiDAR is mounted ~20 cm offset from the crane's pan-axis center (temporary installation). The pivot-center mount is a project design invariant; revisit measurements once the production mount is restored. This does not affect static OneShot tests but does affect any rotation-related test.
