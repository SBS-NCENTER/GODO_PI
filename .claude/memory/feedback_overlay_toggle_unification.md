# Overlay toggle row unification (Feedback)

> Established 2026-05-04 KST as part of issue#28 (B-MAPEDIT-3 close).
> Operator preference + structural rule for any future map-rendering
> tab.

## Rule

All map-rendering tabs (`/map`, `/map-edit`, and any future
map-rendering route) share a single `<OverlayToggleRow>` component.
Every overlay (Origin/Axis, LiDAR scan, Grid, future ones) registers
itself as a toggle in that row. **Per-tab overlay toggles are a
regression** — never duplicate.

Toggle state lives in `godo-frontend/src/stores/overlayToggles.ts`
(localStorage-backed, key `OVERLAY_LS_KEY = 'godo.overlay.toggles.v1'`).
State persists across reloads and across tab switches.

## Why

1. **Operator confusion** — When `/map` and `/map-edit` had separate
   toggle rows the operator would toggle Grid OFF on `/map`, switch
   to `/map-edit`, see Grid still ON, toggle it OFF a second time,
   then return to `/map` and find it ON again because each page
   owned its own state. Multiple round-trips to reach the desired
   visual state. The unified store with localStorage persistence
   removes the surprise.

2. **localStorage drift** — Per-page LS keys
   (`godo.map.overlay.lidar`, `godo.map-edit.overlay.lidar`, etc.)
   were diverging because `/map-edit` was added after `/map` and
   silently introduced its own key. Future migration would have
   needed a rename pass for each key. Single key + single store =
   single migration point.

3. **UI consistency** — When the operator demos to a colleague, the
   demo flows tab-to-tab. Overlay state visibly carrying across
   builds trust ("the system remembers what I want to see").

## How to apply

When adding a NEW overlay (or NEW map-rendering tab):

- **Add the overlay to `<OverlayToggleRow>`** — never inline a
  per-tab toggle. The toggle row is the sole owner of the toggle
  UI surface.
- **Register state in `overlayToggles` store** — extend the
  `OverlayToggleState` interface; add a `localStorage` round-trip in
  the load/save helpers.
- **Mount the overlay component conditionally** on its toggle —
  the overlay component itself does not own the toggle, it owns the
  rendering.
- **Mount `<OverlayToggleRow>` on every map-rendering route** —
  `/map`, `/map-edit`, and any new route belong to the family.

Currently registered overlays (issue#28 state):

| toggle | component | constants |
|---|---|---|
| Origin/Axis | `<OriginAxisOverlay>` | `AXIS_X_COLOR`, `AXIS_Y_COLOR`, `AXIS_LINE_WIDTH_PX`, `AXIS_LABEL_FONT_PX` |
| LiDAR | (existing scan overlay, migrated to shared store) | — |
| Grid | `<GridOverlay>` | `GRID_INTERVAL_SCHEDULE`, `GRID_LINE_COLOR`, `GRID_MAX_LINES_PER_AXIS` |

Future candidates (not yet implemented; mention here so the next
contributor extends correctly): pose-trail breadcrumb, AMCL particle
cloud, candidate-marker-on-pick.

## Cross-links

- `.claude/memory/frontend_stack_decision.md` — Vite + Svelte 5 stack.
- `godo-frontend/CODEBASE.md` — invariants for OverlayToggleRow as
  sole owner; `overlayToggles` store as sole state owner.
- `FRONT_DESIGN.md` §3 I3-bis (issue#28) — MapEdit page contract
  including the unified overlay toggle row.
- `SYSTEM_DESIGN.md` §13 — broader map-edit pipeline that includes
  the overlay toggle UI surface.
