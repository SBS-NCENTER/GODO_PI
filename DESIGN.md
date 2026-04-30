# GODO — Design docs (root)

> **Purpose**: a one-page entry point to the design documents. This file is a TOC + orientation note; it does NOT duplicate content from the leaf design docs.
>
> **Companion**: see [`CODEBASE.md`](./CODEBASE.md) for the runtime scaffold (what is built and where it lives). DESIGN.md and CODEBASE.md split the same way `why?` and `where?` split: design = decisions and trade-offs, codebase = topology and modules.

---

## 1. Two design SSOTs

GODO splits its design narrative into two leaves so each can stay focused and digestible. Both are top-level files; both are linked from `CLAUDE.md §9`.

| Document | Scope | Owner | Read when… |
|---|---|---|---|
| [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) | Backend + RT + AMCL + FreeD + mapping pipeline + 59.94 fps UDP path + phase plan + failure scenarios | C++ implementer + RT engineer | Touching `production/RPi5/`, planning AMCL changes, tuning RT priorities, adding a new tracker subsystem, designing a new UDS verb. |
| [`FRONT_DESIGN.md`](./FRONT_DESIGN.md) | Frontend SSOT (operator SPA + admin web client) — page contracts, component composition, theme, route map, auth model, page-by-page UX spec | Frontend implementer | Touching `godo-webctl/` HTTP surface, touching `godo-frontend/` pages or components, designing a new operator workflow, deciding viewer vs admin gating. |

The split was decided 2026-04-28: SYSTEM_DESIGN was outgrowing its scope by carrying frontend page specs; pulling them into FRONT_DESIGN.md left both files leaner and made the editor experience faster.

---

## 2. Reference documents (deep dives)

Some design questions need their own self-contained reference doc rather than a section in the design SSOTs above. These live under `doc/` and are linked into the design SSOTs where relevant.

| Document | Scope |
|---|---|
| [`doc/RPLIDAR/RPLIDAR_C1.md`](./doc/RPLIDAR/RPLIDAR_C1.md) | Phase-0 deep dive on the RPLIDAR C1 (measurement principle, UART protocol, SDK choices, why raw Python data was noisy, MCU/SBC compatibility matrix). |
| [`doc/Embedded_CheckPoint.md`](./doc/Embedded_CheckPoint.md) | Embedded reliability checklist for code that must run for years in production. |
| [`doc/hardware/floor_tilt_survey_TS5.md`](./doc/hardware/floor_tilt_survey_TS5.md) | Studio floor tilt measurement (TS5 environment). |
| [`doc/hardware/leveling_mount.md`](./doc/hardware/leveling_mount.md) | Hardware decision report — leveling mount design. |
| [`doc/RPLIDAR/sources/`](./doc/RPLIDAR/sources/) | Original SLAMTEC PDFs (read-only, never modified). |

---

## 3. Doc hierarchy + cascade rule

Design docs are organized as:

```text
DESIGN.md                  ← THIS FILE (TOC, orientation, cross-references)
├── SYSTEM_DESIGN.md       ← Backend / RT / AMCL / FreeD design SSOT
└── FRONT_DESIGN.md        ← Frontend / page / component design SSOT
        │
        └── (deeper reference docs under /doc, linked above)
```

Cascade rule: **the leaves are the SSOT.** This file points to them and orients the reader; it does not duplicate their content. When a design decision lands:

- Update SYSTEM_DESIGN.md or FRONT_DESIGN.md (whichever owns the area).
- Update the deep reference doc under `doc/` if one exists for that question.
- Update this file ONLY if the *split itself* shifts (e.g., a new top-level design doc is added, or scope between SYSTEM and FRONT moves).

This keeps the root file stable so it can serve as a reliable cold-start index across sessions.

---

## 4. Where to find decisions

Different kinds of decisions land in different places. Use this quick table when in doubt:

| Decision type | Lands in |
|---|---|
| Architecture / topology / module split | SYSTEM_DESIGN.md |
| Frontend page UX, route map, auth gating | FRONT_DESIGN.md |
| Per-stack invariants (one-liner rules) | per-stack `CODEBASE.md` invariant list |
| Cross-session "what was decided + why" narrative | `PROGRESS.md` (English) + `doc/history.md` (Korean) |
| Operator-locked product decisions (Cancel-no-PATCH, dual-input mandate, etc.) | `.claude/memory/project_*.md` |
| Behavioral preferences for the AI assistant | `.claude/memory/feedback_*.md` and `CLAUDE.md §6` |
| Open / pending questions | `CLAUDE.md §8` (for project-scope questions) or `NEXT_SESSION.md` TL;DR (for in-flight queue) |
