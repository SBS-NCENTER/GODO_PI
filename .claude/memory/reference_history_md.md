---
name: doc/history.md location and conventions
description: Korean-mixed Phase-level history at GODO/doc/history.md — operator/team-facing decision narrative, distinct from PROGRESS.md daily log
type: reference
---

`doc/history.md` is the durable Korean-mixed Phase-level history document for the GODO project.

**Path**: `/home/ncenter/projects/GODO/doc/history.md` (NOT at repo root, NOT in `.claude/`).

**Audience**: user + team members. Korean prose with English engineering terms preserved (e.g. "seqlock", "hot path", "SCHED_FIFO" — never translate).

**Format conventions** (from the file's own header):
- Reverse chronological — newest entries at top.
- One block per session. Same-day multiple sessions split by `(새벽/오전/오후/저녁/심야)`.
- Engineering terms in English originals.
- "왜 / 무엇을 결정했는가" focused — implementation details cross-reference `PROGRESS.md`.

**Distinction from PROGRESS.md**:
- `PROGRESS.md` (English, repo root) — daily session log; "current state + next-up" checklist.
- `doc/history.md` (Korean-mixed) — long-form Phase-level decision narrative; readable 1-year-later.

**When to update**: at session-end alongside `PROGRESS.md` and `SYSTEM_DESIGN.md`. The user explicitly asked (2026-04-27) for these three to be kept in sync at session close.

**Last entry as of memory write**: 2026-04-24 (Phase 4-1 RT hot path). Sessions for 2026-04-25, -26, -27 are in `PROGRESS.md` but not yet folded into `doc/history.md`.
