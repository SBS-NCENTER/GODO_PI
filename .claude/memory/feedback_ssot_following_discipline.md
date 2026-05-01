---
name: SSOT-following discipline when multiple naming schemes exist
description: When two or more places in the codebase name "the same thing" differently, follow the original/upstream SSOT — do not invent or paraphrase a new name. Reinforced 2026-05-01 21:30 KST during Mode-A C1 fix on issue#14 plan (mapping pipeline lidar_port).
type: feedback
---

When the codebase already has a name for something — a TOML key, an enum
value, a config schema row, a struct field — that ORIGINAL location is
the SSOT. Any later code (e.g. webctl, frontend, plan documents,
reviewers) that references the same concept MUST use the original
name verbatim. Do not paraphrase, alias, or invent a parallel name
"because it reads better here."

**Why:** parallel names are silent landmines. The compiler doesn't
catch them. They drift over time. They fragment grep. They make
schema changes touch N files instead of 1. They produce the exact
class of "I implemented against the wrong key, fell back to default"
bug that issue#14 Mode-A C1 caught — the Planner had written
`[main] serial_lidar_port` while the SSOT (`production/RPi5/src/core/config_schema.hpp:120`)
defined `serial.lidar_port`. The writer would have built against
the wrong key and the mapping container would have launched with
the schema default `/dev/ttyUSB0` regardless of operator override.

**How to apply:**

1. Before naming a key, helper, field, or constant that mirrors
   something in another stack, READ the upstream SSOT and copy the
   name verbatim. For tracker-owned TOML keys: read
   `production/RPi5/src/core/config_schema.hpp` (the canonical row).
   For Python ↔ C++ wire fields: read the C++ struct definition.
   For frontend ↔ webctl protocol: read `protocol.py`.

2. When two stacks own different facets of the same concept, the
   SSOT lives where the value originates. Tracker writes
   `tracker.toml` from its schema → tracker schema is SSOT for any
   tracker key. webctl writes `webctl.*` keys → webctl is SSOT for
   those. Both share the same TOML file but with disjoint key
   ownership; readers respect the boundary.

3. When the SSOT name is ambiguous or stylistically inconsistent
   (e.g. snake_case vs dotted), keep the SSOT spelling anyway.
   "Cleaning it up" in a downstream consumer is a paraphrase that
   creates a parallel SSOT. Schema rename is a separate, intentional
   change that touches every consumer in one PR — not a drive-by
   improvement.

4. In Mode-A reviews, treat divergent naming between body sections
   as a Critical finding (drift between two halves of a single plan
   is the same hazard as drift between two halves of the codebase —
   the writer cannot disambiguate without re-reading the source).

5. In code-writer tasks, if you find yourself "translating" a name,
   stop. The translation is the bug. Use the original.

**Cross-references:**

- 2026-05-01 issue#14 Mode-A C1 — `_resolve_lidar_port` planning bug
  (`[main] serial_lidar_port` → `[serial] lidar_port`).
- PR #63 (issue#12) lock-in — webctl-owned vs tracker-owned schema
  rows distinction. webctl reads tracker keys but does NOT add them
  to `WebctlSection` — boundaries preserved.
- `feedback_codebase_md_freshness.md` — adjacent rule: when SSOT
  changes, the cascade must update every leaf in the same commit.
  This memory is the *naming* counterpart.

**Operator phrasing (2026-05-01 21:30 KST):**
"C1처럼 여러 scheme이 존재하는 경우 SSOT를 잘 따라줬으면 좋겠어.
지금처럼 tracker 값으로 통일한 것처럼."
