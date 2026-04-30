---
name: Config tab Edit-mode UX (PR-C)
description: Operator-locked spec for Config tab safety gate (EDIT button + view/edit state machine + best-effort sequential Apply + Cancel-discards-pending). Decided 2026-04-30 ~07:55 KST during PR-B parallel work. Tracks why Cancel is intentionally client-side only and why we use best-effort over all-or-nothing.
type: project
---

## What

Config tab adds an explicit Edit-mode safety gate. View mode is default
(inputs disabled, single `EDIT` button top-right). Admin clicks `EDIT`
→ inputs become editable, button group changes to `Cancel` / `Apply`.
Apply uses best-effort sequential PATCH; Cancel discards pending only.

## Why (decisions worth remembering)

### Why best-effort, not all-or-nothing
- Atomic bulk would require a new C++ UDS verb (`set_config_bulk`) +
  webctl endpoint = ~150 LOC across the language boundary.
- Tracker keys are operationally independent (network.ue_port and
  smoother.deadband_mm being half-applied is no consistency hazard).
- Best-effort lets the operator see exactly which key failed (e.g.
  "out of range") + fix only that one, without re-typing the others.
- Operator chose this explicitly over both atomic and "stop on first
  failure".

### Why Cancel is client-side only (no reverse-PATCH)
- After Apply, any successful key is already committed on the tracker.
  Cancel reverting them would require firing reverse-PATCHes, which
  themselves can fail (rollback inconsistency).
- Operator's intended Cancel semantics: "I'm done editing; don't try
  the remaining failed ones again." NOT "undo everything I just
  applied." The latter would be surprising (and dangerous on
  reload-class=recalibrate keys).
- Result: Cancel is a no-network-call action. Just clears `pending`
  dict and exits Edit mode.

### Why View mode default + admin-disabled EDIT
- Operator stated: "실수로 값이 변경되는 것을 방지" (prevent accidental
  edits). Always-enabled inputs make blur-PATCH (existing behavior)
  too easy to trigger by accident.
- The View/Edit toggle is the primary safety. Admin-gating the EDIT
  button (vs the Apply button) means anonymous viewers see immediately
  that the page is read-only — no need to interact to discover.

### Why backend gets ZERO LOC
- Existing `PATCH /api/config` endpoint already does single-key
  validation + reload_class echo. Looping it from the SPA gives us
  best-effort semantics for free. Adding a bulk endpoint would be
  speculative DRY (no second caller).

## State machine (canonical)

```
            ┌─────────────────┐
            │   View mode     │
            │  - inputs OFF   │
            │  - [EDIT] button│
            │    (disabled if │
            │     not admin)  │
            └────────┬────────┘
                     │ admin clicks EDIT
                     ▼
            ┌─────────────────┐
            │   Edit mode     │
            │  - inputs ON    │  ◄────────┐
            │  - [Cancel]     │           │
            │  - [Apply]      │           │ partial Apply
            └─┬───────────┬───┘           │ (some keys fail)
              │           │               │
   Cancel     │           │ Apply         │
              │           │               │
              ▼           ▼               │
   ┌──────────────┐  ┌────────────────────┴┐
   │ pending == 0 │  │ for each pending:    │
   │  → straight  │  │   try PATCH          │
   │    to View   │  │   collect ✓/✗        │
   ├──────────────┤  │ refresh /api/config  │
   │ pending > 0  │  │                      │
   │  → confirm   │  │ all ✓ → View         │
   │    dialog    │  │ any ✗ → Edit (stay)  │
   │  → discard   │  └──────────────────────┘
   │  → View      │
   └──────────────┘
```

## How to apply

When implementing or maintaining this feature:

- Cancel never sends a PATCH. If somebody adds reverse-PATCH "for
  symmetry," that's a regression — re-read this memory.
- Apply is best-effort. If somebody changes it to "stop on first
  failure" or wraps it in a bulk endpoint for atomicity, that's a
  regression unless the operator explicitly re-asks.
- Default-value display under Current is muted + small. Don't make it
  prominent; it's reference, not action.
- Tracker-inactive banner uses the existing `systemServices` store —
  do not add a new endpoint just to detect tracker liveness.
- The View/Edit toggle is page-level state (not per-row). Per-row
  enable/disable would re-introduce the accidental-edit hazard.

## Cross-references

- Original operator request: see conversation 2026-04-30 ~07:30 KST
  (the Q1–Q5 / locked-spec exchange).
- Backend wire-shape sibling bug: `fix/config-keys-unwrap`
  (project_config_view doesn't unwrap C++'s `keys` envelope; Config
  tab shows "—" for current values until fixed). PR-C requires the
  hotfix to land first or the operator can't see edits take effect.
- Implementation branch: `feat/config-tab-ux-edit-mode`. Sequenced
  AFTER PR-B (process monitor) + PR-A1 (login1 polkit) + Task #6
  hotfix.
