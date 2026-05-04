---
name: NEW component shipped ≠ wired feature
description: Mode-B / Mode-A reviewer checklist — when a PR introduces NEW components, pin that they are actually mounted into a visible route, not just file-created. From operator HIL round 2 on PR #81 (B-MAPEDIT-3) where 6 NEW components shipped but 1 (MapList) was never mounted, leaving the operator-visible feature dark.
type: feedback
---

When a PR creates NEW Svelte components (or any UI module), reviewer
discipline is: **does the PR also mount them into a route the
operator will actually navigate to?**

**Why:** PR #81 round 2 HIL surfaced this clearly. Six NEW components
shipped: `EditModeSwitcher`, `OverlayToggleRow`, `GridOverlay`,
`OriginAxisOverlay`, `ApplyMemoModal`, `MapList`. Five were mounted
into MapEdit / Map; one (`MapList`) was created with full grouped-
tree rendering logic + Vitest mount pin, but the route file
(`Map.svelte`) was never edited to host it. Operator HIL: "Map 목록이
SPA에 보이지 않음." Root cause: the legacy `<MapListPanel>` was still
the only mounted list, and the new `/api/maps` response shape
`{groups, flat}` broke its consumption (writable expected `MapEntry[]`,
got the wrapper object → empty render). Result: the entire grouped-
tree feature was DARK in production despite the components passing
all unit tests.

The file-level test pin proves the component WORKS, not that it's
WIRED. Both are required; the second is easy to miss because grep'ing
for `<MapList` will find the test mount and look "covered."

**How to apply** — Mode-A + Mode-B reviewer checklist additions:

- **Mode-A planning**: when the plan introduces a NEW component file,
  the same plan row must specify which existing route file mounts it.
  If the row says "create `<Foo>` component" without naming a parent
  mount site, request the mount instruction inline.
- **Mode-B implementation review**: for every NEW component file in
  the diff, grep for `<ComponentName` in the **non-test** SPA tree. If
  the only matches are inside `tests/`, flag as a Critical finding
  ("component file created but never mounted into a production route").
  Mode-B output: cite the component name + the absent route mount.
- **Writer self-check before opening PR**: same grep. Catches the
  bug before reviewer sees it.

This pattern also generalises beyond Svelte:
- New webctl endpoint registered but no client call site.
- New tracker module compiled but never invoked from `cold_writer` /
  `main`.
- New constants exported from `lib/constants.ts` but no caller.

The unifying signal: **dead code passes unit tests but fails HIL.**
Production-mount pin is a HIL-level concern that creeps into
implementation review only when the reviewer asks "did you wire it?"
on every NEW file.

**Cross-link**: `feedback_pipeline_short_circuit.md` (when to skip the
full pipeline — the answer is NEVER for ship-but-not-wire risk;
multi-stack features should always go full pipeline).
