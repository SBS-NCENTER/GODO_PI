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
