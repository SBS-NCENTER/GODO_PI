---
name: CODEBASE.md SSOT freshness at task close
description: Every code change must update the relevant CODEBASE.md files (production/RPi5/, godo-webctl/, godo-frontend/) before the task is reported done. They are SSOT documents and stale entries propagate confusion across sessions.
type: feedback
---

Every implementation task must update the relevant `CODEBASE.md` file(s)
in the same change set. Updates land BEFORE any commit / merge / push —
they do not have to ride along every intermediate edit, but the
CODEBASE.md state at the moment of `git commit` / PR open / `git push`
must reflect the final shape of the change.

**Why:** User flagged this on 2026-04-30 during PR-A polkit work, citing
that the previous session's NEXT_SESSION.md / memory files describing
PR-A as a "~120 LOC unit-files-+-polkit" job had drifted from reality —
unit files had already shipped in earlier PRs but the docs still said
they needed to be written. Stale CODEBASE.md content has the same
failure mode: future sessions plan against a fictional state.

**How to apply:**

1. Backend changes (C++ tracker, RT path, systemd, scripts under
   `production/RPi5/`) → update `production/RPi5/CODEBASE.md`. Add a
   dated section in the `## YYYY-MM-DD HH:MM KST — <feature>` style
   already present, and tighten/add `### Invariants` letters as needed.
2. Webctl backend changes (Python FastAPI under `godo-webctl/`) →
   update `godo-webctl/CODEBASE.md` likewise. Letter the new invariants
   continuing from the existing tail (currently (x) → (y), (z), …).
3. Frontend changes (Vite + Svelte under `godo-frontend/`) → update
   `godo-frontend/CODEBASE.md`. The H-Q numbering for FRONT_DESIGN.md
   §H Map viewer is the established pattern for sub-features.
4. Pure config / docs changes still warrant a one-line CODEBASE.md
   change-log entry pointing at the affected paths so the doc trail
   matches the commit trail.

If a task touches multiple surfaces, ALL three CODEBASE.md files get
updated in the same PR.

The CLAUDE.md §6 "Context maintenance" rule already states this; the
user's reminder elevates it from a default-on rule to an explicit
non-negotiable invariant, especially for SSOT freshness in
multi-session work.

---

## Cascade rule for hierarchical SSOT docs (added 2026-04-30 12:50 KST)

The doc tree is now hierarchical:

- Root `CODEBASE.md` = scaffold + module roles + cross-stack data flow.
- Per-stack `production/RPi5/CODEBASE.md`, `godo-webctl/CODEBASE.md`,
  `godo-frontend/CODEBASE.md`, `prototype/Python/CODEBASE.md` = invariants
  + change log (the load-bearing SSOT).

The same hierarchy applies to design docs:

- Root `DESIGN.md` = TOC + cross-doc orientation.
- Leaf `SYSTEM_DESIGN.md` + `FRONT_DESIGN.md` = the design SSOT bodies.

**Cascade-edit rule** (operator-locked 2026-04-30):

- A change in a leaf (per-stack CODEBASE.md, SYSTEM_DESIGN, FRONT_DESIGN)
  is its own complete update. The leaf is the SSOT — the root index files
  do NOT duplicate the leaf content, so most leaf changes touch only the
  leaf.
- The root `CODEBASE.md` / `DESIGN.md` is updated **only** when the
  *shape* of the family shifts: a new stack is added, a stack is renamed
  or moved, the high-level data flow changes, the design-doc split
  itself changes (e.g., a third top-level design doc is added).
- A change that genuinely spans levels (e.g., a new wire-shape that
  crosses webctl ↔ frontend AND changes the cross-stack arrow drawn in
  the root CODEBASE.md) MUST update every affected level in the same
  commit. No half-cascade.
- Ownership stays asymmetric: the leaf invariant text never lives at the
  root; the root scaffold text never lives in a leaf. Duplicating either
  way creates drift between siblings or between levels.

**How to apply:**

1. When opening a new feature plan, identify which level(s) the change
   touches.
2. If only a leaf is affected, update only that leaf's CODEBASE.md /
   design doc.
3. If the cross-stack diagram, module-roles table, or scaffold hierarchy
   in the root file would mislead the next reader without the change,
   include the root update in the same PR.
4. Reviewers (Mode-B) should treat a root-level update without a leaf
   counterpart, or a leaf update that contradicts the root scaffold,
   as a Critical finding.

**Why:** the operator wanted hierarchical SSOT docs to make navigation
easier, but explicitly called out the SSOT/DRY risk: "any modification
must cascade so all content is properly reflected." The cascade-edit
rule is what makes the hierarchy safe — without it, the root files
become a second copy of the leaves and the two drift.
