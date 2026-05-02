---
name: Config tab — group keys by domain instead of alphabetical
description: Operator UX request 2026-05-01 21:30 KST. The Config tab today lists every schema row alphabetically; operator wants groups (AMCL, web/SSE, hint, live, oneshot, smoother, serial, etc.). Candidate work for issue#15.
type: project
---

The Config tab in godo-frontend currently renders every
`CONFIG_SCHEMA[]` row in alphabetical order. With ~48 keys spanning
AMCL, smoother, network, serial, web/SSE, hint, live, oneshot, and
calibrate domains, this is hard to scan — operator must remember
the alphabetic spelling of every key just to find the related set.

**Operator request (2026-05-01 21:30 KST):**
"우리 config 탭에 있는 요소들을 분류대로 봤으면 좋겠어. 이름순으로 다
나열되어 있으니까 너무 보기 헷갈린다. 예를들어 AMCL 그룹, 이 속에 hint나
live나 oneshot 관련된 것들끼리 묶어서 보기. web 페이지 관련된 것들 묶어서
보기. 등등"

**Why:** AMCL knobs (sigma, k_steps, carry hint, etc.) are operationally
related — operator tunes them as a cluster, not one-by-one. Same for
SSE/web rates (pose_stream_hz, scan_stream_hz). Alphabetical order
defeats the operator's mental model.

**How to apply:**

This is queued as a frontend-only enhancement (no schema change, no
backend change). Suggested approach:

1. **Source of grouping:** the schema row's dotted name already
   encodes the domain (`amcl.sigma_*`, `smoother.*`, `webctl.*`,
   `serial.*`, `network.*`, `hint.*`, `live.*`, `oneshot.*`,
   `calibrate.*`). Use the prefix as the group key. No new schema
   metadata required — Writer derives groups from existing names.

2. **UI shape:** the Config tab body becomes a list of collapsible
   sections, one per top-level prefix. Section header is the prefix
   (capitalised). Inside each section, rows ordered alphabetically by
   the leaf name (e.g. `amcl.k_steps`, `amcl.live_carry_pose_as_hint`,
   `amcl.sigma_xy`, etc.).

3. **Section ordering:** by frequency-of-use, NOT alphabetical.
   Operator-tunable order; sensible default = AMCL, smoother, hint,
   live, oneshot, calibrate, serial, network, webctl, ros (or
   whatever exists).

4. **Edit-mode interaction:** group sections do NOT change the
   View/Edit toggle scope (which is page-level per
   `project_config_tab_edit_mode_ux.md`). The whole page enters Edit
   together; collapsed sections are still part of the form.

5. **Search box:** with grouping in place, an inline filter
   ("amcl"/"hint") becomes valuable. Out-of-scope for the first
   iteration; revisit if operator asks.

**Estimated scope:** small frontend PR (~80 LOC + tests). Touches:
- `godo-frontend/src/routes/Config.svelte` — the row-rendering loop.
- `godo-frontend/src/lib/configGroups.ts` — new tiny module that
  derives group from schema dotted-name prefix.
- `godo-frontend/tests/unit/configGroups.test.ts` — pin grouping
  rules + ordering invariants.

**Issue label:** issue#15 (next free integer per CLAUDE.md §6 +
NEXT_SESSION.md). Standalone PR, can ship anytime; no dependency on
issue#14 mapping pipeline.

**Cross-references:**
- `project_config_tab_edit_mode_ux.md` — sibling Config tab spec
  (View/Edit toggle, best-effort Apply).
- `production/RPi5/src/core/config_schema.hpp` — SSOT for the dotted
  names this grouping reads from.
- NEXT_SESSION.md TL;DR — should add as item after issue#14 closes.
